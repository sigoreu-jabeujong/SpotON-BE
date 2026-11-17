"""Index the exact geography expression used for meter-radius searches."""

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_stores_geography_gist ON stores USING gist ((geom::geography)) "
        "WHERE geom IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_index("ix_stores_geography_gist", table_name="stores")
