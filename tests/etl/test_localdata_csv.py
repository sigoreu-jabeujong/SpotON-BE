import csv
import hashlib
import io
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from app.core.config import Settings
from etl.localdata import runner
from etl.localdata.constants import SEOUL_AUTHORITY_CODES, Source
from etl.localdata.csv_source import REQUIRED_CSV_FIELDS, CSVSourceError, load_validated_csv
from etl.localdata.snapshot import load_snapshot, rows_digest, save_snapshot


def csv_fixture(directory: Path, *, bom: bool = True) -> tuple[Path, Path]:
    path, report_path = directory / "source.csv", directory / "validation.json"
    headers = sorted(REQUIRED_CSV_FIELDS | {"TELNO"})
    with path.open("w", encoding="utf-8-sig" if bom else "utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=headers)
        writer.writeheader()
        for index, code in enumerate(("3000000", "3010000")):
            writer.writerow(
                {
                    "MNG_NO": f"synthetic-{index}",
                    "OPN_ATMY_GRP_CD": code,
                    "BPLC_NM": "private-name-canary",
                    "LCPMT_YMD": "2024-02-29",
                    "SALS_STTS_CD": "01",
                    "SALS_STTS_NM": "영업/정상",
                    "SNTTN_BZSTAT_NM": "한식",
                    "TELNO": "private-phone-canary",
                }
            )
    counts = Counter({"3000000": 1, "3010000": 1})
    report = {
        "validation": "PASS",
        "complete": True,
        "coordinates_unchanged": True,
        "fields_unchanged": True,
        "duplicate_management_ids": 0,
        "expected_full_rows": 2,
        "raw_rows": 2,
        "csv_rows": 2,
        "pages": 26,
        "saved_pages": 26,
        "expected_pages": 26,
        "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "validated_at_utc": "2026-11-09T08:00:00+00:00",
        "districts": [
            {"code": code, "raw_rows": counts[code], "pages": 1}
            for code in [*SEOUL_AUTHORITY_CODES, "6110000"]
        ],
    }
    report_path.write_text(json.dumps(report), encoding="utf-8")
    return path, report_path


def refresh_hash(path: Path, report: Path) -> None:
    metadata = json.loads(report.read_text(encoding="utf-8"))
    metadata["source_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    report.write_text(json.dumps(metadata), encoding="utf-8")


@pytest.mark.parametrize("bom", [True, False])
def test_csv_roundtrip_retains_provenance_and_drops_private_fields(
    tmp_path: Path, bom: bool
) -> None:
    path, report = csv_fixture(tmp_path, bom=bom)
    source = load_validated_csv(path, report, Source.GENERAL_RESTAURANT)
    assert source.input_kind == "validated_csv"
    assert source.collected_at.isoformat() == "2026-11-09T17:00:00"
    assert source.as_of_basis == "validation_checked_at"
    assert len(source.authorities) == 25
    assert all(stat.page_count is None for stat in source.authorities)
    assert source.input_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    snapshot = save_snapshot(source, tmp_path / "snapshots")
    assert load_snapshot(snapshot, source.source) == source
    assert "private-phone-canary" not in snapshot.read_text(encoding="utf-8")
    again = load_validated_csv(path, report, Source.GENERAL_RESTAURANT)
    assert rows_digest(again.rows) == rows_digest(source.rows)


@pytest.mark.parametrize(
    "mutation",
    [
        "status",
        "complete",
        "bool_count",
        "naive",
        "future",
        "source",
        "hash",
        "duplicate",
        "district",
        "city",
    ],
)
def test_invalid_validation_report_rejected(tmp_path: Path, mutation: str) -> None:
    path, report_path = csv_fixture(tmp_path)
    report: dict[str, Any] = json.loads(report_path.read_text(encoding="utf-8"))
    if mutation == "status":
        report["validation"] = "FAIL"
    elif mutation == "complete":
        report["complete"] = "true"
    elif mutation == "bool_count":
        report["raw_rows"] = True
    elif mutation == "naive":
        report["validated_at_utc"] = "2026-11-09T08:00:00"
    elif mutation == "future":
        report["validated_at_utc"] = "2099-01-01T00:00:00+00:00"
    elif mutation == "source":
        report["source"] = "rest_cafe"
    elif mutation == "hash":
        report["source_sha256"] = "0" * 64
    elif mutation == "duplicate":
        report["duplicate_management_ids"] = 1
    elif mutation == "district":
        report["districts"].pop(0)
    elif mutation == "city":
        report["districts"][-1]["raw_rows"] = 1
    report_path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(CSVSourceError):
        load_validated_csv(path, report_path, Source.GENERAL_RESTAURANT)


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate_header",
        "missing_header",
        "short",
        "extra",
        "nul",
        "authority",
        "duplicate_id",
        "count",
        "utf8",
    ],
)
def test_csv_rows_are_revalidated_even_when_file_hash_matches(
    tmp_path: Path, mutation: str
) -> None:
    path, report = csv_fixture(tmp_path)
    rows = list(csv.reader(io.StringIO(path.read_text(encoding="utf-8-sig"))))
    if mutation == "duplicate_header":
        rows[0][-1] = rows[0][0]
    elif mutation == "missing_header":
        rows[0][rows[0].index("MNG_NO")] = "UNKNOWN"
    elif mutation == "short":
        rows[1].pop()
    elif mutation == "extra":
        rows[1].append("private-cell-canary")
    elif mutation == "nul":
        rows[1][0] += "\0"
    elif mutation == "authority":
        rows[1][rows[0].index("OPN_ATMY_GRP_CD")] = "6110000"
    elif mutation == "duplicate_id":
        rows[2][rows[0].index("MNG_NO")] = rows[1][rows[0].index("MNG_NO")]
    elif mutation == "count":
        rows.pop()
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        csv.writer(file).writerows(rows)
    if mutation == "utf8":
        with path.open("ab") as file:
            file.write(b"\xff")
    refresh_hash(path, report)
    with pytest.raises(CSVSourceError) as caught:
        load_validated_csv(path, report, Source.GENERAL_RESTAURANT)
    assert "private-cell-canary" not in repr(caught.value)


def test_duplicate_or_nonfinite_report_json_rejected(tmp_path: Path) -> None:
    path, report = csv_fixture(tmp_path)
    for text in ('{"complete":true,"complete":false}', '{"raw_rows":NaN}'):
        report.write_text(text, encoding="utf-8")
        with pytest.raises(CSVSourceError):
            load_validated_csv(path, report, Source.GENERAL_RESTAURANT)


def test_csv_dryrun_does_not_use_database_or_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, report = csv_fixture(tmp_path)

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("CSV dry-run used DB/API")

    monkeypatch.setattr(runner, "create_db_engine", forbidden)
    monkeypatch.setattr(runner, "LocalDataClient", forbidden)
    result = runner.run_import(
        Source.GENERAL_RESTAURANT,
        settings=Settings(_env_file=None, database_url=None, data_go_kr_service_key=None),
        from_csv=path,
        validation=report,
    )
    assert result["reference_date"] == "2026-11-09"
    assert result["expected_pages"] is None
    assert result["transformed"] == 2


@pytest.mark.parametrize(
    "arguments",
    [
        ["--from-csv", "source.csv"],
        ["--validation", "report.json"],
        ["--from-csv", "source.csv", "--validation", "report.json", "--write"],
        ["--from-csv", "source.csv", "--from-snapshot", "snapshot.json"],
    ],
)
def test_invalid_csv_cli_combinations(arguments: list[str]) -> None:
    with pytest.raises(SystemExit):
        runner.main(["--source", "general_restaurant", *arguments])
