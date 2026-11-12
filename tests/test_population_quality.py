import json
from dataclasses import replace
from datetime import date
from unittest.mock import Mock
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.analysis.population_quality import (
    GridHourCounts,
    QualityError,
    QualityQuery,
    QualityReport,
    UnlocatedCounts,
    summarize,
)
from app.core.config import Settings
from etl.living_pop import quality as cli

VID = UUID("00000000-0000-0000-0000-000000000001")
ARGS = ["--population-version", str(VID), "--lat", "37.5", "--lng", "127.0"]
GROUP = GridHourCounts("local", 0, "GRID-CANARY", 4, 1, 1, 1, 1, 2)


def report():
    return QualityReport(
        observation_version_id=VID,
        grid_version_id=VID,
        observation_date=date(2026, 11, 7),
        grid_as_of=None,
        spatial_compatibility="unverified",
        radius_m=500,
        selected_grid_count=2,
        hours=summarize(2, [GROUP]),
        unlocated=tuple(
            UnlocatedCounts(source=s, rows=0, grids=0) for s in ("local", "long", "short")
        ),
    )


def test_row_states_absent_grids_and_multi_admin_are_distinct():
    groups = [GROUP, GridHourCounts("local", 0, "other", 1, 0, 1, 0, 0, 1)]
    rows = summarize(2, groups)
    assert len(rows) == 72
    assert rows[0].model_dump() == dict(
        source="local",
        hour=0,
        rows=5,
        observed_zero=1,
        observed_nonzero=2,
        suppressed=1,
        missing=1,
        grids_with_rows=2,
        grids_without_rows=0,
        grids_with_nonobserved_rows=1,
        grids_with_multi_admin_rows=1,
    )
    assert rows[1].rows == 0 and rows[1].grids_without_rows == 2
    assert rows[24].source == "long" and rows[48].source == "short"
    assert [r.hour for r in rows[:24]] == list(range(24))
    assert all(r.grids_without_rows == 0 for r in summarize(0, []))


@pytest.mark.parametrize(
    "changes",
    [
        {"source": "other"},
        {"hour": -1},
        {"hour": 24},
        {"hour": True},
        {"grid_id": ""},
        {"rows": 0},
        {"rows": 5},
        {"missing": -1},
        {"observed_zero": True},
        {"admins": 0},
        {"admins": 5},
    ],
)
def test_invalid_row_groups_are_not_silently_counted(changes):
    with pytest.raises(QualityError, match="living_pop_quality:counts"):
        summarize(2, [replace(GROUP, **changes)])


@pytest.mark.parametrize(("n", "groups"), [(2, [GROUP, GROUP]), (0, [GROUP]), (-1, []), (True, [])])
def test_duplicate_overflow_and_invalid_grid_count_fail(n, groups):
    with pytest.raises(QualityError):
        summarize(n, groups)


@pytest.mark.parametrize(
    "values",
    [
        {"lat": float("nan")},
        {"lat": float("inf")},
        {"lng": -181.0},
        {"lat": 91.0},
        {"radius": 499},
        {"lat": True},
    ],
)
def test_query_rejects_nonfinite_or_unsupported_values(values):
    with pytest.raises(ValidationError):
        QualityQuery(**{"observation_version_id": VID, "lat": 37.5, "lng": 127.0, **values})


def test_report_output_has_only_declared_diagnostic_fields():
    value = json.loads(report().model_dump_json())
    assert set(value) == {
        "rule_version",
        "observation_version_id",
        "grid_version_id",
        "observation_date",
        "grid_as_of",
        "spatial_compatibility",
        "selection_basis",
        "radius_m",
        "selected_grid_count",
        "stored_counts_match_metadata",
        "content_hash_rechecked",
        "hours",
        "unlocated",
        "limitations",
    }
    assert (
        value["stored_counts_match_metadata"] is True and value["content_hash_rechecked"] is False
    )
    assert "GRID-CANARY" not in json.dumps(value)
    for row in value["hours"]:
        assert set(row) == {
            "source",
            "hour",
            "rows",
            "observed_zero",
            "observed_nonzero",
            "suppressed",
            "missing",
            "grids_with_rows",
            "grids_without_rows",
            "grids_with_nonobserved_rows",
            "grids_with_multi_admin_rows",
        }
        assert not any(
            word in key
            for key in row
            for word in ["complete", "coverage", "population", "rate", "ratio", "sum"]
        )
    query = QualityQuery(observation_version_id=VID, lat=37.5, lng=127.0)
    assert "lat=" not in repr(query) and "lng=" not in repr(query)


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--population-version", "ARG-CANARY"],
        [*ARGS, "--radius", "301"],
        [*ARGS, "--lat", "nan"],
        [*ARGS, "--unexpected=ARG-CANARY"],
    ],
)
def test_bad_cli_arguments_never_connect_or_echo_inputs(args, monkeypatch, capsys):
    run = Mock()
    monkeypatch.setattr(cli, "run_diagnostic", run)
    assert cli.main(args) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"error": "living_pop_quality:arguments"}
    assert "ARG-CANARY" not in captured.out + captured.err
    run.assert_not_called()


def test_cli_success_and_unexpected_failure_are_safe(monkeypatch, capsys):
    run = Mock(return_value=report())
    monkeypatch.setattr(cli, "run_diagnostic", run)
    assert cli.main(ARGS) == 0
    value = json.loads(capsys.readouterr().out)
    assert value["selected_grid_count"] == 2 and len(value["hours"]) == 72
    run.side_effect = RuntimeError("PRIVATE-DB-CANARY")
    assert cli.main(ARGS) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"error": "living_pop_quality:operation_failed"}
    assert "PRIVATE-DB-CANARY" not in captured.out + captured.err


def test_wrong_target_is_rejected_before_engine_creation(monkeypatch, capsys):
    monkeypatch.setattr(
        cli,
        "Settings",
        lambda: Settings(
            _env_file=None,
            database_url="postgresql://other:PRIVATE-CANARY@remote.example/db",
        ),
    )
    resources = Mock()
    monkeypatch.setattr(cli, "DatabaseResources", resources)
    assert cli.main(ARGS) == 1
    assert json.loads(capsys.readouterr().out) == {"error": "living_pop_quality:configuration"}
    resources.assert_not_called()
