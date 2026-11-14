from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text, update

from app.core.config import Settings
from app.models import MarketArea, MarketStore, MarketStoreVersion
from etl.market_areas.archive import load_archive as load_boundary
from etl.market_areas.geometry import prepare
from etl.market_areas.repository import save as save_boundary
from etl.market_stores import __main__ as cli
from etl.market_stores import repository as repo
from etl.market_stores.archive import StatsImportError, load_archive
from tests.etl.market_helpers import make_archive
from tests.etl.market_store_helpers import annual_rows, make_stats_zip
from tests.integration.test_localdata_upsert import migrate

pytestmark = pytest.mark.integration


@pytest.fixture
def setup_stats(temporary_database, tmp_path):
    migrate(temporary_database)
    e = temporary_database.engine
    p = tmp_path / "boundary.zip"
    sha = make_archive(p)
    with e.begin() as c:
        prepared = prepare(c, load_boundary(p, sha, date(2023, 10, 23)))
        boundary, _ = save_boundary(c, prepared)
    p = tmp_path / "statistics.zip"
    rows = annual_rows()
    rows[0]["opbiz_rt"] = ""
    rows[1]["opbiz_rt"] = "0"
    sha = make_stats_zip(p, rows)
    archive = load_archive(p, sha, 2025, date(2026, 5, 21), today=date(2026, 11, 12))
    return e, boundary, archive, p, sha


def test_full_write_replay_manifest_new_rule_and_content_integrity(setup_stats):
    e, b, a, _, _ = setup_stats
    with e.begin() as c:
        vid, reused, report = repo.save(c, a, b)
        assert not reused and report["quarters"]["20251"]["stats_only"] == 0
        before = c.execute(
            select(MarketStoreVersion.loaded_at, MarketStoreVersion.content_sha256)
        ).one()
    with e.begin() as c:
        again, reused, _ = repo.save(c, a, b)
        assert again == vid and reused
        assert (
            c.execute(select(MarketStoreVersion.loaded_at, MarketStoreVersion.content_sha256)).one()
            == before
        )
        assert (
            c.scalar(
                select(MarketStore.opening_rate).where(
                    MarketStore.source_row_sha256 == a.rows[0]["source_row_sha256"]
                )
            )
            is None
        )
        assert (
            c.scalar(
                select(MarketStore.opening_rate).where(
                    MarketStore.source_row_sha256 == a.rows[1]["source_row_sha256"]
                )
            )
            == 0
        )
        assert c.scalar(select(MarketStore.closure_rate).limit(1)) == 450
        other, _, _ = repo.save(c, a, b, rule_version="synthetic-v2")
        assert other != vid
    with pytest.raises(StatsImportError, match="version_metadata"), e.begin() as c:
        repo.save(c, replace(a, source_file_date=date(2026, 5, 22)), b)
    with e.begin() as c:
        c.execute(update(MarketStore).where(MarketStore.version_id == vid).values(closed_stores=99))
    with pytest.raises(StatsImportError, match="stored_content"), e.begin() as c:
        repo.save(c, a, b)
    with e.connect() as c:
        assert c.scalar(select(func.count()).select_from(MarketStore)) == 40


def test_post_insert_failure_rolls_back_manifest_and_all_rows(setup_stats, monkeypatch):
    e, b, a, _, _ = setup_stats

    def fail(*args):
        raise StatsImportError("market_stats:injected")

    monkeypatch.setattr(repo, "_verify", fail)
    with pytest.raises(StatsImportError), e.begin() as c:
        repo.save(c, a, b)
    with e.connect() as c:
        assert c.scalar(select(func.count()).select_from(MarketStoreVersion)) == 0
        assert c.scalar(select(func.count()).select_from(MarketStore)) == 0
        assert c.scalar(select(func.count()).select_from(MarketArea)) == 25


def test_concurrent_writers_one_version_and_replay(setup_stats):
    e, b, a, _, _ = setup_stats
    barrier = Barrier(2)

    def work():
        with e.connect() as c, c.begin():
            barrier.wait(timeout=10)
            return repo.save(c, a, b)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(work) for _ in range(2)]
        results = [f.result(timeout=20) for f in futures]
    assert results[0][0] == results[1][0]
    assert sorted(r[1] for r in results) == [False, True]
    with e.connect() as c:
        assert c.scalar(select(func.count()).select_from(MarketStoreVersion)) == 1
        assert c.scalar(select(func.count()).select_from(MarketStore)) == 20


def test_audit_unmatched_codes_and_quarter_name_change_not_temporal_match(setup_stats):
    e, b, a, _, _ = setup_stats
    markets = {q: {"9999999": ("A", "renamed" if q == "20252" else "synthetic")} for q in a.markets}
    rows = [
        {**row, "market_code": "9999999", "market_name": markets[row["quarter"]]["9999999"][1]}
        for row in a.rows
    ]
    a = replace(a, rows=rows, markets=markets)
    with e.begin() as c:
        vid, _, report = repo.save(c, a, b)
        assert report["quarters"]["20251"]["stats_only"] == 1
        assert report["quarters"]["20251"]["boundary_only"] == 25
        assert report["quarters"]["20252"]["changed_markets"] == 1
        assert c.scalar(select(MarketStoreVersion.boundary_compatibility)) == "unverified"
        assert (
            c.scalar(
                select(func.count()).select_from(MarketStore).where(MarketStore.version_id == vid)
            )
            == 20
        )


def test_boundary_missing_or_corrupt_rejects_before_write(setup_stats):
    e, b, a, _, _ = setup_stats
    with pytest.raises(StatsImportError, match="boundary_missing"), e.begin() as c:
        repo.save(c, a, uuid4())
    with e.begin() as c:
        c.execute(
            update(MarketArea).where(MarketArea.version_id == b).values(market_name="tampered")
        )
    with pytest.raises(StatsImportError, match="boundary_content"), e.begin() as c:
        repo.save(c, a, b)
    with e.connect() as c:
        assert c.scalar(select(func.count()).select_from(MarketStoreVersion)) == 0


def test_cli_real_read_only_write_replay_and_safe_error(setup_stats, monkeypatch, capsys):
    e, b, a, p, sha = setup_stats
    read_only = []
    monkeypatch.setattr(cli, "create_db_engine", lambda _: e)

    def check(c):
        assert c.scalar(text("SELECT version_num FROM alembic_version")) == "0012"
        read_only.append(c.scalar(text("SHOW transaction_read_only")))

    monkeypatch.setattr(cli, "check_local_database", check)
    config = Settings(
        _env_file=None, database_url="postgresql://spoton_app:synthetic@127.0.0.1/spoton_dev"
    )
    monkeypatch.setattr(cli, "Settings", lambda: config)
    result = cli.run_import(p, sha, 2025, date(2026, 5, 21), b, settings=config)
    assert result["inserted"] == 0 and result["mode"] == "dry_run"
    with e.connect() as c:
        assert c.scalar(select(func.count()).select_from(MarketStoreVersion)) == 0
    args = [
        "--zip",
        str(p),
        "--expected-sha256",
        sha,
        "--source-year",
        "2025",
        "--source-file-date",
        "2026-05-21",
        "--code-check-boundary-version",
        str(b),
        "--write",
    ]
    assert cli.main(args) == 0 and cli.main(args) == 0
    assert read_only == ["on", "on", "off", "on", "off"]
    output = capsys.readouterr().out
    for canary in ("synthetic-market-canary", str(p), "3110000", "postgresql", "synthetic@"):
        assert canary not in output

    def fail(*args, **kwargs):
        raise RuntimeError("private-connection-canary")

    monkeypatch.setattr(cli, "run_import", fail)
    assert cli.main(args) == 1
    assert "private-connection-canary" not in capsys.readouterr().out


def test_lock_timeout_returns_safe_error_and_does_not_write(setup_stats, monkeypatch, capsys):
    e, b, a, p, sha = setup_stats
    monkeypatch.setattr(repo, "LOCK_TIMEOUT_MS", 100)
    monkeypatch.setattr(cli, "create_db_engine", lambda _: e)
    monkeypatch.setattr(cli, "check_local_database", lambda _: None)
    config = Settings(
        _env_file=None, database_url="postgresql://spoton_app:synthetic@localhost/spoton_dev"
    )
    monkeypatch.setattr(cli, "Settings", lambda: config)
    with e.connect() as held, held.begin():
        held.execute(
            text("SELECT pg_advisory_xact_lock(:n,:k)"),
            {"n": repo.LOCK_NAMESPACE, "k": repo.LOCK_KEY},
        )
        assert (
            cli.main(
                [
                    "--zip",
                    str(p),
                    "--expected-sha256",
                    sha,
                    "--source-year",
                    "2025",
                    "--source-file-date",
                    "2026-05-21",
                    "--code-check-boundary-version",
                    str(b),
                    "--write",
                ]
            )
            == 1
        )
    assert capsys.readouterr().out.strip() == '{"error": "market_stats:operation_failed"}'
    with e.connect() as c:
        assert c.scalar(select(func.count()).select_from(MarketStoreVersion)) == 0
