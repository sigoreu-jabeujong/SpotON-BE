from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import Store
from app.schemas.stores import HistoryQuery
from app.services.store_history import get_history
from etl.localdata.collection import CollectedSource
from etl.localdata.constants import Source
from etl.localdata.pipeline import StoreRecord, transform_rows
from etl.localdata.provenance import import_batch
from etl.localdata.repository import upsert_records
from tests.etl.test_localdata_pipeline import raw
from tests.integration.conftest import TemporaryDatabase

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]


def migrate(database: TemporaryDatabase) -> None:
    config = Config(str(ROOT / "alembic.ini"))
    with database.engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


def record(floor_unit: str | None, location_level: str) -> StoreRecord:
    return StoreRecord(
        source=Source.GENERAL_RESTAURANT.value,
        license_no="floor-unit-same",
        gu_code="3130000",
        name="테스트 점포",
        address_road="서울특별시 마포구 테스트로 1 2층 201호",
        address_jibun="서울특별시 마포구 서교동 123-4 2층 201호",
        building_key="마포구-서교동-123-4",
        floor_unit=floor_unit,
        location_level=location_level,
        open_date=date(2020, 1, 1),
        close_date=None,
        status="open",
        status_code="01",
        bzstat_nm="한식",
        category="restaurant",
        sub_category="korean",
        seoul_induty_cd=None,
        area_m2=Decimal("10.00"),
        lat=Decimal("37.5522680"),
        lng=Decimal("127.0007880"),
        raw_x="200000",
        raw_y="450000",
        raw_crs="EPSG:5174",
        coord_source="localdata",
        coord_flag=None,
        date_flag=None,
        is_temporary=None,
        category_review_flag=False,
        batch_id=UUID("00000000-0000-0000-0000-000000000001"),
    )


def load_detail(database: TemporaryDatabase) -> tuple[str | None, str, str, datetime | None]:
    with database.engine.connect() as connection:
        return connection.execute(
            select(
                Store.floor_unit, Store.location_level, Store.building_key, Store.deleted_at
            ).where(
                Store.source == Source.GENERAL_RESTAURANT.value,
                Store.license_no == "floor-unit-same",
            )
        ).one()


def test_floor_unit_upsert_updates_and_clears_current_etl_values(
    temporary_database: TemporaryDatabase,
) -> None:
    migrate(temporary_database)
    engine = temporary_database.engine
    cases = (
        ("2층 201호", "same_spot"),
        ("3층", "same_building"),
        (None, "unverified"),
        ("2층 201호", "same_spot"),
    )
    for floor_unit, location_level in cases:
        with engine.connect() as connection:
            assert (
                upsert_records(
                    connection,
                    Source.GENERAL_RESTAURANT,
                    [record(floor_unit, location_level)],
                )
                == 1
            )
        loaded_floor, loaded_level, building_key, _ = load_detail(temporary_database)
        assert loaded_floor == floor_unit
        assert loaded_level == location_level
        assert building_key == "마포구-서교동-123-4"


def test_floor_unit_upsert_updates_etl_key_and_preserves_deleted_at(
    temporary_database: TemporaryDatabase,
) -> None:
    migrate(temporary_database)
    engine = temporary_database.engine
    with engine.connect() as connection:
        upsert_records(connection, Source.GENERAL_RESTAURANT, [record("2층 201호", "same_spot")])
    deleted_at = datetime(2026, 1, 1, tzinfo=UTC)
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE stores SET building_key='kept', deleted_at=:deleted "
                "WHERE source=:source AND license_no='floor-unit-same'"
            ),
            {"source": Source.GENERAL_RESTAURANT.value, "deleted": deleted_at},
        )
    with engine.connect() as connection:
        upsert_records(connection, Source.GENERAL_RESTAURANT, [record(None, "unverified")])
    floor_unit, location_level, building_key, stored_deleted_at = load_detail(temporary_database)
    assert floor_unit is None
    assert location_level == "unverified"
    assert building_key == "마포구-서교동-123-4"
    assert stored_deleted_at == deleted_at


@pytest.mark.parametrize(
    "gu,code,dong", [("중구", "3010000", "중림동"), ("중랑구", "3060000", "중화동")]
)
@pytest.mark.parametrize("detail", ["", "2층", "2층 201호"])
def test_place_detail_survives_transform_postgis_and_history_without_promoting_legacy(
    temporary_database: TemporaryDatabase, gu: str, code: str, dong: str, detail: str
) -> None:
    migrate(temporary_database)
    row = raw(
        "PLACE-HISTORY-1",
        OPN_ATMY_GRP_CD=code,
        ROAD_NM_ADDR=f"서울특별시 {gu} 테스트로 1 {detail}".strip(),
        LOTNO_ADDR=f"서울특별시 {gu} {dong} 1-1 {detail}".strip(),
    )
    batch_id = UUID("00000000-0000-0000-0000-000000000002")
    collection = CollectedSource(
        source=Source.GENERAL_RESTAURANT,
        collected_at=datetime(2026, 11, 10),
        authorities=(),
        rows=(row,),
    )
    normalized = transform_rows(
        collection.source, collection.rows, batch_id=batch_id, today=collection.collected_at.date()
    ).records[0]
    engine = temporary_database.engine
    with engine.connect() as connection:
        assert (
            upsert_records(
                connection,
                collection.source,
                [normalized],
                batch=import_batch(collection, batch_id),
            )
            == 1
        )
    with Session(engine) as session:
        session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        session.execute(text("SET TRANSACTION READ ONLY"))
        stored = session.scalar(select(Store).where(Store.license_no == "PLACE-HISTORY-1"))
        assert stored is not None
        assert stored.floor_unit == (detail or None)
        assert stored.building_key == f"{gu}-{dong}-1-1"
        assert session.scalar(select(Store.bzstat_nm)) == "한식"
        assert session.scalar(select(Store.open_date)) == date(2020, 1, 1)
        assert session.scalar(select(Store.geom.is_not(None))) is True
        assert session.scalar(text("SELECT rule_version FROM store_import_batches")) == (
            "localdata-normalization-v2"
        )
        history = get_history(
            session,
            HistoryQuery(building_key=stored.building_key, floor_unit="2층 201호", category="cafe"),
        )
        assert history.data.total == 1
        assert history.data.stores[0].location_match == (
            "same_spot" if detail == "2층 201호" else "unverified"
        )
    # A new, detailed query never upgrades a pre-backfill NULL/unverified row.
    legacy = replace(normalized, floor_unit=None, location_level="unverified")
    with engine.connect() as connection:
        upsert_records(connection, collection.source, [legacy])
    with Session(engine) as session:
        session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        session.execute(text("SET TRANSACTION READ ONLY"))
        history = get_history(
            session, HistoryQuery(building_key=f"{gu}-{dong}-1-1", floor_unit="2층 201호")
        )
        assert history.data.stores[0].location_match == "unverified"
