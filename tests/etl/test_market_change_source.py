from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

import pytest

from etl.market_changes import __main__ as cli
from etl.market_changes import source as a
from tests.etl.market_change_helpers import (
    NOW,
    RETRIEVED,
    annual_change_rows,
    load_change,
    make_change_csv,
)


def test_all_classes_null_zero_raw_hash_header_order_and_no_industry(tmp_path):
    p = tmp_path / "change.csv"
    rows = annual_change_rows()
    rows[0][a.FIELDS[7]] = ""
    rows[1][a.FIELDS[7]] = "0"
    rows[2][a.FIELDS[7]] = "2147483647"
    for encoding in ("cp949", "utf-8-sig"):
        src = load_change(
            p, make_change_csv(p, rows, headers=tuple(reversed(a.FIELDS)), encoding=encoding)
        )
        assert len(src.rows) == src.source_rows == 16
        assert src.rows[0]["operating_months_avg"] is None
        assert src.rows[1]["operating_months_avg"] == 0
        assert src.rows[2]["operating_months_avg"] == 2147483647
        assert src.rows[0]["source_row_sha256"] == a.digest(rows[0])
        assert {r["change_code"] for r in src.rows} == set(a.CHANGES)
        assert all("induty_cd" not in r and "category" not in r for r in src.rows)
        reverse = load_change(p, make_change_csv(p, list(reversed(rows)), encoding=encoding))
        assert a.content_digest(src.rows, 2025) == a.content_digest(reverse.rows, 2025)
        assert a.content_digest(src.rows, 2025) != a.content_digest(src.rows, 2024)
        assert a.content_digest(src.rows, 2025) != a.content_digest(src.rows, 2025, "new-rule")


@pytest.mark.parametrize(
    "value",
    [
        " 1",
        "1 ",
        "+1",
        "-0",
        "-1",
        "01",
        "1.0",
        "1e2",
        "1,000",
        "1_000",
        "NaN",
        "Infinity",
        "１",
        "١",
        "2147483648",
        "*",
        "1\n",
        "1\t",
    ],
)
def test_strict_months_even_outside_selected_year(tmp_path, value):
    rows = annual_change_rows() + annual_change_rows(2024)
    rows[-1][a.FIELDS[-1]] = value
    p = tmp_path / "c.csv"
    with pytest.raises(a.ChangeImportError):
        load_change(p, make_change_csv(p, rows, encoding="utf-8-sig"))


def test_year_selection_duplicates_labels_and_no_filled_missing_markets(tmp_path):
    p = tmp_path / "c.csv"
    rows = annual_change_rows() + annual_change_rows(2024)
    src = load_change(p, make_change_csv(p, rows))
    assert src.source_rows == 32 and len(src.rows) == 16 and len(src.quarter_rows) == 4
    assert all(q.startswith("2025") for q in src.markets)
    # A missing market is not a missing quarter, and remains absent.
    assert len(load_change(p, make_change_csv(p, rows[1:])).rows) == 15
    for invalid in (rows + [rows[0]], rows[4:16]):
        with pytest.raises(a.ChangeImportError):
            load_change(p, make_change_csv(p, invalid))
    for index, value in [
        (0, "20255"),
        (0, "20991"),
        (1, "Z"),
        (2, "bad"),
        (3, "123"),
        (4, " "),
        (4, "x" * 256),
        (5, "XX"),
        (6, "bad"),
    ]:
        invalid = [*rows]
        invalid[-1] = {**invalid[-1], a.FIELDS[index]: value}
        with pytest.raises(a.ChangeImportError):
            load_change(p, make_change_csv(p, invalid))
    renamed = [{**r, a.FIELDS[4]: "new-name"} if r[a.FIELDS[0]] == "20252" else r for r in rows]
    assert any(
        r["market_name"] == "new-name" for r in load_change(p, make_change_csv(p, renamed)).rows
    )


def test_dates_timezones_and_complete_year(tmp_path):
    p = tmp_path / "c.csv"
    sha = make_change_csv(p)
    for year, stamp in (
        (2026, RETRIEVED),
        (1999, RETRIEVED),
        (2025, RETRIEVED.replace(tzinfo=None)),
        (2025, datetime(2099, 1, 1, tzinfo=UTC)),
        (2025, datetime(2025, 12, 31, tzinfo=UTC)),
    ):
        with pytest.raises(a.ChangeImportError):
            a.load_source(p, sha, year, stamp, now=NOW)
    assert load_change(p, sha).retrieved_at == RETRIEVED


def test_bad_headers_csv_size_rows_fields_encoding_and_repository_input(tmp_path, monkeypatch):
    p = tmp_path / "c.csv"
    for headers in (a.FIELDS[:-1], a.FIELDS + (a.FIELDS[0],), a.FIELDS[:-1] + (a.FIELDS[0],)):
        with pytest.raises(a.ChangeImportError):
            load_change(p, make_change_csv(p, headers=headers))
    for content in (b"not,csv\n", b"\x81", b"", b'"unterminated', b"\x00"):
        with pytest.raises(a.ChangeImportError):
            load_change(p, make_change_csv(p, content=content))
    sha = make_change_csv(p)
    for expected in ("A" * 64, "0" * 64, "invalid"):
        with pytest.raises(a.ChangeImportError):
            load_change(p, expected)
    for attr, value in (("MAX_BYTES", 1), ("MAX_ROWS", 1), ("MAX_FIELD", 1), ("ROOT", tmp_path)):
        with monkeypatch.context() as m:
            m.setattr(a, attr, value)
            with pytest.raises(a.ChangeImportError):
                load_change(p, sha)
    with pytest.raises(a.ChangeImportError):
        load_change(p, make_change_csv(p, content=p.read_bytes() + b"\r\n"))


def test_cli_failure_before_db_and_safe_errors(tmp_path, monkeypatch, capsys):
    p = tmp_path / "private-canary.csv"
    p.write_bytes(b"bad")
    monkeypatch.setattr(cli, "create_db_engine", lambda *_: pytest.fail("DB must not open"))
    assert (
        cli.main(
            [
                "--csv",
                str(p),
                "--expected-sha256",
                sha256(b"bad").hexdigest(),
                "--source-year",
                "2025",
                "--retrieved-at",
                RETRIEVED.isoformat(),
                "--code-check-boundary-version",
                str(uuid4()),
            ]
        )
        == 1
    )
    assert cli.main(["--private-canary"]) == 1
    output = capsys.readouterr().out
    assert "private-canary" not in output and str(p) not in output


def test_lock_keys_distinct_and_digest_vector():
    from etl.living_pop.repository import LOCK_KEY as living_key
    from etl.market_changes.repository import LOCK_KEY as changes_key
    from etl.market_sales.repository import LOCK_KEY as sales_key
    from etl.market_stores.repository import LOCK_KEY as stores_key

    assert len({16, stores_key, sales_key, living_key, changes_key}) == 5
    row = dict(quarter="20251", market_code="3999999", change_code="LL", value=None, zero=0)
    assert (
        a.content_digest([row], 2025)
        == "7346c2362bdd2e10cd0b365f8cffa0dd408d1dae74b701084952a06133b98ae5"
    )


def test_existing_annual_source_digest_vectors_unchanged(tmp_path):
    from datetime import date

    from etl.market_sales.archive import content_digest as sale_digest
    from etl.market_sales.archive import load_archive as load_sales
    from etl.market_stores.archive import content_digest as store_digest
    from etl.market_stores.archive import load_archive as load_stores
    from tests.etl.market_sale_helpers import make_sales_zip
    from tests.etl.market_store_helpers import make_stats_zip

    p = tmp_path / "reference.zip"
    stores = load_stores(p, make_stats_zip(p), 2025, date(2026, 5, 21), today=NOW.date())
    assert store_digest(stores.rows) == (
        "1edd356d6da9572639263e8e058a4c32cb43a6be8a96e09b0db16acd693514bf"
    )
    sales = load_sales(p, make_sales_zip(p), 2025, date(2026, 5, 18), today=NOW.date())
    assert sale_digest(sales.rows, 2025) == (
        "c4f3b27ed6917eca39397b3392b1f6f31be88cc6fa2d80fc57e5a1032bfe6507"
    )
