from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

REMOVED = {
    "franchise": "all",
    "include_unknown_franchise": "true",
    "brand_scope": "all",
    "brand_unknown": "include",
    "brand_evidence": "include_estimates",
    "brand_time_basis": "observed_record",
    "operation_type": "any",
}


@pytest.mark.parametrize("prefix", ["/api", "/api/v2"])
@pytest.mark.parametrize(
    "path", ["/stores/nearby", "/stores/snapshot", "/market/activity", "/risk"]
)
@pytest.mark.parametrize("field,value", REMOVED.items())
def test_removed_filters_rejected_before_database(prefix, path, field, value):
    app = create_app(Settings(_env_file=None))
    app.state.database.get_engine = Mock(side_effect=AssertionError("must not connect"))
    with TestClient(app) as client:
        response = client.get(
            prefix + path,
            params={"lat": 37.5, "lng": 127, "category": "cafe", "as_of": "2026-10", field: value},
        )
    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"
    app.state.database.get_engine.assert_not_called()


def test_brand_status_removed_and_openapi_has_no_affiliation_contract():
    app = create_app(Settings(_env_file=None))
    app.state.database.get_engine = Mock(side_effect=AssertionError("must not connect"))
    with TestClient(app) as client:
        assert client.get("/api/v2/brands/status").status_code == 404
    spec = app.openapi()
    assert not any("brand" in path for path in spec["paths"])
    for methods in spec["paths"].values():
        for operation in methods.values():
            if isinstance(operation, dict):
                assert not (set(REMOVED) & {p["name"] for p in operation.get("parameters", [])})
    for schema in spec["components"]["schemas"].values():
        assert not (
            set(REMOVED) | {"brand", "operation", "franchise_basis", "franchise_reference_year"}
        ) & set(schema.get("properties", {}))
    app.state.database.get_engine.assert_not_called()


def test_v2_does_not_reintroduce_the_legacy_area_alias():
    from pydantic import ValidationError

    from app.schemas.analysis_v2 import AnalysisRiskQuery

    with pytest.raises(ValidationError):
        AnalysisRiskQuery(lat=37.5, lng=127, category="cafe", include_unknown=True)
