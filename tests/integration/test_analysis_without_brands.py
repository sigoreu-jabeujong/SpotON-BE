import re
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.main import create_app
from tests.integration.test_nearby import PARAMS, batch, store
from tests.integration.test_store_migration import migrate

pytestmark = pytest.mark.integration


def assert_no_brand_fields(value):
    if isinstance(value, dict):
        assert not any(re.search(r"brand|franchise|operation_type", key) for key in value)
        for child in value.values():
            assert_no_brand_fields(child)
    elif isinstance(value, list):
        for child in value:
            assert_no_brand_fields(child)


def test_general_apis_preserve_cohort_and_never_query_brand_tables(temporary_database):
    migrate(temporary_database, "head")
    engine = temporary_database.engine
    building = "종로구-청운동-1-0"
    with Session(engine) as session, session.begin():
        provenance = batch(session)
        for i, flag in enumerate([True, False, None]):
            store(
                session,
                provenance,
                f"synthetic-{i}",
                is_franchise=flag,
                building_key=building,
                floor_unit="2층 201호",
                location_level="same_spot",
            )
        store(
            session,
            provenance,
            "closed",
            close_date=date(2026, 10, 1),
            status="closed",
            building_key=building,
            floor_unit="2층 201호",
            location_level="same_spot",
        )
    statements = []

    def observed(conn, cursor, statement, parameters, context, many):
        statements.append(statement.lower())

    event.listen(engine, "before_cursor_execute", observed)
    app = create_app(Settings(_env_file=None))
    app.state.database.engine = engine
    try:
        with TestClient(app) as client:
            results = {}
            for prefix in ["/api", "/api/v2"]:
                for path in [
                    "/stores/nearby",
                    "/stores/snapshot",
                    "/stores/history",
                    "/market/activity",
                    "/risk",
                ]:
                    params = (
                        {"building_key": building}
                        if path.endswith("history")
                        else {**PARAMS, "as_of": "2026-11"}
                    )
                    response = client.get(prefix + path, params=params)
                    assert response.status_code == 200, response.text
                    results[prefix + path] = response.json()
                    assert_no_brand_fields(response.json())
                nearby = results[prefix + "/stores/nearby"]["data"]
                snapshot = results[prefix + "/stores/snapshot"]["data"]
                activity = results[prefix + "/market/activity"]["data"]
                risk = results[prefix + "/risk"]["data"]
                assert nearby["count"] == snapshot["total_at_as_of"] == 3
                assert sum(row["open_count"] for row in activity["by_sub_category"]) == 3
                assert (
                    next(
                        row["value"]
                        for row in risk["indicators"]
                        if row["id"] == "competitor_count"
                    )
                    == 3
                )
                assert results[prefix + "/stores/history"]["data"]["total"] == 4
            for path in ["/market/activity", "/risk"]:
                assert results["/api" + path] == results["/api/v2" + path]
            response = client.get(
                "/api/v2/stores/location-history",
                params={
                    "building_key": building,
                    "floor_unit": "2층 201호",
                    "scope": "unit",
                    "identity_requirement": "address_scope",
                },
            )
            assert response.status_code == 200, response.text
            assert response.json()["data"]["total"] == 4
            assert_no_brand_fields(response.json())
    finally:
        event.remove(engine, "before_cursor_execute", observed)
    assert statements
    assert not any(
        re.search(
            r"(?:from|join)\s+(?:public\.)?(?:brand\w*|chain_\w*|store_brand_matches|store_chain_\w*)",
            statement,
        )
        for statement in statements
    )
