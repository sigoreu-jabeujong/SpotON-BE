from datetime import date
from uuid import uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.util import CommandError
from sqlalchemy import delete, func, insert, select, text
from sqlalchemy.exc import IntegrityError

from app.db.base import Base
from app.models import LivingGrid, LivingGridVersion, Store
from app.models import LivingPopulationObservation as O
from app.models import LivingPopulationVersion as V
from tests.integration.test_localdata_upsert import ROOT, migrate

pytestmark = pytest.mark.integration


def test_population_constraints_spatial_fk_and_guarded_downgrade(temporary_database):
    migrate(temporary_database)
    e = temporary_database.engine
    g, v = uuid4(), uuid4()
    day = date(2026, 11, 7)
    with e.begin() as c:
        c.execute(insert(Store).values(source="synthetic", license_no="preserved"))
        c.execute(
            insert(LivingGridVersion).values(
                grid_version_id=g,
                input_sha256="1" * 64,
                input_bytes=1,
                rule_version="test",
                source_url="https://example.invalid",
                source_crs=5179,
                source_metadata={},
                row_count=1,
                raw_content_sha256="2" * 64,
                content_sha256="3" * 64,
                postgis_version="synthetic",
            )
        )
        grid = dict(
            grid_version_id=g,
            grid_id="가가00000000",
            source_gid="synthetic",
            center_x=950000,
            center_y=1950000,
            source_row_sha256="4" * 64,
            geom=func.ST_GeomFromText(
                "MULTIPOLYGON(((126.97 37.56,126.98 37.56,126.98 37.57,126.97 37.56)))", 4326
            ),
        )
        c.execute(insert(LivingGrid).values(**grid))
        manifest = dict(
            version_id=v,
            grid_version_id=g,
            observation_date=day,
            input_sha256="5" * 64,
            rule_version="test",
            sources={},
            row_count=1,
            content_sha256="6" * 64,
            spatial_compatibility="unverified",
        )
        c.execute(insert(V).values(**manifest))
        row = dict(
            version_id=v,
            source="local",
            hour=0,
            admin_code="11110530",
            grid_id="가가00000000",
            grid_version_id=g,
            observation_date=day,
            located_grid_id="가가00000000",
            population="0.00000",
            value_status="observed",
            geometry_status="located",
            source_row_sha256="7" * 64,
        )
        c.execute(insert(O).values(**row))
        c.execute(insert(O).values(**{**row, "admin_code": "11110540"}))
        c.execute(
            insert(O).values(
                **{
                    **row,
                    "source": "long",
                    "grid_id": "가가99999999",
                    "located_grid_id": None,
                    "population": None,
                    "value_status": "suppressed",
                    "geometry_status": "unlocated",
                }
            )
        )
        for changes in (
            {"hour": 24},
            {"admin_code": "bad"},
            {"source": "unknown"},
            {"population": -1},
            {"population": None},
            {"population": "NaN"},
            {"value_status": "suppressed"},
            {"located_grid_id": None},
            {"grid_id": "가가00000001", "located_grid_id": "가가00000001"},
            {"geometry_status": "unlocated"},
            {"observation_date": date(2026, 11, 8)},
            {"grid_version_id": uuid4()},
            {"source_row_sha256": "bad"},
        ):
            with pytest.raises(IntegrityError), c.begin_nested():
                c.execute(insert(O).values(**{**row, "hour": 1, **changes}))
        with pytest.raises(IntegrityError), c.begin_nested():
            c.execute(insert(O).values(**row))
        for m, col, key in (
            (V, V.version_id, v),
            (LivingGridVersion, LivingGridVersion.grid_version_id, g),
        ):
            with pytest.raises(IntegrityError), c.begin_nested():
                c.execute(delete(m).where(col == key))
        opts = {
            "compare_type": True,
            "include_name": lambda n, k, p: k != "table" or n in Base.metadata.tables,
        }
        assert compare_metadata(MigrationContext.configure(c, opts=opts), Base.metadata) == []
        assert "gist" in c.scalar(
            text("SELECT indexdef FROM pg_indexes WHERE indexname='ix_living_grids_geom_gist'")
        )
        config = Config(str(ROOT / "alembic.ini"))
        config.attributes["connection"] = c
        with pytest.raises(CommandError), c.begin_nested():
            command.downgrade(config, "0007")
        c.execute(delete(O))
        c.execute(delete(V))
        c.execute(delete(LivingGrid))
        c.execute(delete(LivingGridVersion))
        command.downgrade(config, "0007")
        assert c.scalar(select(func.count()).select_from(Store)) == 1
        assert c.scalar(text("SELECT to_regclass('living_grids')")) is None
        command.upgrade(config, "head")
        assert c.scalar(select(func.count()).select_from(O)) == 0
