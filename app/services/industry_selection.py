"""Keep legacy source order separate from canonical projection order."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.schemas.location_reference import LocationReferenceQuery

INDUSTRIES = {
    "korean": ("CS100001", "한식음식점"),
    "chinese": ("CS100002", "중식음식점"),
    "japanese": ("CS100003", "일식음식점"),
    "western": ("CS100004", "양식음식점"),
    "cafe": ("CS100010", "커피-음료"),
}


@dataclass(frozen=True)
class IndustrySelection:
    source_order: tuple[tuple[str, str], ...]
    canonical_order: tuple[tuple[str, str], ...]


def effective_industries(query: "LocationReferenceQuery") -> IndustrySelection:
    chosen = query.sub_category or (
        ("cafe",) if query.category == "cafe" else ("korean", "chinese", "japanese", "western")
    )
    source = tuple(INDUSTRIES[sub] for sub in chosen)
    return IndustrySelection(source, tuple(sorted(source)))
