"""AI 해석 응답 검증(BE-31).

결과에는 실패 종류만 담는다. 문제 문장·숫자·응답 원문·입력 집계는 담지 않는다.
응답 스키마가 확정되기 전이므로 지표 상태·출처 검사는 작업계획 7절의 지표 객체 관례
(`id`·`value`·`status`, `source`/`sources`)를 따른 응답에만 적용된다.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, JsonValue, ValidationError

from app.ai.prompts.builder import FORBIDDEN_CONTEXT_KEYS


class VerifyFailure(StrEnum):
    MALFORMED_JSON = "malformed_json"
    NOT_OBJECT = "not_object"
    SCHEMA_MISMATCH = "schema_mismatch"
    UNKNOWN_NUMBER = "unknown_number"
    FORBIDDEN_EXPRESSION = "forbidden_expression"
    PENDING_AS_VALUE = "pending_as_value"
    UNKNOWN_SOURCE = "unknown_source"
    PERSONAL_INFO = "personal_info"
    TOO_LONG = "too_long"
    REPETITION = "repetition"


@dataclass(frozen=True)
class VerifyPolicy:
    max_chars: int = 2000
    min_repeated_sentence_chars: int = 10


@dataclass(frozen=True)
class VerifyResult:
    failures: tuple[VerifyFailure, ...]
    data: dict[str, JsonValue] | None = field(default=None, repr=False)

    @property
    def ok(self) -> bool:
        return not self.failures


NUMBER_PATTERN = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")
PENDING_STATUSES = frozenset({"pending", "no_data", "link_only", "unverified"})
SOURCE_KEYS = frozenset({"source", "sources"})

FORBIDDEN_EXPRESSIONS = tuple(
    re.compile(pattern, flags)
    for pattern, flags in [
        (r"성공\s*률", 0),
        (r"성공\s*확률", 0),
        (r"성공\s*가능성", 0),
        (r"추천", 0),
        (r"위험\s*점수", 0),
        (r"위험\s*등급", 0),
        (r"(?<![A-Za-z])LQ(?![A-Za-z])", re.IGNORECASE),
        (r"입지\s*계수", 0),
        (r"(?:반드시|무조건|확실히|틀림없이)\s*(?:성공|실패|폐업|망)", 0),
        (r"(?:성공|실패|폐업)할\s*것입니다", 0),
        (r"망할", 0),
    ]
)

_COUNTER_UNITS = r"(?:개월|개|곳|건|명|년|월|일|분기|위|배|%|km|m|미터|호점|점포)"
PERSONAL_INFO_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in [
        r"(?<!\d)0\d{1,2}[-.\s]?\d{3,4}[-.\s]?\d{4}(?!\d)",  # 전화번호
        r"[\w.+-]+@[\w-]+\.[\w.-]+",  # 이메일
        # 도로명 번호. 조사 '으로'와 수량 표현은 제외한다.
        rf"[가-힣0-9](?<!으)(?:로|길)\s?\d+(?:-\d+)?(?![\d.])(?!\s*{_COUNTER_UNITS})",
        r"동\s*\d+(?:-\d+)?\s*번지|\d+-\d+\s*번지",  # 지번
        r"\d+\s*층|\d+\s*호(?!점)|(?<![A-Za-z])B\d+(?![A-Za-z0-9])",  # 층·호
        r"[가-힣]+구-[가-힣0-9]+-산?\d+-\d+",  # building_key
    ]
)
COORDINATE_PATTERN = re.compile(r"(?<![\d.])\d{2,3}\.\d{4,}(?!\d)")
SENTENCE_SPLIT = re.compile(r"(?<!\d)\.|\.(?!\d)|[!?。\n]+")


def _reject_constant(value: str) -> Any:
    raise ValueError("NaN·Infinity는 JSON이 아닙니다")


def _parse(text: str, *, exact: bool) -> object:
    if exact:
        return json.loads(text, parse_float=Decimal, parse_constant=_reject_constant)
    return json.loads(text, parse_constant=_reject_constant)


def _walk(value: object) -> Iterator[tuple[str | None, object]]:
    """(키, 값) 쌍을 깊이 우선으로 돌려준다. 키가 없는 값(목록 원소·최상위)은 키가 None이다."""
    stack: list[tuple[str | None, object]] = [(None, value)]
    while stack:
        key, current = stack.pop()
        yield key, current
        if isinstance(current, Mapping):
            stack.extend((str(k), v) for k, v in current.items())
        elif isinstance(current, list | tuple):
            stack.extend((None, item) for item in current)


def _to_decimal(token: str) -> Decimal | None:
    try:
        return Decimal(token.replace(",", ""))
    except InvalidOperation:
        return None


def _numbers_in_text(text: str) -> Iterator[Decimal]:
    for match in NUMBER_PATTERN.finditer(text):
        number = _to_decimal(match.group())
        if number is not None:
            yield number


def _number_value(value: object) -> Decimal | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return abs(value)
    if isinstance(value, int | float):
        return abs(Decimal(str(value)))
    return None


def allowed_numbers(context: Mapping[str, JsonValue]) -> frozenset[Decimal]:
    """입력 집계의 숫자 값, 그리고 문자열 값·키 안의 숫자 표기."""
    numbers: set[Decimal] = set()
    for key, value in _walk(context):
        if key is not None:
            numbers.update(_numbers_in_text(key))
        number = _number_value(value)
        if number is not None:
            numbers.add(number)
        elif isinstance(value, str):
            numbers.update(_numbers_in_text(value))
    return frozenset(numbers)


def _decimal_places(number: Decimal) -> int:
    exponent = number.as_tuple().exponent
    return -exponent if isinstance(exponent, int) and exponent < 0 else 0


def _is_allowed(number: Decimal, allowed: frozenset[Decimal]) -> bool:
    if number in allowed:
        return True
    places = _decimal_places(number)
    if places < 1:
        return False
    step = Decimal(1).scaleb(-places)
    for candidate in allowed:
        for rounding in (ROUND_HALF_UP, ROUND_HALF_EVEN):
            try:
                rounded = candidate.quantize(step, rounding=rounding)
            except InvalidOperation:  # 자릿수가 Decimal 정밀도를 넘는 표기
                continue
            if rounded == number:
                return True
    return False


def _pending_ids(context: Mapping[str, JsonValue]) -> frozenset[str]:
    ids: set[str] = set()
    for _, value in _walk(context):
        if (
            isinstance(value, Mapping)
            and value.get("status") in PENDING_STATUSES
            and isinstance(value.get("id"), str)
        ):
            ids.add(value["id"])
    return frozenset(ids)


def _sources(value: object) -> Iterator[str]:
    for key, child in _walk(value):
        if key is None or key.strip().lower() not in SOURCE_KEYS:
            continue
        if isinstance(child, str):
            yield child
        elif isinstance(child, list | tuple):
            yield from (item for item in child if isinstance(item, str))


def _has_repetition(sentences: list[str], min_chars: int) -> bool:
    normalized = [
        " ".join(part.split()) for text in sentences for part in SENTENCE_SPLIT.split(text)
    ]
    counts = Counter(part for part in normalized if len(part) >= min_chars)
    return any(count > 1 for count in counts.values())


def verify_output(
    text: str,
    *,
    context: Mapping[str, JsonValue],
    response_model: type[BaseModel] | None = None,
    policy: VerifyPolicy | None = None,
) -> VerifyResult:
    rules = policy or VerifyPolicy()

    exact: object = None
    data: object = None
    malformed = False
    try:
        exact = _parse(text, exact=True)
        data = _parse(text, exact=False)
    except (ValueError, RecursionError):
        malformed = True
    if malformed:
        return VerifyResult((VerifyFailure.MALFORMED_JSON,))
    if not isinstance(exact, dict) or not isinstance(data, dict):
        return VerifyResult((VerifyFailure.NOT_OBJECT,))

    found: set[VerifyFailure] = set()

    if response_model is not None:
        schema_ok = True
        try:
            response_model.model_validate(data)
        except ValidationError:
            schema_ok = False
        if not schema_ok:
            found.add(VerifyFailure.SCHEMA_MISMATCH)

    strings: list[str] = []
    numbers: list[Decimal] = []
    output_keys: list[str] = []
    for key, value in _walk(exact):
        if key is not None:
            output_keys.append(key)
        number = _number_value(value)
        if number is not None:
            numbers.append(number)
        elif isinstance(value, str):
            strings.append(value)
            numbers.extend(_numbers_in_text(value))

    allowed = allowed_numbers(context)
    if any(not _is_allowed(number, allowed) for number in numbers):
        found.add(VerifyFailure.UNKNOWN_NUMBER)

    if any(pattern.search(text) for text in strings for pattern in FORBIDDEN_EXPRESSIONS):
        found.add(VerifyFailure.FORBIDDEN_EXPRESSION)

    pending = _pending_ids(context)
    for _, value in _walk(exact):
        if (
            isinstance(value, Mapping)
            and value.get("id") in pending
            and value.get("value") is not None
        ):
            found.add(VerifyFailure.PENDING_AS_VALUE)
            break

    known_sources = frozenset(_sources(context))
    if any(source not in known_sources for source in _sources(exact)):
        found.add(VerifyFailure.UNKNOWN_SOURCE)

    personal = any(key.strip().lower() in FORBIDDEN_CONTEXT_KEYS for key in output_keys)
    personal = personal or any(
        pattern.search(text) for text in strings for pattern in PERSONAL_INFO_PATTERNS
    )
    personal = personal or any(
        Decimal(match.group()) not in allowed
        for text in strings
        for match in COORDINATE_PATTERN.finditer(text)
    )
    if personal:
        found.add(VerifyFailure.PERSONAL_INFO)

    if sum(len(text) for text in strings) > rules.max_chars:
        found.add(VerifyFailure.TOO_LONG)
    if _has_repetition(strings, rules.min_repeated_sentence_chars):
        found.add(VerifyFailure.REPETITION)

    failures = tuple(kind for kind in VerifyFailure if kind in found)
    return VerifyResult(failures, data=None if failures else data)
