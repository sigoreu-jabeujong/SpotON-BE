from app.schemas.common import ErrorResponse

ERROR_RESPONSES: dict[int | str, dict[str, object]] = {500: {"model": ErrorResponse}}
VALIDATION_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    **ERROR_RESPONSES,
    422: {"model": ErrorResponse},
}
GEOCODE_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    **VALIDATION_ERROR_RESPONSES,
    404: {"model": ErrorResponse},
    502: {"model": ErrorResponse},
}
