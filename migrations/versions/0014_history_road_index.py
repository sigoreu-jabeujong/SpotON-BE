"""Transactionally maintained road address lookup expression index.

Revision ID: 0014
Revises: 0013
"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Immutable v1: future rule changes require a new function and index migration.
    sql = r"""
    CREATE FUNCTION spoton_history_road_key_v1(raw text) RETURNS text
    LANGUAGE plpgsql IMMUTABLE STRICT PARALLEL SAFE AS $$
    DECLARE t text; m text[]; tail text;
      p text := '^서울 ([가-힣]+구) ([가-힣A-Za-z0-9·]+(?:로|길)) '
             || '(지하 *)?([0-9]{1,4})(?:-([0-9]{1,4}))?(?= |,|\(|$)';
    BEGIN
      IF length(raw)>1000 THEN RETURN NULL; END IF;
      t := regexp_replace(btrim(normalize(raw, NFKC)), '^서울(특별시|시)?[[:space:]]+', '서울 ');
      t := regexp_replace(t, '[[:space:]]+', ' ', 'g');
      m := regexp_match(t, p);
      IF m IS NULL OR m[4]::int=0 THEN RETURN NULL; END IF;
      tail := regexp_replace(t, p, '');
      IF tail ~ '서울|[가-힣]+구[[:space:]]|[가-힣0-9]+(?:로|길)[[:space:]]+[0-9]'
        THEN RETURN NULL; END IF;
      RETURN m[1]||'|'||m[2]||'|'||CASE WHEN m[3] IS NULL THEN 'N' ELSE 'Y' END
             ||'|'||m[4]::int::text||'|'||coalesce(nullif(m[5],''),'0')::int::text;
    END $$;
    CREATE INDEX ix_stores_history_road_key ON stores (spoton_history_road_key_v1(address_road));
    """
    op.execute(sa.DDL(sql))  # type: ignore[no-untyped-call]


def downgrade() -> None:
    op.drop_index("ix_stores_history_road_key", table_name="stores")
    op.execute("DROP FUNCTION spoton_history_road_key_v1(text)")
