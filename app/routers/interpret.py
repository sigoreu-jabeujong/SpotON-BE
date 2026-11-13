import json
from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute

from app.core.errors import AppError
from app.core.exception_handlers import log_unhandled_error
from app.db.dependencies import NO_STORE
from app.schemas.common import ApiResponse, ErrorCode
from app.schemas.interpret import InterpretRequest, RiskInterpretation
from app.schemas.responses import VALIDATION_ERROR_RESPONSES
from app.services.risk_interpret import interpret_risk

MAX_BODY_BYTES = 16384


class InterpretRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handle(request: Request) -> Response:
            code = ErrorCode.INTERNAL_ERROR
            try:
                response = await original(request)
                response.headers.update(NO_STORE)
                return response
            except RequestValidationError:
                code = ErrorCode.INVALID_PARAM
            except AppError:
                raise
            except Exception as exc:
                log_unhandled_error(exc)
            raise AppError(code, headers=NO_STORE)

        return handle


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def no_constant(_value: str) -> None:
    raise ValueError("invalid JSON constant")


async def strict_body(request: Request) -> None:
    body = await request.body()
    if request.query_params or len(body) > MAX_BODY_BYTES:
        raise AppError(ErrorCode.INVALID_PARAM, headers=NO_STORE)
    try:
        json.loads(body, object_pairs_hook=unique_object, parse_constant=no_constant)
    except (ValueError, UnicodeError, RecursionError):
        raise AppError(ErrorCode.INVALID_PARAM, headers=NO_STORE) from None


router = APIRouter(tags=["risk"], route_class=InterpretRoute)


@router.post(
    "/risk/interpret",
    response_model=ApiResponse[RiskInterpretation],
    responses=VALIDATION_ERROR_RESPONSES,
    dependencies=[Depends(strict_body)],
)
async def interpret(
    request: Request, body: InterpretRequest, response: Response
) -> ApiResponse[RiskInterpretation]:
    response.headers.update(NO_STORE)
    return await interpret_risk(request.app.state.interpretation, body.query, body.history_query())
