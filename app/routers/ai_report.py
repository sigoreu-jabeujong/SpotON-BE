"""Strict request-only endpoint; no provider calls from the browser."""

import asyncio
from typing import cast

from fastapi import APIRouter, Depends, Request, Response

from app.core.errors import AppError
from app.db.dependencies import NO_STORE
from app.routers.interpret import InterpretRoute, strict_body
from app.schemas.ai_report import AiSectionsReport, ReportRequest
from app.schemas.common import ApiResponse, ErrorCode
from app.schemas.responses import VALIDATION_ERROR_RESPONSES
from app.services.ai_report import ReportResources

router = APIRouter(
    tags=["AI sections"], responses=VALIDATION_ERROR_RESPONSES, route_class=InterpretRoute
)


async def report_body(request: Request) -> None:
    if len(await request.body()) > 16384:
        raise AppError(ErrorCode.INVALID_PARAM, headers=NO_STORE)
    await strict_body(request)


@router.post(
    "/risk/interpret/sections",
    response_model=ApiResponse[AiSectionsReport],
    dependencies=[Depends(report_body)],
)
async def report(
    request: Request, body: ReportRequest, response: Response
) -> ApiResponse[AiSectionsReport]:
    response.headers.update(NO_STORE)
    resources = cast(ReportResources, request.app.state.ai_report)
    task = asyncio.create_task(resources.generate(body))
    try:
        while not task.done():
            if await request.is_disconnected():
                task.cancel()
                raise AppError(ErrorCode.AI_UNAVAILABLE, headers=NO_STORE)
            await asyncio.wait({task}, timeout=0.25)
        return await task
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
