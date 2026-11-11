from datetime import date
from uuid import uuid4

import pytest

from etl.market_sales import __main__ as cli
from etl.market_sales import archive as a
from tests.etl.market_sale_helpers import annual_sales_rows, make_sales_zip

DATE = date(2026, 5, 18)
TODAY = date(2026, 11, 12)


def load(path, sha):
    return a.load_archive(path, sha, 2025, DATE, today=TODAY)


def test_null_zero_bigint_hashes_and_no_partition_recalculation(tmp_path):
    p = tmp_path / "sales.zip"
    rows = annual_sales_rows()
    rows[0][a.FIELDS[7]] = ""
    rows[0][a.FIELDS[8]] = ""
    rows[1][a.FIELDS[7]] = "0"
    rows[1][a.FIELDS[8]] = "0"
    rows[2][a.FIELDS[7]] = str(a.MAX_INTEGER)
    for encoding in ("cp949", "utf-8-sig"):
        archive = load(
            p, make_sales_zip(p, rows, encoding=encoding, headers=tuple(reversed(a.FIELDS)))
        )
        assert len(archive.rows) == archive.source_rows == 20
        assert (
            archive.rows[0]["est_sales"] is None and archive.rows[0]["source_sales_count"] is None
        )
        assert archive.rows[1]["est_sales"] == 0 and archive.rows[2]["est_sales"] == a.MAX_INTEGER
        assert archive.rows[3]["est_sales"] == 3000000001
        assert archive.rows[3]["source_row_sha256"] == a.digest(rows[3])
        reverse = load(p, make_sales_zip(p, list(reversed(rows)), encoding=encoding))
        assert a.content_digest(archive.rows, 2025) == a.content_digest(reverse.rows, 2025)
        assert a.content_digest(archive.rows, 2025) != a.content_digest(
            archive.rows, 2025, "new-rule"
        )
    assert "시간대_건수~06_매출_건수" in a.FIELDS


@pytest.mark.parametrize(
    "value",
    [
        "1_000",
        " 1",
        "1 ",
        "+1",
        "-0",
        "-1",
        "007",
        "1.0",
        "1e3",
        "1,000",
        "１",
        "²",
        "١",
        " ",
        "NaN",
        "Infinity",
        "9223372036854775808",
    ],
)
def test_strict_integers_in_unused_and_excluded_fields(tmp_path, value):
    p = tmp_path / "sales.zip"
    rows = annual_sales_rows()
    other = {
        **rows[0],
        a.FIELDS[5]: "CS100009",
        a.FIELDS[6]: "synthetic-excluded",
        a.FIELDS[-1]: value,
    }
    with pytest.raises(a.SalesImportError):
        load(p, make_sales_zip(p, rows + [other], encoding="utf-8-sig"))


def test_identity_duplicates_missing_combinations_and_annual_rules(tmp_path):
    p = tmp_path / "sales.zip"
    rows = annual_sales_rows()
    changes = [
        (a.FIELDS[0], "20241"),
        (a.FIELDS[0], "20255"),
        (a.FIELDS[1], "Z"),
        (a.FIELDS[2], "bad"),
        (a.FIELDS[3], "bad"),
        (a.FIELDS[4], " "),
        (a.FIELDS[4], "private\tcanary"),
        (a.FIELDS[5], "BAD"),
        (a.FIELDS[6], "bad"),
    ]
    for field, value in changes:
        invalid = [{**rows[0], field: value}] + rows[1:]
        with pytest.raises(a.SalesImportError):
            load(p, make_sales_zip(p, invalid))
    for invalid in (rows[1:], rows[5:], rows + [rows[0]]):
        with pytest.raises(a.SalesImportError):
            load(p, make_sales_zip(p, invalid))
    other = {**rows[0], a.FIELDS[5]: "CS100009", a.FIELDS[6]: "excluded"}
    assert load(p, make_sales_zip(p, rows + [other])).source_rows == 21
    for invalid in (rows + [other, other], rows + [{**other, a.FIELDS[4]: "conflict"}]):
        with pytest.raises(a.SalesImportError):
            load(p, make_sales_zip(p, invalid))
    changed = [{**r, a.FIELDS[4]: "renamed"} if r[a.FIELDS[0]] == "20252" else r for r in rows]
    assert len(load(p, make_sales_zip(p, changed)).rows) == 20
    sha = make_sales_zip(p)
    for year, d in ((2026, DATE), (2025, date(2025, 12, 31)), (2025, date(2026, 11, 13))):
        with pytest.raises(a.SalesImportError):
            a.load_archive(p, sha, year, d, today=TODAY)


def test_headers_and_shared_zip_policy_limits(tmp_path, monkeypatch):
    p = tmp_path / "sales.zip"
    for headers in (
        a.FIELDS[:-1],
        a.FIELDS + (a.FIELDS[0],),
        a.FIELDS[:-1] + (a.FIELDS[0],),
        tuple(k.replace("건수~06", "00~06") for k in a.FIELDS),
    ):
        with pytest.raises(a.SalesImportError):
            load(p, make_sales_zip(p, rows=[], headers=headers))
    sha = make_sales_zip(p)
    with pytest.raises(a.SalesImportError):
        load(p, "0" * 64)
    for name, value in (
        ("MAX_ZIP_BYTES", 1),
        ("MAX_CSV_BYTES", 1),
        ("MAX_ROWS", 1),
        ("MAX_FIELD", 1),
    ):
        with monkeypatch.context() as m:
            m.setattr(a, name, value)
            with pytest.raises(a.SalesImportError):
                load(p, sha)
    with monkeypatch.context() as m:
        m.setattr(a, "ROOT", tmp_path)
        with pytest.raises(a.SalesImportError, match="repository_input"):
            load(p, sha)
    with pytest.raises(a.SalesImportError):
        load(p, make_sales_zip(p, member="../bad.csv"))
    for content in (b"\xff", b"\x00", b"\xef\xbb\xbf" + ",".join(a.FIELDS).encode() + b"\n\n"):
        with pytest.raises(a.SalesImportError):
            load(p, make_sales_zip(p, content=content))


def test_cli_bad_input_safe_and_no_connection(tmp_path, monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("unexpected_db")

    monkeypatch.setattr(cli, "create_db_engine", forbidden)
    args = [
        "--zip",
        str(tmp_path / "private-path"),
        "--expected-sha256",
        "private-key",
        "--source-year",
        "2025",
        "--source-file-date",
        "2026-05-18",
        "--code-check-boundary-version",
        str(uuid4()),
        "--code-check-store-version",
        str(uuid4()),
    ]
    assert cli.main(args) == 1 and cli.main(["--unknown", "private-value"]) == 1
    assert "private-" not in capsys.readouterr().out
