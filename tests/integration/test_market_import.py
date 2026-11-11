from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date
from threading import Barrier

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select, text, update

from app.core.config import Settings
from app.models import MarketArea, MarketAreaVersion
from etl.market_areas import __main__ as cli
from etl.market_areas.archive import MarketImportError, load_archive
from etl.market_areas.geometry import prepare
from etl.market_areas.repository import save
from tests.etl.market_helpers import make_archive
from tests.integration.test_localdata_upsert import migrate

pytestmark = pytest.mark.integration
DATE = date(2023, 10, 23)


@pytest.fixture
def source(tmp_path):
    p = tmp_path / "synthetic.zip"
    sha = make_archive(p)
    return p, sha, load_archive(p, sha, DATE)


def test_full_write_replay_new_rule_conflict_and_tamper(temporary_database, source) -> None:
    migrate(temporary_database)
    e = temporary_database.engine
    with e.connect() as c:
        prepared = prepare(c, source[2])
    with e.begin() as c:
        vid, reused = save(c, prepared)
        assert not reused
        original = c.execute(
            select(MarketAreaVersion.loaded_at, MarketAreaVersion.content_sha256)
        ).one()
    with e.begin() as c:
        again, reused = save(c, prepared)
        assert again == vid and reused
        assert (
            c.execute(select(MarketAreaVersion.loaded_at, MarketAreaVersion.content_sha256)).one()
            == original
        )
        other, _ = save(c, prepared, rule_version="synthetic-rule-v2")
        assert other != vid
    with pytest.raises(MarketImportError), e.begin() as c:
        save(
            c,
            replace(prepared, source=replace(prepared.source, source_file_date=date(2023, 10, 24))),
        )
    with e.begin() as c:
        c.execute(
            update(MarketArea)
            .where(MarketArea.version_id == vid, MarketArea.market_code == "3110000")
            .values(market_name="tampered")
        )
    with pytest.raises(MarketImportError, match="stored_content"), e.begin() as c:
        save(c, prepared)
    with e.connect() as c:
        assert c.scalar(select(func.count()).select_from(MarketArea)) == 50
        assert c.scalar(select(func.count()).select_from(MarketAreaVersion)) == 2


def test_commit_digest_failure_rolls_back_everything(
    temporary_database, source, monkeypatch
) -> None:
    from etl.market_areas import repository

    migrate(temporary_database)
    e = temporary_database.engine
    with e.connect() as c:
        prepared = prepare(c, source[2])

    def fail(*args):
        raise MarketImportError("market:injected_digest_failure")

    monkeypatch.setattr(repository, "_verify", fail)
    with pytest.raises(MarketImportError), e.begin() as c:
        save(c, prepared)
    with e.connect() as c:
        assert c.scalar(select(func.count()).select_from(MarketArea)) == 0
        assert c.scalar(select(func.count()).select_from(MarketAreaVersion)) == 0


def test_concurrent_writers_reuse_one_atomic_version(temporary_database, source) -> None:
    migrate(temporary_database)
    e = temporary_database.engine
    with e.connect() as c:
        prepared = prepare(c, source[2])
    barrier = Barrier(2)

    def write():
        with e.begin() as c:
            barrier.wait(timeout=10)
            return save(c, prepared)

    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(write) for _ in range(2)]
        results = [job.result(timeout=20) for job in jobs]
    assert len({v for v, _ in results}) == 1 and sorted(r for _, r in results) == [False, True]
    with e.connect() as c:
        assert c.scalar(select(func.count()).select_from(MarketArea)) == 25


def test_holes_multipart_boundary_and_gist(temporary_database, tmp_path) -> None:
    p = tmp_path / "shapes.zip"
    outer = [
        [200000, 450000],
        [200000, 450010],
        [200010, 450010],
        [200010, 450000],
        [200000, 450000],
    ]
    hole = [
        [200002, 450002],
        [200008, 450002],
        [200008, 450008],
        [200002, 450008],
        [200002, 450002],
    ]
    a = [[200030, 450000], [200030, 450010], [200040, 450010], [200040, 450000], [200030, 450000]]
    b = [[200050, 450000], [200050, 450010], [200060, 450010], [200060, 450000], [200050, 450000]]
    sha = make_archive(
        p, shapes={0: [outer, hole], 1: [a, b]}, patches={0: {"RELM_AR": 64}, 1: {"RELM_AR": 200}}
    )
    migrate(temporary_database)
    e = temporary_database.engine
    with e.begin() as c:
        prepared = prepare(c, load_archive(p, sha, DATE))
        vid, _ = save(c, prepared)
        row = c.execute(
            text("""SELECT
          ST_Covers(geom,ST_Transform(ST_SetSRID(ST_Point(200000,450000),5181),4326)) boundary,
          ST_Contains(geom,ST_Transform(ST_SetSRID(ST_Point(200000,450000),5181),4326)) interior,
          ST_Covers(geom,ST_Transform(ST_SetSRID(ST_Point(200005,450005),5181),4326)) hole,
          ST_NumInteriorRings(ST_GeometryN(geom,1)) holes FROM market_areas
          WHERE version_id=:v AND market_code='3110000' """),
            {"v": vid},
        ).one()
        assert row.boundary and not row.interior and not row.hole and row.holes == 1
        assert (
            c.scalar(
                text("SELECT ST_NumGeometries(geom) FROM market_areas WHERE market_code='3110001'")
            )
            == 2
        )
        c.execute(text("SET LOCAL enable_seqscan=off"))
        plan = c.scalar(
            text(
                "EXPLAIN (FORMAT JSON) SELECT market_code FROM market_areas WHERE "
                "ST_Covers(geom,ST_Transform(ST_SetSRID(ST_Point(200001,450001),5181),4326))"
            )
        )
        assert "ix_market_areas_geom_gist" in str(plan) and "Index Cond" in str(plan)


def test_bowtie_repair_and_quality_rejects(temporary_database, tmp_path) -> None:
    p = tmp_path / "bowtie.zip"
    ring = list(
        reversed(
            [
                [200000, 450000],
                [200000, 450010],
                [200010, 450000],
                [200010, 450020],
                [200000, 450000],
            ]
        )
    )
    sha = make_archive(p, shapes={0: [ring]}, patches={0: {"RELM_AR": 83.33}})
    archive = load_archive(p, sha, DATE)
    migrate(temporary_database)
    e = temporary_database.engine
    with e.begin() as c:
        prepared = prepare(c, archive)
        assert sum(a.geometry_repaired for a in prepared.areas) == 1
        save(c, prepared)
    for change in [
        {"area_m2": archive.features[0].area_m2 * 2},
        {"geometry": {"type": "Polygon", "coordinates": [[[1, 1], [1, 2], [2, 2], [1, 1]]]}},
        {
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [[200000, 450000], [200001, 450001], [200002, 450002], [200000, 450000]]
                ],
            }
        },
    ]:
        feature = replace(archive.features[0], **change)
        with pytest.raises(MarketImportError), e.connect() as c:
            prepare(c, replace(archive, features=(feature, *archive.features[1:])))


def test_actual_runner_dry_run_write_and_safe_output(
    temporary_database, source, monkeypatch, capsys, caplog
) -> None:
    migrate(temporary_database)
    e = temporary_database.engine
    modes = []

    def guard(c):
        modes.append(c.scalar(text("SHOW transaction_read_only")))

    monkeypatch.setattr(cli, "create_db_engine", lambda *a: e)
    monkeypatch.setattr(cli, "check_local_database", guard)
    config = Settings(
        _env_file=None,
        database_url=SecretStr("postgresql+psycopg://spoton_app:synthetic@127.0.0.1/spoton_dev"),
    )
    path, sha, _ = source
    dry = cli.run_import(path, sha, DATE, settings=config)
    assert dry["inserted"] == 0 and dry["mode"] == "dry_run" and modes == ["on"]
    with e.connect() as c:
        assert c.scalar(select(func.count()).select_from(MarketArea)) == 0
    original = cli.run_import
    monkeypatch.setattr(cli, "run_import", lambda *a, **k: original(*a, **k, settings=config))
    assert (
        cli.main(
            [
                "--zip",
                str(path),
                "--expected-sha256",
                sha,
                "--source-file-date",
                DATE.isoformat(),
                "--write",
            ]
        )
        == 0
    )
    output = capsys.readouterr()
    assert "canary" not in output.out + output.err + caplog.text
    assert "off" in modes and "on" in modes
    with e.connect() as c:
        assert c.scalar(select(func.count()).select_from(MarketArea)) == 25
        assert c.scalar(select(MarketAreaVersion.boundary_as_of)) is None
