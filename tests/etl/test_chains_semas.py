import json
from datetime import UTC, datetime
from urllib.parse import quote

import httpx
import pytest
from pydantic import SecretStr

from etl.chains import semas
from etl.chains.common import ChainsError, digest
from etl.chains.snapshot import load_snapshot, save_snapshot


def item(identifier="SYNTHETIC1", **changes):
    return dict(
        bizesId=identifier,
        bizesNm="스타벅스",
        brchNm="강남점",
        ctprvnCd="11",
        indsLclsCd="I2",
        indsMclsCd="I212",
        indsSclsCd="I21201",
        signguCd="11680",
        rdnmAdr="서울특별시 강남구 테헤란로 1",
        lnoAdr="서울특별시 강남구 역삼동 1",
        bldMngNo="",
        flrNo="1",
        hoNo="",
        lat="37.5",
        lon="127.0",
        **changes,
    )


def response(items, number=1, total=None, month="202601"):
    return dict(
        header=dict(resultCode="00", stdrYm=month),
        body=dict(
            pageNo=number,
            numOfRows=1000,
            totalCount=len(items) if total is None else total,
            items=items,
        ),
    )


def make_snapshot(rows=None):
    selected = tuple(semas.project(r) for r in (rows or [item()]))
    return semas.validate_snapshot(
        semas.Snapshot(
            reference_month="202601",
            observed_at=datetime.now(UTC),
            rows=selected,
            content_sha256=semas.content_hash(selected),
            request_count=2,
        )
    )


def test_authenticated_fixed_scope_full_pagination_recheck_and_minimal_projection():
    rows = [item(f"S{i}") for i in range(1001)]
    rows[0]["phone"] = "DO_NOT_STORE_PHONE"
    rows[0]["representative"] = "DO_NOT_STORE_PERSON"
    calls = []

    def handler(request):
        assert str(request.url).startswith(semas.ENDPOINT)
        assert request.url.params["ServiceKey"] == "FAKE+/="
        assert request.url.params["key"] == "11"
        assert request.url.params["indsLclsCd"] == "I2"
        n = int(request.url.params["pageNo"])
        calls.append(n)
        return httpx.Response(200, json=response(rows[(n - 1) * 1000 : n * 1000], n, 1001))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = semas.collect(SecretStr(quote("FAKE+/=", safe="")), client=client)
    assert calls == [1, 2, 1] and len(result.rows) == 1001
    assert result.request_count == 3
    assert "DO_NOT_STORE" not in result.model_dump_json()
    assert "DO_NOT_STORE" not in repr(result)


@pytest.mark.parametrize("problem", ["redirect", "xml", "http", "timeout", "size", "duplicate"])
def test_errors_do_not_follow_redirects_retry_or_echo_secrets(problem, monkeypatch, caplog):
    calls = []
    if problem == "size":
        monkeypatch.setattr(semas, "MAX_PAGE_BYTES", 10)

    def handler(request):
        calls.append(1)
        if problem == "timeout":
            raise httpx.ReadTimeout("SECRET_CANARY_URL", request=request)
        if problem == "redirect":
            return httpx.Response(
                302, headers={"location": "https://example.invalid/SECRET_CANARY"}
            )
        if problem == "xml":
            return httpx.Response(200, text="<error>SECRET_CANARY</error>")
        if problem == "http":
            return httpx.Response(403, text="SECRET_CANARY")
        if problem == "size":
            return httpx.Response(200, content=b"x" * 11)
        return httpx.Response(200, json=response([item(), item()]))

    with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
        with pytest.raises(ChainsError) as error:
            semas.collect(SecretStr("SECRET_CANARY"), client=client)
    assert "CANARY" not in str(error.value) and "CANARY" not in caplog.text
    assert len(calls) <= 2


@pytest.mark.parametrize("change", ["month", "total", "first_page"])
def test_mid_collection_changes_never_publish_a_partial_snapshot(change):
    rows = [item(f"S{i}") for i in range(1001)]
    calls = []

    def handler(request):
        n = int(request.url.params["pageNo"])
        calls.append(n)
        data = response(rows[(n - 1) * 1000 : n * 1000], n, 1001)
        if change == "month" and n == 2:
            data["header"]["stdrYm"] = "202602"
        if change == "total" and n == 2:
            data["body"]["totalCount"] = 1002
        if change == "first_page" and len(calls) == 3:
            data["body"]["items"][0] = item("CHANGED")
        return httpx.Response(200, json=data)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ChainsError):
            semas.collect(SecretStr("fake"), client=client)


@pytest.mark.parametrize(
    "field,value",
    [
        ("ctprvnCd", "26"),
        ("indsLclsCd", "G2"),
        ("bizesId", ""),
        ("bizesNm", ""),
        ("signguCd", "not-a-gu"),
    ],
)
def test_invalid_scope_identity_and_required_fields_are_rejected(field, value):
    row = item()
    row[field] = value
    with pytest.raises(ChainsError):
        semas.project(row)


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "", None, True, "91"])
def test_invalid_coordinate_pair_is_unknown_without_zero_or_swapping(bad):
    row = item()
    row["lat"] = bad
    point = semas.project(row)
    assert point.lat is None and point.lng is None


def test_snapshot_integrity_includes_manifest_not_just_rows_and_never_overwrites(tmp_path):
    data = make_snapshot()
    path = tmp_path / "new.json"
    save_snapshot(path, data)
    assert load_snapshot(path) == data
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        save_snapshot(path, data)
    assert path.read_bytes() == before
    value = json.loads(before)
    value["payload"]["reference_month"] = "202512"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ChainsError, match="snapshot_integrity"):
        load_snapshot(path)
    value["sha256"] = digest(value["payload"])
    value["payload"]["rows"][0]["lat"] = True
    value["sha256"] = digest(value["payload"])
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ChainsError):
        load_snapshot(path)


def test_repository_and_symlink_to_repository_paths_are_rejected(tmp_path):
    from pathlib import Path

    from etl.chains.common import external_path

    repo = Path(__file__).resolve().parents[2]
    with pytest.raises(ChainsError, match="repository_path"):
        external_path(repo / "secrets.json")
    other = tmp_path / "another-checkout"
    other.mkdir()
    (other / ".git").write_text("gitdir: dummy", encoding="utf-8")
    with pytest.raises(ChainsError, match="repository_path"):
        external_path(other / "snapshot.json")


def test_reference_month_uses_korean_calendar_at_utc_month_boundary():
    data = make_snapshot().model_copy(
        update={
            "reference_month": "202611",
            "observed_at": datetime(2026, 10, 31, 17, tzinfo=UTC),
        }
    )
    assert semas.validate_snapshot(data) == data
