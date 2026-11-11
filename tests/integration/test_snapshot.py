from collections import Counter
from collections.abc import Iterator
from datetime import date
from itertools import product

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.main import create_app
from app.schemas.snapshot import SnapshotStore
from tests.integration.conftest import TemporaryDatabase
from tests.integration.test_localdata_upsert import migrate
from tests.integration.test_nearby import PARAMS, batch, store

pytestmark = pytest.mark.integration


@pytest.fixture
def snapshot_db(temporary_database: TemporaryDatabase) -> TemporaryDatabase:
    migrate(temporary_database)
    return temporary_database


@pytest.fixture
def snapshot_client(snapshot_db: TemporaryDatabase) -> Iterator[TestClient]:
    app = create_app(Settings(_env_file=None))
    app.state.database.engine = snapshot_db.engine
    with TestClient(app) as client:
        yield client


def matching(client: TestClient, **changes: object) -> dict:
    params = {**PARAMS, "as_of": "2020-01", **changes}
    n = client.get("/api/stores/nearby", params=params)
    s = client.get("/api/stores/snapshot", params=params)
    assert n.status_code == s.status_code == 200, (n.status_code, s.status_code)
    nearby, snapshot = n.json(), s.json()
    d = snapshot["data"]
    assert d["total_at_as_of"] == nearby["data"]["count"] == len(d["stores"])
    assert d["total_at_as_of"] == d["still_open"] + d["closed_since"] + d["other"]
    assert d["stores"] == [
        {k: m[k] for k in SnapshotStore.model_fields} for m in nearby["data"]["markers"]
    ]
    counts = Counter(row["current_status"] for row in d["stores"])
    assert (d["still_open"], d["closed_since"], d["other"]) == (
        counts["open"],
        counts["closed"],
        counts["other"],
    )
    assert len({(r["source"], r["license_no"]) for r in d["stores"]}) == len(d["stores"])
    assert d["excluded_no_coord"] == nearby["data"]["excluded_no_coord"]
    assert snapshot["meta"]["excluded_no_coord_scope"] == "seoul_nonspatial_cohort"
    assert snapshot["meta"]["operating_period_basis"] == "latest_data"
    assert (
        snapshot["meta"]["data_version"]["stores_batch_ids"]
        == nearby["meta"]["data_version"]["stores_batch_ids"]
    )
    assert (
        snapshot["meta"]["data_version"]["map_version"]
        == nearby["meta"]["data_version"]["map_version"]
    )
    assert snapshot["meta"]["data_version"]["rule_version"] == "store-snapshot-latest-status-v1"
    assert snapshot["meta"]["denominator"] == d["total_at_as_of"]
    assert s.headers["cache-control"] == "no-store"
    return snapshot


def test_temporal_partition_latest_periods_and_unreliable_dates(
    snapshot_db: TemporaryDatabase,
    snapshot_client: TestClient,
) -> None:
    with Session(snapshot_db.engine) as session, session.begin():
        provenance = batch(session)
        for identity, values in {
            "open": {"name": None},
            "closed": {"status": "closed", "close_date": date(2022, 1, 1)},
            "other": {"status": "other"},
            "null": {"status": None},
            "unexpected": {"status": "paused"},
            "opened-on-T": {"open_date": date(2020, 1, 31)},
            "closed-on-T": {"status": "closed", "close_date": date(2020, 1, 31)},
            "opened-after-T": {"open_date": date(2020, 2, 1)},
            "new-zero-month": {"open_date": date(2026, 11, 1)},
            "missing-close": {"status": "closed"},
            "bad-date": {"date_flag": "unknown_token"},
            "temporary": {"is_temporary": True},
            "review": {"category_review_flag": True},
        }.items():
            store(session, provenance, identity, **values)
        store(session, provenance, "missing-coordinate", None)
    d = matching(snapshot_client)["data"]
    assert (d["total_at_as_of"], d["still_open"], d["closed_since"], d["other"]) == (6, 2, 1, 3)
    by_id = {row["license_no"]: row for row in d["stores"]}
    assert by_id["open"]["name"] is None and by_id["open"]["operating_months"] == 82
    assert (
        by_id["closed"]["operating_months"] == 24 and by_id["closed"]["current_status"] == "closed"
    )
    assert all(
        by_id[k]["operating_period_reason"] == "other_status"
        for k in ["other", "null", "unexpected"]
    )
    assert d["excluded_no_coord"] == 1
    assert (
        d["summary_text"]
        == "2020.01.31 기준 동일 업종 6곳 → 최신 데이터 기준 영업 2곳 · 폐업 1곳 · 기타 3곳"
    )
    latest = matching(snapshot_client, as_of="2026-11")["data"]
    assert latest["as_of"] == "2026-11-10" and latest["closed_since"] == 0
    zero = next(r for r in latest["stores"] if r["license_no"] == "new-zero-month")
    assert zero["operating_months"] == 0 and zero["operating_period_status"] == "fact"
    leap = matching(snapshot_client, as_of="2020-02")["data"]
    assert leap["as_of"] == "2020-02-29"


def test_filter_radius_time_matrix_and_strict_boundary(
    snapshot_db: TemporaryDatabase,
    snapshot_client: TestClient,
) -> None:
    with Session(snapshot_db.engine) as session, session.begin():
        provenance = batch(session)
        for i, (area, franchise) in enumerate(
            product([None, 0, 32.99, 33, 66, 99], [None, False, True])
        ):
            store(session, provenance, f"filter-{i}", area_m2=area, is_franchise=franchise)
        for identity, distance in [
            ("inside", 499),
            ("boundary", 500),
            ("epsilon-outside", 500.001),
            ("outside", 501),
        ]:
            store(session, provenance, identity, distance)
    for radius, month in product([300, 500, 1000], ["2020-01", "2026-11"]):
        matching(snapshot_client, radius=radius, as_of=month)
    for area in ["all", "lt33", "33to66", "66to99", "gte99"]:
        for ua, uf in product([False, True], repeat=2):
            matching(
                snapshot_client,
                area=area,
                franchise="franchise",
                include_unknown_area=str(ua).lower(),
                include_unknown_franchise=str(uf).lower(),
            )
    matching(snapshot_client, franchise="independent", include_unknown="false")
    rows = matching(snapshot_client)["data"]["stores"]
    ids = {r["license_no"] for r in rows}
    assert {"inside", "boundary"} <= ids and not {"epsilon-outside", "outside"} & ids
    empty = matching(snapshot_client, lat=0, lng=0)["data"]
    assert (
        empty["total_at_as_of"]
        == empty["still_open"]
        == empty["closed_since"]
        == empty["other"]
        == 0
    )
    assert empty["stores"] == [] and "0곳" in empty["summary_text"]


def test_same_management_number_different_sources_are_two_rows(
    snapshot_db: TemporaryDatabase,
    snapshot_client: TestClient,
) -> None:
    with Session(snapshot_db.engine) as session, session.begin():
        for source in ["general_restaurant", "rest_cafe"]:
            provenance = batch(session, source=source)
            store(session, provenance, "same", category="cafe", sub_category="cafe")
    result = matching(snapshot_client, category="cafe")["data"]
    assert result["total_at_as_of"] == result["still_open"] == 2
    assert {r["source"] for r in result["stores"]} == {"general_restaurant", "rest_cafe"}


def test_range_limits_empty_category_and_global_failure(
    snapshot_db: TemporaryDatabase,
    snapshot_client: TestClient,
) -> None:
    with Session(snapshot_db.engine) as session, session.begin():
        provenance = batch(session)
        store(session, provenance, "valid")
    matching(snapshot_client, category="cafe", as_of="2026-11")
    for params in [
        {"category": "cafe", "as_of": "2020-01"},
        {"as_of": "2019-12"},
        {"as_of": "2026-12"},
    ]:
        r = snapshot_client.get("/api/stores/snapshot", params={**PARAMS, **params})
        assert r.status_code == 422 and r.json()["error"]["code"] == "AS_OF_OUT_OF_RANGE"
    with Session(snapshot_db.engine) as session, session.begin():
        bad = batch(session, source="rest_cafe", data_updated_at=None)
        store(session, bad, "bad", category="cafe", sub_category="cafe")
    r = snapshot_client.get("/api/stores/snapshot", params={**PARAMS, "as_of": "2020-01"})
    assert r.status_code == 500 and r.json()["error"]["code"] == "INTERNAL_ERROR"
    assert r.json()["meta"] == {} and r.headers["cache-control"] == "no-store"
