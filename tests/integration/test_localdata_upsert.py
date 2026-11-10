from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text
from sqlalchemy.exc import DataError

from app.models import Store
from etl.localdata.constants import Source
from etl.localdata.pipeline import StoreRecord
from etl.localdata.repository import RepositoryContractError, upsert_records
from tests.integration.conftest import TemporaryDatabase

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]


def migrate(database: TemporaryDatabase) -> None:
    config = Config(str(ROOT / "alembic.ini"))
    with database.engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


def record(
    source: Source,
    license_no: str,
    *,
    name: str = "처음 점포",
    batch: str = "00000000-0000-0000-0000-000000000001",
    lat: Decimal | None = Decimal("37.5522680"),
    lng: Decimal | None = Decimal("127.0007880"),
) -> StoreRecord:
    return StoreRecord(
        source=source.value,
        license_no=license_no,
        gu_code="3000000",
        name=name,
        address_road="서울특별시 테스트로 1",
        address_jibun="서울특별시 테스트동 1",
        open_date=date(2020, 1, 1),
        close_date=None,
        status="open",
        status_code="01",
        bzstat_nm="한식",
        category="restaurant",
        sub_category="korean",
        seoul_induty_cd=None,
        area_m2=Decimal("10.00"),
        lat=lat,
        lng=lng,
        raw_x="200000",
        raw_y="450000",
        raw_crs="EPSG:5174",
        coord_source="localdata" if lat is not None else None,
        coord_flag=None if lat is not None else "coord_missing",
        date_flag=None,
        is_temporary=None,
        category_review_flag=False,
        batch_id=UUID(batch),
    )


def test_localdata_upsert_is_idempotent_and_preserves_later_fields(
    temporary_database: TemporaryDatabase,
) -> None:
    migrate(temporary_database)
    engine = temporary_database.engine
    first = record(Source.GENERAL_RESTAURANT, "same")
    with engine.connect() as connection:
        assert upsert_records(connection, Source.GENERAL_RESTAURANT, [first]) == 1
    deleted_at = datetime(2026, 1, 1, tzinfo=UTC)
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE stores SET building_key='kept', floor_unit='2층', deleted_at=:deleted "
                "WHERE source=:source AND license_no='same'"
            ),
            {"source": Source.GENERAL_RESTAURANT.value, "deleted": deleted_at},
        )

    second = record(
        Source.GENERAL_RESTAURANT,
        "same",
        name="갱신 점포",
        batch="00000000-0000-0000-0000-000000000002",
        lat=None,
        lng=None,
    )
    with engine.connect() as connection:
        assert upsert_records(connection, Source.GENERAL_RESTAURANT, [second]) == 1
    with engine.connect() as connection:
        loaded = connection.execute(
            select(
                Store.name,
                Store.batch_id,
                Store.building_key,
                Store.floor_unit,
                Store.deleted_at,
                Store.geom,
            ).where(Store.source == Source.GENERAL_RESTAURANT.value, Store.license_no == "same")
        ).one()
        assert loaded.name == "갱신 점포"
        assert loaded.batch_id == second.batch_id
        assert loaded.building_key == "kept"
        assert loaded.floor_unit == "2층"
        assert loaded.deleted_at == deleted_at
        assert loaded.geom is None
        assert connection.scalar(select(func.count()).select_from(Store)) == 1


def test_localdata_upsert_allows_same_license_for_different_sources_and_sets_geometry(
    temporary_database: TemporaryDatabase,
) -> None:
    migrate(temporary_database)
    engine = temporary_database.engine
    for source in Source:
        with engine.connect() as connection:
            upsert_records(connection, source, [record(source, "shared")])
    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(Store)) == 2
        points = connection.execute(
            text("SELECT ST_SRID(geom), ST_X(geom), ST_Y(geom) FROM stores ORDER BY source")
        ).all()
        assert all(point[0] == 4326 for point in points)
        assert all(float(point[1]) == pytest.approx(127.0007880) for point in points)
        assert all(float(point[2]) == pytest.approx(37.5522680) for point in points)


def test_localdata_upsert_rolls_back_all_chunks_on_failure(
    temporary_database: TemporaryDatabase,
) -> None:
    migrate(temporary_database)
    engine = temporary_database.engine
    records = [
        record(Source.GENERAL_RESTAURANT, "valid"),
        record(Source.GENERAL_RESTAURANT, "too-long", name="x" * 256),
    ]
    with pytest.raises(DataError), engine.connect() as connection:
        upsert_records(connection, Source.GENERAL_RESTAURANT, records, chunk_size=1)
    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(Store)) == 0


def test_localdata_upsert_rejects_dirty_connection_and_duplicate_input(
    temporary_database: TemporaryDatabase,
) -> None:
    migrate(temporary_database)
    engine = temporary_database.engine
    item = record(Source.GENERAL_RESTAURANT, "same")
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
        with pytest.raises(RepositoryContractError, match="새 트랜잭션"):
            upsert_records(connection, Source.GENERAL_RESTAURANT, [item])
    with engine.connect() as connection:
        with pytest.raises(RepositoryContractError, match="중복 키"):
            upsert_records(connection, Source.GENERAL_RESTAURANT, [item, item])
