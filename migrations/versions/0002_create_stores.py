"""stores 핵심 데이터 모델 생성."""

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "stores",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("license_no", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("gu_code", sa.String(length=10), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("address_road", sa.Text(), nullable=True),
        sa.Column("address_jibun", sa.Text(), nullable=True),
        sa.Column("building_key", sa.String(length=255), nullable=True),
        sa.Column("floor_unit", sa.String(length=100), nullable=True),
        sa.Column("location_level", sa.String(length=32), nullable=True),
        sa.Column("open_date", sa.Date(), nullable=True),
        sa.Column("close_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=True),
        sa.Column("status_code", sa.String(length=32), nullable=True),
        sa.Column("bzstat_nm", sa.String(length=100), nullable=True),
        sa.Column("category", sa.String(length=32), nullable=True),
        sa.Column("sub_category", sa.String(length=32), nullable=True),
        sa.Column("seoul_induty_cd", sa.String(length=32), nullable=True),
        sa.Column("area_m2", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("lat", sa.Numeric(precision=10, scale=7), nullable=True),
        sa.Column("lng", sa.Numeric(precision=10, scale=7), nullable=True),
        sa.Column(
            "geom",
            Geometry(geometry_type="POINT", srid=4326, spatial_index=False),
            nullable=True,
        ),
        sa.Column("raw_x", sa.Text(), nullable=True),
        sa.Column("raw_y", sa.Text(), nullable=True),
        sa.Column("raw_crs", sa.String(length=64), nullable=True),
        sa.Column("coord_source", sa.String(length=32), nullable=True),
        sa.Column("coord_flag", sa.Text(), nullable=True),
        sa.Column("date_flag", sa.Text(), nullable=True),
        sa.Column("is_temporary", sa.Boolean(), nullable=True),
        sa.Column("category_review_flag", sa.Boolean(), nullable=True),
        sa.Column("is_franchise", sa.Boolean(), nullable=True),
        sa.Column("brand_id", sa.BigInteger(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint(
            "lat IS NULL OR lat BETWEEN -90 AND 90", name=op.f("ck_stores_lat_range")
        ),
        sa.CheckConstraint(
            "lng IS NULL OR lng BETWEEN -180 AND 180", name=op.f("ck_stores_lng_range")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stores")),
        sa.UniqueConstraint("source", "license_no", name=op.f("uq_stores_source_license_no")),
    )
    op.create_index(
        op.f("ix_stores_geom_gist"),
        "stores",
        ["geom"],
        unique=False,
        postgresql_using="gist",
    )
    op.create_index(op.f("ix_stores_building_key"), "stores", ["building_key"], unique=False)
    op.create_index(
        op.f("ix_stores_category_status"),
        "stores",
        ["category", "status"],
        unique=False,
    )
    op.create_index(op.f("ix_stores_open_date"), "stores", ["open_date"], unique=False)
    op.create_index(op.f("ix_stores_close_date"), "stores", ["close_date"], unique=False)


def downgrade() -> None:
    op.drop_table("stores")
