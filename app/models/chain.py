"""Immutable chain membership publications, separate from external franchise fields."""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
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

PUBLICATION_RULE = "chain-publication-v1"
CHAIN_FIELDS = (
    "source",
    "license_no",
    "name",
    "category",
    "sub_category",
    "is_franchise",
    "brand_id",
    "address_road",
    "address_jibun",
    "building_key",
    "floor_unit",
    "open_date",
    "close_date",
    "status",
    "date_flag",
    "is_temporary",
)
CHAIN_REASONS = (
    "approved_alias_name_estimate",
    "catalog_exact_name_estimate",
    "semas_address_corroborated",
    "ambiguous_brand",
    "seed_catalog_name_collision",
)


class ChainSourceState(Base):
    __tablename__ = "chain_source_state"
    __table_args__ = (CheckConstraint("id=1 AND revision>=0", name="singleton_revision"),)
    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    revision: Mapped[int] = mapped_column(BigInteger, server_default="0")


class ChainPublication(Base):
    __tablename__ = "chain_publications"
    __table_args__ = (
        UniqueConstraint("fingerprint", name="uq_chain_publication_fingerprint"),
        CheckConstraint(
            "fingerprint ~ '^[0-9a-f]{64}$' AND plan_sha256 ~ '^[0-9a-f]{64}$' AND "
            "store_sha256 ~ '^[0-9a-f]{64}$' AND registry_sha256 ~ '^[0-9a-f]{64}$'",
            name="hashes",
        ),
        CheckConstraint(
            "row_count>=0 AND known_count>=0 AND known_count<=row_count",
            name="counts",
        ),
        CheckConstraint("rule_version='chain-publication-v1'", name="rule"),
        CheckConstraint(
            "jsonb_typeof(manifest)='object' AND jsonb_typeof(summary)='object'", name="json"
        ),
    )
    generation: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    plan_sha256: Mapped[str] = mapped_column(String(64))
    store_sha256: Mapped[str] = mapped_column(String(64))
    registry_sha256: Mapped[str] = mapped_column(String(64))
    rule_version: Mapped[str] = mapped_column(String(64))
    row_count: Mapped[int] = mapped_column(Integer)
    known_count: Mapped[int] = mapped_column(Integer)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONB)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChainPublicationBrand(Base):
    __tablename__ = "chain_publication_brands"
    __table_args__ = (
        CheckConstraint("name<>'' AND jsonb_typeof(evidence)='object'", name="evidence"),
    )
    generation: Mapped[UUID] = mapped_column(
        ForeignKey("chain_publications.generation"), primary_key=True
    )
    brand_key: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB)


class StoreChainClassification(Base):
    __tablename__ = "store_chain_classifications"
    __table_args__ = (
        ForeignKeyConstraint(
            ["generation", "brand_key"],
            ["chain_publication_brands.generation", "chain_publication_brands.brand_key"],
        ),
        UniqueConstraint("generation", "input_sha256", name="uq_chain_classification_fingerprint"),
        UniqueConstraint("generation", "semas_id", name="uq_chain_classification_semas"),
        CheckConstraint(
            "(classification_status='estimated' AND brand_key IS NOT NULL) OR "
            "(classification_status='conflict' AND brand_key IS NULL)",
            name="status_brand",
        ),
        CheckConstraint(
            "(classification_status='estimated' AND reason IN ('approved_alias_name_estimate',"
            "'catalog_exact_name_estimate','semas_address_corroborated')) OR "
            "(classification_status='conflict' AND reason IN "
            "('ambiguous_brand','seed_catalog_name_collision'))",
            name="reason",
        ),
        CheckConstraint(
            "(reason='semas_address_corroborated')=(semas_id IS NOT NULL)", name="semas"
        ),
        CheckConstraint(
            "source IN ('general_restaurant','rest_cafe') AND license_no<>'' AND name<>'' AND "
            "input_sha256 ~ '^[0-9a-f]{64}$'",
            name="input",
        ),
        CheckConstraint(
            "(category='cafe' AND sub_category='cafe') OR "
            "(category='restaurant' AND sub_category IN ('korean','chinese','japanese','western'))",
            name="category",
        ),
    )
    generation: Mapped[UUID] = mapped_column(
        ForeignKey("chain_publications.generation"), primary_key=True
    )
    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    license_no: Mapped[str] = mapped_column(String(64), primary_key=True)
    classification_status: Mapped[str] = mapped_column(String(16))
    brand_key: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    reason: Mapped[str] = mapped_column(String(64))
    semas_id: Mapped[str | None] = mapped_column(String(64))
    input_sha256: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(32))
    sub_category: Mapped[str] = mapped_column(String(32))
    is_franchise: Mapped[bool | None] = mapped_column(Boolean)
    brand_id: Mapped[int | None] = mapped_column(BigInteger)
    address_road: Mapped[str | None] = mapped_column(Text)
    address_jibun: Mapped[str | None] = mapped_column(Text)
    building_key: Mapped[str | None] = mapped_column(String(255))
    floor_unit: Mapped[str | None] = mapped_column(String(100))
    open_date: Mapped[date | None] = mapped_column(Date)
    close_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str | None] = mapped_column(String(32))
    date_flag: Mapped[str | None] = mapped_column(Text)
    is_temporary: Mapped[bool | None] = mapped_column(Boolean)


class ChainPublicationState(Base):
    __tablename__ = "chain_publication_state"
    __table_args__ = (CheckConstraint("id=1 AND validated_source_revision>=0", name="singleton"),)
    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    generation: Mapped[UUID] = mapped_column(ForeignKey("chain_publications.generation"))
    validated_source_revision: Mapped[int] = mapped_column(BigInteger)
    activated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
