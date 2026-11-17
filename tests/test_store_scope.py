"""Name policy contract, including deliberately accepted heuristic boundaries."""

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import get_args
from unittest.mock import Mock

import pytest
from sqlalchemy.dialects import postgresql

from app.ai import context as ai
from app.core.cache import CacheResources
from app.core.config import Settings
from app.core.errors import AppError
from app.services import risk_cache
from app.services.store_scope import (
    NAME_EXCLUSION_KEYWORDS,
    NAME_EXCLUSION_PATTERN,
    NAME_EXCLUSION_VERSION,
    NAME_SCOPE,
    excluded_by_name,
    name_exclusion_meta,
)
from tests.ai.context_helpers import history_row, query, response, use_history, use_risk


@pytest.mark.parametrize("keyword", NAME_EXCLUSION_KEYWORDS)
def test_each_substring_excludes_restaurants_only(keyword):
    for name in (keyword, keyword + "상점", "우리" + keyword, "우리" + keyword + "상점"):
        assert excluded_by_name("restaurant", name)
        assert not excluded_by_name("cafe", name)


@pytest.mark.parametrize(
    "name,excluded",
    [
        (None, False),
        ("", False),
        ("서울식당", False),
        ("카페 M", True),
        ("CaFe M", True),
        ("COFFEE", True),
        ("BaKeRy", True),
        ("치 킨", False),
        ("ＣＡＦＥ", False),
        ("baKery", False),
        (unicodedata.normalize("NFD", "치킨"), False),
    ],
)
def test_missing_names_ascii_case_and_normalization_boundaries(name, excluded):
    assert excluded_by_name("restaurant", name) is excluded


def test_fixed_sql_policy_has_no_bind_and_matches_operational_index():
    sql = NAME_SCOPE.compile(dialect=postgresql.dialect())
    assert not sql.params
    assert "!~" in str(sql) and NAME_EXCLUSION_PATTERN in str(sql)
    index = (Path(__file__).parents[1] / "docs/sql/render-free-risk-name-v1.sql").read_text(
        encoding="utf-8"
    )
    assert "OR name !~ '" + NAME_EXCLUSION_PATTERN + "'" in index
    assert name_exclusion_meta()["version"] == NAME_EXCLUSION_VERSION
    assert all(re.fullmatch(r"[가-힣a-z]+", word) for word in NAME_EXCLUSION_KEYWORDS)
    assert get_args(ai._DataVersion.model_fields["name_exclusion_version"].annotation) == (
        NAME_EXCLUSION_VERSION,
    )
    # A keyword edit must introduce a new policy generation, not silently reuse v1 caches.
    versions = {
        "store-name-keywords-v1": (
            "d381e51a4cca15c71c7e3cb94244325f42d1a40155af49d39d6c1a6d5069ad18"
        ),
    }
    assert (
        hashlib.sha256(NAME_EXCLUSION_PATTERN.encode()).hexdigest()
        == versions[NAME_EXCLUSION_VERSION]
    )


def test_risk_cache_does_not_reuse_another_policy_generation(monkeypatch):
    settings = Settings(_env_file=None)
    cache = CacheResources(settings)
    try:
        old = risk_cache.risk_key(cache, "same-snapshot", query(), settings, "same-rule")
        cache.risk.put(old, b"old-result")
        monkeypatch.setattr(risk_cache, "NAME_EXCLUSION_VERSION", "future-policy")
        new = risk_cache.risk_key(cache, "same-snapshot", query(), settings, "same-rule")
        assert new != old and cache.risk.get(new) is None
    finally:
        cache.close()


@pytest.mark.parametrize("version", [None, "legacy", "store-name-keywords-v2"])
def test_ai_rejects_missing_or_unrecognized_policy(version, monkeypatch):
    risk = response()
    if version is None:
        risk.meta["data_version"].pop("name_exclusion_version")
    else:
        risk.meta["data_version"]["name_exclusion_version"] = version
    use_risk(monkeypatch, ai, risk)
    with pytest.raises(AppError):
        ai.prepare_risk_interpretation(Mock(), query(), Settings(_env_file=None))


@pytest.mark.parametrize(
    "part", ["history", "activity", "metadata", "history_meta", "activity_meta"]
)
def test_ai_rejects_inconsistent_policy_and_hash_contains_version(part, monkeypatch):
    risk = response()
    _, activity = use_risk(monkeypatch, ai, risk)
    config = Settings(_env_file=None)
    prepared = ai.prepare_risk_interpretation(Mock(), query(), config)
    version = {**risk.meta["data_version"], "activity_rule_version": ai.ACTIVITY_RULE_VERSION}
    # This reconstruction asserts the actual cache identity contains the policy version.
    encoded = json.dumps(version, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert prepared.data_version_hash == hashlib.sha256(encoded.encode()).hexdigest()
    version.pop("name_exclusion_version")
    old = json.dumps(version, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert prepared.data_version_hash != hashlib.sha256(old.encode()).hexdigest()
    kwargs = {}
    if part == "activity_meta":
        activity.return_value.meta["name_exclusion"]["version"] = "old"
    elif part == "activity":
        activity.return_value.meta["data_version"]["name_exclusion_version"] = "old"
    elif part == "metadata":
        risk.meta["name_exclusion"]["version"] = "old"
    else:
        from tests.ai.context_helpers import history_query

        _, history = use_history(monkeypatch, ai, risk, [history_row()])
        if part == "history_meta":
            history.return_value.meta["name_exclusion"]["version"] = "old"
        else:
            history.return_value.meta["data_version"]["name_exclusion_version"] = "old"
        kwargs["history"] = history_query()
    with pytest.raises(AppError):
        ai.prepare_risk_interpretation(Mock(), query(), config, **kwargs)
