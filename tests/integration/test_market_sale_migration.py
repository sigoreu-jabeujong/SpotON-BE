from datetime import date
from uuid import uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.util import CommandError
from sqlalchemy import delete, func, insert, select, text
from sqlalchemy.exc import DataError, IntegrityError

from app.db.base import Base
from app.models import (
    MarketArea,
    MarketSale,
    MarketSaleVersion,
    MarketStore,
    MarketStoreVersion,
    Store,
)
from tests.integration.market_references import seed_references
from tests.integration.test_localdata_upsert import ROOT, migrate

pytestmark = pytest.mark.integration


def test_sales_schema_constraints_restrict_and_downgrade_preserves_references(
    temporary_database, tmp_path
):
    migrate(temporary_database)
    e = temporary_database.engine
    with e.begin() as c:
        boundary, stores = seed_references(c, tmp_path)
        c.execute(insert(Store).values(source="synthetic", license_no="preserved"))
        version = uuid4()
        manifest = dict(
            version_id=version,
            source_dataset="OA-15572",
            source_url="https://example.invalid",
            source_file_date=date(2026, 5, 18),
            source_year=2025,
            input_sha256="3" * 64,
            input_bytes=1,
            member_name="synthetic.csv",
            member_sha256="4" * 64,
            member_bytes=1,
            member_modified="2026-05-18T00:00:00",
            source_encoding="cp949",
            rule_version="test",
            source_rows=1,
            row_count=1,
            excluded_rows=0,
            content_sha256="5" * 64,
            code_check_boundary_version_id=boundary,
            code_check_store_version_id=stores,
            code_check={},
            boundary_compatibility="unverified",
            currency="KRW",
            amount_basis="source_reported",
            amount_period_status="unverified",
        )
        c.execute(insert(MarketSaleVersion).values(**manifest))
        with pytest.raises(IntegrityError), c.begin_nested():
            c.execute(insert(MarketSaleVersion).values(**{**manifest, "version_id": uuid4()}))
        for n, changes in enumerate(
            (
                {"source_rows": 2},
                {"excluded_rows": -1},
                {"row_count": 0},
                {"source_file_date": date(2025, 12, 31)},
                {"input_sha256": "x"},
                {"source_dataset": "wrong"},
                {"source_encoding": "utf8"},
                {"currency": "USD"},
                {"amount_basis": "quarter_total"},
                {"amount_period_status": "verified"},
                {"boundary_compatibility": "verified"},
                {"code_check_store_version_id": uuid4()},
                {"code_check_boundary_version_id": uuid4()},
            )
        ):
            with pytest.raises(IntegrityError), c.begin_nested():
                c.execute(
                    insert(MarketSaleVersion).values(
                        **{
                            **manifest,
                            "version_id": uuid4(),
                            "input_sha256": f"{n:064x}",
                            **changes,
                        }
                    )
                )
        row = dict(
            version_id=version,
            market_code="9999999",
            quarter="20251",
            induty_cd="CS100010",
            market_name="synthetic",
            market_type_code="A",
            market_type_name="synthetic",
            induty_name="synthetic",
            est_sales=9223372036854775807,
            source_sales_count=None,
            source_row_sha256="6" * 64,
        )
        c.execute(insert(MarketSale).values(**row))
        assert c.scalar(select(MarketSale.est_sales)) == 9223372036854775807
        for changes in (
            {"market_code": "bad"},
            {"quarter": "20255"},
            {"induty_cd": "CS100009"},
            {"market_name": " "},
            {"market_type_code": "Z"},
            {"est_sales": -1},
            {"source_sales_count": -1},
            {"source_row_sha256": "x"},
            {"version_id": uuid4()},
        ):
            with pytest.raises(IntegrityError), c.begin_nested():
                c.execute(insert(MarketSale).values(**{**row, "market_code": "9999998", **changes}))
        with pytest.raises(DataError), c.begin_nested():
            c.execute(
                insert(MarketSale).values(
                    **{**row, "market_code": "9999998", "est_sales": 9223372036854775808}
                )
            )
        for model, vid in ((MarketSaleVersion, version), (MarketStoreVersion, stores)):
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
            command.downgrade(config, "0006")
        assert c.scalar(select(func.count()).select_from(MarketSale)) == 1
        c.execute(delete(MarketSale))
        c.execute(delete(MarketSaleVersion))
        command.downgrade(config, "0006")
        assert c.scalar(text("SELECT to_regclass('market_sales')")) is None
        assert c.scalar(select(func.count()).select_from(MarketStore)) == 20
        assert c.scalar(select(func.count()).select_from(MarketArea)) == 25
        assert c.scalar(select(func.count()).select_from(Store)) == 1
        command.upgrade(config, "head")
        assert c.scalar(select(func.count()).select_from(MarketSale)) == 0
