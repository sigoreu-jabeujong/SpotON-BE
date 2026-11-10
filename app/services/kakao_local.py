"""Privacy-safe adapter for Kakao's address-to-coordinate API."""

from __future__ import annotations

import math
from enum import StrEnum
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from app.core.errors import AppError
from app.schemas.common import ErrorCode
from app.schemas.geocode import Category, GeocodeCandidate, GeocodeData
from etl.address.building_key import build_from_parts
from etl.address.floor_unit import parse_floor_unit

KAKAO_ADDRESS_URL = "https://dapi.kakao.com/v2/local/search/address.json"
NO_STORE_HEADERS = {"Cache-Control": "no-store"}
SEOUL_REGION_NAMES = frozenset({"서울", "서울특별시"})


class KakaoAddress(BaseModel):
    model_config = ConfigDict(extra="ignore")

    address_name: str | None = None
    region_1depth_name: str | None = None
    region_2depth_name: str | None = None
    region_3depth_name: str | None = None
    main_address_no: str | None = None
    sub_address_no: str | None = None
    mountain_yn: str | None = None


class KakaoDocument(BaseModel):
    model_config = ConfigDict(extra="ignore")

    x: str
    y: str
    address: KakaoAddress | None = None
    road_address: KakaoAddress | None = None


class KakaoEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore")

    documents: list[Any]


class CandidateKind(StrEnum):
    MALFORMED = "malformed"
    NON_SEOUL = "non_seoul"
    SEOUL_UNUSABLE = "seoul_unusable"
    USABLE = "usable"


def _upstream_error() -> AppError:
    return AppError(ErrorCode.UPSTREAM_ERROR, headers=NO_STORE_HEADERS)


def _address_not_found() -> AppError:
    return AppError(ErrorCode.ADDRESS_NOT_FOUND, headers=NO_STORE_HEADERS)


def _out_of_seoul() -> AppError:
    return AppError(ErrorCode.OUT_OF_SEOUL, headers=NO_STORE_HEADERS)


def _parse_number(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    if not value.isascii() or not value.isdecimal():
        return None
    return int(value)


def _coordinates(document: KakaoDocument) -> tuple[float, float] | None:
    try:
        lng = float(document.x)
        lat = float(document.y)
    except ValueError:
        return None
    if not math.isfinite(lat) or not math.isfinite(lng):
        return None
    if not -90 <= lat <= 90 or not -180 <= lng <= 180:
        return None
    return lat, lng


def _region_name(document: KakaoDocument) -> str | None:
    if document.address is not None:
        return document.address.region_1depth_name
    if document.road_address is not None:
        return document.road_address.region_1depth_name
    return None


def _floor_unit(query: str) -> str | None:
    result = parse_floor_unit(query)
    return result.value.value if result.value is not None else None


class KakaoLocalService:
    def __init__(
        self,
        *,
        api_key: str | None,
        timeout: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._timeout = timeout
        self._transport = transport

    async def geocode(self, *, query: str, category: Category) -> GeocodeData:
        if not self._api_key:
            raise _upstream_error()

        payload = await self._search(query)
        try:
            envelope = KakaoEnvelope.model_validate(payload)
        except ValidationError:
            raise _upstream_error() from None
        if not envelope.documents:
            raise _address_not_found()

        floor_unit = _floor_unit(query)
        usable: list[GeocodeCandidate] = []
        kinds: set[CandidateKind] = set()
        for raw_document in envelope.documents:
            kind, candidate = self._to_candidate(
                raw_document,
                category=category,
                floor_unit=floor_unit,
            )
            kinds.add(kind)
            if candidate is not None and len(usable) < 5:
                usable.append(candidate)

        if usable:
            first = usable[0]
            return GeocodeData(
                **first.model_dump(),
                candidates=usable if len(usable) > 1 else [],
            )
        if CandidateKind.MALFORMED in kinds:
            raise _upstream_error()
        if CandidateKind.SEOUL_UNUSABLE in kinds:
            raise _address_not_found()
        raise _out_of_seoul()

    async def _search(self, query: str) -> object:
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=self._timeout,
            ) as client:
                response = await client.get(
                    KAKAO_ADDRESS_URL,
                    params={"query": query, "page": 1, "size": 5},
                    headers={"Authorization": f"KakaoAK {self._api_key}"},
                )
                if not response.is_success:
                    raise _upstream_error()
                return response.json()
        except AppError:
            raise
        except (httpx.HTTPError, ValueError):
            raise _upstream_error() from None

    def _to_candidate(
        self,
        raw_document: object,
        *,
        category: Category,
        floor_unit: str | None,
    ) -> tuple[CandidateKind, GeocodeCandidate | None]:
        try:
            document = KakaoDocument.model_validate(raw_document)
        except ValidationError:
            return CandidateKind.MALFORMED, None

        coordinates = _coordinates(document)
        region_name = _region_name(document)
        if coordinates is None or region_name is None:
            return CandidateKind.MALFORMED, None
        if region_name not in SEOUL_REGION_NAMES:
            return CandidateKind.NON_SEOUL, None

        address = document.address
        if address is None or not address.address_name:
            return CandidateKind.SEOUL_UNUSABLE, None
        main_no = _parse_number(address.main_address_no)
        sub_no = _parse_number(address.sub_address_no)
        if main_no is None or (address.sub_address_no not in {None, ""} and sub_no is None):
            return CandidateKind.SEOUL_UNUSABLE, None
        if address.mountain_yn not in {"Y", "N"}:
            return CandidateKind.MALFORMED, None

        key = build_from_parts(
            address.region_2depth_name,
            address.region_3depth_name,
            main_no,
            sub_no,
            is_mountain=address.mountain_yn == "Y",
        )
        if key.lot is None:
            return CandidateKind.SEOUL_UNUSABLE, None

        lat, lng = coordinates
        road_address = document.road_address.address_name if document.road_address else ""
        return CandidateKind.USABLE, GeocodeCandidate(
            address_road=road_address or "",
            address_jibun=address.address_name,
            lat=lat,
            lng=lng,
            category=category,
            sigungu=address.region_2depth_name or "",
            building_key=key.lot.key,
            floor_unit=floor_unit,
        )
