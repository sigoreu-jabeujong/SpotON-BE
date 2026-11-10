import json

import pytest
from pydantic import ValidationError

from app.core.errors import ERROR_SPECS, AppError, error_response
from app.schemas.common import ApiError, ApiResponse, ErrorCode, ErrorResponse


@pytest.mark.parametrize("data", [[], {}, 0, "", False, {"status": "ok"}])
def test_non_null_data_is_valid_even_when_empty(data: object) -> None:
    body = ApiResponse[object](data=data).model_dump(mode="json")
    assert body == {"data": data, "meta": {}, "error": None}


def test_error_response_has_required_error_and_null_data() -> None:
    body = ErrorResponse(error=ApiError(code=ErrorCode.INVALID_PARAM, message="invalid"))
    assert body.model_dump(mode="json") == {
        "data": None,
        "meta": {},
        "error": {"code": "INVALID_PARAM", "message": "invalid"},
    }
    assert "error" in ErrorResponse.model_json_schema()["required"]


@pytest.mark.parametrize(
    "payload",
    [
        {"data": None},
        {"data": {"status": "ok"}, "error": {"code": "INTERNAL_ERROR", "message": "invalid"}},
        {"data": {"status": "ok"}, "meta": None},
        {"data": {"status": "ok"}, "unexpected": True},
        {"data": None, "error": {"code": "UNKNOWN", "message": "invalid"}},
        {"data": None, "error": {"code": "INVALID_PARAM", "message": "invalid", "debug": True}},
    ],
)
def test_invalid_envelopes_are_rejected(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ApiResponse[object].model_validate(payload)


@pytest.mark.parametrize("code", list(ErrorCode))
def test_all_domain_codes_have_fixed_status_and_message(code: ErrorCode) -> None:
    assert set(ERROR_SPECS) == set(ErrorCode)
    response = error_response(code)
    status, message = ERROR_SPECS[code]
    assert response.status_code == status
    assert json.loads(bytes(response.body)) == {
        "data": None,
        "meta": {},
        "error": {"code": code.value, "message": message},
    }
    assert str(AppError(code)) == code.value


def test_meta_defaults_are_not_shared_between_responses() -> None:
    first = ApiResponse(data="first")
    second = ApiResponse(data="second")
    first.meta["source"] = ["sample"]
    assert second.meta == {}
