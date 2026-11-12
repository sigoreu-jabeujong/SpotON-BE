import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import insert, text
from sqlalchemy.exc import DBAPIError

from app.core.config import Settings
from app.models import Store
from etl.brands import __main__ as cli
from etl.brands import compare
from etl.brands.snapshot import save_snapshot
from tests.etl.brands_helpers import catalog, item
from tests.integration.test_localdata_upsert import migrate

pytestmark = pytest.mark.integration


@pytest.fixture
def source(temporary_database, monkeypatch):
    migrate(temporary_database)
    engine = temporary_database.engine
    names = ["Unique Cafe", "Same Cafe", "No Brand", None, "ab", "Retail Brand", "Preserved"]
    payloads = [
        dict(
            source="general_restaurant",
            license_no=str(i),
            name=name,
            category="restaurant",
            sub_category="korean",
        )
        for i, name in enumerate(names)
    ]
    payloads[-1].update(is_franchise=False, brand_id=123)
    payloads += [
        dict(
            source="general_restaurant",
            license_no="excluded",
            name="Unique Cafe",
            category="restaurant",
            sub_category="snack",
        ),
        dict(
            source="rest_cafe",
            license_no="review",
            name="Unique Cafe",
            category="cafe",
            sub_category="cafe",
            category_review_flag=True,
        ),
        dict(
            source="rest_cafe",
            license_no="deleted",
            name="Unique Cafe",
            category="cafe",
            sub_category="cafe",
            deleted_at=datetime.now(UTC),
        ),
        dict(
            source="rest_cafe",
            license_no="cafe",
            name="Unique Cafe",
            category="cafe",
            sub_category="cafe",
        ),
    ]
    with engine.begin() as c:
        for payload in payloads:
            c.execute(insert(Store).values(**payload))
    config = Settings(
        _env_file=None, database_url="postgresql://spoton_app:synthetic@127.0.0.1/spoton_dev"
    )
    monkeypatch.setattr(compare, "create_db_engine", lambda _: engine)
    states = []

    def check(c):
        assert c.scalar(text("SELECT current_database()")).startswith("spoton_it_")
        assert c.scalar(text("SELECT version_num FROM alembic_version")) == "0011"
        state = tuple(
            c.execute(
                text(
                    "SELECT current_setting('transaction_read_only'),"
                    "current_setting('transaction_isolation'),current_setting('statement_timeout'),"
                    "current_setting('lock_timeout')"
                )
            ).one()
        )
        states.append(state)

    monkeypatch.setattr(compare, "check_local_database", check)
    data = catalog(
        [
            item("001", "Unique Cafe"),
            item("002", "Same Cafe"),
            item("003", "Same Cafe", "도소매"),
            item("004", "Retail Brand", "도소매"),
        ]
    )
    return engine, config, data, states


def fingerprint(engine):
    with engine.connect() as c:
        return c.scalar(
            text("SELECT md5(string_agg(md5(to_jsonb(s)::text),'' ORDER BY id)) FROM stores s")
        )


def test_readonly_all_supported_categories_preserves_every_store_field(source):
    engine, config, data, states = source
    before = fingerprint(engine)
    result = compare.compare_local(data, config)
    assert result == dict(
        total=8,
        existing_classification=1,
        missing_name=1,
        weak_name=1,
        repeated_brand_id=0,
        ambiguous_name=1,
        non_food_name=1,
        exact_name_candidate=2,
        no_exact_candidate=1,
    )
    assert states == [("on", "repeatable read", "1min", "5s")]
    assert fingerprint(engine) == before


def test_readonly_database_rejects_an_accidental_write(source, monkeypatch):
    engine, config, data, states = source
    before = fingerprint(engine)
    original = compare.check_local_database

    def write(c):
        original(c)
        c.execute(text("UPDATE stores SET is_franchise=true"))

    monkeypatch.setattr(compare, "check_local_database", write)
    with pytest.raises(DBAPIError) as error:
        compare.compare_local(data, config)
    assert error.value.orig.sqlstate == "25006"
    assert fingerprint(engine) == before


def test_cli_snapshot_replay_readonly_and_private(source, tmp_path, monkeypatch, capsys):
    engine, config, data, states = source
    path = tmp_path / "private-snapshot.json"
    save_snapshot(path, data)
    monkeypatch.setattr(cli, "Settings", lambda: config)
    before = fingerprint(engine)
    assert cli.main(["--snapshot", str(path), "--compare-local"]) == 0
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert result["comparison"]["exact_name_candidate"] == 2
    assert result["request_count"] == 0 and result["classification_status"] == "pending"
    assert fingerprint(engine) == before
    for marker in (str(path), "Unique Cafe", "Same Cafe", "Preserved", "PRIVATE", "postgresql"):
        assert marker not in captured.out + captured.err


def test_failed_guard_preserves_snapshot_and_rows(source, tmp_path, monkeypatch, capsys):
    engine, config, data, states = source
    path = tmp_path / "snapshot.json"
    save_snapshot(path, data)
    before = fingerprint(engine)
    raw = path.read_bytes()

    def fail(c):
        raise RuntimeError("PRIVATE_DB_CANARY")

    monkeypatch.setattr(compare, "check_local_database", fail)
    monkeypatch.setattr(cli, "Settings", lambda: config)
    assert cli.main(["--snapshot", str(path), "--compare-local"]) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out) == dict(
        error="brands:operation_failed", stage="prepare", snapshot_saved=False
    )
    assert "PRIVATE" not in captured.out + captured.err
    assert path.read_bytes() == raw and fingerprint(engine) == before


def test_repeated_source_identifier_is_quarantined_in_real_store_comparison(source):
    engine, config, data, states = source
    rows = [
        item(row.management_no, row.name, row.industry, jnghdqrtrsMnno=row.headquarter_no)
        for row in data.rows
    ]
    rows.append(item("001", "No Brand", jnghdqrtrsMnno="HQ_OTHER"))
    before = fingerprint(engine)
    result = compare.compare_local(catalog(rows), config)
    assert result["total"] == 8 and result["repeated_brand_id"] == 3
    assert result["exact_name_candidate"] == result["no_exact_candidate"] == 0
    assert fingerprint(engine) == before
