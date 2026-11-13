import json
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy.exc import SQLAlchemyError

from etl.localdata.constants import Source
from etl.localdata.floor_backfill import (
    BackfillError,
    PreparedSource,
    digest,
    location_change,
    main,
    prepare_source,
    run_backfill,
)
from etl.localdata.snapshot import save_snapshot
from tests.etl.test_localdata_pipeline import raw
from tests.etl.test_localdata_snapshot import collection


def original(tmp_path: Path, source: Source = Source.GENERAL_RESTAURANT) -> Path:
    kind = "한식" if source == Source.GENERAL_RESTAURANT else "커피숍"
    rows = (
        raw(
            "RESTORE",
            OPN_ATMY_GRP_CD="3010000",
            SNTTN_BZSTAT_NM=kind,
            ROAD_NM_ADDR="서울특별시 중구 명동길 14 2층 201호",
            LOTNO_ADDR="서울특별시 중구 명동2가 1-1 2층 201호",
        ),
        raw("KEEP", SNTTN_BZSTAT_NM=kind),
        raw(
            "AMBIGUOUS",
            OPN_ATMY_GRP_CD="3010000",
            SNTTN_BZSTAT_NM=kind,
            ROAD_NM_ADDR="서울특별시 중구 명동길 14 중2층 201호",
            LOTNO_ADDR="서울특별시 중구 명동2가 1-1 중2층 201호",
        ),
    )
    return save_snapshot(replace(collection(rows), source=source), tmp_path)


def prepared(tmp_path: Path, source: Source = Source.GENERAL_RESTAURANT) -> PreparedSource:
    return prepare_source(original(tmp_path, source), source)


@pytest.mark.parametrize(
    "stored,level,new,expected",
    [
        (None, None, "2층 201호", True),
        (None, "unverified", "2층 201호", True),
        (None, None, None, False),
        (None, "unverified", None, False),
        ("2층 201호", "same_spot", "2층 201호", False),
    ],
)
def test_location_decision_preserves_null_level_and_existing_values(
    tmp_path, stored, level, new, expected
):
    record = next(r for r in prepared(tmp_path).records if r.license_no == "RESTORE")
    assert location_change(stored, level, replace(record, floor_unit=new)) is expected


@pytest.mark.parametrize(
    "stored,level",
    [
        ("3층", "same_building"),
        ("2층 201호", "same_building"),
        (None, "same_spot"),
        (None, "same_building"),
    ],
)
def test_location_conflicts_are_not_overwritten(tmp_path, stored, level):
    record = next(r for r in prepared(tmp_path).records if r.license_no == "RESTORE")
    with pytest.raises(BackfillError, match="backfill:location_conflict"):
        location_change(stored, level, record)


@pytest.mark.parametrize("write,expected", [(True, None), (True, "bad"), (False, "a" * 64)])
def test_invalid_write_arguments_fail_before_file_or_database_access(write, expected, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Should not access configuration, source, or database")

    monkeypatch.setattr("etl.localdata.floor_backfill.validate_local_target", forbidden)
    with pytest.raises(BackfillError, match="backfill:arguments"):
        run_backfill(
            Source.GENERAL_RESTAURANT, Path("missing.json"), write=write, expected_plan=expected
        )


def test_original_reference_date_and_provenance_are_preserved(tmp_path):
    source = prepared(tmp_path)
    assert source.batch_values["recorded_at"].replace(tzinfo=None) == source.collection.collected_at
    assert source.batch_values["collection_basis"] == "api_fetch_start"
    assert source.batch_values["row_count"] == 3
    assert "RESTORE" not in repr(source)
    assert digest({"b": [1, 2], "a": None}) == digest({"a": None, "b": [1, 2]})


def test_cli_suppresses_private_sql_exception_and_connection_details(monkeypatch, capsys):
    secret = "private-name-address-password-canary"

    def fail(*args, **kwargs):
        raise SQLAlchemyError(secret)

    monkeypatch.setattr("etl.localdata.floor_backfill.run_backfill", fail)
    assert main(["--source", "rest_cafe", "--snapshot", "private-path.json"]) == 1
    captured = capsys.readouterr()
    assert secret not in captured.out + captured.err
    assert "private-path" not in captured.out + captured.err
    assert json.loads(captured.out) == {"status": "error", "error": "backfill:database"}


def test_prepare_uses_original_day_for_future_date_quality_flag(tmp_path):
    row = raw("FUTURE-AT-IMPORT", LCPMT_YMD="20261112")
    path = save_snapshot(collection((row,)), tmp_path)
    value = prepare_source(path, Source.GENERAL_RESTAURANT)
    assert value.collection.collected_at.date().isoformat() == "2026-11-11"
    assert "open_date_future" in value.records[0].date_flag


def test_building_key_missing_cannot_promote_location_trust(tmp_path):
    record = next(r for r in prepared(tmp_path).records if r.license_no == "RESTORE")
    with pytest.raises(BackfillError, match="location_conflict"):
        location_change(None, "unverified", replace(record, building_key=None))
