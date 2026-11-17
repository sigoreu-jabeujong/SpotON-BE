"""Cover supported-store provenance without scanning the full stores heap."""

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_index(
        "ix_stores_provenance",
        "stores",
        ["batch_id", "source", "category", "sub_category"],
        postgresql_where=sa.text("deleted_at IS NULL AND category_review_flag IS NOT TRUE"),
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_index("ix_stores_provenance", table_name="stores")
