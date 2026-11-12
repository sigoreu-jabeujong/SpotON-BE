import base64
import json
from urllib.parse import quote

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from etl.brands import __main__ as cli
from etl.brands import catalog as data
from etl.brands import snapshot as snapshots
from etl.brands.client import collect
from etl.brands.compare import PARTITIONS, compare_rows
from tests.etl.brands_helpers import catalog, item, response


def test_actual_client_full_pagination_and_first_page_recheck():
    source = [item(str(i).zfill(6), f"synthetic-{i}") for i in range(1001)]
    calls = []

    def handle(request):
        assert request.url.params["serviceKey"] == "SECRET+/="
        assert request.url.params["jngBizCrtraYr"] == "2025"
        n = int(request.url.params["pageNo"])
        calls.append(n)
        return httpx.Response(200, json=response(source[(n - 1) * 1000 : n * 1000], n, 1001))

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = collect(2025, SecretStr(quote("SECRET+/=", safe="")), client=client)
    assert calls == [1, 2, 1] and len(result.rows) == 1001
    assert result.rows[0].management_no == "000000"
    assert result.summary()["industries"] == {"외식": 1001}


@pytest.mark.parametrize(
    "change",
    [
        {"resultCode": "30"},
        {"numOfRows": "100"},
        {"pageNo": "2"},
        {"totalCount": 0},
        {"totalCount": True},
        {"totalCount": 100001},
        {"items": None},
        {"items": []},
        {"items": [item(jngBizCrtraYr="2024")]},
        {"items": [item(brandMnno=12)]},
        {"items": [item(brandMnno=" 001")]},
        {"items": [item(brandNm=" ")]},
        {"items": [item(industry="unexpected")]},
    ],
)
def test_provider_contract_errors_are_fixed_and_not_partial(change):
    with pytest.raises(data.BrandsError, match="^brands:"):
        data.page(data.canonical({**response(), **change}), 2025, 1)


@pytest.mark.parametrize("kind", ["http", "xml", "redirect", "timeout", "oversize"])
def test_transport_and_gateway_errors_do_not_retry_or_echo_key(kind, monkeypatch):
    calls = []
    if kind == "oversize":
        monkeypatch.setattr("etl.brands.client.MAX_PAGE_BYTES", 10)

    def handle(request):
        calls.append(1)
        if kind == "timeout":
            raise httpx.ReadTimeout("SECRET_URL_CANARY", request=request)
        if kind == "xml":
            return httpx.Response(200, text="<error>SECRET_URL_CANARY</error>")
        if kind == "oversize":
            return httpx.Response(200, content=b"x" * 11)
        return httpx.Response(
            403 if kind == "http" else 302,
            headers={"location": "https://example.invalid/SECRET_URL_CANARY"},
        )

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(data.BrandsError) as error:
            collect(2025, SecretStr("SECRET_URL_CANARY"), client=client)
    assert calls == [1] and "CANARY" not in str(error.value)


def test_missing_key_and_future_year_do_not_open_http(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("HTTP must not open")

    monkeypatch.setattr(httpx, "Client", forbidden)
    for year, key in ((2025, None), (3000, SecretStr("fake")), (True, SecretStr("fake"))):
        with pytest.raises(data.BrandsError):
            collect(year, key)


def test_duplicate_management_number_and_changed_first_page_fail():
    with pytest.raises(data.BrandsError, match="duplicate_source_key"):
        catalog([item(), item()])
    c = catalog()
    with pytest.raises(data.BrandsError, match="source_changed"):
        data.build_catalog(
            2025, c.pages, data.canonical(response([item(name="changed")])), c.collected_at
        )
    with pytest.raises(data.BrandsError, match="total_contract"):
        data.page(data.canonical(response()), 2025, 1, expected_total=2)
    for length, number in ((999, 1), (2, 2)):
        rows = [item(str(i)) for i in range(length)]
        with pytest.raises(data.BrandsError, match="page_length"):
            data.page(data.canonical(response(rows, number, 1001)), 2025, number)


def test_raw_duplicate_json_keys_and_non_json_fail():
    for raw in (b'{"resultCode":"00","resultCode":"30"}', b"not-json"):
        with pytest.raises(data.BrandsError):
            data.page(raw, 2025, 1)


def test_management_number_is_an_opaque_string_with_prefixes_and_leading_zeroes():
    identifiers = ["ABC_00000000001", "00000000001", "XYZ-00001"]
    c = catalog([item(value, f"Synthetic {number}") for number, value in enumerate(identifiers)])
    assert {row.management_no for row in c.rows} == set(identifiers)


@pytest.mark.parametrize("value", [None, "", " ", 123])
def test_headquarter_identifier_is_required_without_coercion(value):
    with pytest.raises(data.BrandsError, match="management_no"):
        catalog([item(jnghdqrtrsMnno=value)])
    missing = item()
    missing.pop("jnghdqrtrsMnno")
    with pytest.raises(data.BrandsError, match="management_no"):
        catalog([missing])


@pytest.mark.parametrize("other_name", ["Same Brand", "Other Brand"])
def test_repeated_brand_identifiers_preserve_rows_but_quarantine_all_related_names(other_name):
    rows = [
        item("001", "Same Brand", jnghdqrtrsMnno="HQ_001"),
        item("001", other_name, "도소매", jnghdqrtrsMnno="HQ_002"),
        item("002", "Unique Brand", jnghdqrtrsMnno="HQ_003"),
    ]
    c = catalog(rows)
    assert c.content_sha256 == catalog(list(reversed(rows))).content_sha256
    assert len(c.rows) == 3
    assert c.summary()["unique_brand_ids"] == 2
    assert c.summary()["repeated_brand_ids"] == 1 and c.summary()["repeated_rows"] == 2
    stores = [
        dict(name=name, is_franchise=None, brand_id=None)
        for name in ("Same Brand", other_name, "Unique Brand")
    ]
    result = compare_rows(c, stores)
    assert result["repeated_brand_id"] == 2 and result["exact_name_candidate"] == 1
    assert sum(result[k] for k in PARTITIONS) == 3


def test_repeated_management_number_across_pages_requires_distinct_source_pair():
    rows = [item(str(i).zfill(6), f"Synthetic {i}") for i in range(1001)]
    rows[-1] = item(rows[0]["brandMnno"], "Different Name", jnghdqrtrsMnno="HQ_OTHER")
    pages = tuple(
        data.canonical(response(part, number, 1001))
        for number, part in enumerate((rows[:1000], rows[1000:]), 1)
    )
    c = data.build_catalog(2025, pages, pages[0], catalog().collected_at)
    assert len(c.rows) == 1001 and c.summary()["repeated_brand_ids"] == 1
    rows[-1]["jnghdqrtrsMnno"] = rows[0]["jnghdqrtrsMnno"]
    invalid = (pages[0], data.canonical(response(rows[1000:], 2, 1001)))
    with pytest.raises(data.BrandsError, match="duplicate_source_key"):
        data.build_catalog(2025, invalid, pages[0], c.collected_at)


def test_unvalidated_acquisition_is_not_a_completed_snapshot(tmp_path):
    path = tmp_path / "unvalidated.json"
    path.write_bytes(
        data.canonical(
            dict(
                schema="ftc-brand-acquisition-unvalidated-v1", status="validation_failed", pages=[]
            )
        )
    )
    with pytest.raises(data.BrandsError, match="snapshot_contract"):
        snapshots.load_snapshot(path)


def test_normalization_keeps_punctuation_and_branch_names_and_raw_is_unchanged():
    c = catalog(
        [
            item("001", " ＡＢＣ  Cafe "),
            item("002", "abc Cafe"),
            item("003", "abc Cafe-강남점"),
            item("004", "Straße"),
        ]
    )
    assert c.rows[0].normalized_name == c.rows[1].normalized_name == "abc cafe"
    assert c.rows[0].name == " ＡＢＣ  Cafe "
    assert c.rows[2].normalized_name != "abc cafe"
    assert c.rows[3].normalized_name == "strasse"
    assert c.summary()["ambiguous_names"] == 1
    assert "PRIVATE" not in repr(c) and "PRIVATE" not in repr(c.rows[0])
    assert "PRIVATE" not in data.canonical([vars_like(r) for r in c.rows]).decode()
    assert b"PRIVATE_PERSON_CANARY" in c.pages[0]


def vars_like(row):
    from dataclasses import asdict

    return asdict(row)


def test_comparison_partition_candidates_are_never_independent():
    c = catalog(
        [
            item("001", "Unique Cafe"),
            item("002", "Same Cafe"),
            item("003", "Same Cafe", "도소매"),
            item("004", "Retail Brand", "도소매"),
        ]
    )

    def row(name, **changes):
        return dict(name=name, is_franchise=None, brand_id=None, **changes)

    rows = [
        row("UNIQUE CAFE"),
        row("Unique Cafe 강남점"),
        row("Same Cafe"),
        row("Retail Brand"),
        row("ab"),
        row("123456"),
        row(None),
        row(" "),
    ]
    rows += [
        dict(name="Same Cafe", is_franchise=False, brand_id=None),
        dict(name=None, is_franchise=None, brand_id=7),
    ]
    before = [dict(r) for r in rows]
    result = compare_rows(c, iter(rows))
    assert result == dict(
        total=10,
        existing_classification=2,
        missing_name=2,
        weak_name=2,
        repeated_brand_id=0,
        ambiguous_name=1,
        non_food_name=1,
        exact_name_candidate=1,
        no_exact_candidate=1,
    )
    assert sum(result[k] for k in PARTITIONS) == result["total"]
    assert rows == before and "independent" not in result


def test_snapshot_roundtrip_is_offline_and_never_overwrites(tmp_path):
    path = tmp_path / "snapshot.json"
    c = catalog()
    snapshots.save_snapshot(path, c)
    before = path.read_bytes()
    restored = snapshots.load_snapshot(path)
    assert restored == c and restored.content_sha256 == c.content_sha256
    with pytest.raises(FileExistsError):
        snapshots.save_snapshot(path, c)
    assert path.read_bytes() == before
    rows = [item("002", "second"), item("001", "first")]
    assert catalog(rows).content_sha256 == catalog(list(reversed(rows))).content_sha256


@pytest.mark.parametrize("target", ["rule", "hash", "body", "total", "time", "extra", "truncated"])
def test_snapshot_metadata_and_raw_tampering_fail(tmp_path, target):
    path = tmp_path / "snapshot.json"
    snapshots.save_snapshot(path, catalog())
    value = json.loads(path.read_bytes())
    if target == "rule":
        value["rule_version"] = "different"
    elif target == "hash":
        value["content_sha256"] = "0" * 64
    elif target == "body":
        value["pages"][0]["body"] = base64.b64encode(b"tampered").decode()
    elif target == "total":
        value["total_count"] = 2
    elif target == "time":
        value["collected_at"] = "2026-11-12"
    elif target == "extra":
        value["unknown"] = "PRIVATE_CANARY"
    if target == "truncated":
        path.write_bytes(b'{"partial"')
    else:
        path.write_bytes(data.canonical(value))
    with pytest.raises(data.BrandsError):
        snapshots.load_snapshot(path)


def test_repository_paths_and_snapshot_size_limits(tmp_path, monkeypatch):
    with pytest.raises(data.BrandsError, match="repository_path"):
        snapshots.save_snapshot(snapshots.WORKSPACE / "SpotON-FE" / "private.json", catalog())
    path = tmp_path / "snapshot.json"
    monkeypatch.setattr(snapshots, "MAX_SNAPSHOT_BYTES", 1)
    with pytest.raises(data.BrandsError, match="snapshot_size"):
        snapshots.save_snapshot(path, catalog())
    assert not path.exists()


@pytest.mark.parametrize("fault", [OSError, KeyboardInterrupt])
def test_snapshot_flush_failure_removes_only_new_file(tmp_path, monkeypatch, fault):
    path = tmp_path / "snapshot.json"

    def fail(fd):
        raise fault("PRIVATE_CANARY")

    monkeypatch.setattr(snapshots.os, "fsync", fail)
    with pytest.raises(fault):
        snapshots.save_snapshot(path, catalog())
    assert not path.exists()


def test_cli_replay_has_no_settings_http_or_db_and_no_private_output(tmp_path, monkeypatch, capsys):
    path = tmp_path / "private-path.json"
    c = catalog()
    snapshots.save_snapshot(path, c)

    def forbidden(*args, **kwargs):
        raise AssertionError("unexpected operation")

    monkeypatch.setattr(cli, "Settings", forbidden)
    monkeypatch.setattr(cli, "collect", forbidden)
    monkeypatch.setattr(cli, "compare_catalog", forbidden)
    assert cli.main(["--snapshot", str(path)]) == 0
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert result["content_sha256"] == c.content_sha256 and result["request_count"] == 0
    assert result["classification_status"] == "pending" and result["comparison"] is None
    events = [json.loads(line) for line in captured.err.splitlines()]
    assert len(events) == 4 and all(e["source"] == "brands" for e in events)
    for marker in ("PRIVATE", str(path), "例", "예시카페", "brandNm", "postgresql"):
        assert marker not in captured.out + captured.err


def test_saved_source_survives_later_db_failure_and_output_is_fixed(tmp_path, monkeypatch, capsys):
    path = tmp_path / "saved.json"
    monkeypatch.setattr(cli, "collect", lambda *args: catalog())
    monkeypatch.setattr(cli, "Settings", lambda: Settings(_env_file=None))

    def fail(*args):
        raise RuntimeError("PRIVATE_DB_URL_CANARY")

    monkeypatch.setattr(cli, "compare_catalog", fail)
    assert cli.main(["--year", "2025", "--output", str(path), "--compare-local"]) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out) == dict(
        error="brands:operation_failed", stage="prepare", snapshot_saved=True
    )
    assert snapshots.load_snapshot(path).summary()["rows"] == 1
    assert "PRIVATE" not in captured.out + captured.err


def test_existing_output_prevents_collection(tmp_path, monkeypatch):
    path = tmp_path / "existing.json"
    path.write_text("existing")

    def forbidden(*args):
        raise AssertionError("must not collect")

    monkeypatch.setattr(cli, "collect", forbidden)
    with pytest.raises(cli.RunFailure, match="output_exists"):
        cli.run_import(year=2025, output=path)
    assert path.read_text() == "existing"


def test_concurrent_snapshot_creation_has_one_winner_and_preserves_content(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    path = tmp_path / "snapshot.json"
    c = catalog()

    def save():
        try:
            snapshots.save_snapshot(path, c)
            return "saved"
        except FileExistsError:
            return "exists"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: save(), range(2)))
    assert sorted(outcomes) == ["exists", "saved"]
    assert snapshots.load_snapshot(path) == c


def test_save_failure_prevents_comparison_and_reports_no_completed_snapshot(
    tmp_path, monkeypatch, capsys
):
    path = tmp_path / "snapshot.json"
    monkeypatch.setattr(cli, "Settings", lambda: Settings(_env_file=None))
    monkeypatch.setattr(cli, "collect", lambda *args: catalog())

    def fail(*args):
        raise OSError("PRIVATE_PATH_CANARY")

    def forbidden(*args):
        raise AssertionError("comparison must not run")

    monkeypatch.setattr(cli, "save_snapshot", fail)
    monkeypatch.setattr(cli, "compare_catalog", forbidden)
    assert cli.main(["--year", "2025", "--output", str(path), "--compare-local"]) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out) == dict(
        error="brands:operation_failed", stage="save_snapshot", snapshot_saved=False
    )
    assert not path.exists() and "PRIVATE" not in captured.out + captured.err


def test_full_collect_cli_does_not_emit_any_source_value_or_key(tmp_path, monkeypatch, capsys):
    path = tmp_path / "PRIVATE_PATH_CANARY.json"
    config = Settings(_env_file=None, data_go_kr_service_key=SecretStr("PRIVATE_KEY_CANARY"))
    monkeypatch.setattr(cli, "Settings", lambda: config)

    def collect_mock(year, key):
        with httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response()))
        ) as client:
            return collect(year, key, client=client)

    monkeypatch.setattr(cli, "collect", collect_mock)
    assert cli.main(["--year", "2025", "--output", str(path)]) == 0
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert result["snapshot_saved"] and result["request_count"] == 2
    events = [json.loads(line) for line in captured.err.splitlines()]
    assert [(event["stage"], event["status"]) for event in events] == [
        ("import", "started"),
        ("collect", "started"),
        ("collect", "completed"),
        ("save_snapshot", "started"),
        ("save_snapshot", "completed"),
        ("import", "completed"),
    ]
    for marker in ("PRIVATE", "예시카페", "serviceKey", "brandMnno"):
        assert marker not in captured.out + captured.err


def test_help_exits_successfully(capsys):
    with pytest.raises(SystemExit) as error:
        cli.main(["--help"])
    assert error.value.code == 0 and "--compare-local" in capsys.readouterr().out


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--year", "PRIVATE_CANARY"],
        ["--year", "2025"],
        ["--snapshot", "PRIVATE_CANARY", "--output", "PRIVATE_CANARY"],
    ],
)
def test_cli_arguments_are_fixed_and_private(args, capsys):
    with pytest.raises(SystemExit) as error:
        cli.main(args)
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert captured.err == "invalid arguments\n" and "PRIVATE" not in captured.out
