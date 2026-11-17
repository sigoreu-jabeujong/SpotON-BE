import hashlib
import json
import sys
import zipfile

import pytest

from etl.admin_population import __main__ as cli
from etl.admin_population import source
from tests.etl.admin_population_helpers import boundary_zip, population_zip


def test_same_zip_accepts_explicit_mixed_file_delimiters(tmp_path):
    first, second = tmp_path / "a.zip", tmp_path / "b.zip"
    population_zip(first, delimiter=";")
    population_zip(second, delimiter=",", day="20261030")
    combined = tmp_path / "combined.zip"
    with zipfile.ZipFile(combined, "w", zipfile.ZIP_DEFLATED) as target:
        for path in (first, second):
            with zipfile.ZipFile(path) as source_zip:
                for name in source_zip.namelist():
                    target.writestr(name, source_zip.read(name))
    result = source.inspect_population(combined, hashlib.sha256(combined.read_bytes()).hexdigest())
    assert result["data_delimiters"] == {";": 1, ",": 1}
    assert result["row_count"] == 96 and result["complete_admin_days"] == 4


@pytest.mark.parametrize(
    "extension,bad_bytes",
    [
        (".prj", b"source-private-canary-invalid-WKT"),
        (".shp", b"bad"),
        (".dbf", b"bad"),
    ],
)
def test_corrupt_geometry_components_never_expose_raw_parsing_errors(
    tmp_path, extension, bad_bytes
):
    original, broken = tmp_path / "valid.zip", tmp_path / "broken.zip"
    boundary_zip(original)
    with zipfile.ZipFile(original) as z, zipfile.ZipFile(broken, "w") as out:
        for name in z.namelist():
            out.writestr(name, bad_bytes if name.endswith(extension) else z.read(name))
    with pytest.raises(source.SourceInspectionError, match="^admin_population:invalid_source$"):
        source.inspect_boundary(broken, hashlib.sha256(broken.read_bytes()).hexdigest())


def test_cli_last_error_boundary_returns_only_fixed_json(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "inspection",
            "--population-zip",
            "unused",
            "--population-sha256",
            "0" * 64,
            "--boundary-zip",
            "unused",
            "--boundary-sha256",
            "0" * 64,
        ],
    )

    def broken(*args):
        raise RuntimeError("source-private-canary")

    monkeypatch.setattr(cli, "inspect_sources", broken)
    assert cli.main() == 1
    result = capsys.readouterr()
    assert result.err == "" and "canary" not in result.out
    assert json.loads(result.out)["reason"] == "invalid_source"
