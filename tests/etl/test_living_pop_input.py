import io
import json
from datetime import date
from decimal import Decimal

import pytest

from etl.living_pop import __main__ as cli
from etl.living_pop import grid as g
from etl.living_pop import source as s
from etl.living_pop.data import PopulationImportError, observations_hash
from etl.living_pop.input import load_input
from tests.etl.living_pop_helpers import make_manifest, source_rows, write_source


def test_sources_admin_mask_null_zero_and_unlocated_preserved(tmp_path):
    p = make_manifest(tmp_path)
    d = load_input(p)
    assert len(d.rows) == 168 and len(d.grid.features) == 2
    assert sum(not r.located for r in d.rows) == 24
    assert d.sources["local"]["statuses"] == {"observed": 46, "suppressed": 25, "missing": 1}
    for kind in ("long", "short"):
        assert d.sources[kind]["statuses"] == {"observed": 46, "suppressed": 1, "missing": 1}
    assert len({r.admin_code for r in d.rows}) == 2
    assert any(r.population == 0 and r.value_status == "observed" for r in d.rows)
    assert all(r.population is None for r in d.rows if r.value_status != "observed")
    before = d.content_sha256
    reversed_rows = list(reversed(source_rows("local")))
    config = json.loads(p.read_text(encoding="utf-8"))
    path = tmp_path / "local.zip"
    config["sources"]["local"]["sha256"] = write_source(path, "local", reversed_rows)
    p.write_text(json.dumps(config), encoding="utf-8")
    again = load_input(p)
    assert again.content_sha256 == before


@pytest.mark.parametrize(
    "raw,status,value",
    [
        ("*", "suppressed", None),
        ("", "missing", None),
        ("0", "observed", Decimal("0")),
        ("0.00", "observed", Decimal("0")),
        ("12.34", "observed", Decimal("12.34")),
        ("0.", "observed", Decimal("0")),
        ("12.", "observed", Decimal("12")),
    ],
)
def test_population_states(raw, status, value):
    got, state = s.population_cell(raw)
    assert state == status and got == value


@pytest.mark.parametrize(
    "value",
    [
        " *",
        " ",
        "-",
        "-1",
        "+1",
        "1e3",
        "1,000",
        "NaN",
        "Infinity",
        "0.000001",
        "01",
        "１",
        "١",
        ".5",
        ".",
        "1000000000000000",
    ],
)
def test_bad_numbers_rejected(value):
    with pytest.raises(PopulationImportError):
        s.population_cell(value)


@pytest.mark.parametrize(
    "source,change",
    [
        ("long", lambda rows: [r[:-1] for r in rows]),
        ("short", lambda rows: [r + [""] for r in rows]),
        ("local", lambda rows: [r + [""] for r in rows]),
        ("long", lambda rows: [r[:-1] + [" "] for r in rows]),
        ("local", lambda rows: rows + [rows[0]]),
        ("local", lambda rows: [r for r in rows if r[1] != "23"]),
        ("local", lambda rows: [r[:1] + ["24"] + r[2:] for r in rows]),
        ("local", lambda rows: [["20261108"] + r[1:] for r in rows]),
        ("local", lambda rows: [r[:2] + [r[2][:-1]] + r[3:] for r in rows]),
        ("local", lambda rows: [r[:2] + [r[2] + " "] + r[3:] for r in rows]),
        ("local", lambda rows: [r[:2] + ["11110530\t"] + r[3:] for r in rows]),
        ("short", lambda rows: [r[:5] + ["bad"] + r[6:] for r in rows]),
    ],
)
def test_no_row_skip_or_padding_loss(tmp_path, source, change):
    with pytest.raises(PopulationImportError):
        load_input(make_manifest(tmp_path, patches={source: change}))


def test_manifest_exact_sources_paths_dates_hashes_and_safe_cli(tmp_path, monkeypatch, capsys):
    p = make_manifest(tmp_path)
    base = json.loads(p.read_text(encoding="utf-8"))
    changes = [
        {**base, "extra": 1},
        {**base, "observation_date": "2099-01-01"},
        {**base, "sources": {k: v for k, v in base["sources"].items() if k != "short"}},
    ]
    for value in changes:
        p.write_text(json.dumps(value), encoding="utf-8")
        with pytest.raises(PopulationImportError):
            load_input(p)
    p.write_text('{"grid":{},"grid":{}}', encoding="utf-8")
    with pytest.raises(PopulationImportError):
        load_input(p)
    p.write_text(json.dumps(base), encoding="utf-8")
    with monkeypatch.context() as m:
        m.setattr(s, "ROOT", tmp_path)
        with pytest.raises(PopulationImportError, match="repository_input"):
            load_input(p)
    base["sources"]["local"]["sha256"] = "0" * 64
    p.write_text(json.dumps(base), encoding="utf-8")

    def forbidden(*args, **kwargs):
        pytest.fail("unexpected_db")

    monkeypatch.setattr(cli, "create_db_engine", forbidden)
    assert cli.main(["--manifest", str(p)]) == 1
    assert cli.main(["--unknown", "private-canary"]) == 1
    assert "private-canary" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "kwargs", [{"crs": 5181}, {"crs": 5186}, {"width": 249.9}, {"duplicate": True}]
)
def test_wrong_grid_crs_and_geometry(tmp_path, kwargs):
    with pytest.raises(PopulationImportError):
        load_input(make_manifest(tmp_path, grid_kwargs=kwargs))


def test_streaming_and_named_limits(tmp_path, monkeypatch):
    p = make_manifest(tmp_path)
    for module, name in (
        (s, "MAX_ROWS"),
        (s, "MAX_FIELD"),
        (s, "MAX_ZIP_BYTES"),
        (s, "MAX_CSV_BYTES"),
        (g, "MAX_GRID_ZIP"),
        (g, "MAX_GRID_EXPANDED"),
        (g, "MAX_GRIDS"),
    ):
        with monkeypatch.context() as m:
            m.setattr(module, name, 1)
            with pytest.raises(PopulationImportError):
                load_input(p)
    with monkeypatch.context() as m:
        m.setattr(s, "MAX_CSV_BYTES", 2)
        stream = s.CountingReader(io.BytesIO(b"ABC"))
        with pytest.raises(PopulationImportError):
            stream.readinto(bytearray(3))


def test_hash_decimal_zero_and_field_changes(tmp_path):
    d = load_input(make_manifest(tmp_path))
    rows = [r.payload() for r in d.rows]
    baseline = observations_hash(rows, d.manifest.day, d.grid.sha256, len(rows))
    zero = next(r for r in rows if r["population"] == "0.00000")
    zero["population"] = Decimal("0E-5")
    assert observations_hash(rows, d.manifest.day, d.grid.sha256, len(rows)) == baseline
    zero["population"] = Decimal("1")
    assert observations_hash(rows, d.manifest.day, d.grid.sha256, len(rows)) != baseline


def test_incremental_hash_fixed_vector():
    row = dict(
        source="local",
        hour=0,
        admin_code="11110530",
        grid_id="가가00000000",
        located_grid_id="가가00000000",
        population=Decimal("12"),
        value_status="observed",
        geometry_status="located",
        source_row_sha256="1" * 64,
    )
    assert (
        observations_hash([row], date(2026, 11, 7), "0" * 64, 1)
        == "8c57660c707574ee23f2bed55a9015dc5d6c2bd98ef4abae5d6a56361e0250a7"
    )


def test_trailing_decimal_preserves_raw_hash_and_counts(tmp_path):
    def patch(rows):
        rows[3][4] = "12."
        rows[3][5] = "1."
        return rows

    d = load_input(make_manifest(tmp_path, patches={"local": patch}))
    row = next(
        r for r in d.rows if r.source == "local" and r.hour == 1 and r.admin_code == "11110540"
    )
    assert row.population == Decimal("12.00000")
    assert d.sources["local"]["trailing_decimal_points"] == {"total": 1, "detail": 1}
