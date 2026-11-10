"""Deterministic, privacy-safe normalization of Seoul jibun building keys."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum

from etl.localdata.constants import SEOUL_AUTHORITY_CODES

MAX_ADDRESS_LENGTH = 1000
SEOUL_HEAD_OFFICE_CODES = frozenset({"6110000", "_ALL"})
SEOUL_PREFIXES = frozenset({"서울특별시", "서울시", "서울"})
LIST_SEPARATORS = frozenset({",", "/", "~", ";"})
HYPHEN_VARIANTS = str.maketrans(
    {
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2212": "-",
        "\ufe63": "-",
        "\uff0d": "-",
    }
)

LEGAL_DONG_RE = re.compile(r"[가-힣]+동", re.ASCII)
LEGAL_GA_RE = re.compile(r"[가-힣]+[0-9]+가", re.ASCII)
LOT_RE = re.compile(
    r"(?P<mountain>산)?(?P<main>[0-9]{1,4})(?:-(?P<sub>[0-9]{1,4}))?(?:번지)?", re.ASCII
)
LOT_LIKE_RE = re.compile(r"(?:산)?[0-9-].*", re.ASCII)
NUMERIC_RE = re.compile(r"[0-9]+", re.ASCII)
UNIT_RE = re.compile(r"[0-9]+호", re.ASCII)
EXTERNAL_LOT_RE = re.compile(r"[0-9]+필지", re.ASCII)


class BuildingKeyFailure(StrEnum):
    EMPTY = "empty"
    NON_SEOUL = "non_seoul"
    GU_MISSING = "gu_missing"
    GU_CONFLICT = "gu_conflict"
    LEGAL_DONG_MISSING = "legal_dong_missing"
    LEGAL_DONG_UNSUPPORTED = "legal_dong_unsupported"
    LOT_MISSING = "lot_missing"
    AMBIGUOUS = "ambiguous"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class BuildingLot:
    gu_name: str
    legal_dong: str
    main_no: int
    sub_no: int
    is_mountain: bool

    @property
    def key(self) -> str:
        mountain = "산" if self.is_mountain else ""
        return f"{self.gu_name}-{self.legal_dong}-{mountain}{self.main_no}-{self.sub_no}"


@dataclass(frozen=True, slots=True)
class BuildingKeyResult:
    lot: BuildingLot | None
    failure: BuildingKeyFailure | None

    def __post_init__(self) -> None:
        if (self.lot is None) == (self.failure is None):
            raise ValueError("lot과 failure 중 하나만 설정해야 합니다")


def _success(lot: BuildingLot) -> BuildingKeyResult:
    return BuildingKeyResult(lot=lot, failure=None)


def _failure(failure: BuildingKeyFailure) -> BuildingKeyResult:
    return BuildingKeyResult(lot=None, failure=failure)


def _normalize_address(address: str | None) -> tuple[list[str] | None, BuildingKeyFailure | None]:
    if address is None or not address.strip():
        return None, BuildingKeyFailure.EMPTY
    if len(address) > MAX_ADDRESS_LENGTH:
        return None, BuildingKeyFailure.INVALID

    for character in address:
        category = unicodedata.category(character)
        if category in {"Cf", "No"} or (category == "Cc" and character not in "\t\r\n"):
            return None, BuildingKeyFailure.INVALID

    normalized = unicodedata.normalize("NFKC", address)
    if len(normalized) > MAX_ADDRESS_LENGTH:
        return None, BuildingKeyFailure.INVALID
    for character in normalized:
        category = unicodedata.category(character)
        if category in {"Cf", "No"} or (category == "Cc" and character not in "\t\r\n"):
            return None, BuildingKeyFailure.INVALID
        if category == "Nd" and character not in "0123456789":
            return None, BuildingKeyFailure.INVALID

    normalized = normalized.translate(HYPHEN_VARIANTS)
    if any(separator in normalized for separator in LIST_SEPARATORS):
        return None, BuildingKeyFailure.AMBIGUOUS
    if "및" in normalized.split():
        return None, BuildingKeyFailure.AMBIGUOUS
    if normalized.count("(") != normalized.count(")") or normalized.count("(") > 1:
        return None, BuildingKeyFailure.INVALID
    return normalized.replace("(", " ( ").replace(")", " ) ").split(), None


def _authority_context(
    authority_code: str | None,
) -> tuple[str | None, bool, BuildingKeyFailure | None]:
    if authority_code is None or authority_code == "":
        return None, False, None
    if authority_code in SEOUL_AUTHORITY_CODES:
        return SEOUL_AUTHORITY_CODES[authority_code], True, None
    if authority_code in SEOUL_HEAD_OFFICE_CODES:
        return None, True, None
    return None, False, BuildingKeyFailure.NON_SEOUL


def _valid_lot_number(value: int, *, minimum: int) -> bool:
    return minimum <= value <= 9999


def _legal_dong_failure(token: str) -> BuildingKeyFailure | None:
    if LEGAL_DONG_RE.fullmatch(token) or LEGAL_GA_RE.fullmatch(token):
        return None
    if token.endswith(("로", "길")) or token.endswith("동") or token.endswith("가"):
        return BuildingKeyFailure.LEGAL_DONG_UNSUPPORTED
    return BuildingKeyFailure.LEGAL_DONG_UNSUPPORTED


def _lot_from_token(token: str, *, mountain_prefix: bool = False) -> BuildingLot | None:
    match = LOT_RE.fullmatch(token)
    if match is None:
        return None
    main_text = match.group("main")
    sub_text = match.group("sub")
    main_no = int(main_text)
    sub_no = int(sub_text) if sub_text is not None else 0
    if not _valid_lot_number(main_no, minimum=1) or not _valid_lot_number(sub_no, minimum=0):
        return None
    return BuildingLot(
        gu_name="",
        legal_dong="",
        main_no=main_no,
        sub_no=sub_no,
        is_mountain=mountain_prefix or match.group("mountain") is not None,
    )


def _build_lot(
    gu_name: str,
    legal_dong: str,
    lot: BuildingLot,
) -> BuildingKeyResult:
    return _success(
        BuildingLot(
            gu_name=gu_name,
            legal_dong=legal_dong,
            main_no=lot.main_no,
            sub_no=lot.sub_no,
            is_mountain=lot.is_mountain,
        )
    )


def _validate_trailing(tokens: list[str], *, has_sub_no: bool) -> BuildingKeyFailure | None:
    if not tokens:
        return None
    if tokens[0] == "번지":
        tokens = tokens[1:]
    if not tokens:
        return None
    if tokens[0] == "외" or tokens[0].startswith("외"):
        if tokens[0] == "외":
            if len(tokens) < 2:
                return BuildingKeyFailure.AMBIGUOUS
            if EXTERNAL_LOT_RE.fullmatch(tokens[1]):
                tokens = tokens[2:]
            elif len(tokens) >= 3 and NUMERIC_RE.fullmatch(tokens[1]) and tokens[2] == "필지":
                tokens = tokens[3:]
            else:
                return BuildingKeyFailure.AMBIGUOUS
        elif re.fullmatch(r"외[0-9]+필지", tokens[0], re.ASCII):
            tokens = tokens[1:]
        else:
            return BuildingKeyFailure.AMBIGUOUS
    if not tokens:
        return None
    if NUMERIC_RE.fullmatch(tokens[0]) or tokens[0].startswith("-"):
        return BuildingKeyFailure.AMBIGUOUS
    if not has_sub_no and UNIT_RE.fullmatch(tokens[0]):
        return BuildingKeyFailure.AMBIGUOUS
    return None


def parse_jibun_address(
    address: str | None,
    *,
    authority_code: str | None = None,
) -> BuildingKeyResult:
    """Parse one raw jibun address without exposing its contents in results or logs."""
    if address is not None and not isinstance(address, str):
        raise TypeError(f"address must be str or None, not {type(address).__name__}")
    if authority_code is not None and not isinstance(authority_code, str):
        raise TypeError(f"authority_code must be str or None, not {type(authority_code).__name__}")

    tokens, input_failure = _normalize_address(address)
    if input_failure is not None:
        return _failure(input_failure)
    assert tokens is not None

    authority_gu, authority_is_seoul, authority_failure = _authority_context(authority_code)
    if authority_failure is not None:
        return _failure(authority_failure)

    index = 0
    explicit_seoul = tokens[0] in SEOUL_PREFIXES
    if explicit_seoul:
        index += 1
    elif tokens[0].endswith(("시", "도")):
        return _failure(BuildingKeyFailure.NON_SEOUL)

    if index >= len(tokens):
        return _failure(BuildingKeyFailure.GU_MISSING)

    first = tokens[index]
    gu_names = frozenset(SEOUL_AUTHORITY_CODES.values())
    address_gu: str | None = None
    if first in gu_names:
        address_gu = first
        index += 1
    elif first.endswith("구"):
        if any(first.startswith(gu) or first.startswith("서울") for gu in gu_names):
            return _failure(BuildingKeyFailure.INVALID)
        return _failure(BuildingKeyFailure.NON_SEOUL)
    elif any(first.startswith(gu) or first.startswith("서울") for gu in gu_names):
        return _failure(BuildingKeyFailure.INVALID)

    if address_gu is not None and authority_gu is not None and address_gu != authority_gu:
        return _failure(BuildingKeyFailure.GU_CONFLICT)
    if address_gu is not None and not (explicit_seoul or authority_is_seoul):
        return _failure(BuildingKeyFailure.AMBIGUOUS)
    gu_name = address_gu or authority_gu
    if gu_name is None:
        return _failure(BuildingKeyFailure.GU_MISSING)

    if index >= len(tokens):
        return _failure(BuildingKeyFailure.LEGAL_DONG_MISSING)
    legal_dong = tokens[index]
    if legal_dong in {"(", ")"}:
        return _failure(BuildingKeyFailure.AMBIGUOUS)
    if LOT_LIKE_RE.fullmatch(legal_dong):
        return _failure(BuildingKeyFailure.LEGAL_DONG_MISSING)
    legal_failure = _legal_dong_failure(legal_dong)
    if legal_failure is not None:
        return _failure(legal_failure)
    index += 1

    if index >= len(tokens):
        return _failure(BuildingKeyFailure.LOT_MISSING)
    if tokens[index] in {"(", ")"}:
        return _failure(BuildingKeyFailure.AMBIGUOUS)
    mountain_prefix = tokens[index] == "산"
    if mountain_prefix:
        index += 1
        if index >= len(tokens):
            return _failure(BuildingKeyFailure.LOT_MISSING)
    lot_token = tokens[index]
    parsed_lot = _lot_from_token(lot_token, mountain_prefix=mountain_prefix)
    if parsed_lot is None:
        if LOT_LIKE_RE.fullmatch(lot_token):
            return _failure(BuildingKeyFailure.INVALID)
        return _failure(BuildingKeyFailure.LOT_MISSING)
    index += 1
    trailing_failure = _validate_trailing(tokens[index:], has_sub_no=parsed_lot.sub_no != 0)
    if trailing_failure is not None:
        return _failure(trailing_failure)
    return _build_lot(gu_name, legal_dong, parsed_lot)


def build_from_parts(
    gu_name: str | None,
    legal_dong: str | None,
    main_no: int,
    sub_no: int | None = None,
    is_mountain: bool = False,
) -> BuildingKeyResult:
    """Build the same canonical key from a structured address provider response."""
    if gu_name is None or not isinstance(gu_name, str) or not gu_name.strip():
        return _failure(BuildingKeyFailure.GU_MISSING)
    if gu_name not in SEOUL_AUTHORITY_CODES.values():
        return _failure(BuildingKeyFailure.NON_SEOUL)
    if legal_dong is None or not isinstance(legal_dong, str) or not legal_dong.strip():
        return _failure(BuildingKeyFailure.LEGAL_DONG_MISSING)
    normalized, failure = _normalize_address(legal_dong)
    if failure is not None or normalized is None or len(normalized) != 1:
        return _failure(failure or BuildingKeyFailure.INVALID)
    legal_failure = _legal_dong_failure(normalized[0])
    if legal_failure is not None:
        return _failure(legal_failure)
    if isinstance(main_no, bool) or not isinstance(main_no, int):
        return _failure(BuildingKeyFailure.INVALID)
    if sub_no is None:
        sub_no = 0
    if isinstance(sub_no, bool) or not isinstance(sub_no, int) or not isinstance(is_mountain, bool):
        return _failure(BuildingKeyFailure.INVALID)
    if not _valid_lot_number(main_no, minimum=1) or not _valid_lot_number(sub_no, minimum=0):
        return _failure(BuildingKeyFailure.INVALID)
    return _success(
        BuildingLot(
            gu_name=gu_name,
            legal_dong=normalized[0],
            main_no=main_no,
            sub_no=sub_no,
            is_mountain=is_mountain,
        )
    )
