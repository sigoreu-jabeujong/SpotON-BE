"""v2 server recomputation and independent, identifier-free model projection."""

import hashlib
import json
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.ai.context import (
    FILTER_FIELDS,
    PreparedRiskInterpretation,
    _activity,
    _DataVersion,
    _history,
    _indicator,
    check_history_location,
)
from app.ai.population_context import project_population
from app.ai.prompts.builder import build_interpret_request, serialize_context
from app.ai.prompts.loader import PromptError, load_v2_prompt_bundle
from app.core.cache import CacheResources
from app.core.config import Settings
from app.core.errors import AppError
from app.db.dependencies import NO_STORE
from app.schemas.ai_context import (
    AnalysisRiskInterpretContext,
    ContextAnalysisFilters,
    ContextFlags,
    ContextMethodology,
    ContextNearby,
)
from app.schemas.analysis_v2 import AnalysisRiskQuery
from app.schemas.common import ApiMeta, ApiResponse, ErrorCode
from app.schemas.market_activity import ActivityQuery
from app.schemas.population_reference import PopulationReferenceQuery
from app.schemas.risk import Risk, RiskQuery
from app.schemas.stores import HistoryQuery
from app.services.market_activity import RULE_VERSION as ACTIVITY_RULE_VERSION
from app.services.market_activity import get_activity
from app.services.population_reference import get_population_reference
from app.services.risk import RULE_VERSION, get_risk
from app.services.risk_cache import snapshot_token
from app.services.spatial_stores import effective_date
from app.services.store_cohort import MIN_OPEN_DATE
from app.services.store_history import HISTORY_RULE_VERSION, get_history
from app.services.store_scope import name_exclusion_meta


def v2_query_parts(query: AnalysisRiskQuery) -> dict[str, Any]:
    parts = query.model_dump(mode="json")
    parts["sub_category"] = sorted(
        query.sub_category
        or (("cafe",) if query.category == "cafe" else ("korean", "chinese", "japanese", "western"))
    )
    parts["include"] = sorted(query.include)
    return parts


def _checked_risk(
    response: ApiResponse[Risk], query: AnalysisRiskQuery
) -> tuple[Risk, date, ContextMethodology, _DataVersion]:
    if response.error is not None or response.data is None:
        raise ValueError("analysis risk unavailable")
    data = Risk.model_validate(response.data.model_dump(warnings="error"))
    legacy = query.legacy(RiskQuery)
    if (
        data.query.category != query.category
        or data.query.radius_m != query.radius
        or data.query.lat != query.lat
        or data.query.lng != query.lng
        or data.query.filters != legacy.model_dump(include=FILTER_FIELDS, mode="json")
    ):
        raise ValueError("analysis risk query mismatch")
    data.query.filters = query.echo_filters()
    meta = response.meta
    reference = date.fromisoformat(str(meta.get("data_updated_at")))
    target = data.query.as_of
    if (
        target > reference
        or meta.get("as_of") != target.isoformat()
        or target != effective_date(reference, MIN_OPEN_DATE, query.as_of)
    ):
        raise ValueError("analysis risk date mismatch")
    method = ContextMethodology()
    expected_meta: ApiMeta = {
        "name_exclusion": name_exclusion_meta(),
        "collected_at": None,
        "collection_reason": "source_completion_time_not_recorded",
        "source": ["R5", "R6"],
        "denominator": None,
        "event_basis": "validated_license_dates",
        "minimum_samples": {"closure": 10, "survival": 5},
        **method.model_dump(
            mode="json", exclude={"minimum_closure_sample", "minimum_survival_sample"}
        ),
    }
    if any(key not in meta or meta[key] != value for key, value in expected_meta.items()):
        raise ValueError("analysis methodology mismatch")
    version = _DataVersion.model_validate_json(
        json.dumps(meta.get("data_version"), allow_nan=False)
    )
    if version.rule_version != RULE_VERSION:
        raise ValueError("analysis data version mismatch")
    return data, reference, method, version


def prepare_v2_interpretation(
    session: Session,
    query: AnalysisRiskQuery,
    settings: Settings,
    *,
    cache: CacheResources | None = None,
    history: HistoryQuery | None = None,
) -> PreparedRiskInterpretation:
    try:
        checked = AnalysisRiskQuery.model_validate(query.model_dump(warnings="error"))
        token = snapshot_token(session, cache) if cache is not None and cache.enabled else None
        response = get_risk(session, checked.legacy(RiskQuery), settings)
        activity_query = ActivityQuery.model_validate(
            checked.legacy(RiskQuery).model_dump(
                exclude={"include", "include_unknown"}, warnings="error"
            )
        )
        activity = get_activity(session, activity_query)
        building = None
        if history is not None:
            check_history_location(session, checked.legacy(RiskQuery), history)
            building = get_history(session, history)
        data, reference, method, version = _checked_risk(response, checked)
        population_query = PopulationReferenceQuery.model_validate(
            checked.model_dump(
                include={
                    "lat",
                    "lng",
                    "radius",
                    "category",
                    "sub_category",
                    "as_of",
                }
            )
        )
        population, population_digest = project_population(
            get_population_reference(session, population_query),
            population_query,
            data.query.as_of,
        )
        sub = tuple(
            sorted(
                checked.sub_category
                or (
                    ("cafe",)
                    if checked.category == "cafe"
                    else ("korean", "chinese", "japanese", "western")
                )
            )
        )
        context = AnalysisRiskInterpretContext(
            category=checked.category,
            sub_category=sub,
            radius_m=checked.radius,
            filters=ContextAnalysisFilters.model_validate(
                checked.model_dump(include={"area", "include_unknown_area"})
            ),
            population_reference=population,
            as_of=data.query.as_of,
            data_updated_at=reference,
            indicators=tuple(
                _indicator(r, data.query.as_of, checked.radius) for r in data.indicators
            ),
            flags=ContextFlags(
                insufficient_sample=data.flags.insufficient_sample,
                missing=tuple(data.flags.missing),
            ),
            methodology=method,
            activity=_activity(
                activity,
                data,
                response.meta,
                sub,
                checked.radius,
            ),
            nearby=None
            if activity.meta.get("record_profile") is None
            else ContextNearby.model_validate(activity.meta["record_profile"]),
            history=None
            if building is None or history is None
            else _history(
                building,
                response.meta,
                history,
                checked.category,
                reference,
            ),
        )
        version_json = version.model_dump(mode="json")
        version_json["stores_batch_ids"] = sorted(str(v) for v in version.stores_batch_ids)
        version_json["activity_rule_version"] = ACTIVITY_RULE_VERSION
        version_json["population_digest"] = population_digest
        if history is not None:
            version_json["history_rule_version"] = HISTORY_RULE_VERSION
        # Internal provenance is hashed here, never passed to serialize_context or LLM.
        version_hash = hashlib.sha256(
            json.dumps(
                version_json,
                sort_keys=True,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        safe = context.model_dump(mode="json")
        bundle = load_v2_prompt_bundle()
        return PreparedRiskInterpretation(
            context=context,
            request=build_interpret_request(safe, bundle=bundle),
            context_hash=hashlib.sha256(serialize_context(safe).encode()).hexdigest(),
            data_version_hash=version_hash,
            prompt_version=bundle.version,
            prompt_sha256=bundle.sha256,
            snapshot_token=token,
            bundle=bundle,
            response_meta={
                "source": ["R5", "R6", "R4"]
                if any(s.status == "partial" for s in population.sources)
                else ["R5", "R6"],
            },
        )
    except (ValueError, TypeError, AttributeError, PromptError):
        pass
    raise AppError(ErrorCode.INTERNAL_ERROR, headers=NO_STORE)
