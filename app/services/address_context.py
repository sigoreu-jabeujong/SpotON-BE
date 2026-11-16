"""Server-verified address pairs; no DB writes or process-lifetime signing keys."""

import base64
import hmac
import json
import re
import time
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.core.config import Settings
from app.core.errors import AppError
from app.schemas.address_history import ContextRequest
from app.schemas.common import ErrorCode
from app.schemas.stores import HistoryQuery
from app.services.kakao_local import (
    NO_STORE_HEADERS,
    KakaoDocument,
    KakaoEnvelope,
    KakaoLocalService,
)
from etl.address.road_key import RULE, normalized, parse_road


class AddressPair(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    building_key: str
    road_key: str | None
    rule: str = RULE
    issued_at: int = Field(ge=0)
    context_version: int = Field(default=1, ge=1, le=2)
    lat: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False, repr=False)
    lng: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False, repr=False)
    category: Literal["cafe", "restaurant"] | None = None

    @model_validator(mode="after")
    def v2_location(self) -> Self:
        if self.context_version == 2 and (
            self.lat is None or self.lng is None or self.category is None
        ):
            raise ValueError("missing signed location")
        return self


def signing_key(settings: Settings) -> bytes:
    if settings.history_context_signing_key is None:
        raise AppError(ErrorCode.HISTORY_UNAVAILABLE, headers=NO_STORE_HEADERS)
    return settings.history_context_signing_key.get_secret_value().encode()


def encode_pair(pair: AddressPair, settings: Settings) -> str:
    body = base64.urlsafe_b64encode(pair.model_dump_json().encode()).rstrip(b"=")
    signature = hmac.digest(signing_key(settings), body, "sha256").hex()
    return body.decode() + "." + signature


def decode_pair(token: str, settings: Settings) -> AddressPair:
    key = signing_key(settings)
    try:
        body, signature = token.split(".")
        if re.fullmatch(r"[0-9a-f]{64}", signature) is None:
            raise ValueError("signature format")
        expected = hmac.digest(key, body.encode(), "sha256").hex()
        if not hmac.compare_digest(expected, signature):
            raise ValueError("signature")
        raw = base64.b64decode(body + "=" * (-len(body) % 4), altchars=b"-_", validate=True)
        pair = AddressPair.model_validate(json.loads(raw))
        HistoryQuery(building_key=pair.building_key)
        if pair.issued_at > int(time.time()) + 300:
            raise ValueError("future context")
    except (ValueError, ValidationError, UnicodeError):
        raise AppError(ErrorCode.INVALID_PARAM, headers=NO_STORE_HEADERS) from None
    if pair.rule != RULE:
        raise AppError(ErrorCode.HISTORY_UNAVAILABLE, headers=NO_STORE_HEADERS)
    return pair


async def create_context(
    service: KakaoLocalService, query: ContextRequest, settings: Settings
) -> dict[str, str | None]:
    signing_key(settings)  # Missing config is 503, before provider or DB access.
    if not service._api_key:
        raise AppError(ErrorCode.UPSTREAM_ERROR, headers=NO_STORE_HEADERS)
    try:
        envelope = KakaoEnvelope.model_validate(await service._search(query.address))
    except ValidationError:
        raise AppError(ErrorCode.UPSTREAM_ERROR, headers=NO_STORE_HEADERS) from None
    matches: list[AddressPair] = []
    for raw in envelope.documents:
        kind, candidate = service._to_candidate(raw, category=query.category, floor_unit=None)
        if candidate is None:
            continue
        if (
            candidate.building_key != query.building_key
            or candidate.lat != query.lat
            or candidate.lng != query.lng
            or normalized(query.address)
            not in {normalized(candidate.address_road), normalized(candidate.address_jibun)}
        ):
            continue
        document = KakaoDocument.model_validate(raw)
        road = document.road_address
        road_key = None
        if road is not None and road.address_name:
            parsed = parse_road(road.address_name)
            main, sub = road.main_building_no, road.sub_building_no or "0"
            if (
                parsed is None
                or road.underground_yn not in {"N", "Y"}
                or main is None
                or not main.isascii()
                or not main.isdigit()
                or not sub.isascii()
                or not sub.isdigit()
                or road.road_name is None
                or road.region_2depth_name is None
                or road.region_2depth_name != candidate.sigungu
            ):
                raise AppError(ErrorCode.UPSTREAM_ERROR, headers=NO_STORE_HEADERS)
            structured = "|".join(
                (
                    road.region_2depth_name,
                    road.road_name,
                    road.underground_yn,
                    str(int(main)),
                    str(int(sub)),
                )
            )
            if structured != parsed.key:
                raise AppError(ErrorCode.UPSTREAM_ERROR, headers=NO_STORE_HEADERS)
            road_key = structured
        matches.append(
            AddressPair(
                building_key=candidate.building_key,
                road_key=road_key,
                issued_at=int(time.time()),
                context_version=2,
                lat=candidate.lat,
                lng=candidate.lng,
                category=query.category,
            )
        )
    if len(matches) != 1:
        raise AppError(ErrorCode.INVALID_PARAM, headers=NO_STORE_HEADERS)
    pair = matches[0]
    return {
        "context": encode_pair(pair, settings),
        "building_key": pair.building_key,
        "road_key": pair.road_key,
        "rule_version": RULE,
    }
