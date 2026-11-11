from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MarketSaleVersion(Base):
    __tablename__ = "market_sale_versions"
    __table_args__ = (
        UniqueConstraint(
            "input_sha256",
            "rule_version",
            "code_check_boundary_version_id",
            "code_check_store_version_id",
            name="uq_market_sale_versions_input_rule_references",
        ),
        CheckConstraint(
            "source_rows = row_count + excluded_rows AND row_count > 0 AND excluded_rows >= 0",
            name="counts",
        ),
        CheckConstraint(
            "source_year BETWEEN 2000 AND 2099 AND source_file_date > make_date(source_year,12,31)",
            name="year",
        ),
        CheckConstraint(
            "input_bytes > 0 AND member_bytes > 0 AND source_dataset='OA-15572' AND "
            "source_encoding IN ('cp949','utf-8-sig') AND boundary_compatibility='unverified' AND "
            "jsonb_typeof(code_check)='object' AND currency='KRW' AND "
            "amount_basis='source_reported' AND amount_period_status='unverified'",
            name="source",
        ),
        CheckConstraint(
            "input_sha256 ~ '^[0-9a-f]{64}$' AND member_sha256 ~ '^[0-9a-f]{64}$' AND "
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            name="hashes",
        ),
    )
    version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    source_dataset: Mapped[str] = mapped_column(String(32), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_file_date: Mapped[date] = mapped_column(Date, nullable=False)
    source_year: Mapped[int] = mapped_column(Integer, nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    input_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    member_name: Mapped[str] = mapped_column(Text, nullable=False)
    member_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    member_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    member_modified: Mapped[str] = mapped_column(String(19), nullable=False)
    source_encoding: Mapped[str] = mapped_column(String(16), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    excluded_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    code_check_boundary_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("market_area_versions.version_id", ondelete="RESTRICT"),
        nullable=False,
    )
    code_check_store_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("market_store_versions.version_id", ondelete="RESTRICT"),
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    amount_basis: Mapped[str] = mapped_column(String(32), nullable=False)
    amount_period_status: Mapped[str] = mapped_column(String(16), nullable=False)
    code_check: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    boundary_compatibility: Mapped[str] = mapped_column(String(16), nullable=False)
    loaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class MarketSale(Base):
    __tablename__ = "market_sales"
    __table_args__ = (
        CheckConstraint(
            "market_code ~ '^[0-9]{7}$' AND quarter ~ '^20[0-9]{2}[1-4]$' AND "
            "induty_cd IN ('CS100001','CS100002','CS100003','CS100004','CS100010') AND "
            "market_type_code IN ('A','D','R','U')",
            name="codes",
        ),
        CheckConstraint(
            "length(btrim(market_name))>0 AND length(btrim(market_type_name))>0 AND "
            "length(btrim(induty_name))>0",
            name="names",
        ),
        CheckConstraint(
            "(est_sales IS NULL OR est_sales >= 0) AND "
            "(source_sales_count IS NULL OR source_sales_count >= 0)",
            name="nonnegative",
        ),
        CheckConstraint("source_row_sha256 ~ '^[0-9a-f]{64}$'", name="hash"),
        Index("ix_market_sales_version_quarter_induty", "version_id", "quarter", "induty_cd"),
    )
    version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("market_sale_versions.version_id", ondelete="RESTRICT", onupdate="RESTRICT"),
        primary_key=True,
    )
    market_code: Mapped[str] = mapped_column(String(7), primary_key=True)
    quarter: Mapped[str] = mapped_column(String(5), primary_key=True)
    induty_cd: Mapped[str] = mapped_column(String(8), primary_key=True)
    market_name: Mapped[str] = mapped_column(String(255), nullable=False)
    market_type_code: Mapped[str] = mapped_column(String(1), nullable=False)
    market_type_name: Mapped[str] = mapped_column(String(32), nullable=False)
    induty_name: Mapped[str] = mapped_column(String(255), nullable=False)
    est_sales: Mapped[int | None] = mapped_column(BigInteger)
    source_sales_count: Mapped[int | None] = mapped_column(BigInteger)
    source_row_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
