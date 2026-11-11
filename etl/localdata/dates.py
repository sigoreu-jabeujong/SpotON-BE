"""Parse only the exact compact and ISO formats observed in source contracts."""

import re
from datetime import date, datetime

DATE_FORMATS = (
    (r"[0-9]{8}", "%Y%m%d"),
    (r"[0-9]{4}-[0-9]{2}-[0-9]{2}", "%Y-%m-%d"),
)
TIMESTAMP_FORMATS = (
    (r"[0-9]{14}", "%Y%m%d%H%M%S"),
    (r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}", "%Y-%m-%d %H:%M:%S"),
)


def _parse(value: str | None, formats: tuple[tuple[str, str], ...]) -> datetime | None:
    if value is None:
        return None
    for pattern, format_string in formats:
        if re.fullmatch(pattern, value) is None:
            continue
        try:
            parsed = datetime.strptime(value, format_string)
        except ValueError:
            return None
        return parsed if parsed.strftime(format_string) == value else None
    return None


def parse_source_date(value: str | None) -> date | None:
    parsed = _parse(value, DATE_FORMATS)
    return parsed.date() if parsed is not None else None


def parse_source_timestamp(value: str | None) -> datetime | None:
    return _parse(value, TIMESTAMP_FORMATS)
