import zipfile
from datetime import date
from hashlib import sha256
from uuid import uuid4

import pytest

from etl.market_stores import __main__ as cli
from etl.market_stores import archive as a
from tests.etl.market_store_helpers import annual_rows, make_stats_zip

DATE = date(2026, 5, 21)
TODAY = date(2026, 11, 12)


def load(path, sha):
    return a.load_archive(path, sha, 2025, DATE, today=TODAY)


def test_valid_encodings_headers_order_raw_hash_and_rate_semantics(tmp_path):
    p = tmp_path / "input.zip"
    for encoding in ("cp949", "utf-8-sig"):
        rows = annual_rows()
        rows[0]["opbiz_rt"] = ""
        rows[1]["opbiz_rt"] = "12.500000"
        result = load(
            p, make_stats_zip(p, rows, encoding=encoding, headers=tuple(reversed(a.FIELDS)))
        )
        assert result.source_rows == len(result.rows) == 20
        assert result.source_encoding == encoding
        assert result.rows[0]["opening_rate"] is None
        assert result.rows[0]["closure_rate"] == 450
        assert result.rows[0]["closed_stores"] > result.rows[0]["general_stores"]
        assert result.rows[0]["total_stores"] == 3
        assert result.rows[0]["source_row_sha256"] == a.digest(rows[0])
        reversed_result = load(p, make_stats_zip(p, list(reversed(rows)), encoding=encoding))
        assert a.content_digest(result.rows) == a.content_digest(reversed_result.rows)
        rows[1]["opbiz_rt"] = "12.5"
        different = load(p, make_stats_zip(p, rows, encoding=encoding))
        assert result.rows[1]["opening_rate"] == different.rows[1]["opening_rate"]
        assert a.content_digest(result.rows) != a.content_digest(different.rows)


@pytest.mark.parametrize(
    "field,value",
    [
        ("stor_co", ""),
        ("stor_co", "-1"),
        ("stor_co", "01"),
        ("stor_co", "1.0"),
        ("stor_co", " 1"),
        ("stor_co", "2147483648"),
        ("similr_induty_stor_co", "2"),
        ("clsbiz_rt", "NaN"),
        ("clsbiz_rt", "Infinity"),
        ("clsbiz_rt", "-1"),
        ("clsbiz_rt", "1e2"),
        ("clsbiz_rt", "1.0000001"),
        ("clsbiz_rt", "1,000"),
        ("clsbiz_rt", "100000000"),
        ("clsbiz_rt", " 1"),
        ("trdar_cd", "bad"),
        ("trdar_cd_nm", " "),
        ("trdar_cd_nm", "x\tsecret"),
        ("trdar_se_cd", "Z"),
        ("trdar_se_cd_nm", "bad"),
        ("svc_induty_cd_nm", "bad"),
        ("stdr_yyqu_cd", "20241"),
        ("stdr_yyqu_cd", "20255"),
    ],
)
def test_invalid_values_reject_whole_archive(tmp_path, field, value):
    p = tmp_path / "input.zip"
    rows = annual_rows()
    rows[0][field] = value
    with pytest.raises(a.StatsImportError):
        load(p, make_stats_zip(p, rows))


def test_missing_combinations_duplicates_and_excluded_rows_validated(tmp_path):
    p = tmp_path / "input.zip"
    base = annual_rows()
    for rows in (base[1:], base[5:], base + [base[0]]):
        with pytest.raises(a.StatsImportError):
            load(p, make_stats_zip(p, rows))
    other = {**base[0], "svc_induty_cd": "CS100009", "svc_induty_cd_nm": "synthetic-excluded"}
    result = load(p, make_stats_zip(p, base + [other]))
    assert result.source_rows == 21 and len(result.rows) == 20
    for rows in (
        base + [other, other],
        base + [{**other, "stor_co": "bad"}],
        base + [{**other, "trdar_cd_nm": "conflicting"}],
    ):
        with pytest.raises(a.StatsImportError):
            load(p, make_stats_zip(p, rows))
    changed = [{**r, "trdar_cd_nm": "changed"} if r["stdr_yyqu_cd"] == "20252" else r for r in base]
    assert len(load(p, make_stats_zip(p, changed)).rows) == 20


@pytest.mark.parametrize(
    "headers",
    [
        a.FIELDS[:-1],
        a.FIELDS + ("extra",),
        a.FIELDS[:-1] + (a.FIELDS[0],),
        tuple(k.upper() for k in a.FIELDS),
    ],
)
def test_headers_strict(tmp_path, headers):
    p = tmp_path / "input.zip"
    with pytest.raises(a.StatsImportError):
        load(p, make_stats_zip(p, headers=headers, rows=[]))


def test_date_hash_path_limits_and_zip_safety(tmp_path, monkeypatch):
    p = tmp_path / "input.zip"
    sha = make_stats_zip(p)
    for year, d, t in (
        (2026, DATE, TODAY),
        (2025, date(2025, 12, 31), TODAY),
        (2025, date(2026, 11, 13), TODAY),
    ):
        with pytest.raises(a.StatsImportError):
            a.load_archive(p, sha, year, d, today=t)
    with pytest.raises(a.StatsImportError):
        load(p, "0" * 64)
    monkeypatch.setattr(a, "ROOT", tmp_path)
    with pytest.raises(a.StatsImportError, match="repository_input"):
        load(p, sha)
    monkeypatch.setattr(a, "ROOT", tmp_path / "elsewhere")
    for kwargs in (
        {"member": "../bad.csv"},
        {"member": "C:bad.csv"},
        {"extra": "extra.csv"},
        {"member": "folder/"},
        {"content": b"\xff"},
        {"content": b"x\x00"},
    ):
        with pytest.raises(a.StatsImportError):
            load(p, make_stats_zip(p, **kwargs))
    for limit, value in (
        ("MAX_ZIP_BYTES", 1),
        ("MAX_CSV_BYTES", 1),
        ("MAX_ROWS", 2),
        ("MAX_FIELD", 2),
    ):
        sha = make_stats_zip(p)
        with monkeypatch.context() as m:
            m.setattr(a, limit, value)
            with pytest.raises(a.StatsImportError):
                load(p, sha)
    for content in (
        b"\xef\xbb\xbf" + ",".join(a.FIELDS).encode() + b"\n\n",
        b"\xef\xbb\xbf" + ",".join(a.FIELDS).encode() + b'\n"unterminated',
    ):
        with pytest.raises(a.StatsImportError):
            load(p, make_stats_zip(p, content=content))
    # Stored CRC corruption is deterministic; synthetic byte changed after zip creation.
    with zipfile.ZipFile(p, "w", compression=zipfile.ZIP_STORED) as z:
        z.writestr("input.csv", b"CRC_CANARY")
    raw = p.read_bytes().replace(b"CRC_CANARY", b"CRC_BANARY")
    p.write_bytes(raw)
    with pytest.raises(a.StatsImportError):
        load(p, sha256(raw).hexdigest())
    with zipfile.ZipFile(p, "w") as z:
        info = zipfile.ZipInfo("input.csv")
        info.create_system = 3
        info.external_attr = 0o120777 << 16
        z.writestr(info, b"target")
    with pytest.raises(a.StatsImportError):
        load(p, sha256(p.read_bytes()).hexdigest())


def test_cli_errors_do_not_echo_values_or_connect_on_bad_input(tmp_path, monkeypatch, capsys):
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
        "2026-05-21",
        "--code-check-boundary-version",
        str(uuid4()),
    ]
    assert cli.main(args) == 1
    assert cli.main(["--unexpected", "private-key"]) == 1
    output = capsys.readouterr().out
    assert "private-" not in output


def test_canonical_hash_vectors():
    assert (
        a.digest({"z": "한글", "a": 1})
        == "a97a9a83f42502033e933b3cb9c8b9a8bbabf4fad5ec1c9cfd37c1f9d98db786"
    )
    row = dict(
        quarter="20251",
        market_code="3110000",
        induty_cd="CS100010",
        opening_rate=None,
        closure_rate=0,
    )
    assert a.content_digest([row]) != a.content_digest([row], "new-rule")


def test_pre_refactor_official_store_hashes_remain_identical(tmp_path):
    path = tmp_path / "synthetic.zip"
    archive = load(path, make_stats_zip(path))
    assert (
        a.content_digest(archive.rows)
        == "1edd356d6da9572639263e8e058a4c32cb43a6be8a96e09b0db16acd693514bf"
    )
    assert (
        archive.rows[0]["source_row_sha256"]
        == "f65c6b6d3d4638cec889c2d6548f95c02e9621c534b9d4367817491ea005ec08"
    )
