from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.util import CommandError
from sqlalchemy import delete, func, insert, select, text, update
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.db.base import Base
from app.models import MarketArea, MarketChange, MarketChangeVersion, Store
from etl.market_changes import __main__ as cli
from etl.market_changes import repository as repo
from etl.market_changes.source import ChangeImportError
from tests.etl.market_change_helpers import annual_change_rows, load_change, make_change_csv
from tests.integration.market_references import seed_references
from tests.integration.test_localdata_upsert import ROOT, migrate

pytestmark = pytest.mark.integration


@pytest.fixture
def change_source(temporary_database, tmp_path):
    migrate(temporary_database)
    e = temporary_database.engine
    with e.begin() as c:
        boundary, _ = seed_references(c, tmp_path)
        c.execute(insert(Store).values(source="synthetic", license_no="preserved"))
    p = tmp_path / "change.csv"
    rows = annual_change_rows() + annual_change_rows(2024)
    rows[0]["운영_영업_개월_평균"] = ""
    rows[1]["운영_영업_개월_평균"] = "0"
    sha = make_change_csv(p, rows)
    return e, boundary, load_change(p, sha), p, sha


def test_replay_null_zero_new_rule_year_and_identical_content_different_bytes(change_source):
    e, b, a, p, sha = change_source
    with e.begin() as c:
        vid, reused, _ = repo.save(c, a, b)
        assert not reused
        before = c.execute(select(MarketChangeVersion.__table__)).mappings().one()
        assert before["source_file_date"] is None and before["excluded_rows"] == 16
        assert (
            c.scalar(
                select(MarketChange.operating_months_avg).where(
                    MarketChange.quarter == "20251", MarketChange.market_code == "3999990"
                )
            )
            is None
        )
        assert (
            c.scalar(
                select(MarketChange.operating_months_avg).where(
                    MarketChange.quarter == "20251", MarketChange.market_code == "3999991"
                )
            )
            == 0
        )
    with e.begin() as c:
        assert repo.save(c, a, b)[:2] == (vid, True)
        assert c.execute(select(MarketChangeVersion.__table__)).mappings().one() == before
        assert repo.save(c, a, b, rule_version="new-rule")[0] != vid
        other = load_change(p, sha, 2024)
        assert repo.save(c, other, b)[0] != vid
    # Encoding/order changes bytes but not source-map/content hashes.
    import csv
    import io

    raw = list(csv.DictReader(io.StringIO(p.read_bytes().decode("cp949"))))
    another = load_change(p, make_change_csv(p, list(reversed(raw)), encoding="utf-8-sig"))
    with e.begin() as c:
        assert repo.same_content_versions(c, another) == 1
        assert repo.save(c, another, b)[0] != vid
        assert c.scalar(select(func.count()).select_from(MarketChangeVersion)) == 4


def test_provenance_conflict_and_missing_reference(change_source):
    e, b, a, _, _ = change_source
    with e.begin() as c:
        repo.save(c, a, b)
    with pytest.raises(ChangeImportError, match="provenance_conflict"), e.begin() as c:
        repo.save(c, replace(a, retrieved_at=a.retrieved_at + timedelta(seconds=1)), b)
    with pytest.raises(ChangeImportError, match="boundary_missing"), e.begin() as c:
        repo.save(c, a, uuid4())


def test_quarter_label_changes_and_missing_markets_are_reported_not_filled(change_source):
    e, b, a, p, _ = change_source
    rows = annual_change_rows()
    for row in rows:
        if row["기준_년분기_코드"] == "20252":
            row["상권_코드_명"] = "renamed"
    # One absent market in Q4 remains absent; it does not trigger a prior-quarter fallback.
    rows.pop()
    source = load_change(p, make_change_csv(p, rows))
    with e.begin() as c:
        _, _, report = repo.save(c, source, b)
        quarters = report["quarters"]
        assert quarters["20252"]["changed_markets"] == 4
        assert quarters["20253"]["changed_markets"] == 4
        assert quarters["20254"]["supported_rows"] == 3
        assert c.scalar(select(func.count()).select_from(MarketChange)) == 15


@pytest.mark.parametrize("target", ["row", "manifest", "boundary"])
def test_tamper_is_rejected_without_repair(change_source, target):
    e, b, a, _, _ = change_source
    with e.begin() as c:
        vid, _, _ = repo.save(c, a, b)
        if target == "row":
            c.execute(
                update(MarketChange)
                .where(MarketChange.version_id == vid)
                .values(operating_months_avg=999)
            )
        elif target == "manifest":
            c.execute(
                update(MarketChangeVersion).values(source_rows=a.source_rows + 1, excluded_rows=17)
            )
        else:
            c.execute(
                update(MarketArea).where(MarketArea.version_id == b).values(market_name="tampered")
            )
    expected = {
        "row": "stored_content",
        "manifest": "version_metadata",
        "boundary": "boundary_content",
    }[target]
    with pytest.raises(ChangeImportError, match=expected), e.begin() as c:
        repo.save(c, a, b)


def test_failure_after_inserts_rolls_back_entire_year(change_source, monkeypatch):
    e, b, a, _, _ = change_source

    def reject(*args, **kwargs):
        raise ChangeImportError("market_changes:injected")

    monkeypatch.setattr(repo, "_verify", reject)
    with pytest.raises(ChangeImportError), e.begin() as c:
        repo.save(c, a, b)
    with e.connect() as c:
        for model in (MarketChange, MarketChangeVersion):
            assert c.scalar(select(func.count()).select_from(model)) == 0
        assert c.scalar(select(func.count()).select_from(Store)) == 1


def test_two_writers_share_one_immutable_version(change_source):
    e, b, a, _, _ = change_source
    barrier = Barrier(2)

    def worker():
        with e.connect() as c:
            barrier.wait(timeout=10)
            with c.begin():
                return repo.save(c, a, b)[:2]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: worker(), range(2)))
    assert results[0][0] == results[1][0]
    assert sorted(r[1] for r in results) == [False, True]


def test_real_cli_readonly_no_insert_write_replay_and_safe_output(
    change_source, monkeypatch, capsys
):
    e, b, a, p, sha = change_source
    monkeypatch.setattr(cli, "validate_local_target", lambda _: None)
    monkeypatch.setattr(cli, "create_db_engine", lambda _: e)

    def check(c):
        assert c.scalar(text("SELECT version_num FROM alembic_version")) == "0012"

    monkeypatch.setattr(cli, "check_local_database", check)
    original = cli.inspect_import

    def readonly(c, *args, **kwargs):
        assert c.scalar(text("SHOW transaction_read_only")) == "on"
        assert c.scalar(text("SHOW transaction_isolation")) == "repeatable read"
        assert c.scalar(text("SHOW lock_timeout")) == "5s"
        assert c.scalar(text("SHOW statement_timeout")) == "1min"
        return original(c, *args, **kwargs)

    monkeypatch.setattr(cli, "inspect_import", readonly)
    args = (p, sha, 2025, a.retrieved_at, b)
    first = cli.run_import(*args, settings=Settings(_env_file=None))
    assert (
        first["inserted"] == 0
        and not first["would_reuse"]
        and first["excluded_scope"] == "outside_selected_year"
    )
    with e.connect() as c:
        assert c.scalar(select(func.count()).select_from(MarketChangeVersion)) == 0
    assert cli.run_import(*args, write=True, settings=Settings(_env_file=None))["inserted"] == 16
    assert cli.run_import(*args, write=True, settings=Settings(_env_file=None))["reused"]
    assert cli.run_import(*args, settings=Settings(_env_file=None))["would_reuse"]
    cliargs = [
        "--csv",
        str(p),
        "--expected-sha256",
        sha,
        "--source-year",
        "2025",
        "--retrieved-at",
        a.retrieved_at.isoformat(),
        "--code-check-boundary-version",
        str(b),
    ]
    assert cli.main(cliargs) == 0
    output = capsys.readouterr().out
    assert str(p) not in output and "synthetic-market-canary" not in output


def test_schema_constraints_model_diff_and_downgrade_preserve_other_data(change_source):
    e, b, a, _, _ = change_source
    with e.begin() as c:
        vid, _, _ = repo.save(c, a, b)
        row = dict(c.execute(select(MarketChange.__table__).limit(1)).mappings().one())
        for changes in (
            {"change_name": "bad"},
            {"change_code": "XX"},
            {"quarter": "20255"},
            {"operating_months_avg": -1},
            {"market_type_code": "Z"},
            {"source_row_sha256": "bad"},
            {"version_id": uuid4()},
        ):
            with pytest.raises(IntegrityError), c.begin_nested():
                c.execute(
                    insert(MarketChange).values(**{**row, "market_code": "3999999", **changes})
                )
        for changes in (
            {"source_year": 2026},
            {"input_sha256": "bad"},
            {"source_dataset": "wrong"},
            {"row_count": 0},
            {"code_check": []},
            {"code_check_boundary_version_id": uuid4()},
            {"boundary_compatibility": "verified"},
            {"source_file_date": a.retrieved_at.date()},
        ):
            manifest = dict(c.execute(select(MarketChangeVersion.__table__)).mappings().one())
            with pytest.raises(IntegrityError), c.begin_nested():
                c.execute(
                    insert(MarketChangeVersion).values(
                        **{**manifest, "version_id": uuid4(), "input_sha256": "8" * 64, **changes}
                    )
                )
        with pytest.raises(IntegrityError), c.begin_nested():
            c.execute(delete(MarketChangeVersion).where(MarketChangeVersion.version_id == vid))
        opts = {
            "compare_type": True,
            "compare_server_default": True,
            "include_name": lambda n, k, p: k != "table" or n in Base.metadata.tables,
        }
        assert compare_metadata(MigrationContext.configure(c, opts=opts), Base.metadata) == []
        assert (
            c.scalar(
                text(
                    "SELECT count(*) FROM pg_indexes "
                    "WHERE indexname='ix_market_changes_version_quarter_change'"
                )
            )
            == 1
        )
        cfg = Config(str(ROOT / "alembic.ini"))
        cfg.attributes["connection"] = c
        with pytest.raises(CommandError), c.begin_nested():
            command.downgrade(cfg, "0008")
        assert c.scalar(select(func.count()).select_from(MarketChange)) == 16
        c.execute(delete(MarketChange))
        c.execute(delete(MarketChangeVersion))
        command.downgrade(cfg, "0008")
        assert c.scalar(text("SELECT to_regclass('market_changes')")) is None
        assert c.scalar(select(func.count()).select_from(Store)) == 1
        assert c.scalar(select(func.count()).select_from(MarketArea)) == 25
        command.upgrade(cfg, "head")
