"""Immutable source versions and validated WGS84 market boundaries."""

import geoalchemy2
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "market_area_versions",
        sa.Column("version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_dataset", sa.String(32), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_file_date", sa.Date(), nullable=False),
        sa.Column("boundary_as_of", sa.Date(), nullable=True),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("input_bytes", sa.Integer(), nullable=False),
        sa.Column("source_crs", sa.Integer(), nullable=False),
        sa.Column("rule_version", sa.String(64), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("repaired_count", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("postgis_version", sa.Text(), nullable=False),
        sa.Column(
            "loaded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("version_id", name=op.f("pk_market_area_versions")),
        sa.UniqueConstraint(
            "input_sha256", "rule_version", name="uq_market_area_versions_input_rule"
        ),
        sa.CheckConstraint(
            "row_count > 0 AND repaired_count BETWEEN 0 AND row_count",
            name=op.f("ck_market_area_versions_counts"),
        ),
        sa.CheckConstraint(
            "input_bytes > 0 AND source_crs = 5181", name=op.f("ck_market_area_versions_source")
        ),
        sa.CheckConstraint(
            "input_sha256 ~ '^[0-9a-f]{64}$' AND content_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_market_area_versions_hashes"),
        ),
    )
    op.create_table(
        "market_areas",
        sa.Column("version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("market_code", sa.String(7), nullable=False),
        sa.Column("market_name", sa.String(255), nullable=False),
        sa.Column("market_type", sa.String(32), nullable=False),
        sa.Column("market_type_code", sa.String(1), nullable=False),
        sa.Column("gu_code", sa.String(5), nullable=False),
        sa.Column("area_m2", sa.Numeric(18, 2), nullable=False),
        sa.Column("source_feature_sha256", sa.String(64), nullable=False),
        sa.Column("geometry_repaired", sa.Boolean(), nullable=False),
        sa.Column(
            "geom",
            geoalchemy2.Geometry("MULTIPOLYGON", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("version_id", "market_code", name=op.f("pk_market_areas")),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["market_area_versions.version_id"],
            ondelete="RESTRICT",
            name=op.f("fk_market_areas_version_id_market_area_versions"),
        ),
        sa.CheckConstraint(
            "market_code ~ '^[0-9]{7}$' AND gu_code ~ '^11[0-9]{3}$'",
            name=op.f("ck_market_areas_codes"),
        ),
        sa.CheckConstraint(
            "area_m2 > 0 AND length(market_name) > 0", name=op.f("ck_market_areas_area_name")
        ),
        sa.CheckConstraint(
            "(market_type_code='A' AND market_type='alley') OR "
            "(market_type_code='D' AND market_type='developed') OR "
            "(market_type_code='R' AND market_type='traditional_market') OR "
            "(market_type_code='U' AND market_type='tourism_zone')",
            name=op.f("ck_market_areas_type"),
        ),
        sa.CheckConstraint(
            "source_feature_sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_market_areas_hash")
        ),
        sa.CheckConstraint(
            "(ST_IsValidDetail(geom,0)).valid AND NOT ST_IsEmpty(geom)",
            name=op.f("ck_market_areas_geometry"),
        ),
    )
    op.create_index("ix_market_areas_geom_gist", "market_areas", ["geom"], postgresql_using="gist")
    op.create_index("ix_market_areas_version_gu", "market_areas", ["version_id", "gu_code"])
    op.create_index("ix_market_areas_version_type", "market_areas", ["version_id", "market_type"])


def downgrade() -> None:
    op.drop_table("market_areas")
    op.drop_table("market_area_versions")
