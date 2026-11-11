"""Read a previously validated API-field CSV; never copy the original raw file."""

import csv
import hashlib
import io
import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO
from zoneinfo import ZoneInfo

from etl.localdata.collection import AuthorityStats, CollectedSource
from etl.localdata.constants import SEOUL_AUTHORITY_CODES, Source
from etl.localdata.dto import LocalDataRow

REQUIRED_CSV_FIELDS = frozenset(
    {
        "OPN_ATMY_GRP_CD",
        "MNG_NO",
        "BPLC_NM",
        "ROAD_NM_ADDR",
        "LOTNO_ADDR",
        "SALS_STTS_NM",
        "SALS_STTS_CD",
        "DTL_SALS_STTS_NM",
        "DTL_SALS_STTS_CD",
        "SNTTN_BZSTAT_NM",
        "BZSTAT_SE_NM",
        "LCTN_AREA",
        "FCLT_TOTAL_SCL",
        "LCPMT_YMD",
        "CLSBIZ_YMD",
        "CRD_INFO_X",
        "CRD_INFO_Y",
        "DAT_UPDT_SE",
        "DAT_UPDT_PNT",
        "LAST_MDFCN_PNT",
    }
)
SOURCE_LABELS = {
    Source.GENERAL_RESTAURANT: {"general_restaurant", "restaurant"},
    Source.REST_CAFE: {"rest_cafe", "cafe"},
}


class CSVSourceError(ValueError):
    pass


class _HashingReader(io.RawIOBase):
    def __init__(self, source: BinaryIO) -> None:
        self.source = source
        self.digest = hashlib.sha256()

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: Any) -> int:
        chunk = self.source.read(len(buffer))
        buffer[: len(chunk)] = chunk
        self.digest.update(chunk)
        return len(chunk)


def _reject_constant(value: str) -> Any:
    raise CSVSourceError("csv:non_finite")


def _unique_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CSVSourceError("csv:duplicate_json_field")
        result[key] = value
    return result


def _count(value: object) -> int:
    if type(value) is not int or value < 0:
        raise CSVSourceError("csv:report_count")
    return value


def load_validated_csv(path: Path, validation: Path, source: Source) -> CollectedSource:
    try:
        return _load_validated_csv(path, validation, source)
    except CSVSourceError:
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError, csv.Error):
        pass
    raise CSVSourceError("csv:invalid")


def _load_validated_csv(path: Path, validation: Path, source: Source) -> CollectedSource:
    with validation.open("rb") as file:
        report_bytes = file.read(2 * 1024 * 1024 + 1)
    if len(report_bytes) > 2 * 1024 * 1024:
        raise CSVSourceError("csv:report_size")
    report = json.loads(
        report_bytes.decode("utf-8-sig"),
        parse_constant=_reject_constant,
        object_pairs_hook=_unique_fields,
    )
    if not isinstance(report, dict) or report.get("validation") != "PASS":
        raise CSVSourceError("csv:report_status")
    if (
        report.get("complete") is not True
        or report.get("coordinates_unchanged") is not True
        or report.get("fields_unchanged") is not True
    ):
        raise CSVSourceError("csv:report_incomplete")
    if "source" in report and report["source"] not in SOURCE_LABELS[source]:
        raise CSVSourceError("csv:report_source")
    expected_hash = report.get("source_sha256")
    if not isinstance(expected_hash, str) or re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None:
        raise CSVSourceError("csv:report_hash")
    if _count(report["duplicate_management_ids"]) != 0:
        raise CSVSourceError("csv:report_duplicates")
    expected = _count(report["expected_full_rows"])
    if _count(report["raw_rows"]) != expected or _count(report["csv_rows"]) != expected:
        raise CSVSourceError("csv:report_count")
    expected_pages = _count(report["expected_pages"])
    if _count(report["pages"]) != expected_pages or _count(report["saved_pages"]) != expected_pages:
        raise CSVSourceError("csv:report_pages")
    validated_at = datetime.fromisoformat(report["validated_at_utc"])
    if validated_at.tzinfo is None or validated_at > datetime.now(UTC):
        raise CSVSourceError("csv:report_timestamp")
    stamp = validated_at.astimezone(ZoneInfo("Asia/Seoul")).replace(tzinfo=None, microsecond=0)
    districts = report["districts"]
    if not isinstance(districts, list):
        raise CSVSourceError("csv:report_authorities")
    expected_counts: dict[str, int] = {}
    seen: set[str] = set()
    pages = 0
    for stat in districts:
        if not isinstance(stat, dict):
            raise CSVSourceError("csv:report_authorities")
        code = stat["code"]
        if not isinstance(code, str) or code in seen:
            raise CSVSourceError("csv:report_authorities")
        seen.add(code)
        count, page_count = _count(stat["raw_rows"]), _count(stat["pages"])
        pages += page_count
        if code == "6110000" and count == 0:
            continue
        if code not in SEOUL_AUTHORITY_CODES:
            raise CSVSourceError("csv:report_authorities")
        expected_counts[code] = count
    if (
        set(expected_counts) != set(SEOUL_AUTHORITY_CODES)
        or sum(expected_counts.values()) != expected
        or pages != expected_pages
    ):
        raise CSVSourceError("csv:report_authorities")

    before = path.stat()
    rows: list[LocalDataRow] = []
    counts: Counter[str] = Counter()
    management_ids: set[str] = set()
    with path.open("rb") as binary:
        hashing = _HashingReader(binary)
        with io.TextIOWrapper(io.BufferedReader(hashing), encoding="utf-8-sig", newline="") as file:
            reader = csv.reader(file, dialect="excel", strict=True)
            headers = next(reader)
            if (
                len(headers) != len(set(headers))
                or any(not name or "\0" in name for name in headers)
                or not REQUIRED_CSV_FIELDS <= set(headers)
            ):
                raise CSVSourceError("csv:headers")
            positions = {name: headers.index(name) for name in REQUIRED_CSV_FIELDS}
            for cells in reader:
                if len(cells) != len(headers) or any("\0" in cell for cell in cells):
                    raise CSVSourceError("csv:record")
                # Retain only allow-listed fields; telephone and other extras are discarded.
                row = LocalDataRow.from_api(
                    {name: cells[index] for name, index in positions.items()}
                )
                if row.authority_code not in SEOUL_AUTHORITY_CODES or not row.management_no:
                    raise CSVSourceError("csv:row_identity")
                if row.management_no in management_ids:
                    raise CSVSourceError("csv:duplicate_management")
                management_ids.add(row.management_no)
                counts[row.authority_code] += 1
                rows.append(row)
        actual_hash = hashing.digest.hexdigest()
    after = path.stat()
    if actual_hash != expected_hash or (before.st_size, before.st_mtime_ns) != (
        after.st_size,
        after.st_mtime_ns,
    ):
        raise CSVSourceError("csv:file_changed_or_hash")
    if len(rows) != expected or any(
        counts[code] != count for code, count in expected_counts.items()
    ):
        raise CSVSourceError("csv:row_counts")
    return CollectedSource(
        source,
        stamp,
        tuple(
            AuthorityStats(code, expected_counts[code], None, counts[code])
            for code in SEOUL_AUTHORITY_CODES
        ),
        tuple(rows),
        input_kind="validated_csv",
        input_sha256=actual_hash,
        validation_sha256=hashlib.sha256(report_bytes).hexdigest(),
        as_of_basis="validation_checked_at",
    )
