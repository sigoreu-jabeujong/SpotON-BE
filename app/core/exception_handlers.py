import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.responses import Response

from app.core.errors import AppError, error_response
from app.schemas.common import ErrorCode

PROTOCOL_HEADERS = frozenset({"allow", "www-authenticate", "retry-after"})
logger = logging.getLogger(__name__)


async def handle_app_error(_request: Request, exc: Exception) -> Response:
    assert isinstance(exc, AppError)
    return error_response(exc.code, headers=exc.headers)


async def handle_validation_error(_request: Request, _exc: Exception) -> Response:
    return error_response(ErrorCode.INVALID_PARAM)


async def handle_http_error(_request: Request, exc: Exception) -> Response:
    assert isinstance(exc, HTTPException)
    headers = {
        name: value
        for name, value in (exc.headers or {}).items()
        if name.lower() in PROTOCOL_HEADERS
    }
    if exc.status_code in {204, 304}:
        return Response(status_code=exc.status_code, headers=headers)
    code = ErrorCode.INTERNAL_ERROR if exc.status_code >= 500 else ErrorCode.INVALID_PARAM
    return error_response(code, status_code=exc.status_code, headers=headers)


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, handle_app_error)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(HTTPException, handle_http_error)
    app.add_exception_handler(Exception, handle_unhandled_error)


async def handle_unhandled_error(_request: Request, exc: Exception) -> Response:
    log_unhandled_error(exc)
    return error_response(ErrorCode.INTERNAL_ERROR)


def log_unhandled_error(exc: Exception) -> None:
    logger.error("unhandled_error type=%s", type(exc).__name__)
