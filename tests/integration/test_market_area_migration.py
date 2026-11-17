from datetime import date
from uuid import uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import delete, func, insert, select, text
from sqlalchemy.exc import IntegrityError

from app.db.base import Base
from app.models import MarketArea, MarketAreaVersion, Store
from tests.integration.conftest import TemporaryDatabase
from tests.integration.test_localdata_upsert import ROOT, migrate

pytestmark = pytest.mark.integration


def test_market_schema_constraints_spatial_index_and_store_preservation(
    temporary_database: TemporaryDatabase,
) -> None:
    migrate(temporary_database)
    version = uuid4()
    with temporary_database.engine.begin() as c:
        c.execute(insert(Store).values(source="synthetic", license_no="preserved"))
        values = dict(
            version_id=version,
            source_dataset="OA-15560",
            source_url="https://example.invalid",
            source_file_date=date(2023, 10, 23),
            boundary_as_of=None,
            input_sha256="1" * 64,
            input_bytes=100,
            source_crs=5181,
            rule_version="test",
            row_count=1,
            repaired_count=0,
            content_sha256="2" * 64,
            postgis_version="test",
        )
        c.execute(insert(MarketAreaVersion).values(**values))
        area = dict(
            version_id=version,
            market_code="1234567",
            market_name="synthetic",
            market_type="alley",
            market_type_code="A",
            gu_code="11110",
            area_m2=100,
            source_feature_sha256="3" * 64,
            geometry_repaired=False,
            geom=func.ST_GeomFromText(
                "MULTIPOLYGON(((126.97 37.56,126.98 37.56,126.98 37.57,126.97 37.56)))", 4326
            ),
        )
        c.execute(insert(MarketArea).values(**area))
        for changes in [
            {"market_code": "bad"},
            {"area_m2": 0},
            {"market_type_code": "D"},
            {"source_feature_sha256": "invalid"},
            {"version_id": uuid4()},
        ]:
            with pytest.raises(IntegrityError), c.begin_nested():
                c.execute(
                    insert(MarketArea).values(**{**area, "market_code": "1234568", **changes})
                )
        with pytest.raises(IntegrityError), c.begin_nested():
            c.execute(delete(MarketAreaVersion).where(MarketAreaVersion.version_id == version))
        with pytest.raises(IntegrityError), c.begin_nested():
            c.execute(insert(MarketAreaVersion).values(**{**values, "version_id": uuid4()}))
        indexes = dict(
            c.execute(
                text("SELECT indexname,indexdef FROM pg_indexes WHERE tablename='market_areas'")
            ).all()
        )
        assert "USING gist (geom)" in indexes["ix_market_areas_geom_gist"]
        opts = {
            "compare_type": True,
            "include_name": lambda n, k, p: k != "table" or n in Base.metadata.tables,
        }
        assert compare_metadata(MigrationContext.configure(c, opts=opts), Base.metadata) == []
        config = Config(str(ROOT / "alembic.ini"))
        config.attributes["connection"] = c
        command.downgrade(config, "0004")
        assert c.scalar(select(func.count()).select_from(Store)) == 1
        assert c.scalar(text("SELECT to_regclass('market_areas')")) is None
        command.upgrade(config, "head")
        assert c.scalar(select(func.count()).select_from(MarketArea)) == 0
        assert c.scalar(select(func.count()).select_from(Store)) == 1
