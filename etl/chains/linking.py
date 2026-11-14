import calendar
import re
from collections import defaultdict
from collections.abc import Mapping
from datetime import date
from typing import Any

from etl.address.building_key import parse_jibun_address
from etl.address.floor_unit import FloorUnitFailure, parse_floor_unit
from etl.brands.catalog import normalize_name
from etl.chains.matching import ChainMatcher, Decision
from etl.chains.semas import Outlet, Snapshot

_ROAD = re.compile(
    r"^(?:서울특별시|서울시|서울)\s+([가-힣]+구)\s+"
    r"([가-힣a-z0-9·.]+(?:대로|로|길))\s+([0-9]{1,4})(?:-([0-9]{1,4}))?(?=$|[ ,(])"
)


def address_keys(jibun: str | None, road: str | None, building_key: str | None = None) -> set[str]:
    keys = set()
    if building_key:
        keys.add("lot:" + building_key)
    else:
        parsed = parse_jibun_address(jibun)
        if parsed.lot:
            keys.add("lot:" + parsed.lot.key)
    if road:
        match = _ROAD.match(normalize_name(road))
        if match:
            gu, street, main, sub = match.groups()
            keys.add(f"road:{gu}:{street}:{int(main)}:{int(sub or 0)}")
    return keys


def eligible(row: Mapping[str, Any], month: str) -> bool:
    opened = row.get("open_date")
    year, number = int(month[:4]), int(month[4:])
    end = date(year, number, calendar.monthrange(year, number)[1])
    return (
        row.get("status") == "open"
        and row.get("close_date") is None
        and not row.get("date_flag")
        and row.get("is_temporary") is not True
        and type(opened) is date
        and date(1960, 1, 1) <= opened <= end
    )


def _details(outlet: Outlet) -> str:
    floor = outlet.floor
    if re.fullmatch(r"[1-9][0-9]{0,2}", floor):
        floor += "층"
    elif re.fullmatch(r"-[1-9][0-9]{0,2}", floor):
        floor = "B" + floor[1:]
    unit = outlet.unit
    if unit and not unit.endswith("호"):
        unit += "호"
    return " ".join(v for v in (floor, unit) if v)


def compatible_details(row: Mapping[str, Any], outlet: Outlet) -> bool:
    left_text = row.get("floor_unit") or row.get("address_road") or row.get("address_jibun")
    right_text = _details(outlet)
    left, right = parse_floor_unit(left_text), parse_floor_unit(right_text)
    if left.failure in {FloorUnitFailure.AMBIGUOUS, FloorUnitFailure.INVALID}:
        return False
    # Explicit but unparseable/ambiguous provider detail must not become "no contradiction".
    if right_text and right.value is None:
        return False
    if left.value is not None and right.value is not None:
        for a, b in ((left.value.floor, right.value.floor), (left.value.unit, right.value.unit)):
            if a is not None and b is not None and a != b:
                return False
    return True


class OutletIndex:
    def __init__(self, snapshot: Snapshot, matcher: ChainMatcher) -> None:
        self.snapshot = snapshot
        self.matcher = matcher
        self.by_address: dict[str, dict[str, tuple[Outlet, Decision]]] = defaultdict(dict)
        for outlet in snapshot.rows:
            separate = f"{outlet.name} {outlet.branch}" if outlet.branch else outlet.name
            decision = matcher.classify(separate)
            if decision.status != "estimated":
                decision = matcher.classify(outlet.name)
            if decision.status != "estimated":
                continue
            if decision.brand is None or not matcher.branch_words_allowed(
                outlet.branch, decision.brand.key
            ):
                continue
            for key in address_keys(outlet.jibun, outlet.road):
                self.by_address[key][outlet.source_id] = outlet, decision

    def corroborate(
        self, row: Mapping[str, Any], local_counts: Mapping[str, int]
    ) -> tuple[Decision | None, str | None]:
        if not eligible(row, self.snapshot.reference_month):
            return None, None
        keys = address_keys(
            row.get("address_jibun"), row.get("address_road"), row.get("building_key")
        )
        candidates: dict[str, tuple[Outlet, Decision]] = {}
        matching_keys = keys & self.by_address.keys()
        for key in matching_keys:
            candidates.update(self.by_address[key])
        if not candidates:
            return None, None
        name = row.get("name")
        possible = self.matcher.prefix_candidates(name)
        # An exact catalog alias may be corroborated by this specific provider outlet's
        # separate branch and address. This does not enable catalog-wide suffix matching.
        current_name = normalize_name(name or "")
        for _, candidate in candidates.values():
            brand = candidate.brand
            if brand is not None and brand.origin == "ftc_exact":
                if any(current_name.startswith(normalize_name(alias)) for alias in brand.aliases):
                    possible.add(brand.key)
        if not possible:
            return Decision("unknown", None, "address_only_candidate"), None
        if len(candidates) != 1 or any(local_counts.get(key, 0) != 1 for key in matching_keys):
            return Decision("unknown", None, "multiple_outlets_or_licenses"), None
        outlet, decision = next(iter(candidates.values()))
        brand = decision.brand
        if brand is None or brand.key not in possible or not compatible_details(row, outlet):
            return None, None

        # Even a matching building and prefix are insufficient: require the same complete
        # approved alias+provider branch, allowing spacing/branch parentheses only here.
        def compact(value: str) -> str:
            return normalize_name(value).replace(" ", "").replace("(", "").replace(")", "")

        current = compact(self.matcher.stripped(normalize_name(name or ""), brand))
        allowed = {compact(outlet.name), compact(outlet.name + outlet.branch)}
        allowed.update(compact(alias + outlet.branch) for alias in brand.aliases if outlet.branch)
        if current not in allowed:
            return None, None
        return Decision("estimated", brand, "semas_address_corroborated"), outlet.source_id
