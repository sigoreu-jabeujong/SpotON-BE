import copy
import json
from uuid import uuid4

import pytest
from pyproj import Geod, Transformer
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.orm import Session

from app.analysis.population_quality import QualityError, QualityQuery, diagnose
from app.core.config import Settings
from app.db.dependencies import DatabaseResources
from app.models import LivingGrid as G
from app.models import LivingGridVersion as GV
from app.models import LivingPopulationObservation as O
from app.models import LivingPopulationVersion as V
from app.models import Store
from etl.living_pop import quality as cli
from etl.living_pop import repository as repo
from etl.living_pop.grid import prepare_grid
from etl.living_pop.input import load_input
from tests.etl.living_pop_helpers import make_manifest
from tests.integration.test_localdata_upsert import migrate

pytestmark = pytest.mark.integration
LNG, LAT = Transformer.from_crs(5179, 4326, always_xy=True).transform(950000, 1950000)


@pytest.fixture
def observations(temporary_database, tmp_path):
    migrate(temporary_database)
    engine = temporary_database.engine
    daily = load_input(make_manifest(tmp_path))
    with engine.connect() as connection:
        grid = prepare_grid(connection, daily.grid)
    with engine.begin() as connection:
        gid, vid, _, _ = repo.save(connection, daily, grid)
    query = QualityQuery(observation_version_id=vid, lat=LAT, lng=LNG, radius=300)
    return engine, daily, grid, gid, vid, query


def test_stored_states_and_global_unlocated_scope(observations):
    engine, _, _, _, _, query = observations
    with Session(engine) as session:
        result = diagnose(session, query)
    assert result.selected_grid_count == 2 and len(result.hours) == 72
    first, second = result.hours[:2]
    assert (first.suppressed, first.missing, first.observed_zero, first.observed_nonzero) == (
        1,
        1,
        0,
        0,
    )
    assert (first.grids_with_rows, first.grids_without_rows, first.grids_with_multi_admin_rows) == (
        1,
        1,
        1,
    )
    assert (second.observed_zero, second.observed_nonzero) == (1, 1)
    assert result.unlocated[0].rows == 24 and result.unlocated[0].grids == 1
    assert all(r.scope == "observation_version_global" for r in result.unlocated)
    assert result.content_hash_rechecked is False and result.spatial_compatibility == "unverified"


@pytest.mark.parametrize("radius", [300, 500, 1000])
@pytest.mark.parametrize("delta", [-0.01, 0.01])
def test_source_center_boundary_against_independent_spheroid(observations, radius, delta):
    engine, _, _, _, _, query = observations
    # Query west of the first grid; the other grid is farther east, beyond the radius.
    lng, lat, _ = Geod(ellps="WGS84").fwd(LNG, LAT, 270, radius + delta)
    query = query.model_copy(update={"lat": lat, "lng": lng, "radius": radius})
    with Session(engine) as session:
        result = diagnose(session, query)
    assert result.selected_grid_count == (1 if delta < 0 else 0)
    if delta > 0:
        assert all(r.rows == r.grids_with_rows == r.grids_without_rows == 0 for r in result.hours)
    assert result.unlocated[0].rows == 24


def test_center_attributes_are_used_even_if_polygon_is_elsewhere(observations):
    engine, _, _, _, _, query = observations
    with engine.begin() as connection:
        connection.execute(update(G).values(geom=func.ST_Translate(G.geom, 1, 1)))
    with Session(engine) as session:
        result = diagnose(session, query)
    assert result.selected_grid_count == 2
    assert result.selection_basis == "source_center_5179_spheroid_distance_le_radius"
    assert result.content_hash_rechecked is False


def test_explicit_version_never_uses_another_version(observations):
    engine, daily, grid, _, vid, query = observations
    with engine.begin() as connection:
        _, other, _, _ = repo.save(connection, daily, grid, rule="quality-other-v2")
        assert other != vid
    with Session(engine) as session:
        result = diagnose(session, query)
        with pytest.raises(QualityError, match="living_pop_quality:version"):
            diagnose(session, query.model_copy(update={"observation_version_id": uuid4()}))
    assert result.observation_version_id == vid and result.hours[0].rows == 2


def test_another_grid_version_is_not_mixed_into_selection(observations):
    engine, _, _, gid, _, query = observations
    with Session(engine) as session, session.begin():
        original = session.get(GV, gid)
        other = uuid4()
        values = {c.name: getattr(original, c.name) for c in GV.__table__.columns}
        values.update(grid_version_id=other, rule_version="quality-other-grid")
        session.add(GV(**values))
        session.flush()
        for item in list(session.scalars(select(G).where(G.grid_version_id == gid))):
            values = {c.name: getattr(item, c.name) for c in G.__table__.columns}
            values["grid_version_id"] = other
            session.add(G(**values))
    with Session(engine) as session:
        result = diagnose(session, query)
    assert result.grid_version_id == gid and result.selected_grid_count == 2


@pytest.mark.parametrize(
    "problem", ["deleted_row", "deleted_grid", "rows", "status", "missing_source", "counter_type"]
)
def test_partial_data_or_metadata_mismatch_is_not_a_success(observations, problem):
    engine, _, _, gid, vid, query = observations
    with engine.begin() as connection:
        if problem == "deleted_row":
            connection.execute(delete(O).where(O.source == "short", O.hour == 0))
        elif problem == "deleted_grid":
            connection.execute(
                delete(G).where(G.grid_id == "가가00000001", G.grid_version_id == gid)
            )
        else:
            meta = copy.deepcopy(connection.scalar(select(V.sources).where(V.version_id == vid)))
            if problem == "rows":
                meta["local"]["rows"] += 1
            elif problem == "status":
                meta["local"]["statuses"]["observed"] += 1
            elif problem == "missing_source":
                del meta["short"]
            elif problem == "counter_type":
                meta["local"]["unlocated_rows"] = False
            connection.execute(update(V).where(V.version_id == vid).values(sources=meta))
    with Session(engine) as session, pytest.raises(QualityError, match="living_pop_quality:counts"):
        diagnose(session, query)


def resources_for_test(engine, config):
    result = DatabaseResources(config)
    result.engine = engine
    return result


@pytest.mark.parametrize("attempt_write", [False, True])
def test_cli_snapshot_is_read_only_and_releases_resources(
    observations, monkeypatch, capsys, attempt_write
):
    engine, _, _, _, vid, query = observations
    config = Settings(
        _env_file=None, database_url="postgresql://spoton_app:synthetic@127.0.0.1/spoton_dev"
    )
    resources = resources_for_test(engine, config)
    monkeypatch.setattr(cli, "Settings", lambda: config)
    monkeypatch.setattr(cli, "DatabaseResources", lambda _: resources)
    checked = []

    def check(connection):
        checked.append(True)
        assert connection.scalar(text("SHOW transaction_read_only")) == "on"
        assert connection.scalar(text("SHOW transaction_isolation")) == "repeatable read"
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0010"

    monkeypatch.setattr(cli, "check_local_database", check)
    if attempt_write:

        def write(session, q):
            session.execute(
                text("INSERT INTO stores(source,license_no) VALUES ('test','WRITE-CANARY')")
            )

        monkeypatch.setattr(cli, "diagnose", write)
    args = [
        "--population-version",
        str(vid),
        "--lat",
        str(query.lat),
        "--lng",
        str(query.lng),
        "--radius",
        "300",
    ]
    assert cli.main(args) == (1 if attempt_write else 0)
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert "WRITE-CANARY" not in captured.out + captured.err
    assert checked and resources.engine is None
    if attempt_write:
        assert payload == {"error": "living_pop_quality:database"}
    else:
        assert payload["selected_grid_count"] == 2
    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(Store)) == 0
        assert connection.scalar(select(func.count()).select_from(O)) == 168
