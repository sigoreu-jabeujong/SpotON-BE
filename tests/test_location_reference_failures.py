from unittest.mock import Mock

import pytest

from app.core.errors import AppError
from app.schemas.location_reference import LocationReferenceQuery
from app.services import location_reference as service


@pytest.mark.parametrize("period", ["", "202", "20250", "20255", "abcd1", "20254extra"])
def test_bad_quarter_raises_fixed_validation_instead_of_index_error(period):
    with pytest.raises(ValueError, match="^invalid source period$"):
        service._bounds(period)


def test_catalog_read_failure_is_fixed_application_error(monkeypatch):
    def broken(*args):
        raise FileNotFoundError("source-private-canary")

    monkeypatch.setattr(service, "_get_location_reference", broken)
    with pytest.raises(AppError) as failure:
        service.get_location_reference(
            Mock(), LocationReferenceQuery(lat=37.5, lng=127, category="cafe")
        )
    assert failure.value.headers == {"Cache-Control": "no-store"}
    assert "canary" not in str(failure.value)


def test_internal_error_is_in_openapi_contract(client):
    assert (
        "500"
        in client.get("/openapi.json").json()["paths"]["/api/v2/location-reference"]["get"][
            "responses"
        ]
    )
