"""Strict Seoul road keys. Road underground numbers are not basement floors."""

import re
import unicodedata
from dataclasses import dataclass

RULE = "road-jibun-v1"
ROAD_PATTERN = (
    r"^서울 ([가-힣]+구) ([가-힣A-Za-z0-9·]+(?:로|길)) "
    r"(지하 *)?([0-9]{1,4})(?:-([0-9]{1,4}))?(?= |,|\(|$)"
)


def normalized(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = re.sub(r"^서울(?:특별시|시)?\s+", "서울 ", value.strip())
    return re.sub(r"\s+", " ", value)


@dataclass(frozen=True)
class RoadAddress:
    key: str
    detail: str


def parse_road(value: str | None) -> RoadAddress | None:
    if not value or len(value) > 1000:
        return None
    text = normalized(value)
    match = re.match(ROAD_PATTERN, text)
    if match is None:
        return None
    gu, road, underground, main, sub = match.groups()
    tail = text[match.end() :].strip(" ,")
    # Multiple addresses are not a single key; building names in parentheses are allowed.
    if re.search(r"서울|[가-힣]+구\s|[가-힣0-9]+(?:로|길)\s+\d", tail):
        return None
    if int(main) == 0:
        return None
    return RoadAddress(
        "|".join((gu, road, "Y" if underground else "N", str(int(main)), str(int(sub or 0)))),
        tail,
    )
