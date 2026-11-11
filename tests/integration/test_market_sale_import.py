from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date
from hashlib import sha256
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError

from app.core.config import Settings
from app.models import MarketArea, MarketSale, MarketSaleVersion, MarketStore, MarketStoreVersion
from etl.market_areas.archive import load_archive as load_boundary
from etl.market_areas.geometry import prepare
from etl.market_areas.repository import save as save_boundary
from etl.market_sales import __main__ as cli
from etl.market_sales import repository as repo
from etl.market_sales.archive import SalesImportError, load_archive
from etl.market_stores import repository as store_repo
from etl.market_stores.archive import load_archive as load_stores
from tests.etl.market_helpers import make_archive
from tests.etl.market_sale_helpers import annual_sales_rows, make_sales_zip
from tests.integration.market_references import seed_references
from tests.integration.test_localdata_upsert import migrate

pytestmark = pytest.mark.integration


@pytest.fixture
def sales_source(temporary_database, tmp_path):
    migrate(temporary_database)
    e = temporary_database.engine
    with e.begin() as c:
        boundary, stores = seed_references(c, tmp_path)
    p = tmp_path / "sales.zip"
    rows = annual_sales_rows()
    rows[0]["당월_매출_금액"] = ""
    rows[0]["당월_매출_건수"] = ""
    rows[1]["당월_매출_금액"] = "0"
    rows[1]["당월_매출_건수"] = "0"
    sha = make_sales_zip(p, rows)
    archive = load_archive(p, sha, 2025, date(2026, 5, 18), today=date(2026, 11, 12))
    return e, boundary, stores, archive, p, sha


def test_atomic_replay_semantics_new_rule_manifest_conflict_and_tamper(sales_source):
    e, b, s, a, _, _ = sales_source
    with e.begin() as c:
        vid, reused, report = repo.save(c, a, b, s)
        assert not reused and report["quarters"]["20251"]["sales_only_combinations"] == 0
        before = c.execute(
            select(MarketSaleVersion.loaded_at, MarketSaleVersion.content_sha256)
        ).one()
    with e.begin() as c:
        again, reused, _ = repo.save(c, a, b, s)
        assert again == vid and reused
        assert (
            c.execute(select(MarketSaleVersion.loaded_at, MarketSaleVersion.content_sha256)).one()
            == before
        )
        for name in ("amount_period_status", "boundary_compatibility"):
            assert c.scalar(select(getattr(MarketSaleVersion, name))) == "unverified"
        assert c.scalar(select(MarketSaleVersion.currency)) == "KRW"
        assert (
            c.scalar(
                select(MarketSale.est_sales).where(
                    MarketSale.source_row_sha256 == a.rows[0]["source_row_sha256"]
                )
            )
            is None
        )
        assert (
            c.scalar(
                select(MarketSale.est_sales).where(
                    MarketSale.source_row_sha256 == a.rows[1]["source_row_sha256"]
                )
            )
            == 0
        )
        other, _, _ = repo.save(c, a, b, s, rule_version="synthetic-v2")
        assert other != vid
    with pytest.raises(SalesImportError, match="version_metadata"), e.begin() as c:
        repo.save(c, replace(a, source_file_date=date(2026, 5, 19)), b, s)
    with e.begin() as c:
        c.execute(
            update(MarketSale)
            .where(MarketSale.version_id == vid, MarketSale.est_sales.is_not(None))
            .values(est_sales=99)
        )
    with pytest.raises(SalesImportError, match="stored_content"), e.begin() as c:
        repo.save(c, a, b, s)


def test_post_insert_digest_failure_rolls_back_both_tables(sales_source, monkeypatch):
    e, b, s, a, _, _ = sales_source

    def fail(*args, **kwargs):
        raise SalesImportError("market_sales:injected")

    monkeypatch.setattr(repo, "_verify", fail)
    with pytest.raises(SalesImportError), e.begin() as c:
        repo.save(c, a, b, s)
    with e.connect() as c:
        assert c.scalar(select(func.count()).select_from(MarketSaleVersion)) == 0
        assert c.scalar(select(func.count()).select_from(MarketSale)) == 0
        assert c.scalar(select(func.count()).select_from(MarketStore)) == 20


def test_two_writers_single_version(sales_source):
    e, b, s, a, _, _ = sales_source
    barrier = Barrier(2)

    def work():
        with e.connect() as c, c.begin():
            barrier.wait(timeout=10)
            return repo.save(c, a, b, s)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(work) for _ in range(2)]
        results = [f.result(timeout=20) for f in futures]
    assert results[0][0] == results[1][0] and sorted(r[1] for r in results) == [False, True]
    with e.connect() as c:
        assert c.scalar(select(func.count()).select_from(MarketSale)) == 20


def test_missing_combinations_reported_without_zero_fill(sales_source):
    e, b, s, a, _, _ = sales_source
    rows = [{**r, "market_code": "9999999"} if n == 0 else r for n, r in enumerate(a.rows)]
    a = replace(a, rows=rows)
    with e.begin() as c:
        _, _, report = repo.save(c, a, b, s)
        q = report["quarters"]["20251"]
        assert q["sales_only_combinations"] == q["stores_only_combinations"] == 1
        assert c.scalar(select(func.count()).select_from(MarketSale)) == 20


@pytest.mark.parametrize("target", ["boundary", "stores"])
def test_corrupt_references_fail_before_write(sales_source, target):
    e, b, s, a, _, _ = sales_source
    with e.begin() as c:
        if target == "boundary":
            c.execute(
                update(MarketArea).where(MarketArea.version_id == b).values(market_name="tampered")
            )
        else:
            c.execute(
                update(MarketStore).where(MarketStore.version_id == s).values(closed_stores=99)
            )
    with pytest.raises(SalesImportError, match="boundary_content|store_content"), e.begin() as c:
        repo.save(c, a, b, s)
    with e.connect() as c:
        assert c.scalar(select(func.count()).select_from(MarketSaleVersion)) == 0


def test_missing_references_wrong_year_and_mismatched_boundary(sales_source, tmp_path):
    e, b, s, a, _, _ = sales_source
    for boundary, stores in ((uuid4(), s), (b, uuid4())):
        with pytest.raises(SalesImportError), e.begin() as c:
            repo.save(c, a, boundary, stores)
    other = tmp_path / "different"
    other.mkdir()
    with e.begin() as c:
        other_b, other_s = seed_references(c, other, year=2024)
    with pytest.raises(SalesImportError, match="store_year"), e.begin() as c:
        repo.save(c, a, other_b, other_s)
    p = other / "different-boundary.zip"
    sha = make_archive(p, patches={0: {"TRDAR_CD_N": "renamed"}})
    with e.begin() as c:
        changed, _ = save_boundary(c, prepare(c, load_boundary(p, sha, date(2023, 10, 23))))
    with pytest.raises(SalesImportError, match="reference_boundary"), e.begin() as c:
        repo.save(c, a, changed, s)


def cli_config(e, monkeypatch):
    config = Settings(
        _env_file=None, database_url="postgresql://spoton_app:synthetic@localhost/spoton_dev"
    )
    monkeypatch.setattr(cli, "Settings", lambda: config)
    monkeypatch.setattr(cli, "create_db_engine", lambda _: e)
    return config


def args(b, s, p, sha):
    return [
        "--zip",
        str(p),
        "--expected-sha256",
        sha,
        "--source-year",
        "2025",
        "--source-file-date",
        "2026-05-18",
        "--code-check-boundary-version",
        str(b),
        "--code-check-store-version",
        str(s),
        "--write",
    ]


def test_real_cli_read_only_snapshot_replay_plan_and_safe_output(sales_source, monkeypatch, capsys):
    e, b, s, a, p, sha = sales_source
    states = []
    config = cli_config(e, monkeypatch)

    def check(c):
        assert c.scalar(text("SELECT version_num FROM alembic_version")) == "0007"
        states.append(
            (
                c.scalar(text("SHOW transaction_read_only")),
                c.scalar(text("SHOW transaction_isolation")),
            )
        )

    monkeypatch.setattr(cli, "check_local_database", check)
    dry = cli.run_import(p, sha, 2025, date(2026, 5, 18), b, s, settings=config)
    assert dry["inserted"] == 0 and not dry["would_reuse"]
    with e.connect() as c:
        assert c.scalar(select(func.count()).select_from(MarketSaleVersion)) == 0
    assert cli.main(args(b, s, p, sha)) == 0
    after = cli.run_import(p, sha, 2025, date(2026, 5, 18), b, s, settings=config)
    assert after["would_reuse"] and after["inserted"] == 0
    assert cli.main(args(b, s, p, sha)) == 0
    assert states == [
        ("on", "repeatable read"),
        ("on", "repeatable read"),
        ("off", "read committed"),
        ("on", "repeatable read"),
        ("on", "repeatable read"),
        ("off", "read committed"),
    ]
    output = capsys.readouterr().out
    for marker in ("synthetic-sales-private-canary", "3110000", str(p), "postgresql", "synthetic@"):
        assert marker not in output


def test_lock_timeout_safe_and_reference_share_blocks_old_writer(sales_source, monkeypatch, capsys):
    e, b, s, a, p, sha = sales_source
    cli_config(e, monkeypatch)
    monkeypatch.setattr(cli, "check_local_database", lambda _: None)
    monkeypatch.setattr(repo, "LOCK_TIMEOUT_MS", 100)
    assert len({16, store_repo.LOCK_KEY, repo.LOCK_KEY}) == 3
    assert repo.LOCK_NAMESPACE == store_repo.LOCK_NAMESPACE
    with e.connect() as held, held.begin():
        held.execute(
            text("SELECT pg_advisory_xact_lock(:n,:k)"),
            {"n": repo.LOCK_NAMESPACE, "k": repo.LOCK_KEY},
        )
        assert cli.main(args(b, s, p, sha)) == 1
    assert capsys.readouterr().out.strip() == '{"error": "market_sales:operation_failed"}'
    oldpath = p.parent / "stores.zip"
    old = load_stores(oldpath, sha256(oldpath.read_bytes()).hexdigest(), 2025, date(2026, 5, 21))
    monkeypatch.setattr(store_repo, "LOCK_TIMEOUT_MS", 100)
    with e.begin() as held:
        repo.inspect_import(held, a, b, s, lock=True)
        with pytest.raises(DBAPIError), e.begin() as writer:
            store_repo.save(writer, old, b)
        repo.save(held, a, b, s)
    with e.connect() as c:
        assert c.scalar(select(func.count()).select_from(MarketSale)) == 20
        assert c.scalar(select(func.count()).select_from(MarketStoreVersion)) == 1
