from datetime import date

from etl.market_areas.archive import load_archive as load_boundary
from etl.market_areas.geometry import prepare
from etl.market_areas.repository import save as save_boundary
from etl.market_stores.archive import load_archive as load_stores
from etl.market_stores.repository import save as save_stores
from tests.etl.market_helpers import make_archive
from tests.etl.market_store_helpers import annual_rows, make_stats_zip


def seed_references(connection, tmp_path, *, year=2025):
    """Persist synthetic, correctly digested reference versions using existing writers."""
    p = tmp_path / "boundary.zip"
    sha = make_archive(p)
    boundary, _ = save_boundary(
        connection, prepare(connection, load_boundary(p, sha, date(2023, 10, 23)))
    )
    rows = annual_rows()
    for row in rows:
        row["stdr_yyqu_cd"] = str(year) + row["stdr_yyqu_cd"][-1]
    p = tmp_path / "stores.zip"
    sha = make_stats_zip(p, rows)
    archive = load_stores(p, sha, year, date(2026, 5, 21), today=date(2026, 11, 12))
    stores, _, _ = save_stores(connection, archive, boundary)
    return boundary, stores
