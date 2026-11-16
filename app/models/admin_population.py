"""Immutable administrative reference sources, separate from whole-grid population."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from geoalchemy2 import Geometry
from geoalchemy2.elements import WKBElement, WKTElement
from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

CODE_SYSTEM = "mois_admin8_reference"


class AdminBoundaryVersion(Base):
    __tablename__ = "admin_boundary_versions"
    __table_args__ = (
        UniqueConstraint("input_sha256", "rule_version", name="uq_admin_boundary_input_rule"),
        UniqueConstraint("version_id", "code_system", name="uq_admin_boundary_code_system"),
        CheckConstraint(
            "source_dataset='OA-22160' AND source_crs=5181 AND row_count>0", name="source"
        ),
        CheckConstraint("code_system='mois_admin8_reference'", name="code_system"),
        CheckConstraint(
            "input_sha256 ~ '^[0-9a-f]{64}$' AND content_sha256 ~ '^[0-9a-f]{64}$'", name="hashes"
        ),
    )
    version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    source_dataset: Mapped[str] = mapped_column(String(32), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    code_system: Mapped[str] = mapped_column(String(64), nullable=False)
    source_crs: Mapped[int] = mapped_column(Integer, nullable=False)
    source_file_date: Mapped[date | None] = mapped_column(Date)
    boundary_as_of: Mapped[date | None] = mapped_column(Date)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(128), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    loaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AdminArea(Base):
    __tablename__ = "admin_areas"
    __table_args__ = (
        ForeignKeyConstraint(
            ["boundary_version_id", "code_system"],
            ["admin_boundary_versions.version_id", "admin_boundary_versions.code_system"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "boundary_version_id", "code_system", "admin_code", name="uq_admin_area_identity"
        ),
        CheckConstraint(
            "admin_code ~ '^11[0-9]{6}$' AND length(btrim(admin_name))>0", name="identity"
        ),
        CheckConstraint("source_feature_sha256 ~ '^[0-9a-f]{64}$'", name="hash"),
        CheckConstraint(
            "ST_IsValid(geom) AND NOT ST_IsEmpty(geom) AND ST_Area(geom)>0", name="geometry"
        ),
        Index("ix_admin_areas_geom_gist", "geom", postgresql_using="gist"),
    )
    boundary_version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    admin_code: Mapped[str] = mapped_column(String(8), primary_key=True)
    code_system: Mapped[str] = mapped_column(String(64), nullable=False)
    admin_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_feature_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    geometry_repaired: Mapped[bool] = mapped_column(nullable=False)
    geom: Mapped[WKBElement | WKTElement] = mapped_column(
        Geometry("MULTIPOLYGON", srid=4326, spatial_index=False), nullable=False
    )


class AdminPopulationVersion(Base):
    __tablename__ = "admin_population_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["boundary_version_id", "code_system"],
            ["admin_boundary_versions.version_id", "admin_boundary_versions.code_system"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "input_sha256",
            "rule_version",
            "observation_date",
            "source",
            "boundary_version_id",
            name="uq_admin_population_source",
        ),
        UniqueConstraint(
            "version_id",
            "boundary_version_id",
            "code_system",
            "observation_date",
            "source",
            name="uq_admin_population_scope",
        ),
        CheckConstraint(
            "source_dataset='OA-23016' AND source='local' AND "
            "source_series='seoul_250m_admin_local'",
            name="source",
        ),
        CheckConstraint(
            "row_count>0 AND source_row_count=row_count+excluded_rows AND excluded_rows>=0",
            name="counts",
        ),
        CheckConstraint(
            "input_sha256 ~ '^[0-9a-f]{64}$' AND content_sha256 ~ '^[0-9a-f]{64}$' "
            "AND member_sha256 ~ '^[0-9a-f]{64}$'",
            name="hashes",
        ),
        Index("ix_admin_population_date", "observation_date", "source"),
    )
    version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    boundary_version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    code_system: Mapped[str] = mapped_column(String(64), nullable=False)
    source_dataset: Mapped[str] = mapped_column(String(32), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_series: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(8), nullable=False)
    observation_date: Mapped[date] = mapped_column(Date, nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    member_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(128), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    source_row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    excluded_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    quality: Mapped[dict[str, int]] = mapped_column(JSONB, nullable=False)
    loaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AdminPopulationHour(Base):
    __tablename__ = "admin_population_hours"
    __table_args__ = (
        ForeignKeyConstraint(
            ["version_id", "boundary_version_id", "code_system", "observation_date", "source"],
            [
                "admin_population_versions.version_id",
                "admin_population_versions.boundary_version_id",
                "admin_population_versions.code_system",
                "admin_population_versions.observation_date",
                "admin_population_versions.source",
            ],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["boundary_version_id", "code_system", "admin_code"],
            [
                "admin_areas.boundary_version_id",
                "admin_areas.code_system",
                "admin_areas.admin_code",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint("hour BETWEEN 0 AND 23 AND admin_code ~ '^11[0-9]{6}$'", name="identity"),
        CheckConstraint(
            "(value_status='observed' AND population IS NOT NULL AND population>=0 "
            "AND population<1000000000000000) OR (value_status IN "
            "('suppressed','missing') AND population IS NULL)",
            name="value",
        ),
        CheckConstraint("source_row_sha256 ~ '^[0-9a-f]{64}$'", name="hash"),
    )
    version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    admin_code: Mapped[str] = mapped_column(String(8), primary_key=True)
    hour: Mapped[int] = mapped_column(Integer, primary_key=True)
    boundary_version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    code_system: Mapped[str] = mapped_column(String(64), nullable=False)
    observation_date: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(String(8), nullable=False)
    population: Mapped[Decimal | None] = mapped_column(Numeric(20, 5))
    value_status: Mapped[str] = mapped_column(String(16), nullable=False)
    source_row_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
