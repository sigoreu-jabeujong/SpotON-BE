import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.main import create_app
from app.models import Store
from app.routers.geocode import get_geocode_service
from app.services.kakao_local import KakaoLocalService
from etl.address.road_key import parse_road
from tests.integration.test_store_history import KEY, seed
from tests.test_address_context import configured
from tests.test_geocode import document

pytestmark = pytest.mark.integration
ROAD = "서울 마포구 양화로 45"


def test_road_jibun_union_detail_conflicts_and_transactional_index(temporary_database):
    db = temporary_database
    seed(db)
    with Session(db.engine) as session, session.begin():
        # A both-address record and an entirely road-only record outside the lot branch.
        same = session.scalar(
            select(Store).where(Store.source == "general_restaurant", Store.license_no == "same")
        )
        same.address_road = ROAD + " 2층 201호"
        session.add(
            Store(
                source="general_restaurant",
                license_no="road-only",
                name="synthetic",
                category="restaurant",
                sub_category="korean",
                status="open",
                address_road=ROAD,
                floor_unit="2층 201호",
                location_level="same_spot",
                batch_id=same.batch_id,
            )
        )
        # Same lot but an explicitly different underground road is excluded.
        bad = session.scalar(select(Store).where(Store.license_no == "2"))
        bad.address_road = "서울 마포구 양화로 지하 45"
    settings = configured()
    app = create_app(settings)
    app.state.database.engine = db.engine
    doc = document()
    doc["address"] = {
        **doc["address"],
        "address_name": "서울 마포구 서교동 123-4",
        "region_3depth_name": "서교동",
        "main_address_no": "123",
        "sub_address_no": "4",
    }
    doc["road_address"] = {
        "address_name": ROAD,
        "road_name": "양화로",
        "region_2depth_name": "마포구",
        "underground_yn": "N",
        "main_building_no": "45",
        "sub_building_no": "",
    }
    app.dependency_overrides[get_geocode_service] = lambda: KakaoLocalService(
        api_key="synthetic",
        timeout=1,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"documents": [doc]})),
    )
    with TestClient(app) as client:
        context = client.post(
            "/api/v3/address-context",
            json={
                "address": ROAD,
                "building_key": KEY,
                "category": "restaurant",
                "lat": 37.5563,
                "lng": 126.922,
            },
        )
        assert context.status_code == 200, context.text
        token = context.json()["data"]["context"]
        params = {"context": token}
        base = client.get("/api/v3/stores/location-history", params=params)
        assert base.status_code == 200, base.text
        data = base.json()["data"]
        assert data["total"] == 8  # 8 lot + 1 road-only - 1 conflicting, no double count.
        assert data["candidate_count"] == 9
        assert data["address_conflict_count"] == 1
        assert data["selection"]["scope"] == "address"
        by_id = {(r["source"], r["license_no"]): r for r in data["stores"]}
        assert by_id[("general_restaurant", "same")]["match_evidence"] == "both"
        assert by_id[("general_restaurant", "road-only")]["match_evidence"] == "road"
        unit = client.get(
            "/api/v3/stores/location-history",
            params={
                **params,
                "floor_unit": "2층 201호",
            },
        ).json()["data"]
        assert unit["total"] == 6
        assert unit["detail_unresolved_count"] == 1
        assert unit["excluded_counts"]["floor"] == 1
        assert unit["open_count"] == 5 and unit["closed_count"] == 1
        # Existing APIs retain their broader semantics.
        assert (
            client.get("/api/stores/history", params={"building_key": KEY}).json()["data"]["total"]
            == 8
        )
        with Session(db.engine) as session, session.begin():
            row = session.scalar(select(Store).where(Store.license_no == "road-only"))
            row.address_road = "서울 마포구 양화로 46"
        assert (
            client.get("/api/v3/stores/location-history", params=params).json()["data"]["total"]
            == 7
        )
        with db.engine.connect() as connection:
            connection.execute(text("SET enable_seqscan=off"))
            plan = str(
                connection.execute(
                    text(
                        "EXPLAIN SELECT id FROM stores "
                        "WHERE spoton_history_road_key_v1(address_road)=:key"
                    ),
                    {"key": "마포구|양화로|N|45|0"},
                ).all()
            )
            assert "ix_stores_history_road_key" in plan


def test_postgres_and_python_road_normalization_agree(temporary_database):
    seed(temporary_database)
    values = [
        ROAD,
        ROAD + " 2층",
        "서울특별시 마포구 양화로 지하45 지하1층",
        "서울 마포구 양화로 45-1 (서교동)",
        "서울 마포구 독막로9길 5",
        "",
        "서울 마포구 양화로 45, 서울 마포구 다른길 1",
        "서울 마포구 양화로 0",
    ]
    with temporary_database.engine.connect() as connection:
        for value in values:
            parsed = parse_road(value)
            actual = connection.scalar(
                text("SELECT spoton_history_road_key_v1(:raw)"), {"raw": value}
            )
            assert actual == (parsed.key if parsed else None), value


def test_road_index_downgrade_preserves_source_records(temporary_database):
    from tests.integration.test_store_migration import migrate

    db = temporary_database
    seed(db)
    checksum = text("SELECT md5(string_agg(to_jsonb(s)::text, '' ORDER BY id)) FROM stores s")
    with db.engine.connect() as connection:
        before = connection.scalar(checksum)
    migrate(db, "0013", downgrade=True)
    with db.engine.connect() as connection:
        assert connection.scalar(checksum) == before
        assert (
            connection.scalar(text("SELECT to_regprocedure('spoton_history_road_key_v1(text)')"))
            is None
        )
    migrate(db, "head")
    with db.engine.connect() as connection:
        assert connection.scalar(checksum) == before
