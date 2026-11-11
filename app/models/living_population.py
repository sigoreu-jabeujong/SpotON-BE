from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from geoalchemy2 import Geometry
from geoalchemy2.elements import WKBElement, WKTElement
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LivingGridVersion(Base):
    __tablename__ = "living_grid_versions"
    __table_args__ = (
        UniqueConstraint("input_sha256", "rule_version", name="uq_living_grid_versions_input_rule"),
        CheckConstraint("input_bytes>0 AND row_count>0 AND source_crs=5179", name="source"),
        CheckConstraint("jsonb_typeof(source_metadata)='object'", name="metadata"),
        CheckConstraint(
            "input_sha256 ~ '^[0-9a-f]{64}$' AND raw_content_sha256 ~ "
            "'^[0-9a-f]{64}$' AND content_sha256 ~ '^[0-9a-f]{64}$'",
            name="hashes",
        ),
    )
    grid_version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    input_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    rule_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_crs: Mapped[int] = mapped_column(Integer, nullable=False)
    grid_as_of: Mapped[date | None] = mapped_column(Date)
    source_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    postgis_version: Mapped[str] = mapped_column(Text, nullable=False)
    loaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class LivingGrid(Base):
    __tablename__ = "living_grids"
    __table_args__ = (
        CheckConstraint(
            "grid_id ~ '^[가-힣]{2}[0-9]{8}$' AND length(source_gid) BETWEEN 1 AND 14", name="codes"
        ),
        CheckConstraint("center_x>0 AND center_y>0", name="center"),
        CheckConstraint("source_row_sha256 ~ '^[0-9a-f]{64}$'", name="hash"),
        CheckConstraint(
            "(ST_IsValidDetail(geom,0)).valid AND NOT ST_IsEmpty(geom)", name="geometry"
        ),
        Index("ix_living_grids_geom_gist", "geom", postgresql_using="gist"),
    )
    grid_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("living_grid_versions.grid_version_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    grid_id: Mapped[str] = mapped_column(String(10), primary_key=True)
    source_gid: Mapped[str] = mapped_column(String(14), nullable=False)
    center_x: Mapped[int] = mapped_column(BigInteger, nullable=False)
    center_y: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_row_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    geom: Mapped[WKBElement | WKTElement] = mapped_column(
        Geometry("MULTIPOLYGON", srid=4326, spatial_index=False), nullable=False
    )


class LivingPopulationVersion(Base):
    __tablename__ = "living_population_versions"
    __table_args__ = (
        UniqueConstraint(
            "input_sha256",
            "rule_version",
            "grid_version_id",
            name="uq_living_population_versions_input_rule_grid",
        ),
        UniqueConstraint(
            "version_id",
            "grid_version_id",
            "observation_date",
            name="uq_living_population_versions_identity",
        ),
        CheckConstraint(
            "row_count>0 AND spatial_compatibility='unverified' AND jsonb_typeof(sources)='object'",
            name="source",
        ),
        CheckConstraint("observation_date >= DATE '2000-01-01'", name="date"),
        CheckConstraint(
            "input_sha256 ~ '^[0-9a-f]{64}$' AND content_sha256 ~ '^[0-9a-f]{64}$'", name="hashes"
        ),
        Index("ix_living_population_versions_date", "observation_date"),
    )
    version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    grid_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("living_grid_versions.grid_version_id", ondelete="RESTRICT"),
        nullable=False,
    )
    observation_date: Mapped[date] = mapped_column(Date, nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(64), nullable=False)
    sources: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    spatial_compatibility: Mapped[str] = mapped_column(String(16), nullable=False)
    loaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class LivingPopulationObservation(Base):
    __tablename__ = "living_population_observations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["version_id", "grid_version_id", "observation_date"],
            [
                "living_population_versions.version_id",
                "living_population_versions.grid_version_id",
                "living_population_versions.observation_date",
            ],
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["grid_version_id", "located_grid_id"],
            ["living_grids.grid_version_id", "living_grids.grid_id"],
            ondelete="RESTRICT",
            onupdate="RESTRICT",
            match="SIMPLE",
        ),
        CheckConstraint(
            "source IN ('local','long','short') AND hour BETWEEN 0 AND 23 AND "
            "admin_code ~ '^11[0-9]{6}$' AND grid_id ~ '^[가-힣]{2}[0-9]{8}$'",
            name="codes",
        ),
        CheckConstraint(
            "(value_status='observed' AND population IS NOT NULL AND population>=0 "
            "AND population<1000000000000000) OR (value_status IN "
            "('suppressed','missing') AND population IS NULL)",
            name="value",
        ),
        CheckConstraint(
            "(geometry_status='located' AND located_grid_id IS NOT NULL AND "
            "located_grid_id=grid_id) OR (geometry_status='unlocated' AND "
            "located_grid_id IS NULL)",
            name="location",
        ),
        CheckConstraint("source_row_sha256 ~ '^[0-9a-f]{64}$'", name="hash"),
        Index(
            "ix_living_population_located",
            "version_id",
            "located_grid_id",
            "hour",
            postgresql_where=text("located_grid_id IS NOT NULL"),
        ),
    )
    version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    source: Mapped[str] = mapped_column(String(8), primary_key=True)
    hour: Mapped[int] = mapped_column(Integer, primary_key=True)
    admin_code: Mapped[str] = mapped_column(String(8), primary_key=True)
    grid_id: Mapped[str] = mapped_column(String(10), primary_key=True)
    grid_version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    observation_date: Mapped[date] = mapped_column(Date, nullable=False)
    located_grid_id: Mapped[str | None] = mapped_column(String(10))
    population: Mapped[Decimal | None] = mapped_column(Numeric(20, 5))
    value_status: Mapped[str] = mapped_column(String(16), nullable=False)
    geometry_status: Mapped[str] = mapped_column(String(16), nullable=False)
    source_row_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
