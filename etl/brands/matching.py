"""One conservative classification rule shared by diagnostics and persisted evidence."""

from collections import Counter, defaultdict
from collections.abc import Mapping
from typing import Any

from etl.brands.catalog import Brand, Catalog, normalize_name

PARTITIONS = (
    "existing_classification",
    "missing_name",
    "weak_name",
    "repeated_brand_id",
    "ambiguous_name",
    "non_food_name",
    "exact_name_candidate",
    "no_exact_candidate",
)


class Matcher:
    def __init__(self, catalog: Catalog) -> None:
        self.names: dict[str, list[Brand]] = defaultdict(list)
        for item in catalog.rows:
            self.names[item.normalized_name].append(item)
        counts = Counter(item.management_no for item in catalog.rows)
        self.repeated_names = {
            item.normalized_name for item in catalog.rows if counts[item.management_no] > 1
        }

    def classify(self, row: Mapping[Any, Any]) -> tuple[str, Brand | None]:
        if row["is_franchise"] is not None or row["brand_id"] is not None:
            return "existing_classification", None
        name = normalize_name(row["name"]) if row["name"] is not None else ""
        candidates = self.names.get(name, [])
        if not name:
            return "missing_name", None
        if sum(c.isalnum() for c in name) < 3 or not any(c.isalpha() for c in name):
            return "weak_name", None
        if name in self.repeated_names:
            return "repeated_brand_id", None
        if len(candidates) > 1:
            return "ambiguous_name", None
        if not candidates:
            return "no_exact_candidate", None
        if candidates[0].industry != "외식":
            return "non_food_name", None
        return "exact_name_candidate", candidates[0]
