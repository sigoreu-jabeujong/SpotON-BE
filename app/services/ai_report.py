"""One logical report, three no-retry model-authored, evidence-checked roles."""

import asyncio
import hashlib
import hmac
import json
import re
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import event, text

from app.ai.client import LlmClient, LlmError, LlmErrorKind, LlmRequest
from app.ai.factory import create_llm_client
from app.ai.interpretation import CHECKLIST
from app.ai.limits import RetryPolicy
from app.ai.report_basis import basis, canonical, signing_key
from app.ai.report_catalog import (
    ReportCatalog,
    build_report_catalog,
)
from app.ai.report_narrative import (
    COMMON,
    INSTRUCTIONS,
    VERSION,
    DraftItem,
    parse,
    payload,
    schema,
    validate,
)
from app.ai.report_runtime import ReportFlights
from app.core.errors import AppError
from app.core.operations import ai_report_cache_hit, ai_report_role
from app.db.dependencies import NO_STORE, read_only_session
from app.schemas.address_history import AddressHistory
from app.schemas.ai_report import (
    AiSectionsReport,
    ReportBaseline,
    ReportRequest,
    ReportSection,
    ReportText,
    ReportVerification,
    Role,
)
from app.schemas.analysis_v2 import AnalysisActivityQuery
from app.schemas.common import ApiMeta, ApiResponse, ErrorCode
from app.schemas.location_reference import LocationReferenceQuery
from app.schemas.population_reference import PopulationReferenceQuery
from app.services import analysis_v2
from app.services.address_context import AddressPair, decode_pair
from app.services.address_history import get_address_history
from app.services.location_reference import get_location_reference
from app.services.population_reference import get_population_reference
from app.services.risk_interpret import InterpretationResources

BUDGET = 70.0
PREPARATION_BUDGET = 35.0
ROLES: tuple[Role, ...] = ("advantages", "cautions", "summary")
PROMPT_SHA = hashlib.sha256(
    canonical({"common": COMMON, "roles": INSTRUCTIONS, "version": VERSION})
).hexdigest()


class CachedReport(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    drafts: dict[Role, list[ReportText]]
    models: dict[Role, str]


@dataclass(frozen=True)
class PreparedReport:
    catalog: ReportCatalog
    baseline: ReportBaseline
    meta: ApiMeta
    key: str | None


def verified_pair(body: ReportRequest, resources: InterpretationResources) -> AddressPair | None:
    if body.address_history is None:
        return None
    pair = decode_pair(body.address_history.context, resources.database.settings)
    if pair.context_version != 2:
        raise AppError(ErrorCode.AI_HISTORY_CONTEXT_OUTDATED, headers=NO_STORE)
    if (pair.lat, pair.lng, pair.category) != (body.query.lat, body.query.lng, body.query.category):
        raise AppError(ErrorCode.INVALID_PARAM, headers=NO_STORE)
    return pair


def _prepare(
    resources: InterpretationResources,
    body: ReportRequest,
    pair: AddressPair | None,
    deadline: float,
    stop: threading.Event,
) -> PreparedReport:
    config = resources.database.settings

    def check(*_args: object) -> None:
        if stop.is_set() or time.monotonic() >= deadline:
            raise LlmError(LlmErrorKind.TIMEOUT)

    check()
    with read_only_session(resources.database) as session:
        connection = session.connection()
        event.listen(connection, "before_cursor_execute", check)
        try:
            risk = basis("risk", body.query, analysis_v2.risk(session, body.query, config), config)
            activity_query = AnalysisActivityQuery.model_validate(
                {**body.query.model_dump(exclude={"include"}), "include": ("sales", "living_pop")}
            )
            activity = basis(
                "activity", activity_query, analysis_v2.activity(session, activity_query), config
            )
            scope = body.query.model_dump(
                include={"lat", "lng", "radius", "category", "sub_category", "as_of"}
            )
            location_query = LocationReferenceQuery.model_validate(
                {**scope, "time_mode": body.time_mode}
            )
            location = basis(
                "location", location_query, get_location_reference(session, location_query), config
            )
            grid_query = PopulationReferenceQuery.model_validate(scope)
            grid = basis("grid", grid_query, get_population_reference(session, grid_query), config)
            history: AddressHistory | None = None
            history_token: str | None = None
            if body.address_history is not None and pair is not None:
                if (
                    session.scalar(
                        text("SELECT to_regprocedure('spoton_history_road_key_v1(text)')")
                    )
                    is None
                ):
                    raise AppError(ErrorCode.HISTORY_UNAVAILABLE, headers=NO_STORE)
                envelope = basis(
                    "address_history",
                    body.address_history,
                    get_address_history(session, body.address_history, pair),
                    config,
                )
                history, history_token = (
                    envelope.data,
                    cast(str, envelope.meta["ai_report_basis_token"]),
                )
            baseline = ReportBaseline(
                risk=risk.meta["ai_report_basis_token"],
                activity=activity.meta["ai_report_basis_token"],
                location=location.meta["ai_report_basis_token"],
                grid=grid.meta["ai_report_basis_token"],
                address_history=history_token,
            )
            for field in ReportBaseline.model_fields:
                left, right = getattr(baseline, field), getattr(body.baseline, field)
                if (left is None) != (right is None) or (
                    left is not None and not hmac.compare_digest(left, right)
                ):
                    raise AppError(ErrorCode.AI_CONTEXT_CHANGED, headers=NO_STORE)
            if (
                risk.data is None
                or activity.data is None
                or location.data is None
                or grid.data is None
            ):
                raise ValueError("missing prepared report data")
            catalog = build_report_catalog(
                risk.data, activity.data, location.data, grid.data, history, activity.meta
            )
            _verify_sentences(catalog)
            check()
            key = resources.database.cache.key(
                "ai",
                "sections-v1",
                baseline.model_dump(),
                catalog.digest,
                PROMPT_SHA,
                config.llm_provider,
                config.llm_model,
                config.llm_reasoning_effort,
                4096,
            )
            meta: ApiMeta = {
                **risk.meta,
                "source": cast(
                    JsonValue, sorted({source for m in catalog.metrics for source in m.source_ids})
                ),
                "schema_version": "ai-sections-v1",
                "prompt_version": VERSION,
                "prompt_sha256": PROMPT_SHA,
                "report_context_hash": catalog.digest,
                "interpretation_method": "model_authored_evidence_checked_v2",
                "llm_model": config.llm_model,
                "llm_provider": config.llm_provider,
                "reasoning_effort": config.llm_reasoning_effort,
            }
            return PreparedReport(catalog, baseline, meta, key)
        finally:
            event.remove(connection, "before_cursor_execute", check)


NUMBER = re.compile(r"(?<![A-Za-z])\d[\d,]*(?:\.\d+)?")


def _verify_sentences(catalog: ReportCatalog) -> None:
    metrics = {m.id: m for m in catalog.metrics}
    fixed = {"0", "1", "3", "6", "06", "17", "24", "250"}

    def numbers(value: str) -> set[str]:
        from decimal import Decimal

        return {str(Decimal(m.replace(",", "")).normalize()) for m in NUMBER.findall(value)}

    for section in [
        *catalog.candidates.values(),
        {str(i): v for i, v in enumerate(catalog.mandatory_cautions)},
    ]:
        for candidate in section.values():
            if any(key not in metrics for key in candidate.evidence_ids):
                raise ValueError("unknown report evidence")
            evidence = " ".join(metrics[key].model_dump_json() for key in candidate.evidence_ids)
            if not numbers(candidate.text) <= numbers(evidence + " " + " ".join(fixed)):
                raise ValueError("server report numeric mismatch")


def _selection(raw: str) -> list[str]:
    if len(raw.encode()) > 32768:
        raise ValueError("large model selection")

    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate model key")
            result[key] = value
        return result

    data = json.loads(raw, object_pairs_hook=unique)
    if (
        not isinstance(data, dict)
        or set(data) != {"ids"}
        or not isinstance(data["ids"], list)
        or not all(type(i) is str for i in data["ids"])
    ):
        raise ValueError("invalid role selection")
    return cast(list[str], data["ids"])


class ReportResources:
    def __init__(self, resources: InterpretationResources):
        self.shared = resources
        self.flights: ReportFlights[ApiResponse[AiSectionsReport]] = ReportFlights()
        self.busy = False
        self.cleanups: set[asyncio.Task[None]] = set()
        config = resources.database.settings
        self.client: LlmClient = create_llm_client(
            config,
            limiter=resources.provider_limiter,
            policy=RetryPolicy(
                request_timeout=15, time_budget=35, max_retries=0, base_delay=1, max_delay=1
            ),
        )

    async def generate(self, body: ReportRequest) -> ApiResponse[AiSectionsReport]:
        try:
            self.shared.limiter.acquire()
        except LlmError:
            raise AppError(ErrorCode.AI_UNAVAILABLE, headers=NO_STORE) from None
        config = self.shared.database.settings
        secret = signing_key(config)
        if (
            secret is None
            or config.llm_api_key is None
            or not config.llm_api_key.get_secret_value().strip()
        ):
            raise AppError(ErrorCode.AI_UNAVAILABLE, headers=NO_STORE)
        pair = verified_pair(body, self.shared)
        identity = body.model_dump(mode="json", exclude={"address_history"})
        if pair is not None and body.address_history is not None:
            identity["address_history"] = {
                "pair": pair.model_dump(exclude={"issued_at"}),
                "floor_unit": body.address_history.floor_unit,
            }
        key = hmac.new(secret, canonical(identity), hashlib.sha256).hexdigest()
        try:
            return await self.flights.run(key, lambda: self._generate(body, pair))
        except AppError:
            raise
        except (TimeoutError, LlmError):
            raise AppError(ErrorCode.AI_UNAVAILABLE, headers=NO_STORE) from None
        except (ValueError, TypeError, KeyError):
            raise AppError(ErrorCode.INTERNAL_ERROR, headers=NO_STORE) from None

    async def _generate(
        self, body: ReportRequest, pair: AddressPair | None
    ) -> ApiResponse[AiSectionsReport]:
        if self.busy:
            raise AppError(ErrorCode.AI_UNAVAILABLE, headers=NO_STORE)
        self.busy = True
        stop = threading.Event()
        preparation: asyncio.Task[PreparedReport] | None = None
        entered_thread = False
        try:
            async with asyncio.timeout(BUDGET):
                deadline = time.monotonic() + BUDGET

                async def prepare() -> PreparedReport:
                    nonlocal entered_thread
                    async with self.shared.db_gate:
                        entered_thread = True
                        return await asyncio.to_thread(
                            _prepare,
                            self.shared,
                            body,
                            pair,
                            min(deadline, time.monotonic() + PREPARATION_BUDGET),
                            stop,
                        )

                preparation = asyncio.create_task(prepare())
                async with asyncio.timeout(PREPARATION_BUDGET):
                    prepared = await asyncio.shield(preparation)
                cache = self.shared.database.cache.ai
                cached: CachedReport | None = None
                if prepared.key is not None:
                    encoded = cache.get(prepared.key)
                    if encoded is not None:
                        try:
                            candidate = CachedReport.model_validate_json(encoded)
                            if set(candidate.drafts) != set(ROLES) or set(candidate.models) != set(
                                ROLES
                            ):
                                raise ValueError("invalid cached report")
                            for role in ROLES:
                                validate(
                                    [
                                        DraftItem.model_validate(item.model_dump())
                                        for item in candidate.drafts[role]
                                    ],
                                    prepared.catalog,
                                    role,
                                )
                            cached = candidate
                        except (ValueError, TypeError):
                            cache.discard(prepared.key)
                if cached is not None:
                    ai_report_cache_hit()
                    return self._render(prepared, cached.drafts, {})
                slots = min(2, self.shared.database.settings.interpret_max_concurrent)
                if not self.shared.gate.try_reserve(slots):
                    raise AppError(ErrorCode.AI_UNAVAILABLE, headers=NO_STORE)
                try:
                    local_gate = asyncio.Semaphore(slots)
                    global_failure = asyncio.Event()
                    failures: dict[Role, str] = {}
                    selections: dict[Role, list[ReportText]] = {}
                    models: dict[Role, str] = {}

                    async def generate_role(role: Role) -> None:
                        async with local_gate:
                            started = time.monotonic()
                            if global_failure.is_set():
                                failures[role] = "provider_error"
                                return
                            try:
                                async with asyncio.timeout(
                                    min(15, max(0, deadline - time.monotonic()))
                                ):
                                    request = LlmRequest(
                                        system_instruction=COMMON + " " + INSTRUCTIONS[role],
                                        user_content=payload(prepared.catalog, role),
                                        response_json_schema=cast(
                                            dict[str, JsonValue], schema(prepared.catalog, role)
                                        ),
                                        max_output_tokens=4096,
                                    )
                                    result = await self.client.generate(request)
                                    if result.attempts != 1:
                                        raise ValueError("unexpected provider retries")
                                    selections[role] = parse(result.text, prepared.catalog, role)
                                    models[role] = result.model
                            except TimeoutError:
                                failures[role] = "timeout"
                            except LlmError as exc:
                                failures[role] = (
                                    "rate_limited"
                                    if exc.kind
                                    in {LlmErrorKind.RATE_LIMITED, LlmErrorKind.QUOTA_EXHAUSTED}
                                    else "timeout"
                                    if exc.kind == LlmErrorKind.TIMEOUT
                                    else "provider_error"
                                )
                                if exc.kind in {
                                    LlmErrorKind.NOT_CONFIGURED,
                                    LlmErrorKind.AUTHENTICATION,
                                    LlmErrorKind.QUOTA_EXHAUSTED,
                                }:
                                    global_failure.set()
                            except (ValueError, TypeError, RecursionError):
                                failures[role] = "verification_failed"
                            finally:
                                ai_report_role(
                                    role=role,
                                    status="ready"
                                    if role in selections
                                    else failures.get(role, "cancelled"),
                                    duration=int((time.monotonic() - started) * 1000),
                                )

                    # Unexpected programming errors fail the request rather than presenting
                    # an apparently verified partial result. Cancellation also propagates.
                    async with asyncio.TaskGroup() as tasks:
                        for role in ROLES:
                            tasks.create_task(generate_role(role))
                finally:
                    await self.shared.gate.release(slots)
                output = self._render(prepared, selections, failures)
                if not failures and prepared.key is not None:
                    try:
                        cache.put(
                            prepared.key,
                            CachedReport(drafts=selections, models=models)
                            .model_dump_json()
                            .encode(),
                        )
                    except Exception:
                        pass
                return output
        finally:
            stop.set()
            if preparation is None or preparation.done():
                if preparation is not None and not preparation.cancelled():
                    preparation.exception()
                self.busy = False
            else:
                # Return HTTP promptly, but retain admission until the actual worker releases DB.
                if not entered_thread:
                    preparation.cancel()

                async def cleanup() -> None:
                    try:
                        await asyncio.gather(preparation, return_exceptions=True)
                    finally:
                        self.busy = False

                task = asyncio.create_task(cleanup())
                self.cleanups.add(task)

                def finished(done: asyncio.Task[None]) -> None:
                    self.cleanups.discard(done)
                    if not done.cancelled():
                        done.exception()

                task.add_done_callback(finished)

    @staticmethod
    def _render(
        prepared: PreparedReport,
        selections: dict[Role, list[ReportText]],
        failures: dict[Role, str],
    ) -> ApiResponse[AiSectionsReport]:
        if not selections:
            code = (
                ErrorCode.AI_VERIFY_FAILED
                if "verification_failed" in failures.values()
                else ErrorCode.AI_UNAVAILABLE
            )
            raise AppError(code, headers=NO_STORE)
        sections: dict[Role, ReportSection] = {}
        for role in ROLES:
            if role in failures:
                sections[role] = ReportSection(
                    status="unavailable", reason=cast(object, failures[role])
                )
            else:
                items = selections[role]
                groups = [cast(str, i.group_id) for i in items] if role == "summary" else []
                sections[role] = ReportSection(
                    status="ready",
                    items=items,
                    verification=ReportVerification(),
                    group_count=len(groups),
                    group_ids=groups,
                )
        output = AiSectionsReport(
            status="partial" if failures else "complete",
            advantages=sections["advantages"],
            cautions=sections["cautions"],
            summary=sections["summary"],
            limitations=list(prepared.catalog.mandatory_cautions),
            metrics=list(prepared.catalog.metrics),
            checklist=[CHECKLIST[k] for k in ("time_flow", "access", "visibility")],
            generated_at=datetime.now(UTC),
            report_context_hash=hashlib.sha256(
                canonical(
                    {
                        "catalog": prepared.catalog.digest,
                        "baseline": prepared.baseline.model_dump(),
                        "prompt": PROMPT_SHA,
                        "model": prepared.meta.get("llm_model"),
                        "reasoning_effort": prepared.meta.get("reasoning_effort"),
                    }
                )
            ).hexdigest(),
            baseline=prepared.baseline,
        )
        return ApiResponse(
            data=output, meta={**prepared.meta, "report_context_hash": output.report_context_hash}
        )
