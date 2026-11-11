"""Persist verified source dates separately from database write timestamps."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "store_import_batches",
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("data_updated_at", sa.Date(), nullable=True),
        sa.Column("update_reason", sa.String(64), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("collection_basis", sa.String(64), nullable=False),
        sa.Column("input_kind", sa.String(32), nullable=False),
        sa.Column("input_sha256", sa.String(64), nullable=True),
        sa.Column("rows_sha256", sa.String(64), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("map_version", sa.String(64), nullable=False),
        sa.Column("rule_version", sa.String(64), nullable=False),
        sa.Column(
            "loaded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("batch_id", name=op.f("pk_store_import_batches")),
    )


def downgrade() -> None:
    op.drop_table("store_import_batches")
