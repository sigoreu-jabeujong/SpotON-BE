from fastapi import APIRouter, Depends, Request, Response

from app.db.dependencies import NO_STORE
from app.routers.interpret import InterpretRoute, strict_body
from app.schemas.common import ApiResponse
from app.schemas.interpret import RiskInterpretation
from app.schemas.interpret_v2 import AnalysisInterpretRequest
from app.schemas.responses import VALIDATION_ERROR_RESPONSES
from app.services.risk_interpret import interpret_risk

router = APIRouter(tags=["analysis v2"], route_class=InterpretRoute)


@router.post(
    "/risk/interpret",
    response_model=ApiResponse[RiskInterpretation],
    responses=VALIDATION_ERROR_RESPONSES,
    dependencies=[Depends(strict_body)],
)
async def interpret(
    request: Request, body: AnalysisInterpretRequest, response: Response
) -> ApiResponse[RiskInterpretation]:
    response.headers.update(NO_STORE)
    return await interpret_risk(request.app.state.interpretation, body.query, body.history_query())
