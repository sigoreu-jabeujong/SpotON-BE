from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text

from app.models import Store
from etl.localdata.constants import Source
from etl.localdata.pipeline import StoreRecord
from etl.localdata.repository import upsert_records
from tests.integration.conftest import TemporaryDatabase

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]


def migrate(database: TemporaryDatabase) -> None:
    config = Config(str(ROOT / "alembic.ini"))
    with database.engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


def record(building_key: str | None) -> StoreRecord:
    return StoreRecord(
        source=Source.GENERAL_RESTAURANT.value,
        license_no="building-key-same",
        gu_code="3130000",
        name="테스트 점포",
        address_road="서울특별시 마포구 양화로 1",
        address_jibun="서울특별시 마포구 서교동 123",
        building_key=building_key,
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


def load_key(database: TemporaryDatabase) -> str | None:
    with database.engine.connect() as connection:
        return connection.scalar(
            select(Store.building_key).where(
                Store.source == Source.GENERAL_RESTAURANT.value,
                Store.license_no == "building-key-same",
            )
        )


def test_building_key_upsert_updates_and_clears_current_etl_value(
    temporary_database: TemporaryDatabase,
) -> None:
    migrate(temporary_database)
    engine = temporary_database.engine
    key_a = "마포구-서교동-123-0"
    key_b = "마포구-서교동-124-0"
    for building_key, expected in ((key_a, key_a), (key_b, key_b), (None, None), (key_a, key_a)):
        with engine.connect() as connection:
            assert (
                upsert_records(connection, Source.GENERAL_RESTAURANT, [record(building_key)]) == 1
            )
        assert load_key(temporary_database) == expected


def test_building_key_upsert_preserves_later_owner_columns(
    temporary_database: TemporaryDatabase,
) -> None:
    migrate(temporary_database)
    engine = temporary_database.engine
    with engine.connect() as connection:
        upsert_records(connection, Source.GENERAL_RESTAURANT, [record("마포구-서교동-123-0")])
    deleted_at = datetime(2026, 1, 1, tzinfo=UTC)
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE stores SET floor_unit='2층', location_level='same_spot', "
                "deleted_at=:deleted "
                "WHERE source=:source AND license_no='building-key-same'"
            ),
            {"source": Source.GENERAL_RESTAURANT.value, "deleted": deleted_at},
        )
    with engine.connect() as connection:
        upsert_records(connection, Source.GENERAL_RESTAURANT, [record("마포구-서교동-124-0")])
    with engine.connect() as connection:
        loaded = connection.execute(
            select(
                Store.building_key, Store.floor_unit, Store.location_level, Store.deleted_at
            ).where(
                Store.source == Source.GENERAL_RESTAURANT.value,
                Store.license_no == "building-key-same",
            )
        ).one()
        assert loaded.building_key == "마포구-서교동-124-0"
        assert loaded.floor_unit == "2층"
        assert loaded.location_level == "same_spot"
        assert loaded.deleted_at == deleted_at
        index_exists = connection.scalar(
            text("SELECT to_regclass('ix_stores_building_key') IS NOT NULL")
        )
        assert index_exists is True
