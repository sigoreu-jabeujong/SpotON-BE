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
from app.models import MarketAreaVersion, MarketStore, MarketStoreVersion, Store
from tests.integration.test_localdata_upsert import ROOT, migrate

pytestmark = pytest.mark.integration


def test_official_schema_constraints_downgrade_guard_and_preservation(temporary_database):
    migrate(temporary_database)
    e = temporary_database.engine
    boundary, version = uuid4(), uuid4()
    with e.begin() as c:
        c.execute(insert(Store).values(source="synthetic", license_no="preserved"))
        c.execute(
            insert(MarketAreaVersion).values(
                version_id=boundary,
                source_dataset="OA-15560",
                source_url="https://example.invalid",
                source_file_date=date(2023, 10, 23),
                input_sha256="1" * 64,
                input_bytes=1,
                source_crs=5181,
                rule_version="synthetic",
                row_count=1,
                repaired_count=0,
                content_sha256="2" * 64,
                postgis_version="synthetic",
            )
        )
        values = dict(
            version_id=version,
            source_dataset="OA-15577",
            source_url="https://example.invalid",
            source_file_date=date(2026, 5, 21),
            source_year=2025,
            input_sha256="3" * 64,
            input_bytes=1,
            member_name="synthetic.csv",
            member_sha256="4" * 64,
            member_bytes=1,
            member_modified="2026-05-21T00:00:00",
            source_encoding="cp949",
            rule_version="test",
            source_rows=1,
            row_count=1,
            excluded_rows=0,
            content_sha256="5" * 64,
            code_check_boundary_version_id=boundary,
            code_check={},
            boundary_compatibility="unverified",
        )
        c.execute(insert(MarketStoreVersion).values(**values))
        row = dict(
            version_id=version,
            market_code="9999999",
            quarter="20251",
            induty_cd="CS100010",
            market_name="synthetic",
            market_type_code="A",
            market_type_name="synthetic",
            induty_name="synthetic",
            total_stores=2,
            general_stores=1,
            franchise_stores=1,
            open_stores=5,
            closed_stores=9,
            opening_rate=None,
            closure_rate=450,
            source_row_sha256="6" * 64,
        )
        c.execute(insert(MarketStore).values(**row))  # No FK to market_areas; >100 is valid.
        for changes in (
            {"total_stores": 1},
            {"closed_stores": -1},
            {"opening_rate": -1},
            {"closure_rate": "NaN"},
            {"quarter": "20255"},
            {"induty_cd": "CS100009"},
            {"market_type_code": "Z"},
            {"market_code": "bad"},
            {"market_name": " "},
            {"source_row_sha256": "x"},
            {"version_id": uuid4()},
        ):
            with pytest.raises(IntegrityError), c.begin_nested():
                c.execute(
                    insert(MarketStore).values(**{**row, "market_code": "9999998", **changes})
                )
        for changes in (
            {"source_rows": 2},
            {"excluded_rows": -1},
            {"row_count": 0},
            {"source_file_date": date(2025, 12, 31)},
            {"source_encoding": "utf8"},
            {"boundary_compatibility": "verified"},
            {"input_sha256": "x"},
            {"code_check_boundary_version_id": uuid4()},
        ):
            with pytest.raises(IntegrityError), c.begin_nested():
                c.execute(
                    insert(MarketStoreVersion).values(
                        **{**values, "version_id": uuid4(), **changes}
                    )
                )
        for model, vid in ((MarketStoreVersion, version), (MarketAreaVersion, boundary)):
            with pytest.raises(IntegrityError), c.begin_nested():
                c.execute(delete(model).where(model.version_id == vid))
        opts = {
            "compare_type": True,
            "include_name": lambda n, k, p: k != "table" or n in Base.metadata.tables,
        }
        assert compare_metadata(MigrationContext.configure(c, opts=opts), Base.metadata) == []
        config = Config(str(ROOT / "alembic.ini"))
        config.attributes["connection"] = c
        with pytest.raises(CommandError), c.begin_nested():
            command.downgrade(config, "0005")
        assert c.scalar(select(func.count()).select_from(MarketStore)) == 1
        c.execute(delete(MarketStore))
        c.execute(delete(MarketStoreVersion))
        command.downgrade(config, "0005")
        assert c.scalar(text("SELECT to_regclass('market_stores')")) is None
        assert c.scalar(select(func.count()).select_from(MarketAreaVersion)) == 1
        assert c.scalar(select(func.count()).select_from(Store)) == 1
        command.upgrade(config, "head")
        assert c.scalar(select(func.count()).select_from(MarketStore)) == 0
