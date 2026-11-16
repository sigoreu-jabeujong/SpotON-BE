"""All-status license history at an explicit location; legacy/AI cohorts stay unchanged."""

from datetime import date
from typing import Literal

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from app.models import Store, StoreImportBatch
from app.schemas.common import ApiResponse
from app.schemas.location_history import (
    POLICY,
    HistorySelection,
    LocationHistory,
    LocationHistoryQuery,
    LocationHistoryStore,
)
from app.schemas.stores import HistoryQuery
from app.services.analysis_v2 import stores as enrich_stores
from app.services.store_history import get_history, operating_period
from etl.address.floor_unit import parse_floor_unit

LIMITATIONS = ["address_scope_not_physical_building", "other_lot_records_not_searched"]


def compare_detail(requested: str, stored: str | None, level: str | None, scope: str) -> str:
    left, right = parse_floor_unit(requested).value, parse_floor_unit(stored).value
    assert left is not None and left.floor
    if level not in {"same_spot", "same_building"} or right is None or not right.floor:
        return "unresolved"
    if left.floor != right.floor:
        return "floor"
    if scope == "unit":
        if not right.unit:
            return "unresolved"
        if left.unit != right.unit:
            return "unit"
    return "match"


def get_location_history(
    session: Session | None, query: LocationHistoryQuery
) -> ApiResponse[LocationHistory]:
    detail = parse_floor_unit(query.floor_unit).value
    assert detail is not None and detail.floor
    selection = HistorySelection(
        building_key=query.building_key,
        floor=detail.floor,
        unit=detail.unit,
        scope=query.scope,
        identity_requirement=query.identity_requirement,
        unit_ignored=query.scope == "floor" and detail.unit is not None,
    )
    if query.identity_requirement == "verified_building":
        return ApiResponse(
            data=LocationHistory(
                selection=selection,
                result_status="pending_identity",
                location_coverage="not_evaluated",
                total=0,
                open_count=0,
                closed_count=0,
                other_count=0,
                dated_closure_count=0,
                undated_closure_count=0,
                unresolved_count=0,
                excluded_counts={"floor": 0, "unit": 0},
                stores=[],
                scope_limitations=["physical_building_evidence_not_verified"],
            ),
            meta={"history_policy_version": POLICY, "building_mapping_version": None},
        )
    assert session is not None
    original = get_history(
        session,
        HistoryQuery(
            building_key=query.building_key, floor_unit=query.floor_unit, category=query.category
        ),
    )
    assert original.data is not None
    excluded: dict[Literal["floor", "unit"], int] = {"floor": 0, "unit": 0}
    unresolved = 0
    selected = original.data.stores
    keys = [(row.source, row.license_no) for row in selected]
    raw = (
        {
            (s.source, s.license_no): s
            for s in session.scalars(
                select(Store).where(tuple_(Store.source, Store.license_no).in_(keys))
            )
        }
        if keys
        else {}
    )
    batch_ids = {s.batch_id for s in raw.values() if s.batch_id is not None}
    batches = (
        {
            b.batch_id: b
            for b in session.scalars(
                select(StoreImportBatch).where(StoreImportBatch.batch_id.in_(batch_ids))
            )
        }
        if batch_ids
        else {}
    )
    accepted = []
    closure_status: dict[tuple[str, str], Literal["dated", "undated", "not_applicable"]] = {}
    for row in selected:
        source = raw.get((row.source, row.license_no))
        if source is None:
            raise ValueError("location_history_source_missing")
        comparison = compare_detail(
            query.floor_unit, source.floor_unit, source.location_level, query.scope
        )
        if comparison == "unresolved":
            unresolved += 1
            continue
        if comparison in {"floor", "unit"}:
            excluded["floor" if comparison == "floor" else "unit"] += 1
            continue
        batch = batches.get(source.batch_id) if source.batch_id is not None else None
        if batch is not None and batch.source != source.source:
            batch = None
        reference = batch.data_updated_at if batch else None
        months, reason, opened, closed = operating_period(source, reference, batch)
        quality: Literal["dated", "undated", "not_applicable"] = "not_applicable"
        if row.store_status == "closed":
            # An unknown opening date does not erase a valid closure date.
            if closed is None or reference is None or closed > reference:
                closed = None
            if opened is not None and closed is not None and closed < opened:
                closed = None
            if closed is None and months is not None:
                months = None
                reason = "missing_source_date" if reference is None else "invalid_close_date"
            quality = "dated" if closed is not None else "undated"
        else:
            # Open durations use the source batch date, never an invented closure.
            closed = None
        closure_status[(row.source, row.license_no)] = quality
        accepted.append(
            row.model_copy(
                update={
                    "open_date": opened,
                    "close_date": closed,
                    "operating_months": months,
                    "operating_period_status": "fact" if months is not None else "no_data",
                    "operating_period_reason": reason,
                }
            )
        )
    rows = [
        LocationHistoryStore.model_validate(
            {**s.model_dump(), "closure_date_status": closure_status[(s.source, s.license_no)]}
        )
        for s in enrich_stores(accepted)
    ]
    rows.sort(
        key=lambda s: (
            s.open_date is None,
            -(s.open_date or date.min).toordinal(),
            s.source,
            s.license_no,
        )
    )
    meta = dict(original.meta)
    version = meta.get("data_version")
    if isinstance(version, dict):
        meta["data_version"] = {**version, "rule_version": POLICY}
    meta.update(
        {
            "history_policy_version": POLICY,
            "building_mapping_version": None,
            "date_basis": "per_store_source_batch",
            "denominator": len(rows),
        }
    )
    dated_count = sum(s.closure_date_status == "dated" for s in rows)
    return ApiResponse(
        data=LocationHistory(
            selection=selection,
            result_status="matched" if rows else "no_data",
            location_coverage="partial" if unresolved else "complete",
            total=len(rows),
            open_count=sum(s.current_status == "open" for s in rows),
            closed_count=sum(s.current_status == "closed" for s in rows),
            other_count=sum(s.current_status == "other" for s in rows),
            dated_closure_count=dated_count,
            undated_closure_count=sum(s.closure_date_status == "undated" for s in rows),
            unresolved_count=unresolved,
            excluded_counts=excluded,
            scope_limitations=LIMITATIONS,
            stores=rows,
        ),
        meta=meta,
    )
