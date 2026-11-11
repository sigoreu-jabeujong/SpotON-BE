from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from geoalchemy2.elements import WKTElement
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import create_session_factory, session_scope
from app.models import Store
from tests.integration.conftest import TemporaryDatabase
from tests.stores_schema_spec import COLUMN_SPECS, CONSTRAINT_NAMES, INDEX_SPECS

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]


def migrate(database: TemporaryDatabase, revision: str, *, downgrade: bool = False) -> None:
    config = Config(str(ROOT / "alembic.ini"))
    with database.engine.begin() as connection:
        config.attributes["connection"] = connection
        action = command.downgrade if downgrade else command.upgrade
        action(config, revision)


def assert_database_schema(engine: Engine) -> None:
    with engine.connect() as connection:
        rows = (
            connection.execute(
                text(
                    """
                SELECT a.attname,
                       pg_catalog.format_type(a.atttypid, a.atttypmod) AS database_type,
                       NOT a.attnotnull AS nullable,
                       (a.attidentity <> '' OR d.adbin IS NOT NULL) AS has_default,
                       a.attidentity
                FROM pg_catalog.pg_attribute AS a
                LEFT JOIN pg_catalog.pg_attrdef AS d
                  ON d.adrelid = a.attrelid AND d.adnum = a.attnum
                WHERE a.attrelid = 'stores'::regclass
                  AND a.attnum > 0
                  AND NOT a.attisdropped
                ORDER BY a.attnum
                """
                )
            )
            .mappings()
            .all()
        )
        assert tuple(row["attname"] for row in rows) == tuple(COLUMN_SPECS)
        for row in rows:
            spec = COLUMN_SPECS[row["attname"]]
            assert row["database_type"] == spec.database_type
            assert row["nullable"] is spec.nullable
            assert row["has_default"] is spec.has_default
        identity = next(row for row in rows if row["attname"] == "id")
        assert identity["attidentity"] == "d"

        constraints = dict(
            connection.execute(
                text(
                    "SELECT conname, contype FROM pg_constraint WHERE conrelid = 'stores'::regclass"
                )
            ).all()
        )
        assert set(constraints) == CONSTRAINT_NAMES
        assert constraints["pk_stores"] == "p"
        assert constraints["uq_stores_source_license_no"] == "u"
        assert constraints["ck_stores_lat_range"] == "c"
        assert constraints["ck_stores_lng_range"] == "c"

        geometry = (
            connection.execute(
                text(
                    "SELECT type, srid FROM geometry_columns "
                    "WHERE f_table_name='stores' AND f_geometry_column='geom'"
                )
            )
            .mappings()
            .one()
        )
        assert geometry == {"type": "POINT", "srid": 4326}

        indexes = (
            connection.execute(
                text(
                    """
                SELECT idx.relname AS name,
                       am.amname AS method,
                       i.indisprimary,
                       i.indisunique,
                       array_agg(att.attname ORDER BY keys.ordinality) AS columns
                FROM pg_index AS i
                JOIN pg_class AS tbl ON tbl.oid = i.indrelid
                JOIN pg_class AS idx ON idx.oid = i.indexrelid
                JOIN pg_am AS am ON am.oid = idx.relam
                CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY AS keys(attnum, ordinality)
                JOIN pg_attribute AS att
                  ON att.attrelid = tbl.oid AND att.attnum = keys.attnum
                WHERE tbl.oid = 'stores'::regclass
                GROUP BY idx.relname, am.amname, i.indisprimary, i.indisunique
                """
                )
            )
            .mappings()
            .all()
        )
        index_by_name = {row["name"]: row for row in indexes}
        assert set(index_by_name) == {
            "pk_stores",
            "uq_stores_source_license_no",
            *INDEX_SPECS,
        }
        for name, (method, columns) in INDEX_SPECS.items():
            assert index_by_name[name]["method"] == method
            assert tuple(index_by_name[name]["columns"]) == columns
        assert "idx_stores_geom" not in index_by_name


def assert_database_error(
    engine: Engine,
    statement: str,
    parameters: Mapping[str, Any],
    *,
    sqlstate: str,
    constraint: str | None = None,
) -> None:
    with pytest.raises(SQLAlchemyError) as caught, engine.begin() as connection:
        connection.execute(text(statement), parameters)
    original = caught.value.orig
    assert getattr(original, "sqlstate", None) == sqlstate
    if constraint is not None:
        assert getattr(getattr(original, "diag", None), "constraint_name", None) == constraint


def test_stores_migration_schema_and_constraints(
    temporary_database: TemporaryDatabase,
) -> None:
    database = temporary_database
    migrate(database, "head")
    with database.engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0004"
    assert_database_schema(database.engine)

    insert = (
        "INSERT INTO stores (source, license_no, lat, lng) VALUES (:source, :license, :lat, :lng)"
    )
    with database.engine.begin() as connection:
        connection.execute(
            text(insert),
            {"source": "local", "license": "same", "lat": None, "lng": None},
        )
        connection.execute(
            text(insert),
            {"source": "other", "license": "same", "lat": -90, "lng": -180},
        )
        connection.execute(
            text(insert),
            {"source": "edge", "license": "edge", "lat": 90, "lng": 180},
        )

    assert_database_error(
        database.engine,
        insert,
        {"source": "local", "license": "same", "lat": None, "lng": None},
        sqlstate="23505",
        constraint="uq_stores_source_license_no",
    )
    for value in (Decimal("91"), Decimal("-91")):
        assert_database_error(
            database.engine,
            insert,
            {"source": "lat", "license": str(value), "lat": value, "lng": 0},
            sqlstate="23514",
            constraint="ck_stores_lat_range",
        )
    for value in (Decimal("181"), Decimal("-181")):
        assert_database_error(
            database.engine,
            insert,
            {"source": "lng", "license": str(value), "lat": 0, "lng": value},
            sqlstate="23514",
            constraint="ck_stores_lng_range",
        )
    assert_database_error(
        database.engine,
        "INSERT INTO stores (license_no) VALUES ('missing-source')",
        {},
        sqlstate="23502",
    )
    assert_database_error(
        database.engine,
        "INSERT INTO stores (source) VALUES ('missing-license')",
        {},
        sqlstate="23502",
    )
    assert_database_error(
        database.engine,
        "INSERT INTO stores (source, license_no, geom) "
        "VALUES ('geometry', 'line', ST_GeomFromText('LINESTRING(0 0, 1 1)', 4326))",
        {},
        sqlstate="22023",
    )
    assert_database_error(
        database.engine,
        "INSERT INTO stores (source, license_no, geom) "
        "VALUES ('geometry', 'srid', ST_SetSRID(ST_MakePoint(0, 0), 5179))",
        {},
        sqlstate="22023",
    )


def test_store_round_trip_and_migration_reversibility(
    temporary_database: TemporaryDatabase,
) -> None:
    database = temporary_database
    migrate(database, "head")
    factory = create_session_factory(database.engine)
    batch_id = uuid4()
    store = Store(
        source="synthetic",
        license_no="orm-1",
        raw_x="X=127,0",
        raw_y="Y=3,160",
        raw_crs="EPSG:5174",
        open_date=date(2099, 1, 1),
        close_date=date(2000, 1, 1),
        area_m2=Decimal("-1"),
        batch_id=batch_id,
        geom=WKTElement("POINT(126.9780 37.5665)", srid=4326),
    )
    with session_scope(factory) as session:
        session.add(store)
    with session_scope(factory) as session:
        loaded = session.get(Store, store.id)
        assert loaded is not None
        assert loaded.is_temporary is None
        assert loaded.category_review_flag is None
        assert loaded.is_franchise is None
        assert loaded.raw_x == "X=127,0"
        assert loaded.raw_y == "Y=3,160"
        assert loaded.open_date == date(2099, 1, 1)
        assert loaded.close_date == date(2000, 1, 1)
        assert loaded.area_m2 == Decimal("-1.00")
        assert loaded.updated_at.tzinfo is not None
        assert loaded.batch_id == batch_id

    with database.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO stores (source, license_no, open_date) "
                "VALUES ('synthetic', 'old-date', DATE '1950-01-01')"
            )
        )
        point = (
            connection.execute(
                text(
                    "SELECT ST_SRID(geom) AS srid, GeometryType(geom) AS kind, "
                    "ST_X(geom) AS x, ST_Y(geom) AS y FROM stores WHERE id=:id"
                ),
                {"id": store.id},
            )
            .mappings()
            .one()
        )
        assert point["srid"] == 4326
        assert point["kind"] == "POINT"
        assert float(point["x"]) == pytest.approx(126.978)
        assert float(point["y"]) == pytest.approx(37.5665)

    migrate(database, "0001", downgrade=True)
    with database.engine.connect() as connection:
        assert connection.scalar(text("SELECT to_regclass('stores')")) is None
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0001"
        assert connection.scalar(
            text("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname='postgis')")
        )
    migrate(database, "head")
    assert_database_schema(database.engine)
