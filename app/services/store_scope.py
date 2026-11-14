"""Versioned analysis scope; source records and provenance remain unchanged."""

import re

from sqlalchemy import and_, literal_column, or_
from sqlalchemy.sql.elements import ColumnClause

from app.models import Store
from app.schemas.common import ApiMeta

NAME_EXCLUSION_VERSION = "store-name-keywords-v1"
NAME_EXCLUSION_LIMITATION = "restaurant_name_keywords_may_exclude_valid_stores"
NAME_EXCLUSION_KEYWORDS = (
    "치킨",
    "통닭",
    "호프",
    "주점",
    "포차",
    "맥주",
    "분식",
    "김밥",
    "떡볶",
    "피자",
    "카페",
    "커피",
    "cafe",
    "coffee",
    "베이커리",
    "제과",
    "빵집",
    "bakery",
)
_ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


def excluded_by_name(category: str | None, name: str | None) -> bool:
    """Reference for diagnostics; SQL applies the same literal substring policy."""
    if category != "restaurant" or not name:
        return False
    return any(keyword in name.translate(_ASCII_LOWER) for keyword in NAME_EXCLUSION_KEYWORDS)


def _pattern(word: str) -> str:
    # Explicit ASCII classes avoid locale-dependent Unicode case folding in SQL/Python.
    return "".join(f"[{c}{c.upper()}]" if "a" <= c <= "z" else re.escape(c) for c in word)


NAME_EXCLUSION_PATTERN = "(" + "|".join(map(_pattern, NAME_EXCLUSION_KEYWORDS)) + ")"
_PATTERN_LITERAL: ColumnClause[str] = literal_column(
    "'" + NAME_EXCLUSION_PATTERN.replace("'", "''") + "'"
)
# These are trusted policy constants, never request values. Keep them unparameterized so
# prepared generic plans can prove the matching operational partial-index predicate.
NAME_SCOPE = or_(
    Store.category != literal_column("'restaurant'"),
    Store.name.is_(None),
    Store.name == literal_column("''"),
    Store.name.bool_op("!~")(_PATTERN_LITERAL),
)
SOURCE_SUPPORTED_STORES = and_(
    Store.deleted_at.is_(None),
    Store.source.in_(("general_restaurant", "rest_cafe")),
    Store.category_review_flag.is_not(True),
    or_(
        and_(Store.category == "cafe", Store.sub_category == "cafe"),
        and_(
            Store.category == "restaurant",
            Store.sub_category.in_(("korean", "chinese", "japanese", "western")),
        ),
    ),
)
SUPPORTED_STORES = and_(SOURCE_SUPPORTED_STORES, NAME_SCOPE)


def name_exclusion_meta() -> ApiMeta:
    return {
        "version": NAME_EXCLUSION_VERSION,
        "basis": "store_name_keyword",
        "applies_to": "restaurant",
        "match": "ascii_case_insensitive_substring",
        "keywords": list(NAME_EXCLUSION_KEYWORDS),
    }
