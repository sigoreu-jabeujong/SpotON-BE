"""Local, allow-listed, complete source snapshots; never commit these files."""

import hashlib
import json
import math
import os
import tempfile
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

from etl.localdata.collection import AuthorityStats, CollectedSource
from etl.localdata.constants import PAGE_SIZE, SEOUL_AUTHORITY_CODES, Source
from etl.localdata.dates import parse_source_timestamp
from etl.localdata.dto import LocalDataRow

FORMAT_VERSION = 1
DTO_FIELDS = (
    "authority_code",
    "management_no",
    "business_name",
    "road_address",
    "jibun_address",
    "status_name",
    "status_code",
    "detail_status_name",
    "detail_status_code",
    "business_type_name",
    "business_kind_name",
    "location_area",
    "facility_total_scale",
    "license_date",
    "closure_date",
    "raw_x",
    "raw_y",
    "update_type",
    "update_point",
    "last_modified_point",
)
TOP_FIELDS = {
    "format_version",
    "source",
    "collected_at",
    "authorities",
    "row_count",
    "rows_sha256",
    "rows",
}
STAT_FIELDS = {"gu_code", "total_count", "page_count", "row_count"}


class SnapshotError(ValueError):
    pass


def _encoded_rows(rows: tuple[LocalDataRow, ...]) -> Iterator[str]:
    for row in rows:
        yield json.dumps(
            {name: getattr(row, name) for name in DTO_FIELDS},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )


def rows_digest(rows: tuple[LocalDataRow, ...]) -> str:
    digest = hashlib.sha256(b"[")
    for index, encoded in enumerate(_encoded_rows(rows)):
        if index:
            digest.update(b",")
        digest.update(encoded.encode("utf-8"))
    digest.update(b"]")
    return digest.hexdigest()


def save_snapshot(collection: CollectedSource, directory: Path) -> Path:
    _validate_collection(collection)
    directory.mkdir(parents=True, exist_ok=True)
    final = directory / (
        f"{collection.source.value}-{collection.collected_at:%Y%m%dT%H%M%S}-{uuid4().hex}.json"
    )
    metadata = {
        "format_version": FORMAT_VERSION,
        "source": collection.source.value,
        "collected_at": collection.collected_at.strftime("%Y-%m-%d %H:%M:%S"),
        "authorities": [
            {
                "gu_code": stat.gu_code,
                "total_count": stat.total_count,
                "page_count": stat.page_count,
                "row_count": stat.row_count,
            }
            for stat in collection.authorities
        ],
        "row_count": len(collection.rows),
        "rows_sha256": rows_digest(collection.rows),
    }
    descriptor, temporary = tempfile.mkstemp(prefix=".import-", suffix=".part", dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            output.write(json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))[:-1])
            output.write(',"rows":[')
            for index, encoded in enumerate(_encoded_rows(collection.rows)):
                if index:
                    output.write(",")
                output.write(encoded)
            output.write("]}\n")
            output.flush()
            os.fsync(output.fileno())
        os.link(
            temporary, final
        )  # Atomic publish, and fails rather than replacing an existing file.
    finally:
        Path(temporary).unlink(missing_ok=True)
    return final


def _reject_constant(value: str) -> Any:
    raise SnapshotError("snapshot:non_finite")


def _unique_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SnapshotError("snapshot:duplicate_field")
        result[key] = value
    return result


def _validate_collection(collection: CollectedSource) -> None:
    codes = [stat.gu_code for stat in collection.authorities]
    if len(codes) != len(SEOUL_AUTHORITY_CODES) or set(codes) != set(SEOUL_AUTHORITY_CODES):
        raise SnapshotError("snapshot:authorities")
    counts = Counter(row.authority_code for row in collection.rows)
    if any(code not in SEOUL_AUTHORITY_CODES for code in counts):
        raise SnapshotError("snapshot:row_authority")
    for stat in collection.authorities:
        numbers = (stat.total_count, stat.page_count, stat.row_count)
        if any(type(number) is not int or number < 0 for number in numbers):
            raise SnapshotError("snapshot:counts")
        if (
            stat.row_count != stat.total_count
            or counts[stat.gu_code] != stat.row_count
            or stat.page_count != max(math.ceil(stat.total_count / PAGE_SIZE), 1)
        ):
            raise SnapshotError("snapshot:counts")


def load_snapshot(path: Path, source: Source) -> CollectedSource:
    if path.suffix != ".json":
        raise SnapshotError("snapshot:filename")
    try:
        with path.open(encoding="utf-8") as file:
            payload = json.load(
                file, parse_constant=_reject_constant, object_pairs_hook=_unique_fields
            )
        if not isinstance(payload, dict) or set(payload) != TOP_FIELDS:
            raise SnapshotError("snapshot:fields")
        if (
            type(payload["format_version"]) is not int
            or payload["format_version"] != FORMAT_VERSION
        ):
            raise SnapshotError("snapshot:version")
        if payload["source"] != source.value:
            raise SnapshotError("snapshot:source")
        collected_at = parse_source_timestamp(payload["collected_at"])
        if collected_at is None:
            raise SnapshotError("snapshot:date")
        raw_stats, raw_rows = payload["authorities"], payload["rows"]
        if not isinstance(raw_stats, list) or not isinstance(raw_rows, list):
            raise SnapshotError("snapshot:structure")
        for stat in raw_stats:
            if not isinstance(stat, dict) or set(stat) != STAT_FIELDS:
                raise SnapshotError("snapshot:authority_fields")
        for row in raw_rows:
            if (
                not isinstance(row, dict)
                or set(row) != set(DTO_FIELDS)
                or any(value is not None and not isinstance(value, str) for value in row.values())
            ):
                raise SnapshotError("snapshot:row_fields")
        collection = CollectedSource(
            source,
            collected_at,
            tuple(AuthorityStats(**stat) for stat in raw_stats),
            tuple(LocalDataRow(**row) for row in raw_rows),
        )
        _validate_collection(collection)
        if (
            type(payload["row_count"]) is not int
            or payload["row_count"] != len(collection.rows)
            or payload["rows_sha256"] != rows_digest(collection.rows)
        ):
            raise SnapshotError("snapshot:digest")
        return collection
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        pass
    # No parser/OS exception context (which may hold a source row or filename).
    raise SnapshotError("snapshot:invalid")
