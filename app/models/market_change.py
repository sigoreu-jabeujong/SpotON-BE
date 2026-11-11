from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
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


class MarketChangeVersion(Base):
    __tablename__ = "market_change_versions"
    __table_args__ = (
        UniqueConstraint(
            "input_sha256",
            "source_year",
            "rule_version",
            "code_check_boundary_version_id",
            name="uq_market_change_versions_input_year_rule_boundary",
        ),
        CheckConstraint(
            "source_rows=row_count+excluded_rows AND row_count>0 AND excluded_rows>=0",
            name="counts",
        ),
        CheckConstraint(
            "source_year BETWEEN 2000 AND 2099 AND "
            "source_year < EXTRACT(YEAR FROM retrieved_at AT TIME ZONE 'Asia/Seoul') AND "
            "isfinite(retrieved_at) AND source_file_date IS NULL",
            name="dates",
        ),
        CheckConstraint(
            "input_bytes>0 AND source_dataset='OA-15576' AND "
            "source_encoding IN ('cp949','utf-8-sig') AND "
            "boundary_compatibility='unverified' AND jsonb_typeof(code_check)='object'",
            name="source",
        ),
        CheckConstraint(
            "input_sha256 ~ '^[0-9a-f]{64}$' AND content_sha256 ~ '^[0-9a-f]{64}$'",
            name="hashes",
        ),
    )
    version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    source_dataset: Mapped[str] = mapped_column(String(32), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_year: Mapped[int] = mapped_column(Integer, nullable=False)
    source_file_date: Mapped[date | None] = mapped_column(Date)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    input_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    source_encoding: Mapped[str] = mapped_column(String(16), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    excluded_rows: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="Rows outside the selected year; not industry exclusions"
    )
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    code_check_boundary_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("market_area_versions.version_id", ondelete="RESTRICT"),
        nullable=False,
    )
    code_check: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    boundary_compatibility: Mapped[str] = mapped_column(String(16), nullable=False)
    loaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MarketChange(Base):
    __tablename__ = "market_changes"
    __table_args__ = (
        CheckConstraint(
            "market_code ~ '^[0-9]{7}$' AND quarter ~ '^20[0-9]{2}[1-4]$' AND "
            "market_type_code IN ('A','D','R','U')",
            name="codes",
        ),
        CheckConstraint(
            "length(btrim(market_name))>0 AND length(btrim(market_type_name))>0",
            name="names",
        ),
        CheckConstraint(
            "(change_code='LL' AND change_name='다이나믹') OR "
            "(change_code='LH' AND change_name='상권확장') OR "
            "(change_code='HL' AND change_name='상권축소') OR "
            "(change_code='HH' AND change_name='정체')",
            name="change_pair",
        ),
        CheckConstraint(
            "(operating_months_avg IS NULL OR operating_months_avg>=0) AND "
            "(closed_months_avg IS NULL OR closed_months_avg>=0) AND "
            "(seoul_operating_months_avg IS NULL OR seoul_operating_months_avg>=0) AND "
            "(seoul_closed_months_avg IS NULL OR seoul_closed_months_avg>=0)",
            name="months",
        ),
        CheckConstraint("source_row_sha256 ~ '^[0-9a-f]{64}$'", name="hash"),
        Index("ix_market_changes_version_quarter_change", "version_id", "quarter", "change_code"),
    )
    version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("market_change_versions.version_id", ondelete="RESTRICT", onupdate="RESTRICT"),
        primary_key=True,
    )
    market_code: Mapped[str] = mapped_column(String(7), primary_key=True)
    quarter: Mapped[str] = mapped_column(String(5), primary_key=True)
    market_name: Mapped[str] = mapped_column(String(255), nullable=False)
    market_type_code: Mapped[str] = mapped_column(String(1), nullable=False)
    market_type_name: Mapped[str] = mapped_column(String(32), nullable=False)
    change_code: Mapped[str] = mapped_column(String(2), nullable=False)
    change_name: Mapped[str] = mapped_column(String(32), nullable=False)
    operating_months_avg: Mapped[int | None] = mapped_column(Integer)
    closed_months_avg: Mapped[int | None] = mapped_column(Integer)
    seoul_operating_months_avg: Mapped[int | None] = mapped_column(Integer)
    seoul_closed_months_avg: Mapped[int | None] = mapped_column(Integer)
    source_row_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
