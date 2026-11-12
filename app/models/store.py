from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from geoalchemy2 import Geography, Geometry
from geoalchemy2.elements import WKBElement, WKTElement
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Identity,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    cast,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Store(Base):
    __tablename__ = "stores"
    __table_args__ = (
        UniqueConstraint("source", "license_no", name="uq_stores_source_license_no"),
        CheckConstraint("lat IS NULL OR lat BETWEEN -90 AND 90", name="lat_range"),
        CheckConstraint("lng IS NULL OR lng BETWEEN -180 AND 180", name="lng_range"),
        Index("ix_stores_geom_gist", "geom", postgresql_using="gist"),
        Index("ix_stores_building_key", "building_key"),
        Index("ix_stores_category_status", "category", "status"),
        Index("ix_stores_open_date", "open_date"),
        Index("ix_stores_close_date", "close_date"),
        Index(
            "ix_stores_provenance",
            "batch_id",
            "source",
            "category",
            "sub_category",
            postgresql_where=text("deleted_at IS NULL AND category_review_flag IS NOT TRUE"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    license_no: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    gu_code: Mapped[str | None] = mapped_column(String(10))
    name: Mapped[str | None] = mapped_column(String(255))

    address_road: Mapped[str | None] = mapped_column(Text)
    address_jibun: Mapped[str | None] = mapped_column(Text)
    building_key: Mapped[str | None] = mapped_column(String(255))
    floor_unit: Mapped[str | None] = mapped_column(String(100))
    location_level: Mapped[str | None] = mapped_column(String(32))

    open_date: Mapped[date | None] = mapped_column(Date)
    close_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str | None] = mapped_column(String(32))
    status_code: Mapped[str | None] = mapped_column(String(32))
    bzstat_nm: Mapped[str | None] = mapped_column(String(100))

    category: Mapped[str | None] = mapped_column(String(32))
    sub_category: Mapped[str | None] = mapped_column(String(32))
    seoul_induty_cd: Mapped[str | None] = mapped_column(String(32))
    area_m2: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))

    lat: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    lng: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    geom: Mapped[WKBElement | WKTElement | None] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=False)
    )
    raw_x: Mapped[str | None] = mapped_column(Text)
    raw_y: Mapped[str | None] = mapped_column(Text)
    raw_crs: Mapped[str | None] = mapped_column(String(64))
    coord_source: Mapped[str | None] = mapped_column(String(32))
    coord_flag: Mapped[str | None] = mapped_column(Text)

    date_flag: Mapped[str | None] = mapped_column(Text)
    is_temporary: Mapped[bool | None] = mapped_column(Boolean)
    category_review_flag: Mapped[bool | None] = mapped_column(Boolean)

    is_franchise: Mapped[bool | None] = mapped_column(Boolean)
    brand_id: Mapped[int | None] = mapped_column(BigInteger)

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    batch_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))


# No geography typmod: query and index must have the same cast expression.
STORE_GEOGRAPHY = Geography(geometry_type=None, spatial_index=False)
Index(
    "ix_stores_geography_gist",
    cast(Store.geom, STORE_GEOGRAPHY),
    postgresql_using="gist",
    postgresql_where=Store.geom.is_not(None),
)
