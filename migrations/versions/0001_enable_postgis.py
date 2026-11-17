"""PostGIS 확장 활성화. 사용자 테이블은 생성하지 않는다."""

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")


def downgrade() -> None:
    # 공유 공간 데이터에 영향이 없도록 확장을 DROP하지 않고 revision만 되돌린다.
    pass
