from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from fastapi.routing import APIRoute
from pydantic import ValidationError

from app.core.errors import AppError
from app.core.exception_handlers import log_unhandled_error
from app.db.dependencies import NO_STORE
from app.schemas.common import ApiResponse, ErrorCode
from app.schemas.responses import VALIDATION_ERROR_RESPONSES
from app.schemas.support import SEOUL_DISTRICTS, SupportLinks, SupportLinksQuery
from app.services.support_links import get_support_links


class SupportRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handle(request: Request) -> Response:
            try:
                response = await original(request)
                response.headers.update(NO_STORE)
                return response
            except AppError:
                raise
            except Exception as exc:
                log_unhandled_error(exc)
            raise AppError(ErrorCode.INTERNAL_ERROR, headers=NO_STORE)

        return handle


def support_query(request: Request) -> SupportLinksQuery:
    params = request.query_params
    if any(
        name not in SupportLinksQuery.model_fields or len(params.getlist(name)) != 1
        for name in params
    ):
        raise AppError(ErrorCode.INVALID_PARAM, headers=NO_STORE)
    try:
        return SupportLinksQuery.model_validate(dict(params))
    except ValidationError:
        raise AppError(ErrorCode.INVALID_PARAM, headers=NO_STORE) from None


router = APIRouter(tags=["support"], route_class=SupportRoute)


@router.get(
    "/support-links",
    response_model=ApiResponse[SupportLinks],
    responses=VALIDATION_ERROR_RESPONSES,
    summary="공식 상담·지원기관 공통 링크",
    openapi_extra={
        "parameters": [
            {
                "name": "sigungu",
                "in": "query",
                "required": False,
                "schema": {"type": "string", "enum": sorted(SEOUL_DISTRICTS)},
            },
            {
                "name": "category",
                "in": "query",
                "required": False,
                "schema": {"type": "string", "enum": ["cafe", "restaurant"]},
            },
        ]
    },
)
def support_links(
    query: Annotated[SupportLinksQuery, Depends(support_query)],
) -> ApiResponse[SupportLinks]:
    """Return the general catalog after validation; no targeted candidates exist yet."""
    return get_support_links()
