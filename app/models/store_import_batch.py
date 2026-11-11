from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Date, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class StoreImportBatch(Base):
    """Visible only after the source transaction has committed successfully."""

    __tablename__ = "store_import_batches"

    batch_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    data_updated_at: Mapped[date | None] = mapped_column(Date)
    update_reason: Mapped[str | None] = mapped_column(String(64))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    collection_basis: Mapped[str] = mapped_column(String(64), nullable=False)
    input_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    input_sha256: Mapped[str | None] = mapped_column(String(64))
    rows_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    map_version: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(64), nullable=False)
    loaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
