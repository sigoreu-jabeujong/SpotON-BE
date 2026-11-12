import json
from dataclasses import replace
from decimal import Decimal

import pytest

from app.core import operations
from app.core.config import Settings
from etl.living_pop import __main__ as cli
from etl.living_pop import observability as quality
from etl.living_pop.data import Observation
from etl.living_pop.input import load_input
from tests.etl.living_pop_helpers import make_manifest

EXPECTED = dict(
    suppressed_rows=27,
    missing_value_rows=3,
    observed_zero_rows=3,
    unlocated_rows=24,
    multi_admin_groups=72,
    multi_admin_rows=144,
)


def records(capsys):
    return [json.loads(line) for line in capsys.readouterr().err.splitlines()]


def test_real_manifest_summary_preserves_rows_hashes_and_absence(tmp_path):
    daily = load_input(make_manifest(tmp_path))
    before = [row.payload() for row in daily.rows]
    identities = [id(row) for row in daily.rows]
    hashes = daily.input_sha256, daily.content_sha256
    assert len(daily.rows) == 168
    assert quality.summarize(daily.rows) == EXPECTED
    assert daily.input_sha256 == hashes[0] and daily.content_sha256 == hashes[1]
    assert identities == [id(row) for row in daily.rows]
    assert [row.payload() for row in daily.rows] == before
    # The second geometry cell has no source row; neither rows nor zeroes are synthesized.
    assert len(daily.rows) == 168
    assert sum(row.population == 0 for row in daily.rows) == 3


def test_distinct_admin_only_and_source_hour_grid_isolation():
    row = Observation("local", 0, "admin-a", "grid-a", Decimal(0), "observed", True, b"x")
    rows = [
        row,
        row,  # Repeated identical admin does not establish a second admin.
        replace(row, grid_id="grid-b"),
        replace(row, grid_id="unlocated", located=False),
        replace(row, grid_id="unlocated", admin_code="admin-b", located=False),
        replace(row, hour=1),
        replace(row, source="long", admin_code="admin-b"),
    ]
    summary = quality.summarize(rows)
    assert summary == {
        **{key: 0 for key in EXPECTED},
        **dict(observed_zero_rows=7, unlocated_rows=2, multi_admin_groups=1, multi_admin_rows=2),
    }
    assert quality.summarize([]) == {key: 0 for key in EXPECTED}


def test_status_not_nullable_value_decides_zero_or_suppression():
    row = Observation("local", 0, "a", "g", None, "missing", True, b"x")
    rows = [row, replace(row, value_status="suppressed"), replace(row, value_status="observed")]
    assert quality.summarize(rows) == {
        **{key: 0 for key in EXPECTED},
        "suppressed_rows": 1,
        "missing_value_rows": 1,
    }


@pytest.mark.parametrize(
    "bad",
    [
        None,
        {},
        {**EXPECTED, "unlocated_rows": True},
        {**EXPECTED, "unlocated_rows": -1},
        {**EXPECTED, "unlocated_rows": 2**63},
        {**EXPECTED, "unlocated_rows": 1.0},
    ],
)
def test_incomplete_invalid_counts_never_report_completed_or_fake_zero(bad, capsys):
    @operations.logged_import("living_pop")
    def run():
        operations.population_quality(bad)
        return {"rows": 168}

    assert run() == {"rows": 168}
    event = records(capsys)[1]
    assert event["event"] == "etl_quality" and event["status"] == "failed"
    assert event["reason"] == "quality_summary_unavailable" and "counts" not in event


def test_fixed_event_keys_and_context_gate(capsys, monkeypatch):
    operations.population_quality(EXPECTED)
    assert records(capsys) == []

    @operations.logged_import("market_sales")
    def other():
        operations.population_quality(EXPECTED)
        return {}

    other()
    assert len(records(capsys)) == 2

    @operations.logged_import("living_pop")
    def run():
        operations.population_quality({**EXPECTED, "private-code": "private-value"})
        return {}

    run()
    event = records(capsys)[1]
    assert set(event) == {
        "time",
        "event",
        "source",
        "run_id",
        "stage",
        "status",
        "scope",
        "spatial_compatibility",
        "aggregation_status",
        "counts",
    }
    assert event["counts"] == EXPECTED
    assert event["scope"] == "source_day_all_sources"
    assert event["spatial_compatibility"] == "unverified"
    assert event["aggregation_status"] == "pending"
    for identifier in (None, "private-invalid-id"):
        monkeypatch.setattr(operations, "new_id", lambda value=identifier: value)
        run()
        assert not any(e["event"] == "etl_quality" for e in records(capsys))


@pytest.mark.parametrize("point", ["Settings", "validate_local_target", "create_db_engine"])
def test_quality_precedes_setup_failure_without_changing_cli_error(
    point, tmp_path, monkeypatch, capsys
):
    path = make_manifest(tmp_path)
    monkeypatch.setattr(
        cli,
        "Settings",
        lambda: Settings(
            _env_file=None, database_url="postgresql://spoton_app:fake@localhost/spoton_dev"
        ),
    )

    def fail(*args, **kwargs):
        raise RuntimeError("private-failure")

    monkeypatch.setattr(cli, point, fail)
    assert cli.main(["--manifest", str(path)]) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"error": "living_pop:operation_failed"}
    events = [json.loads(line) for line in captured.err.splitlines()]
    assert [(e["stage"], e["status"]) for e in events[:3]] == [
        ("import", "started"),
        ("read_source", "started"),
        ("read_source", "completed"),
    ]
    assert events[3]["event"] == "etl_quality" and events[3]["counts"] == EXPECTED
    assert events[-1]["event"] == "etl_run" and events[-1]["status"] == "failed"
    for marker in (str(path), "가가", "11110530", "12.34", "postgresql", "private-failure"):
        assert marker not in captured.err


def test_bad_block_order_reports_summary_failure_without_reordering(capsys):
    row = Observation("local", 0, "a", "g", None, "missing", True, b"x")
    rows = [row, replace(row, hour=1), row]
    before = [r.payload() for r in rows]

    @operations.logged_import("living_pop")
    def run():
        quality.record_quality(rows)
        return {"rows": len(rows)}

    assert run() == {"rows": 3}
    event = records(capsys)[1]
    assert event["status"] == "failed" and "counts" not in event
    assert before == [r.payload() for r in rows]


def test_summary_exception_is_private_but_cancellation_propagates(monkeypatch, capsys):
    def fail(rows):
        raise RuntimeError("private-summary-failure")

    monkeypatch.setattr(quality, "summarize", fail)

    @operations.logged_import("living_pop")
    def run():
        quality.record_quality([])
        return {"rows": 0}

    assert run() == {"rows": 0}
    event = records(capsys)[1]
    assert event["status"] == "failed" and "private" not in json.dumps(event)

    def cancel(rows):
        raise KeyboardInterrupt

    monkeypatch.setattr(quality, "summarize", cancel)
    with pytest.raises(KeyboardInterrupt):
        run()
    events = records(capsys)
    assert len(events) == 2 and events[-1]["status"] == "failed"


def test_quality_sink_failure_does_not_replace_result(monkeypatch):
    emit = operations._emit

    def fail_quality(event):
        if event["event"] == "etl_quality":
            raise OSError("private-sink-error")
        emit(event)

    monkeypatch.setattr(operations, "_emit", fail_quality)

    @operations.logged_import("living_pop")
    def run():
        quality.record_quality([])
        return {"rows": 0}

    assert run() == {"rows": 0}
