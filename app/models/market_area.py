from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from geoalchemy2 import Geometry
from geoalchemy2.elements import WKBElement, WKTElement
from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MarketAreaVersion(Base):
    __tablename__ = "market_area_versions"
    __table_args__ = (
        UniqueConstraint("input_sha256", "rule_version", name="uq_market_area_versions_input_rule"),
        CheckConstraint("row_count > 0 AND repaired_count BETWEEN 0 AND row_count", name="counts"),
        CheckConstraint("input_bytes > 0 AND source_crs = 5181", name="source"),
        CheckConstraint(
            "input_sha256 ~ '^[0-9a-f]{64}$' AND content_sha256 ~ '^[0-9a-f]{64}$'", name="hashes"
        ),
    )
    version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    source_dataset: Mapped[str] = mapped_column(String(32), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_file_date: Mapped[date] = mapped_column(Date, nullable=False)
    boundary_as_of: Mapped[date | None] = mapped_column(Date)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    input_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    source_crs: Mapped[int] = mapped_column(Integer, nullable=False)
    rule_version: Mapped[str] = mapped_column(String(64), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    repaired_count: Mapped[int] = mapped_column(Integer, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    postgis_version: Mapped[str] = mapped_column(Text, nullable=False)
    loaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class MarketArea(Base):
    __tablename__ = "market_areas"
    __table_args__ = (
        CheckConstraint("market_code ~ '^[0-9]{7}$' AND gu_code ~ '^11[0-9]{3}$'", name="codes"),
        CheckConstraint("area_m2 > 0 AND length(market_name) > 0", name="area_name"),
        CheckConstraint(
            "(market_type_code='A' AND market_type='alley') OR "
            "(market_type_code='D' AND market_type='developed') OR "
            "(market_type_code='R' AND market_type='traditional_market') OR "
            "(market_type_code='U' AND market_type='tourism_zone')",
            name="type",
        ),
        CheckConstraint("source_feature_sha256 ~ '^[0-9a-f]{64}$'", name="hash"),
        CheckConstraint(
            "(ST_IsValidDetail(geom,0)).valid AND NOT ST_IsEmpty(geom)", name="geometry"
        ),
        Index("ix_market_areas_geom_gist", "geom", postgresql_using="gist"),
        Index("ix_market_areas_version_gu", "version_id", "gu_code"),
        Index("ix_market_areas_version_type", "version_id", "market_type"),
    )
    version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("market_area_versions.version_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    market_code: Mapped[str] = mapped_column(String(7), primary_key=True)
    market_name: Mapped[str] = mapped_column(String(255), nullable=False)
    market_type: Mapped[str] = mapped_column(String(32), nullable=False)
    market_type_code: Mapped[str] = mapped_column(String(1), nullable=False)
    gu_code: Mapped[str] = mapped_column(String(5), nullable=False)
    area_m2: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    source_feature_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    geometry_repaired: Mapped[bool] = mapped_column(nullable=False)
    geom: Mapped[WKBElement | WKTElement] = mapped_column(
        Geometry("MULTIPOLYGON", srid=4326, spatial_index=False), nullable=False
    )
