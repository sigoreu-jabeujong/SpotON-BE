from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

import pytest
from sqlalchemy import func, select, text, update

from app.core.config import Settings
from app.models import LivingGrid as G
from app.models import LivingGridVersion as GV
from app.models import LivingPopulationObservation as O
from app.models import LivingPopulationVersion as V
from etl.living_pop import __main__ as cli
from etl.living_pop import repository as repo
from etl.living_pop.data import PopulationImportError
from etl.living_pop.grid import prepare_grid
from etl.living_pop.input import load_input
from tests.etl.living_pop_helpers import make_manifest
from tests.integration.test_localdata_upsert import migrate

pytestmark = pytest.mark.integration


@pytest.fixture
def source(temporary_database, tmp_path):
    migrate(temporary_database)
    e = temporary_database.engine
    p = make_manifest(tmp_path)
    daily = load_input(p)
    with e.connect() as c:
        grid = prepare_grid(c, daily.grid)
    return e, p, daily, grid


def test_atomic_all_sources_replay_new_rule_and_missing_geometry(source):
    e, p, d, g = source
    with e.begin() as c:
        gid, vid, reused, inserted = repo.save(c, d, g)
        assert not reused and inserted == 2
        before = c.execute(select(V.loaded_at, V.content_sha256)).one()
    with e.begin() as c:
        again, version, reused, inserted = repo.save(c, d, g)
        assert (again, version, reused, inserted) == (gid, vid, True, 0)
        assert c.execute(select(V.loaded_at, V.content_sha256)).one() == before
        assert c.scalar(select(func.count()).select_from(O)) == 168
        assert (
            c.scalar(select(func.count()).select_from(O).where(O.geometry_status == "unlocated"))
            == 24
        )
        assert c.scalar(select(func.count()).select_from(O).where(O.population == 0)) == 3
        query = (
            select(func.count())
            .select_from(O)
            .join(G, (G.grid_version_id == O.grid_version_id) & (G.grid_id == O.located_grid_id))
        )
        assert c.scalar(query) == 144
        assert c.scalar(query.where(O.geometry_status == "unlocated")) == 0
        assert (
            c.scalar(
                select(func.count())
                .select_from(O)
                .where(O.hour == 0, O.source == "local", O.grid_id == "가가00000000")
            )
            == 2
        )
        assert c.scalar(select(GV.grid_as_of)) is None
        assert c.scalar(select(V.spatial_compatibility)) == "unverified"
        _, other, _, _ = repo.save(c, d, g, rule="synthetic-v2")
        assert other != vid
        assert c.scalar(select(func.count()).select_from(G)) == 2
        assert c.scalar(select(func.count()).select_from(O)) == 336


def test_all_four_tables_rollback_on_post_insert_failure(source, monkeypatch):
    e, p, d, g = source

    def fail(*args, **kwargs):
        raise PopulationImportError("living_pop:injected")

    monkeypatch.setattr(repo, "_verify_observations", fail)
    with pytest.raises(PopulationImportError), e.begin() as c:
        repo.save(c, d, g)
    with e.connect() as c:
        for model in (O, V, G, GV):
            assert c.scalar(select(func.count()).select_from(model)) == 0


def test_two_writers_one_grid_and_population_version(source):
    e, p, d, g = source
    barrier = Barrier(2)

    def work():
        with e.connect() as c, c.begin():
            barrier.wait(timeout=10)
            return repo.save(c, d, g)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(work) for _ in range(2)]
        got = [r.result(timeout=20) for r in results]
    assert got[0][:2] == got[1][:2] and sorted(r[2] for r in got) == [False, True]
    with e.connect() as c:
        assert c.scalar(select(func.count()).select_from(V)) == 1
        assert c.scalar(select(func.count()).select_from(GV)) == 1


@pytest.mark.parametrize("target", ["grid", "observation", "metadata"])
def test_stored_content_and_manifest_tamper_rejected(source, target):
    e, p, d, g = source
    with e.begin() as c:
        gid, vid, _, _ = repo.save(c, d, g)
        if target == "grid":
            c.execute(update(G).where(G.grid_version_id == gid).values(source_gid="tampered"))
        elif target == "observation":
            c.execute(
                update(O)
                .where(O.version_id == vid, O.value_status == "observed")
                .values(population=Decimal("99"))
            )
        else:
            c.execute(update(V).where(V.version_id == vid).values(sources={}))
    with pytest.raises(PopulationImportError), e.begin() as c:
        repo.save(c, d, g)


def test_known_grid_cannot_be_reclassified_unlocated(source):
    e, p, d, g = source
    with e.begin() as c:
        gid, vid, _, _ = repo.save(c, d, g)
        c.execute(
            update(O)
            .where(O.version_id == vid, O.geometry_status == "located")
            .values(geometry_status="unlocated", located_grid_id=None)
        )
    with pytest.raises(PopulationImportError, match="stored_location"), e.begin() as c:
        repo.save(c, d, g)


def test_real_cli_read_only_plan_safe_output_and_timeout(source, monkeypatch, capsys):
    e, p, d, g = source
    states = []
    config = Settings(
        _env_file=None, database_url="postgresql://spoton_app:synthetic@localhost/spoton_dev"
    )
    monkeypatch.setattr(cli, "Settings", lambda: config)
    monkeypatch.setattr(cli, "create_db_engine", lambda _: e)

    def check(c):
        assert c.scalar(text("SELECT version_num FROM alembic_version")) == "0010"
        states.append(
            (
                c.scalar(text("SHOW transaction_read_only")),
                c.scalar(text("SHOW transaction_isolation")),
            )
        )

    monkeypatch.setattr(cli, "check_local_database", check)
    dry = cli.run_import(p, settings=config)
    assert dry["inserted"] == dry["inserted_grids"] == 0 and not dry["would_reuse"]
    with e.connect() as c:
        for m in (O, V, G, GV):
            assert c.scalar(select(func.count()).select_from(m)) == 0
    assert cli.main(["--manifest", str(p), "--write"]) == 0
    assert cli.main(["--manifest", str(p), "--write"]) == 0
    assert states == [
        ("on", "repeatable read"),
        ("on", "repeatable read"),
        ("off", "read committed"),
        ("on", "repeatable read"),
        ("off", "read committed"),
    ]
    output = capsys.readouterr().out
    for marker in (str(p), "가가00000000", "11110530", "postgresql", "12.34000"):
        assert marker not in output
    monkeypatch.setattr(repo, "LOCK_TIMEOUT_MS", 100)
    with e.connect() as held, held.begin():
        held.execute(
            text("SELECT pg_advisory_xact_lock(:n,:k)"),
            {"n": repo.LOCK_NAMESPACE, "k": repo.LOCK_KEY},
        )
        assert cli.main(["--manifest", str(p), "--write"]) == 1
    assert capsys.readouterr().out.strip() == '{"error": "living_pop:operation_failed"}'


def test_transformed_grid_matches_independent_center_and_uses_gist(source):
    e, p, d, g = source
    with e.begin() as c:
        gid, _, _, _ = repo.save(c, d, g)
        assert c.scalar(
            text("""SELECT bool_and(ST_Covers(geom,ST_Transform(ST_SetSRID(
           ST_MakePoint(center_x,center_y),5179),4326))) FROM living_grids""")
        )
        # Small fixture: force planner eligibility, rather than claiming a latency/plan SLA.
        c.execute(text("SET LOCAL enable_seqscan=off"))
        plan = c.scalar(
            text("""EXPLAIN (FORMAT JSON) SELECT * FROM living_grids
           WHERE ST_Covers(geom,ST_SetSRID(ST_Point(126.9,37.5),4326))""")
        )
        import json

        assert "ix_living_grids_geom_gist" in json.dumps(plan)
