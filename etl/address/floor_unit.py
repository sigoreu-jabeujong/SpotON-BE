"""Safe, deterministic extraction of explicit floor and unit address details."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum

MAX_ADDRESS_LENGTH = 1000
_FORBIDDEN_CATEGORIES = frozenset({"Cf", "Cs", "Co", "Cn", "No"})
_FLOOR_RE = re.compile(r"(?:B[1-9][0-9]{0,2}|[1-9][0-9]{0,2}층)", re.ASCII)
_UNIT_RE = re.compile(r"(?:[A-Za-z]?[0-9]{1,4}|[0-9]{1,4}[A-Za-z]?)호", re.ASCII)
_GROUND_FLOOR_RE = re.compile(r"(?:제|지상)?(?P<number>[0-9]{1,3})(?:층|[Ff])", re.ASCII)
_BASEMENT_FLOOR_RE = re.compile(r"(?:지하)?[Bb](?P<number>[0-9]{1,3})(?:층|[Ff])?", re.ASCII)
_BASEMENT_KOREAN_RE = re.compile(r"지하(?P<number>[0-9]{1,3})(?:층|[Ff])", re.ASCII)
_UNIT_INPUT_RE = re.compile(
    r"(?:제)?(?P<prefix>[A-Za-z]?)(?P<number>[0-9]{1,4})(?P<suffix>[A-Za-z]?)호",
    re.ASCII,
)
_SPLITTABLE_DETAIL_RE = re.compile(
    r"(?:제?(?:[1-9][0-9]{0,2})(?:층|[Ff])|(?:지하)?[Bb][1-9][0-9]{0,2}(?:층|[Ff])?|"
    r"(?:지하)?[1-9][0-9]{0,2}(?:층|[Ff])|(?:제)?(?:[A-Za-z]?[0-9]{1,4}|[0-9]{1,4}[A-Za-z]?)호)",
    re.ASCII,
)
_RANGE_RE = re.compile(r"[0-9]+(?:[~,/\-·][0-9]+)+(?:층|[Ff]|호)", re.ASCII)
_UNIT_HYPHEN_RE = re.compile(r"[0-9]+-[0-9]+호", re.ASCII)
_INVALID_SUFFIX_RE = re.compile(r"(?:제|지상|지하|[Bb])?[0-9A-Za-z.\-]+(?:층|[Ff]|호)", re.ASCII)
_MIDDLE_DETAIL_RE = re.compile(
    r"중(?:간)?(?:[^가-힣]|층|제|지하|지상|지층|반지하|옥탑|옥상|메자닌)", re.ASCII
)
_COMPLEX_FLOOR_TOKENS = frozenset(
    {"반지하", "지층", "지하층", "옥탑", "옥상", "중", "중간", "중층", "중간층", "M층", "메자닌"}
)
_SINGLE_BUILDING_RE = re.compile(r"(?:[0-9]{1,4}|[A-Za-z])동", re.ASCII)


class LocationLevel(StrEnum):
    SAME_SPOT = "same_spot"
    SAME_BUILDING = "same_building"
    UNVERIFIED = "unverified"


class FloorUnitFailure(StrEnum):
    EMPTY = "empty"
    NO_DETAIL = "no_detail"
    AMBIGUOUS = "ambiguous"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class FloorUnitValue:
    floor: str | None = field(repr=False)
    unit: str | None = field(repr=False)

    def __post_init__(self) -> None:
        if self.floor is None and self.unit is None:
            raise ValueError("floor 또는 unit이 필요합니다")
        if self.floor is not None and _FLOOR_RE.fullmatch(self.floor) is None:
            raise ValueError("유효하지 않은 floor입니다")
        if self.unit is not None and _UNIT_RE.fullmatch(self.unit) is None:
            raise ValueError("유효하지 않은 unit입니다")

    @property
    def value(self) -> str:
        return " ".join(part for part in (self.floor, self.unit) if part is not None)

    @property
    def location_level(self) -> LocationLevel:
        if self.floor is not None and self.unit is not None:
            return LocationLevel.SAME_SPOT
        return LocationLevel.SAME_BUILDING


@dataclass(frozen=True, slots=True)
class FloorUnitResult:
    value: FloorUnitValue | None = field(repr=False)
    failure: FloorUnitFailure | None

    def __post_init__(self) -> None:
        if (self.value is None) == (self.failure is None):
            raise ValueError("value와 failure 중 하나만 설정해야 합니다")


def _success(value: FloorUnitValue) -> FloorUnitResult:
    return FloorUnitResult(value=value, failure=None)


def _failure(failure: FloorUnitFailure) -> FloorUnitResult:
    return FloorUnitResult(value=None, failure=failure)


def _invalid_characters(value: str) -> bool:
    for character in value:
        category = unicodedata.category(character)
        if category in _FORBIDDEN_CATEGORIES:
            return True
        if category == "Cc" and character not in "\t\r\n":
            return True
    return False


def _normalize(address: str | None) -> tuple[str | None, FloorUnitFailure | None]:
    if address is None or not address.strip():
        return None, FloorUnitFailure.EMPTY
    if len(address) > MAX_ADDRESS_LENGTH or _invalid_characters(address):
        return None, FloorUnitFailure.INVALID
    normalized = unicodedata.normalize("NFKC", address)
    if len(normalized) > MAX_ADDRESS_LENGTH or _invalid_characters(normalized):
        return None, FloorUnitFailure.INVALID
    if any(
        unicodedata.category(character) == "Nd" and character not in "0123456789"
        for character in normalized
    ):
        return None, FloorUnitFailure.INVALID
    if normalized.count("(") != normalized.count(")") or normalized.count("(") > 1:
        return None, FloorUnitFailure.INVALID
    if "(" in normalized:
        start = normalized.index("(")
        end = normalized.index(")")
        normalized = normalized[:start] + " " + normalized[end + 1 :]
    return " ".join(normalized.split()), None


def _normalize_floor(token: str) -> str | None:
    match = _GROUND_FLOOR_RE.fullmatch(token)
    if match is not None:
        number = int(match.group("number"))
        return f"{number}층" if number > 0 else None
    match = _BASEMENT_KOREAN_RE.fullmatch(token) or _BASEMENT_FLOOR_RE.fullmatch(token)
    if match is not None:
        number = int(match.group("number"))
        return f"B{number}" if number > 0 else None
    return None


def _normalize_unit(token: str) -> str | None:
    match = _UNIT_INPUT_RE.fullmatch(token)
    if match is None:
        return None
    prefix = match.group("prefix")
    suffix = match.group("suffix")
    if prefix and suffix:
        return None
    number = match.group("number")
    if int(number) == 0:
        return None
    return f"{prefix.upper()}{number}{suffix.upper()}호"


def _is_detail_token(token: str) -> bool:
    return _normalize_floor(token) is not None or _normalize_unit(token) is not None


def _split_chunks(text: str) -> list[str]:
    chunks: list[str] = []
    for chunk in text.split():
        if chunk.endswith(",") and chunk[:-1].isdigit():
            chunks.append(chunk[:-1])
            continue
        if any(separator in chunk for separator in (",", "/", "-")):
            pieces = re.split(r"[,/\-]", chunk)
            if all(pieces) and all(_is_detail_token(piece) for piece in pieces):
                chunks.extend(pieces)
                continue
        chunks.append(chunk)
    return chunks


def _combine_tokens(chunks: list[str]) -> list[str]:
    combined: list[str] = []
    index = 0
    while index < len(chunks):
        current = chunks[index]
        following = chunks[index + 1] if index + 1 < len(chunks) else None
        if (
            following is not None
            and current.isascii()
            and current.isdigit()
            and following in {"층", "F", "f", "호"}
        ):
            combined.append(f"{current}{following}")
            index += 2
            continue
        if following is not None and current in {"지상", "지하"}:
            floor = _normalize_floor(following)
            if floor is not None and following.endswith(("층", "F", "f")):
                combined.append(f"{current}{following}")
                index += 2
                continue
        if following is not None and current == "제" and _is_detail_token(following):
            combined.append(f"제{following}")
            index += 2
            continue
        combined.append(current)
        index += 1
    return combined


def _candidate_failure(token: str) -> FloorUnitFailure | None:
    if _UNIT_HYPHEN_RE.fullmatch(token):
        return FloorUnitFailure.INVALID
    if _RANGE_RE.fullmatch(token):
        return FloorUnitFailure.AMBIGUOUS
    if any(dash in token for dash in ("–", "—", "‐")) and token.endswith(("층", "F", "f", "호")):
        return FloorUnitFailure.INVALID
    if _SINGLE_BUILDING_RE.fullmatch(token):
        return FloorUnitFailure.AMBIGUOUS
    # 중구·중랑구 같은 지명은 통과시키고 실제 중간층/호수 표현만 모호하게 남긴다.
    if (
        token in _COMPLEX_FLOOR_TOKENS
        or token.startswith(("반지하", "옥탑"))
        or _MIDDLE_DETAIL_RE.match(token)
    ):
        return FloorUnitFailure.AMBIGUOUS
    if _INVALID_SUFFIX_RE.fullmatch(token):
        return FloorUnitFailure.INVALID
    if token in {"B0", "b0"}:
        return FloorUnitFailure.INVALID
    return None


def parse_floor_unit(address: str | None) -> FloorUnitResult:
    """Extract only explicit floor/unit tokens without logging address contents."""
    if address is not None and not isinstance(address, str):
        raise TypeError(f"address must be str or None, not {type(address).__name__}")
    text, normalization_failure = _normalize(address)
    if normalization_failure is not None:
        return _failure(normalization_failure)
    assert text is not None

    chunks = _combine_tokens(_split_chunks(text))
    floors: set[str] = set()
    units: set[str] = set()
    invalid = False
    ambiguous = False
    previous = ""
    for chunk in chunks:
        floor = _normalize_floor(chunk)
        unit = _normalize_unit(chunk)
        if floor is None and unit is None:
            candidate_failure = _candidate_failure(chunk)
            if candidate_failure is FloorUnitFailure.INVALID:
                invalid = True
            elif candidate_failure is FloorUnitFailure.AMBIGUOUS:
                ambiguous = True
        if unit is not None and previous.endswith("번지"):
            ambiguous = True
        if floor is not None:
            floors.add(floor)
        if unit is not None:
            units.add(unit)
        previous = chunk

    if invalid:
        return _failure(FloorUnitFailure.INVALID)
    if ambiguous or len(floors) > 1 or len(units) > 1:
        return _failure(FloorUnitFailure.AMBIGUOUS)
    if not floors and not units:
        return _failure(FloorUnitFailure.NO_DETAIL)
    return _success(FloorUnitValue(floor=next(iter(floors), None), unit=next(iter(units), None)))


def reconcile_floor_units(road: FloorUnitResult, jibun: FloorUnitResult) -> FloorUnitResult:
    """Reconcile independent road and jibun parse results without choosing a guess."""
    if road.failure is FloorUnitFailure.INVALID or jibun.failure is FloorUnitFailure.INVALID:
        return _failure(FloorUnitFailure.INVALID)
    if road.failure is FloorUnitFailure.AMBIGUOUS or jibun.failure is FloorUnitFailure.AMBIGUOUS:
        return _failure(FloorUnitFailure.AMBIGUOUS)
    if road.value is not None and jibun.value is not None:
        return (
            _success(road.value)
            if road.value == jibun.value
            else _failure(FloorUnitFailure.AMBIGUOUS)
        )
    if road.value is not None:
        return _success(road.value)
    if jibun.value is not None:
        return _success(jibun.value)
    if road.failure is FloorUnitFailure.NO_DETAIL or jibun.failure is FloorUnitFailure.NO_DETAIL:
        return _failure(FloorUnitFailure.NO_DETAIL)
    return _failure(FloorUnitFailure.EMPTY)
