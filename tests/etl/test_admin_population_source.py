import json
import sys

import pytest

from etl.admin_population import __main__ as cli
from etl.admin_population import source
from tests.etl.admin_population_helpers import boundary_zip, population_zip


@pytest.mark.parametrize("delimiter", [",", ";"])
def test_official_structure_masks_absence_and_actual_zero_are_preserved(tmp_path, delimiter):
    path = tmp_path / "population.zip"
    sha = population_zip(
        path,
        delimiter=delimiter,
        patches={
            ("11110530", 0): "0",
            ("11110530", 1): "*",
            ("11110530", 2): "",
        },
    )
    result = source.inspect_population(path, sha)
    assert result["row_count"] == 48
    assert result["statuses"] == {"observed": 46, "suppressed": 1, "missing": 1}
    assert result["complete_admin_days"] == 1
    assert result["max_precision"] == 2
    assert result["codes"] == ["11110530", "11110540"]
    assert result["data_delimiters"] == {delimiter: 1}


def test_exact_codes_only_and_cli_has_no_database_or_credentials(tmp_path, monkeypatch, capsys):
    pop, boundary = tmp_path / "pop.zip", tmp_path / "boundary.zip"
    psha, bsha = population_zip(pop), boundary_zip(boundary)
    report = source.inspect_sources(pop, psha, boundary, bsha)
    assert report["matched_code_count"] == 1
    assert report["population_only_codes"] == ["11110540"]
    assert report["boundary_only_codes"] == []
    assert report["population_total_validated"] is False
    assert report["boundary"]["geometry_validated_by_postgis"] is False
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "inspection",
            "--population-zip",
            str(pop),
            "--population-sha256",
            psha,
            "--boundary-zip",
            str(boundary),
            "--boundary-sha256",
            bsha,
        ],
    )
    assert cli.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["database_access"] is False


@pytest.mark.parametrize("value", ["NaN", "-1", "1e4", "1.000001", "1000000000000000", " 3", "1."])
def test_invalid_population_or_excess_precision_is_rejected_without_rounding(tmp_path, value):
    path = tmp_path / "bad.zip"
    sha = population_zip(path, patches={("11110530", 0): value})
    with pytest.raises(source.SourceInspectionError, match="^admin_population:invalid_source$"):
        source.inspect_population(path, sha)


@pytest.mark.parametrize(
    "options",
    [
        {"duplicate": True},
        {"member": "../250_LOCAL_RESD_ADMDONG_20261031.csv"},
        {"member": "250_LOCAL_RESD_ADMDONG_20261030.csv"},
    ],
)
def test_duplicate_identity_unexpected_member_and_date_mismatch_rejected(tmp_path, options):
    path = tmp_path / "bad.zip"
    sha = population_zip(path, **options)
    with pytest.raises(source.SourceInspectionError):
        source.inspect_population(path, sha)


@pytest.mark.parametrize("options", [{"cpg": b"CP949"}, {"crs": 4326}, {"code": "1234567"}])
def test_boundary_code_crs_and_encoding_must_match_declared_source(tmp_path, options):
    path = tmp_path / "bad.zip"
    sha = boundary_zip(path, **options)
    with pytest.raises(source.SourceInspectionError):
        source.inspect_boundary(path, sha)


def test_hash_and_resource_limits_fail_before_unbounded_processing(tmp_path, monkeypatch):
    path = tmp_path / "pop.zip"
    sha = population_zip(path)
    with pytest.raises(source.SourceInspectionError):
        source.inspect_population(path, "0" * 64)
    monkeypatch.setattr(source, "MAX_ROWS", 1)
    with pytest.raises(source.SourceInspectionError):
        source.inspect_population(path, sha)
    monkeypatch.setattr(source, "MAX_EXPANDED_BYTES", 1)
    with pytest.raises(source.SourceInspectionError):
        source.inspect_population(path, sha)


def test_cli_failure_does_not_print_input_path_or_raw_error(tmp_path, monkeypatch, capsys):
    private = tmp_path / "source-private-canary.zip"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "inspection",
            "--population-zip",
            str(private),
            "--population-sha256",
            "0" * 64,
            "--boundary-zip",
            str(private),
            "--boundary-sha256",
            "0" * 64,
        ],
    )
    assert cli.main() == 1
    out = capsys.readouterr().out
    assert "canary" not in out
    assert json.loads(out) == {
        "status": "failed",
        "reason": "invalid_source",
        "database_access": False,
    }
