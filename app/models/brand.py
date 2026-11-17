"""Catalog evidence is separate from externally owned Store franchise fields."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

MAPPING_RULE = "ftc-name-exact-estimate-v1"


class BrandCatalogVersion(Base):
    __tablename__ = "brand_catalog_versions"
    __table_args__ = (
        UniqueConstraint("input_sha256", "catalog_rule", name="uq_brand_catalog_input_rule"),
        CheckConstraint(
            "input_sha256 ~ '^[0-9a-f]{64}$' AND content_sha256 ~ '^[0-9a-f]{64}$'", name="hashes"
        ),
        CheckConstraint(
            "reference_year BETWEEN 2000 AND 9999 AND row_count BETWEEN 1 AND 100000", name="source"
        ),
        CheckConstraint("catalog_rule='ftc-brand-catalog-exact-name-v2'", name="rule"),
    )
    catalog_version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    input_sha256: Mapped[str] = mapped_column(String(64))
    content_sha256: Mapped[str] = mapped_column(String(64))
    catalog_rule: Mapped[str] = mapped_column(String(64))
    reference_year: Mapped[int] = mapped_column(Integer)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    row_count: Mapped[int] = mapped_column(Integer)
    loaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Brand(Base):
    __tablename__ = "brands"
    __table_args__ = (
        UniqueConstraint(
            "catalog_version_id",
            "management_no",
            "headquarter_no",
            name="uq_brands_catalog_source_key",
        ),
        UniqueConstraint("brand_id", "catalog_version_id", name="uq_brands_id_catalog"),
        CheckConstraint(
            "management_no ~ '^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$' AND "
            "headquarter_no ~ '^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$'",
            name="source_keys",
        ),
        CheckConstraint(
            "industry IN ('외식','서비스','도소매') AND name<>'' AND "
            "normalized_name<>'' AND sub_industry<>''",
            name="content",
        ),
    )
    brand_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    catalog_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("brand_catalog_versions.catalog_version_id")
    )
    management_no: Mapped[str] = mapped_column(String(64))
    headquarter_no: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(255))
    normalized_name: Mapped[str] = mapped_column(Text)
    industry: Mapped[str] = mapped_column(String(100))
    sub_industry: Mapped[str] = mapped_column(String(255))


class BrandMappingRun(Base):
    __tablename__ = "brand_mapping_runs"
    __table_args__ = (
        UniqueConstraint(
            "catalog_version_id",
            "rule_version",
            "store_input_sha256",
            name="uq_brand_mapping_run_input",
        ),
        UniqueConstraint("run_id", "catalog_version_id", name="uq_brand_mapping_run_catalog"),
        CheckConstraint(
            "rule_version='ftc-name-exact-estimate-v1' AND store_input_sha256 ~ '^[0-9a-f]{64}$'",
            name="rule_hash",
        ),
        CheckConstraint(
            "row_count>=0 AND matched_count>=0 AND matched_count<=row_count AND "
            "jsonb_typeof(counts)='object'",
            name="counts",
        ),
    )
    run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    catalog_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("brand_catalog_versions.catalog_version_id")
    )
    rule_version: Mapped[str] = mapped_column(String(64))
    store_input_sha256: Mapped[str] = mapped_column(String(64))
    row_count: Mapped[int] = mapped_column(Integer)
    matched_count: Mapped[int] = mapped_column(Integer)
    counts: Mapped[dict[str, Any]] = mapped_column(JSONB)
    loaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StoreBrandMatch(Base):
    __tablename__ = "store_brand_matches"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "catalog_version_id"],
            ["brand_mapping_runs.run_id", "brand_mapping_runs.catalog_version_id"],
        ),
        ForeignKeyConstraint(
            ["brand_id", "catalog_version_id"], ["brands.brand_id", "brands.catalog_version_id"]
        ),
        Index(
            "uq_store_brand_matches_run_store",
            "run_id",
            "source",
            "license_no",
            unique=True,
            postgresql_include=["name", "category", "sub_category"],
        ),
        CheckConstraint(
            "source IN ('general_restaurant','rest_cafe') AND license_no<>'' "
            "AND name<>'' AND input_sha256 ~ '^[0-9a-f]{64}$'",
            name="input",
        ),
        CheckConstraint(
            "(category='cafe' AND sub_category='cafe') OR "
            "(category='restaurant' AND sub_category IN "
            "('korean','chinese','japanese','western'))",
            name="category",
        ),
    )
    match_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    catalog_version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    brand_id: Mapped[int] = mapped_column(BigInteger)
    source: Mapped[str] = mapped_column(String(32))
    license_no: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(32))
    sub_category: Mapped[str] = mapped_column(String(32))
    input_sha256: Mapped[str] = mapped_column(String(64))


class BrandMappingState(Base):
    __tablename__ = "brand_mapping_state"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "catalog_version_id"],
            ["brand_mapping_runs.run_id", "brand_mapping_runs.catalog_version_id"],
        ),
        CheckConstraint("id=1", name="singleton"),
    )
    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    catalog_version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
