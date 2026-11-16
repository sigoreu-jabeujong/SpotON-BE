from copy import deepcopy
from datetime import date

import pytest
from fastapi.testclient import TestClient
from pyproj import Transformer
from sqlalchemy import event, select, text, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.main import create_app
from app.models import LivingPopulationObservation as O
from app.models import LivingPopulationVersion as V
from app.schemas.population_reference import PopulationReferenceQuery
from app.services import population_reference as service
from etl.living_pop import repository
from etl.living_pop.grid import prepare_grid
from etl.living_pop.input import load_input
from tests.etl.living_pop_helpers import make_manifest
from tests.integration.test_localdata_upsert import migrate
from tests.integration.test_nearby import batch, store

pytestmark = pytest.mark.integration
PATH = "/api/v2/population-reference"
LNG, LAT = Transformer.from_crs(5179, 4326, always_xy=True).transform(950000, 1950000)
PARAMS = dict(lat=LAT, lng=LNG, radius=500, category="restaurant")


def public_local(rows):
    for row in rows:
        if row[3] == "가가00000000":
            row[4] = "*" if row[1] == "03" and row[2].strip() == "11110540" else "12.34"
    return rows


def suppressed_foreign(rows):
    for row in rows:
        row[4] = "*"
    return rows


@pytest.fixture
def population_db(temporary_database, tmp_path):
    migrate(temporary_database)
    engine = temporary_database.engine
    daily = load_input(
        make_manifest(
            tmp_path,
            patches={
                "local": public_local,
                "long": suppressed_foreign,
                "short": suppressed_foreign,
            },
        )
    )
    with engine.connect() as connection:
        grid = prepare_grid(connection, daily.grid)
    with engine.begin() as connection:
        gid, vid, _, _ = repository.save(connection, daily, grid)
    with Session(engine) as session, session.begin():
        provenance = batch(session, data_updated_at=date(2026, 11, 8))
        store(session, provenance, "population-clock")
    app = create_app(Settings(_env_file=None))
    app.state.database.engine = engine
    with TestClient(app) as client:
        yield engine, client, daily, grid, vid, gid


def payload(client, **changes):
    response = client.get(PATH, params=PARAMS | changes)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()


def test_actual_postgis_loader_assembles_local_without_foreign_and_avoids_global_scans(
    population_db,
    monkeypatch,
):
    engine, client, _, _, _, _ = population_db
    statements = []
    original = service._get_population_reference

    def inspect_transaction(session, query):
        assert session.scalar(text("SHOW transaction_isolation")) == "repeatable read"
        assert session.scalar(text("SHOW transaction_read_only")) == "on"
        return original(session, query)

    monkeypatch.setattr(service, "_get_population_reference", inspect_transaction)

    def observe(conn, cursor, statement, parameters, context, many):
        statements.append(statement.lower())

    event.listen(engine, "before_cursor_execute", observe)
    try:
        result = payload(client)
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    assert result["data"]["analysis_date"] == "2026-11-08"
    assert result["data"]["observation_date"] == "2026-11-07"
    domestic, long, short = result["data"]["sources"]
    assert domestic["status"] == "partial"
    assert domestic["values"]["day_night_ratio"]["value"] == "1.00000"
    q = domestic["quality"]
    assert (
        q["selected_grid_count"],
        q["candidate_component_count"],
        q["used_component_count"],
    ) == (2, 2, 1)
    assert q["version_unlocated_rows"] == 24
    assert long["reason"] == short["reason"] == "no_common_public_components"
    assert all(
        "count(" not in s and "group by" not in s
        for s in statements
        if "living_population_observations" in s
    )
    assert not result["meta"]["global_content_rechecked"]
    assert not result["meta"]["population_total_validated"]
    assert result["meta"]["public_subset_calculation_performed"] == dict(
        local=True, long=False, short=False
    )
    assert (
        payload(client)["meta"]["population_snapshot_token"]
        == result["meta"]["population_snapshot_token"]
    )


def test_empty_radius_old_month_future_range_and_existing_api_preserved(population_db):
    _, client, _, _, _, _ = population_db
    empty = payload(client, lat=0, lng=0)
    assert all(s["reason"] == "no_selected_grids" for s in empty["data"]["sources"])
    old = payload(client, as_of="2026-10")
    assert old["data"]["reason"] == "no_observation_in_period"
    assert old["data"]["analysis_date"] == "2026-10-31"
    assert old["data"]["observation_date"] is None
    assert client.get(PATH, params=PARAMS | {"as_of": "2026-12"}).status_code == 422
    assert client.get(PATH, params=PARAMS | {"as_of": "2019-01"}).status_code == 422
    activity = client.get("/api/market/activity", params=PARAMS | {"include": "living_pop"})
    assert activity.status_code == 200 and activity.json()["data"]["living_pop"] is None
    risk = client.get("/api/risk", params=PARAMS | {"include": "day_night_ratio"})
    assert risk.status_code == 200
    assert (
        next(i for i in risk.json()["data"]["indicators"] if i["id"] == "day_night_ratio")["status"]
        == "pending"
    )


def test_same_day_duplicate_version_is_pending_without_selecting_a_candidate(population_db):
    engine, client, daily, grid, _, _ = population_db
    with engine.begin() as connection:
        repository.save(connection, daily, grid, rule="synthetic-alternative")
    result = payload(client)
    assert result["data"]["status"] == "pending"
    assert result["data"]["observation_date"] == "2026-11-07"
    assert result["data"]["sources"] == []
    assert result["meta"]["observation_version_id"] is None


@pytest.mark.parametrize("limit", ["MAX_ROWS", "MAX_GRIDS"])
def test_real_sql_limit_plus_one_rejects_without_truncating(population_db, monkeypatch, limit):
    _, client, _, _, _, _ = population_db
    monkeypatch.setattr(service, limit, 1)
    result = payload(client)
    assert result["data"]["status"] == "not_supported"
    assert result["data"]["reason"] == "scope_too_large"
    assert result["data"]["sources"] == []


def test_metadata_damage_is_an_error_not_missing_or_partial(population_db):
    engine, client, _, _, vid, _ = population_db
    with engine.begin() as connection:
        sources = deepcopy(connection.scalar(select(V.sources).where(V.version_id == vid)))
        sources["local"]["statuses"]["observed"] += 1
        connection.execute(update(V).where(V.version_id == vid).values(sources=sources))
    response = client.get(PATH, params=PARAMS)
    assert response.status_code == 500 and response.json()["data"] is None
    assert response.headers["cache-control"] == "no-store"


def test_repeatable_read_keeps_one_snapshot_and_next_request_observes_change(population_db):
    engine, client, _, _, vid, _ = population_db
    query = PopulationReferenceQuery(**PARAMS)
    with Session(engine) as session:
        session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        session.execute(text("SET TRANSACTION READ ONLY"))
        before = service.get_population_reference(session, query)
        with engine.begin() as connection:
            connection.execute(
                update(O)
                .where(
                    O.version_id == vid,
                    O.source == "local",
                    O.admin_code == "11110530",
                    O.hour == 6,
                    O.grid_id == "가가00000000",
                )
                .values(population=25)
            )
        assert service.get_population_reference(session, query) == before
        assert session.scalar(text("SHOW transaction_read_only")) == "on"
    after = payload(client)
    assert after["meta"]["population_snapshot_token"] != before.meta["population_snapshot_token"]
