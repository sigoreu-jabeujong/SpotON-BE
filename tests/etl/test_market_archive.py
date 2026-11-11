import hashlib
import json
import struct
import zipfile
from datetime import date, timedelta

import pytest

from etl.market_areas import __main__ as cli
from etl.market_areas.archive import MarketImportError, load_archive
from tests.etl.market_helpers import make_archive

DATE = date(2023, 10, 23)


def test_full_source_and_canonical_geometry(tmp_path) -> None:
    p = tmp_path / "source.zip"
    sha = make_archive(p)
    data = load_archive(p, sha, DATE)
    assert len(data.features) == 25 and len({f.gu_code for f in data.features}) == 25
    assert all(f.area_m2 == 100 and f.geometry["type"] == "Polygon" for f in data.features)
    assert data.input_sha256 == sha and data.source_file_date == DATE
    assert hashlib.sha256(p.read_bytes()).hexdigest() == sha


@pytest.mark.parametrize(
    "changes",
    [
        {"TRDAR_CD": "bad"},
        {"TRDAR_CD": "3110001"},
        {"SIGNGU_CD": "99999"},
        {"SIGNGU_CD": "11140"},
        {"TRDAR_CD_N": ""},
        {"TRDAR_SE_C": "X"},
        {"TRDAR_SE_1": "wrong"},
        {"RELM_AR": 0},
        {"RELM_AR": -1},
        {"RELM_AR": float("nan")},
        {"RELM_AR": float("inf")},
    ],
)
def test_bad_attributes_never_become_partial_snapshot(tmp_path, changes) -> None:
    p = tmp_path / "source.zip"
    sha = make_archive(p, patches={0: changes})
    with pytest.raises(MarketImportError):
        load_archive(p, sha, DATE)


@pytest.mark.parametrize(
    "replacements,crs,extra",
    [
        ({".cpg": b"CP949"}, 5181, None),
        ({".prj": b"invalid"}, 5181, None),
        ({}, 5186, None),
        ({}, 5181, ("unexpected.txt", b"bad")),
    ],
)
def test_invalid_archive_components(tmp_path, replacements, crs, extra) -> None:
    p = tmp_path / "source.zip"
    sha = make_archive(p, replacements=replacements, crs=crs, extra=extra)
    with pytest.raises(MarketImportError):
        load_archive(p, sha, DATE)


@pytest.mark.parametrize("unsafe", ["../synthetic.cpg", "/synthetic.cpg", "C:/synthetic.cpg"])
def test_archive_member_paths_cannot_escape_or_rename_layer(tmp_path, unsafe) -> None:
    p = tmp_path / "source.zip"
    make_archive(p)
    with zipfile.ZipFile(p) as z:
        parts = [(i.filename, z.read(i)) for i in z.infolist()]
    with zipfile.ZipFile(p, "w") as z:
        for name, blob in parts:
            z.writestr(unsafe if name.endswith(".cpg") else name, blob)
    sha = hashlib.sha256(p.read_bytes()).hexdigest()
    with pytest.raises(MarketImportError):
        load_archive(p, sha, DATE)


def test_hash_date_limits_deleted_rows_and_orientation(tmp_path, monkeypatch) -> None:
    from etl.market_areas import archive

    p = tmp_path / "source.zip"
    sha = make_archive(p)
    for wrong in ["0" * 64, "invalid"]:
        with pytest.raises(MarketImportError):
            load_archive(p, wrong, DATE)
    with pytest.raises(MarketImportError):
        load_archive(p, sha, date.today() + timedelta(days=3))
    with zipfile.ZipFile(p) as z:
        dbf = bytearray(z.read("synthetic.dbf"))
    head = struct.unpack("<H", dbf[8:10])[0]
    dbf[head] = ord("*")
    sha = make_archive(p, replacements={".dbf": bytes(dbf)})
    with pytest.raises(MarketImportError):
        load_archive(p, sha, DATE)
    hole = [
        [[200000, 450000], [200010, 450000], [200010, 450010], [200000, 450010], [200000, 450000]]
    ]
    sha = make_archive(p, shapes={0: hole})
    with pytest.raises(MarketImportError, match="orientation"):
        load_archive(p, sha, DATE)
    sha = make_archive(p)
    monkeypatch.setattr(archive, "MAX_EXPANDED_BYTES", 100)
    with pytest.raises(MarketImportError):
        load_archive(p, sha, DATE)


def test_cli_failure_does_not_echo_arguments_or_source(tmp_path, capsys, monkeypatch) -> None:
    p = tmp_path / "path-private-canary.zip"
    make_archive(p)
    guard = []
    monkeypatch.setattr(cli, "create_db_engine", lambda *a: guard.append(True))
    code = cli.main(
        ["--zip", str(p), "--expected-sha256", "0" * 64, "--source-file-date", DATE.isoformat()]
    )
    assert code == 1 and not guard
    output = capsys.readouterr()
    assert "canary" not in output.out + output.err
    assert json.loads(output.out)["error"] == "market:hash_mismatch"
    assert cli.main(["--private-key", "private-secret-canary"]) == 1
    output = capsys.readouterr()
    assert "canary" not in output.out + output.err


def test_malformed_crc_symlink_and_duplicate_suffix(tmp_path) -> None:
    p = tmp_path / "source.zip"
    for mode in ["crc", "symlink", "duplicate"]:
        make_archive(p)
        with zipfile.ZipFile(p) as z:
            parts = [(i, z.read(i)) for i in z.infolist()]
        with zipfile.ZipFile(p, "w", zipfile.ZIP_STORED) as z:
            for info, blob in parts:
                if info.filename.endswith(".cpg") and mode == "symlink":
                    info.external_attr = 0o120777 << 16
                if info.filename.endswith(".prj") and mode == "duplicate":
                    info.filename = "SYNTHETIC.CPG"
                z.writestr(info, blob)
        if mode == "crc":
            value = bytearray(p.read_bytes())
            central = value.index(b"PK\x01\x02")
            value[central + 16] ^= 1
            p.write_bytes(value)
        sha = hashlib.sha256(p.read_bytes()).hexdigest()
        with pytest.raises(MarketImportError):
            load_archive(p, sha, DATE)


def test_coordinate_and_shape_guards() -> None:
    from types import SimpleNamespace

    from etl.market_areas.archive import _geometry

    for shape in [
        SimpleNamespace(shapeType=0),
        SimpleNamespace(shapeType=1),
        SimpleNamespace(shapeType=5, points=[[float("nan"), 450000]], parts=[0]),
        SimpleNamespace(shapeType=5, points=[[1e100, 450000]], parts=[0]),
    ]:
        with pytest.raises(MarketImportError):
            _geometry(shape)
