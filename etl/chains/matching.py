import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Literal

from etl.brands.catalog import normalize_name
from etl.chains.registry import BrandSpec

Status = Literal["estimated", "unknown", "conflict"]
_BRANCH = re.compile(r"[가-힣a-z0-9][가-힣a-z0-9 ._-]{0,39}(?:지점|점)")
_DENIED = (
    "집",
    "비빔밥",
    "옆",
    "맞은편",
    "앞",
    "분식",
    "식당",
    "전문",
    "커피숍",
    "판매",
    "죽집",
    "비빔밥집",
    "카레집",
    "맛집",
    "호프",
    "치킨",
    "메뉴",
    "대리점",
)


@dataclass(frozen=True, slots=True, repr=False)
class Decision:
    status: Status
    brand: BrandSpec | None
    reason: str


class ChainMatcher:
    def __init__(self, brands: tuple[BrandSpec, ...]) -> None:
        self.exact: dict[str, set[int]] = defaultdict(set)
        self.brands = brands
        self.patterns: list[tuple[str, int]] = []
        for i, brand in enumerate(brands):
            for alias in brand.aliases:
                norm = normalize_name(alias)
                self.exact[norm].add(i)
                if brand.branch_patterns:
                    self.patterns.append((norm, i))
        self.patterns.sort(key=lambda pair: (-len(pair[0]), pair[0], pair[1]))

    def stripped(self, value: str, brand: BrandSpec) -> str:
        for prefix in sorted(brand.legal_prefixes, key=len, reverse=True):
            norm = normalize_name(prefix)
            if value.startswith(norm):
                return value[len(norm) :].lstrip()
        return value

    def prefix_candidates(self, name: str | None) -> set[str]:
        if not name or len(name) > 255:
            return set()
        value = normalize_name(name)
        return {
            self.brands[i].key
            for alias, i in self.patterns
            if self.stripped(value, self.brands[i]).startswith(alias)
        }

    def branch_words_allowed(self, value: str, brand_key: str) -> bool:
        normalized = normalize_name(value)
        return not any(word in normalized for word in _DENIED) and not any(
            alias in normalized for alias, i in self.patterns if self.brands[i].key != brand_key
        )

    def classify(self, name: str | None) -> Decision:
        if not name or len(name) > 255 or any(ord(c) < 32 for c in name):
            return Decision("unknown", None, "invalid_or_missing_name")
        value = normalize_name(name)
        hits = set(self.exact.get(value, ()))
        reason = "approved_alias_name_estimate"
        pending_short = False
        # Catalog aliases are exact-only. Prefix scanning is limited to reviewed seeds.
        for alias, i in self.patterns:
            brand = self.brands[i]
            current = self.stripped(value, brand)
            if current == alias:
                hits.add(i)
                continue
            if not current.startswith(alias):
                continue
            suffix = current[len(alias) :]
            separator = suffix.startswith((" ", "(", "-"))
            if sum(c.isalnum() for c in alias) < 3 and not separator:
                pending_short = True
                continue
            suffix = suffix.strip().removeprefix("-").strip()
            if suffix.startswith("(") and suffix.endswith(")"):
                suffix = suffix[1:-1].strip()
            if not _BRANCH.fullmatch(suffix) or not self.branch_words_allowed(suffix, brand.key):
                continue
            hits.add(i)
        if len(hits) > 1:
            collision = {self.brands[i].origin for i in hits} == {"reviewed_seed", "ftc_exact"}
            return Decision(
                "conflict", None, "seed_catalog_name_collision" if collision else "ambiguous_brand"
            )
        if hits:
            brand = self.brands[hits.pop()]
            if brand.origin == "ftc_exact":
                reason = "catalog_exact_name_estimate"
            return Decision("estimated", brand, reason)
        return Decision(
            "unknown",
            None,
            "short_alias_no_separator" if pending_short else "no_approved_name_match",
        )
