"""Exact road/jibun union in one read-only snapshot; legacy cohorts are unchanged."""

from collections import Counter
from datetime import date
from typing import Literal

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import CompoundSelect, Select

from app.models import Store, StoreImportBatch
from app.schemas.address_history import (
    AddressHistory,
    AddressHistoryQuery,
    AddressHistorySelection,
    AddressHistoryStore,
)
from app.schemas.common import ApiMeta, ApiResponse
from app.schemas.stores import HistoryStore
from app.services.address_context import AddressPair
from app.services.chain_api import stores as enrich_stores
from app.services.chains import ChainSelection
from app.services.store_history import operating_period
from app.services.store_scope import (
    SOURCE_SUPPORTED_STORES,
    SUPPORTED_STORES,
    name_exclusion_meta,
)
from etl.address.building_key import parse_jibun_address
from etl.address.floor_unit import FloorUnitFailure, parse_floor_unit
from etl.address.road_key import RULE, parse_road


def address_match(store: Store, pair: AddressPair) -> str:
    road = parse_road(store.address_road)
    lot = parse_jibun_address(store.address_jibun)
    if store.address_jibun and lot.lot is None:
        return "address_unresolved"
    lot_key = lot.lot.key if lot.lot else store.building_key
    if lot.lot and store.building_key and lot.lot.key != store.building_key:
        return "address_conflict"
    if pair.road_key and store.address_road and road is None:
        return "address_unresolved"
    road_match = pair.road_key is not None and road is not None and road.key == pair.road_key
    lot_match = lot_key == pair.building_key
    if (road_match and lot_key and not lot_match) or (
        lot_match and pair.road_key and road and not road_match
    ):
        return "address_conflict"
    if road_match and lot_match:
        return "both"
    if road_match:
        return "road"
    if lot_match:
        return "jibun"
    return "address_conflict"


def stored_detail(store: Store) -> str | None:
    inputs = [store.floor_unit, store.address_jibun]
    road = parse_road(store.address_road)
    if road:
        inputs.append(road.detail)
    if store.floor_unit and store.location_level not in {"same_spot", "same_building"}:
        return None
    floors: set[str] = set()
    units: set[str] = set()
    for value in inputs:
        result = parse_floor_unit(value)
        if result.value:
            detail = result.value
            if detail.floor:
                floors.add(detail.floor)
            if detail.unit:
                units.add(detail.unit)
        elif result.failure not in {FloorUnitFailure.EMPTY, FloorUnitFailure.NO_DETAIL}:
            return None
    if len(floors) != 1 or len(units) > 1:
        return None
    return " ".join([next(iter(floors)), *sorted(units)])


def get_address_history(
    session: Session, query: AddressHistoryQuery, pair: AddressPair
) -> ApiResponse[AddressHistory]:
    detail = parse_floor_unit(query.floor_unit).value
    scope: Literal["address", "floor", "unit"] = (
        "address" if detail is None else "unit" if detail.unit else "floor"
    )
    # Separate indexed branches, UNION removes duplicates before the shared source filter.
    lot_ids = select(Store.id).where(Store.building_key == pair.building_key)
    ids: Select[int] | CompoundSelect[int] = lot_ids
    if pair.road_key is not None:
        ids = lot_ids.union(
            select(Store.id).where(
                func.spoton_history_road_key_v1(Store.address_road) == pair.road_key
            )
        )
    candidates = list(session.scalars(select(Store).where(SUPPORTED_STORES, Store.id.in_(ids))))
    batches = list(
        session.scalars(
            select(StoreImportBatch).where(
                exists(
                    select(Store.id).where(
                        SOURCE_SUPPORTED_STORES,
                        Store.batch_id == StoreImportBatch.batch_id,
                        Store.source == StoreImportBatch.source,
                    )
                )
            )
        )
    )
    batch_map = {b.batch_id: b for b in batches}
    counts: Counter[str] = Counter()
    evidence: dict[tuple[str, str], str] = {}
    closure: dict[tuple[str, str], str] = {}
    accepted: list[HistoryStore] = []
    for store in candidates:
        match = address_match(store, pair)
        if match in {"address_conflict", "address_unresolved"}:
            counts[match] += 1
            continue
        actual = stored_detail(store)
        right = parse_floor_unit(actual).value
        if detail is not None:
            if right is None or right.floor is None:
                counts["detail_unresolved"] += 1
                continue
            if right.floor != detail.floor:
                counts["floor"] += 1
                continue
            if scope == "unit" and not right.unit:
                counts["detail_unresolved"] += 1
                continue
            if scope == "unit" and right.unit != detail.unit:
                counts["unit"] += 1
                continue
        batch = batch_map.get(store.batch_id) if store.batch_id else None
        if batch and batch.source != store.source:
            batch = None
        reference = batch.data_updated_at if batch else None
        months, reason, opened, closed = operating_period(store, reference, batch)
        status: Literal["open", "closed", "other"] = (
            "open" if store.status == "open" else "closed" if store.status == "closed" else "other"
        )
        quality = "not_applicable"
        if status == "closed":
            if reference is None or (closed and closed > reference):
                closed = None
            if opened and closed and closed < opened:
                closed = None
            if closed is None and months is not None:
                months, reason = None, "invalid_close_date"
            quality = "dated" if closed else "undated"
        else:
            closed = None
        accepted.append(
            HistoryStore(
                source=store.source,
                license_no=store.license_no,
                name=store.name,
                category=store.category,
                sub_category=store.sub_category,
                open_date=opened,
                close_date=closed,
                store_status=status,
                operating_months=months,
                operating_period_status="fact" if months is not None else "no_data",
                operating_period_reason=reason,
                franchise="unknown",
                floor_unit=actual,
                location_match="unverified",
            )
        )
        evidence[(store.source, store.license_no)] = match
        closure[(store.source, store.license_no)] = quality
    chain = ChainSelection.load(session)
    rows = [
        AddressHistoryStore.model_validate(
            {
                **s.model_dump(),
                "match_evidence": evidence[(s.source, s.license_no)],
                "history_scope": scope,
                "closure_date_status": closure[(s.source, s.license_no)],
            }
        )
        for s in enrich_stores(session, chain, accepted)
    ]
    rows.sort(
        key=lambda s: (
            s.open_date is None,
            -(s.open_date or date.min).toordinal(),
            s.source,
            s.license_no,
        )
    )
    status_counts = Counter(s.current_status for s in rows)
    reference = max((b.data_updated_at for b in batches if b.data_updated_at), default=None)
    meta: ApiMeta = {
        "source": ["R5", "R6"],
        "space": "point",
        "is_demo": False,
        "denominator": len(rows),
        "data_updated_at": reference.isoformat() if reference else None,
        "as_of": reference.isoformat() if reference else None,
        "collected_at": None,
        "collection_reason": "source_completion_time_not_recorded",
        "date_basis": "per_store_source_batch",
        "history_policy_version": RULE,
        "address_index_version": "spoton_history_road_key_v1",
        "name_exclusion": name_exclusion_meta(),
        "brand_classification": chain.meta(),
        "brand_counts_scope": "returned_location_history",
        "data_version": {
            "rule_version": RULE,
            "stores_batch_ids": [str(b.batch_id) for b in batches],
        },
    }
    return ApiResponse(
        data=AddressHistory(
            selection=AddressHistorySelection(
                building_key=pair.building_key,
                road_key=pair.road_key,
                scope=scope,
                floor=detail.floor if detail else None,
                unit=detail.unit if detail else None,
            ),
            result_status="matched" if rows else "no_data",
            location_coverage="partial"
            if sum(
                counts[k] for k in ("address_conflict", "address_unresolved", "detail_unresolved")
            )
            else "complete",
            total=len(rows),
            open_count=status_counts["open"],
            closed_count=status_counts["closed"],
            other_count=status_counts["other"],
            dated_closure_count=sum(s.closure_date_status == "dated" for s in rows),
            undated_closure_count=sum(s.closure_date_status == "undated" for s in rows),
            address_conflict_count=counts["address_conflict"],
            address_unresolved_count=counts["address_unresolved"],
            detail_unresolved_count=counts["detail_unresolved"],
            excluded_counts={"floor": counts["floor"], "unit": counts["unit"]},
            candidate_count=len(candidates),
            stores=rows,
        ),
        meta=meta,
    )
