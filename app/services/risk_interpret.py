import asyncio
import threading
import time

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy import event

from app.ai.chain_context import chain_query_parts, prepare_chain_interpretation
from app.ai.client import LlmClient, LlmError, LlmErrorKind
from app.ai.context import PreparedRiskInterpretation, prepare_risk_interpretation
from app.ai.interpretation import build_catalog, render_interpretation
from app.ai.limits import RequestLimiter
from app.ai.prompts.builder import build_interpret_request
from app.ai.verified import AiVerifyFailedError, generate_verified
from app.core.cache import Flights
from app.core.errors import AppError
from app.db.dependencies import NO_STORE, DatabaseResources, read_only_session
from app.schemas.ai_context import ChainRiskInterpretContext
from app.schemas.chains import ChainRiskQuery
from app.schemas.common import ApiMeta, ApiResponse, ErrorCode
from app.schemas.interpret import CandidateSelection, RiskInterpretation
from app.schemas.risk import RiskQuery
from app.schemas.stores import HistoryQuery
from app.services.risk_cache import query_parts

MIN_REGENERATION_SECONDS = 1.0
SELECTION_CACHE_RULE = "selection-current-validation-v4-narrative"
CHAIN_SELECTION_CACHE_RULE = "selection-chain-current-validation-v1"


class _CachedSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    selection: CandidateSelection = Field(repr=False)
    model: str = Field(min_length=1, max_length=256)


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
        self.flights = Flights()


def _prepare(
    resources: InterpretationResources,
    query: RiskQuery | ChainRiskQuery,
    deadline: float,
    stop: threading.Event,
    history: HistoryQuery | None = None,
) -> PreparedRiskInterpretation:
    def check(*_args: object) -> None:
        if stop.is_set() or time.monotonic() >= deadline:
            raise LlmError(LlmErrorKind.TIMEOUT)

    check()
    with read_only_session(resources.database) as session:
        connection = session.connection()
        event.listen(connection, "before_cursor_execute", check)
        try:
            if isinstance(query, ChainRiskQuery):
                result = prepare_chain_interpretation(
                    session,
                    query,
                    resources.database.settings,
                    cache=resources.database.cache,
                    history=history,
                )
            else:
                result = prepare_risk_interpretation(
                    session,
                    query,
                    resources.database.settings,
                    cache=resources.database.cache,
                    history=history,
                )
            check()
            return result
        finally:
            event.remove(connection, "before_cursor_execute", check)


async def interpret_risk(
    resources: InterpretationResources,
    query: RiskQuery | ChainRiskQuery,
    history: HistoryQuery | None = None,
) -> ApiResponse[RiskInterpretation]:
    budget = resources.database.settings.llm_time_budget
    deadline = time.monotonic() + budget
    stop = threading.Event()
    error = ErrorCode.AI_UNAVAILABLE
    try:
        async with asyncio.timeout(budget):
            resources.limiter.acquire()
            async with resources.gate:
                prepared = await asyncio.to_thread(
                    _prepare, resources, query, deadline, stop, history
                )
            catalog = build_catalog(prepared)
            payload: dict[str, JsonValue] = {
                "analysis": prepared.json_context(),
                "candidates": catalog.candidates(),
            }
            is_chain = isinstance(query, ChainRiskQuery)
            if is_chain and (
                not isinstance(prepared.context, ChainRiskInterpretContext)
                or prepared.bundle is None
                or prepared.bundle.version != prepared.prompt_version
                or prepared.bundle.sha256 != prepared.prompt_sha256
            ):
                raise ValueError("chain prompt context mismatch")
            if is_chain:
                request = build_interpret_request(
                    payload, response_json_schema=catalog.selection_schema(), bundle=prepared.bundle
                )
            else:
                request = build_interpret_request(
                    payload, response_json_schema=catalog.selection_schema()
                )
            cache = resources.database.cache
            config = resources.database.settings
            key = None
            if (
                cache.enabled
                and prepared.snapshot_token is not None
                and config.llm_api_key is not None
                and config.llm_api_key.get_secret_value().strip()
            ):
                key = cache.key(
                    "ai",
                    CHAIN_SELECTION_CACHE_RULE if is_chain else SELECTION_CACHE_RULE,
                    prepared.snapshot_token,
                    chain_query_parts(query)
                    if isinstance(query, ChainRiskQuery)
                    else query_parts(query),
                    prepared.data_version_hash,
                    prepared.context_hash,
                    prepared.prompt_version,
                    prepared.prompt_sha256,
                    resources.client.provider,
                    resources.client.model,
                    config.llm_max_output_tokens,
                    payload,
                    request.response_json_schema,
                )

            def before(generation: int) -> None:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or (generation > 1 and remaining < MIN_REGENERATION_SECONDS):
                    raise LlmError(LlmErrorKind.TIMEOUT)

            async with resources.flights.hold(key) as waited:
                cached = None
                if key is not None:
                    try:
                        encoded = cache.ai.get(key)
                        if encoded is not None:
                            cached = _CachedSelection.model_validate_json(encoded)
                            if not catalog.selection_valid(
                                cached.selection.model_dump(mode="json")
                            ):
                                raise ValueError("invalid cached selection")
                    except Exception:
                        cache.ai.discard(key)
                        cached = None
                regenerated = False
                if cached is None:
                    if waited:
                        before(2)
                    async with resources.gate:
                        generated = await generate_verified(
                            resources.client,
                            request,
                            context=payload,
                            response_model=CandidateSelection,
                            data_validator=catalog.selection_valid,
                            before_generation=before,
                        )
                    selected = CandidateSelection.model_validate(generated.data)
                    model = generated.result.model
                    regenerated = generated.generations > 1
                else:
                    selected, model = cached.selection, cached.model
                before(1)
                output = render_interpretation(
                    prepared,
                    catalog,
                    selected,
                    model=model,
                    regenerated=regenerated,
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
                response: ApiResponse[RiskInterpretation] = ApiResponse(data=output, meta=meta)
                if is_chain:
                    if prepared.response_meta is None:
                        raise ValueError("chain response metadata missing")
                    response.meta.update(prepared.response_meta)
                before(1)
                if key is not None and cached is None:
                    try:
                        cache.ai.put(
                            key,
                            _CachedSelection(selection=selected, model=model)
                            .model_dump_json()
                            .encode(),
                        )
                    except Exception:
                        pass
                return response
    except AiVerifyFailedError:
        error = ErrorCode.AI_VERIFY_FAILED
    except (TimeoutError, LlmError):
        pass
    except (ValueError, TypeError):
        error = ErrorCode.INTERNAL_ERROR
    finally:
        stop.set()
    raise AppError(error, headers=NO_STORE)
