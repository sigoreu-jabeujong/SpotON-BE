from copy import deepcopy
from uuid import UUID

import pytest

from app.core.errors import AppError
from app.schemas.franchise import ESTIMATE_LIMIT, BrandDataVersion, EstimatedClassification
from tests.ai.test_context import prepare, query, response


def estimated_response():
    q = query(franchise="franchise", include_unknown_franchise=False)
    result = response(q)
    result.meta["franchise_classification"] = EstimatedClassification(
        reference_year=2025
    ).model_dump(mode="json")
    result.meta["data_version"]["brand_mapping"] = BrandDataVersion(
        catalog_version_id=UUID(int=1),
        mapping_run_id=UUID(int=2),
        input_sha256="a" * 64,
        content_sha256="b" * 64,
        store_input_sha256="c" * 64,
        catalog_rule="ftc-brand-catalog-exact-name-v2",
        rule_version="ftc-name-exact-estimate-v1",
        reference_year=2025,
    ).model_dump(mode="json")
    result.meta["limitations"].append(ESTIMATE_LIMIT)
    return q, result


def test_estimate_is_typed_and_no_private_provenance_reaches_outbound(monkeypatch):
    q, result = estimated_response()
    p = prepare(monkeypatch, q, result)
    data = p.json_context()
    assert data["franchise_classification"] == "estimate"
    assert data["franchise_reference_year"] == 2025
    assert data["franchise_basis"] == "reference_catalog_name_match"
    assert ESTIMATE_LIMIT in data["methodology"]["limitations"]
    for token in (str(UUID(int=1)), str(UUID(int=2)), "input_sha256", "management_no", "brand_id"):
        assert token not in str(data)


@pytest.mark.parametrize(
    "change",
    [
        "status",
        "source",
        "year",
        "extra",
        "missing_version",
        "pending_version",
        "invalid_hash",
        "invalid_rule",
        "missing_limit",
    ],
)
def test_malformed_classification_or_version_is_safe_500(monkeypatch, change):
    q, result = estimated_response()
    classification = result.meta["franchise_classification"]
    version = result.meta["data_version"]["brand_mapping"]
    if change == "status":
        classification["status"] = "fact"
    elif change == "source":
        classification["source"] = ["R5"]
    elif change == "year":
        version["reference_year"] = 2024
    elif change == "extra":
        classification["name"] = "PRIVATE_CANARY"
    elif change == "missing_version":
        result.meta["data_version"].pop("brand_mapping")
    elif change == "pending_version":
        result.meta["franchise_classification"] = dict(
            status="pending", reason="brand_mapping_blocked"
        )
    elif change == "invalid_hash":
        version["input_sha256"] = "PRIVATE_CANARY"
    elif change == "invalid_rule":
        version["rule_version"] = "PRIVATE_CANARY"
    elif change == "missing_limit":
        result.meta["limitations"].remove(ESTIMATE_LIMIT)
    with pytest.raises(AppError) as error:
        prepare(monkeypatch, q, result)
    assert error.value.headers == {"Cache-Control": "no-store"}
    assert "PRIVATE_CANARY" not in str(error.value)


def test_same_counts_and_context_different_run_has_different_internal_hash(monkeypatch):
    q, result = estimated_response()
    first = prepare(monkeypatch, q, result)
    another = deepcopy(result)
    another.meta["data_version"]["brand_mapping"]["mapping_run_id"] = str(UUID(int=3))
    second = prepare(monkeypatch, q, another)
    assert first.context_hash == second.context_hash
    assert first.data_version_hash != second.data_version_hash
