import asyncio
import threading
import time

from pydantic import JsonValue
from sqlalchemy import event

from app.ai.client import LlmClient, LlmError, LlmErrorKind
from app.ai.context import PreparedRiskInterpretation, prepare_risk_interpretation
from app.ai.interpretation import build_catalog, render_interpretation
from app.ai.limits import RequestLimiter
from app.ai.prompts.builder import build_interpret_request
from app.ai.verified import AiVerifyFailedError, generate_verified
from app.core.errors import AppError
from app.db.dependencies import NO_STORE, DatabaseResources, read_only_session
from app.schemas.common import ApiMeta, ApiResponse, ErrorCode
from app.schemas.interpret import CandidateSelection, RiskInterpretation
from app.schemas.risk import RiskQuery

MIN_REGENERATION_SECONDS = 1.0


class InterpretationResources:
    def __init__(self, database: DatabaseResources, client: LlmClient):
        self.database = database
        self.client = client
        config = database.settings
        self.limiter = RequestLimiter(
            per_minute=config.interpret_requests_per_minute,
            per_day=config.interpret_requests_per_day,
        )
        self.gate = asyncio.Semaphore(config.interpret_max_concurrent)


def _prepare(
    resources: InterpretationResources,
    query: RiskQuery,
    deadline: float,
    stop: threading.Event,
) -> PreparedRiskInterpretation:
    def check(*_args: object) -> None:
        if stop.is_set() or time.monotonic() >= deadline:
            raise LlmError(LlmErrorKind.TIMEOUT)

    check()
    with read_only_session(resources.database) as session:
        connection = session.connection()
        event.listen(connection, "before_cursor_execute", check)
        try:
            result = prepare_risk_interpretation(session, query, resources.database.settings)
            check()
            return result
        finally:
            event.remove(connection, "before_cursor_execute", check)


async def interpret_risk(
    resources: InterpretationResources, query: RiskQuery
) -> ApiResponse[RiskInterpretation]:
    budget = resources.database.settings.llm_time_budget
    deadline = time.monotonic() + budget
    stop = threading.Event()
    error = ErrorCode.AI_UNAVAILABLE
    try:
        async with asyncio.timeout(budget):
            resources.limiter.acquire()
            async with resources.gate:
                prepared = await asyncio.to_thread(_prepare, resources, query, deadline, stop)
                catalog = build_catalog(prepared)
                payload: dict[str, JsonValue] = {
                    "analysis": prepared.json_context(),
                    "candidates": catalog.candidates(),
                }
                request = build_interpret_request(
                    payload, response_json_schema=CandidateSelection.model_json_schema()
                )

                def before(generation: int) -> None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or (generation > 1 and remaining < MIN_REGENERATION_SECONDS):
                        raise LlmError(LlmErrorKind.TIMEOUT)

                generated = await generate_verified(
                    resources.client,
                    request,
                    context=payload,
                    response_model=CandidateSelection,
                    data_validator=catalog.selection_valid,
                    before_generation=before,
                )
                before(1)
                output = render_interpretation(
                    prepared,
                    catalog,
                    CandidateSelection.model_validate(generated.data),
                    model=generated.result.model,
                    regenerated=generated.generations > 1,
                )
                before(1)
                meta: ApiMeta = {
                    "source": ["R5", "R6"],
                    "as_of": prepared.context.as_of.isoformat(),
                    "data_updated_at": prepared.context.data_updated_at.isoformat(),
                    "collected_at": None,
                    "space": f"radius_{query.radius}m",
                    "denominator": None,
                    "is_demo": False,
                    "data_version_hash": prepared.data_version_hash,
                    "context_hash": prepared.context_hash,
                    "prompt_version": prepared.prompt_version,
                    "prompt_sha256": prepared.prompt_sha256,
                    "interpretation_method": "server_sentences_model_ordering",
                }
                return ApiResponse(data=output, meta=meta)
    except AiVerifyFailedError:
        error = ErrorCode.AI_VERIFY_FAILED
    except (TimeoutError, LlmError):
        pass
    except (ValueError, TypeError):
        error = ErrorCode.INTERNAL_ERROR
    finally:
        stop.set()
    raise AppError(error, headers=NO_STORE)
