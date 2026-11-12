"""BE-28 / API v1.2 §4-8 rules 25–27: recalculate, then project a typed allowlist."""

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import Field, JsonValue, model_validator
from sqlalchemy.orm import Session

from app.ai.client import LlmRequest
from app.ai.prompts.builder import build_interpret_request, serialize_context
from app.ai.prompts.loader import PromptError, load_prompt_bundle
from app.core.cache import CacheResources
from app.core.config import Settings
from app.core.errors import AppError
from app.db.dependencies import NO_STORE
from app.schemas.ai_context import (
    ContextActivity,
    ContextActivityGroup,
    ContextFilters,
    ContextFlags,
    ContextIndicator,
    ContextMethodology,
    ContextModel,
    RiskInterpretContext,
)
from app.schemas.common import ApiResponse, ErrorCode
from app.schemas.franchise import (
    CLASSIFICATION,
    ESTIMATE_LIMIT,
    BrandDataVersion,
    EstimatedClassification,
)
from app.schemas.market_activity import ActivityQuery, MarketActivity
from app.schemas.risk import Risk, RiskIndicator, RiskQuery
from app.services.market_activity import RULE_VERSION as ACTIVITY_RULE_VERSION
from app.services.market_activity import get_activity, year_cutoff
from app.services.risk import RULE_VERSION, get_risk, percent, period
from app.services.risk_cache import snapshot_token
from app.services.spatial_stores import effective_date
from app.services.store_cohort import MIN_OPEN_DATE

FILTER_FIELDS = {
    "sub_category",
    "area",
    "franchise",
    "include_unknown_area",
    "include_unknown_franchise",
}


class _DataVersion(ContextModel):
    stores_batch_ids: tuple[UUID, ...] = Field(min_length=1)
    trdar_quarter: None
    map_version: str | None
    rule_version: Literal["risk-reference-fixed-anniversary-v1"]
    brand_mapping: BrandDataVersion | None = None

    @model_validator(mode="after")
    def unique_batches(self) -> "_DataVersion":
        if len(set(self.stores_batch_ids)) != len(self.stores_batch_ids):
            raise ValueError("invalid data version")
        return self


@dataclass(frozen=True)
class PreparedRiskInterpretation:
    context: RiskInterpretContext = field(repr=False, compare=False, hash=False)
    request: LlmRequest = field(repr=False, compare=False, hash=False)
    context_hash: str
    data_version_hash: str
    prompt_version: str
    prompt_sha256: str
    snapshot_token: str | None = field(default=None, repr=False)

    def json_context(self) -> dict[str, JsonValue]:
        return self.context.model_dump(mode="json")


def prepare_risk_interpretation(
    session: Session,
    query: RiskQuery,
    settings: Settings,
    *,
    cache: CacheResources | None = None,
) -> PreparedRiskInterpretation:
    """No client metrics, no provider invocation; caller supplies the read-only transaction."""
    try:
        checked = RiskQuery.model_validate(
            query.model_dump(exclude={"include_unknown"}, warnings="error")
        )
        token = None
        if cache is not None and cache.enabled:
            token = snapshot_token(session, cache)
            response = get_risk(session, checked, settings, cache=cache)
        else:
            response = get_risk(session, checked, settings)
        activity = get_activity(
            session,
            ActivityQuery.model_validate(
                checked.model_dump(exclude={"include", "include_unknown"}, warnings="error")
            ),
        )
        context, data_version_hash = _extract_context(response, checked, activity)
        safe = context.model_dump(mode="json")
        serialized = serialize_context(safe)
        bundle = load_prompt_bundle()
        return PreparedRiskInterpretation(
            context=context,
            request=build_interpret_request(safe),
            context_hash=hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
            data_version_hash=data_version_hash,
            prompt_version=bundle.version,
            prompt_sha256=bundle.sha256,
            snapshot_token=token,
        )
    except (ValueError, TypeError, AttributeError, PromptError):
        pass
    raise AppError(ErrorCode.INTERNAL_ERROR, headers=NO_STORE)


def _indicator(row: RiskIndicator, target: date, radius: int) -> ContextIndicator:
    expected_period = None
    expected_space = "market" if row.type == "official" else "grid"
    if row.id in {"closure_rate_12m", "survival_rate_1y", "survival_rate_3y", "competitor_count"}:
        expected_space = f"radius_{radius}m"
        if row.id == "competitor_count":
            expected_period = target.isoformat()
        elif row.id == "closure_rate_12m":
            expected_period = period(year_cutoff(target, target.year - 1), target)
        else:
            years = 1 if row.id == "survival_rate_1y" else 3
            expected_period = period(
                year_cutoff(target, target.year - years - 1),
                year_cutoff(target, target.year - years),
            )
    if row.period != expected_period or row.space != expected_space:
        raise ValueError("inconsistent indicator period or space")
    for value, num, den in (
        (row.value, row.numerator, row.denominator),
        (row.seoul_avg, row.seoul_numerator, row.seoul_denominator),
    ):
        if isinstance(value, float) and value == 0 and math.copysign(1, value) < 0:
            raise ValueError("negative zero")
        if value is not None and row.id != "competitor_count":
            if num is None or not den or value != percent(num, den):
                raise ValueError("inconsistent indicator ratio")
    return ContextIndicator.model_validate(
        {
            "id": row.id,
            "type": row.type,
            "value": row.value,
            "unit": row.unit,
            "numerator": row.numerator,
            "denominator": row.denominator,
            "seoul_avg": row.seoul_avg,
            "seoul_avg_reason": row.seoul_avg_reason,
            "seoul_numerator": row.seoul_numerator,
            "seoul_denominator": row.seoul_denominator,
            "space": expected_space,
            "period": expected_period,
            "source": tuple(row.source),
            "status": row.status,
            "reason": row.reason,
        }
    )


def _activity(
    activity: ApiResponse[MarketActivity],
    risk: Risk,
    risk_meta: dict[str, JsonValue],
    sub: tuple[str, ...],
    radius: int,
) -> ContextActivity:
    """Same-session recomputation; reject any drift from the Risk cohort (design §4)."""
    if activity.error is not None or activity.data is None:
        raise ValueError("activity result unavailable")
    data = MarketActivity.model_validate(activity.data.model_dump(warnings="error"))
    meta = activity.meta
    for key in ("as_of", "data_updated_at", "franchise_classification", "cohort_size"):
        if key not in meta or meta.get(key) != risk_meta.get(key):
            raise ValueError("activity provenance mismatch")
    cohort = meta.get("cohort_size")
    if type(cohort) is not int or cohort < 0:
        raise ValueError("activity cohort mismatch")
    if (
        meta.get("space") != f"radius_{radius}m"
        or meta.get("source") != ["R5", "R6"]
        or meta.get("collected_at") is not None
        or "collected_at" not in meta
        or meta.get("denominator") is not None
        or "denominator" not in meta
    ):
        raise ValueError("activity metadata mismatch")
    version, risk_version = meta.get("data_version"), risk_meta.get("data_version")
    if not isinstance(version, dict) or not isinstance(risk_version, dict):
        raise ValueError("activity data version mismatch")
    batches, risk_batches = version.get("stores_batch_ids"), risk_version.get("stores_batch_ids")
    if (
        not isinstance(batches, list)
        or not isinstance(risk_batches, list)
        or len(batches) != len(set(map(str, batches)))
        or set(map(str, batches)) != set(map(str, risk_batches))
        or version.get("map_version") != risk_version.get("map_version")
        or version.get("rule_version") != ACTIVITY_RULE_VERSION
        or version.get("brand_mapping") != risk_version.get("brand_mapping")
    ):
        raise ValueError("activity data version mismatch")
    if data.sales is not None or data.living_pop is not None or data.flags.missing:
        raise ValueError("activity optional data requested")
    groups = sorted(data.by_sub_category, key=lambda g: g.sub_category)
    if tuple(g.sub_category for g in groups) != sub:
        raise ValueError("activity scope mismatch")
    rows = {r.id: r for r in risk.indicators}
    competitor, closure = rows["competitor_count"], rows["closure_rate_12m"]
    active = sum(g.open_count for g in groups)
    closed = data.recent_12m.closed
    if (
        competitor.value != active
        or data.recent_12m.period != closure.period
        or closure.denominator != active + closed
        or (closure.numerator is not None and closure.numerator != closed)
    ):
        raise ValueError("activity counts mismatch")
    return ContextActivity.model_validate(
        {
            "space": f"radius_{radius}m",
            "recent_period": data.recent_12m.period,
            "recent_opened": data.recent_12m.opened,
            "recent_closed": closed,
            "groups": tuple(
                ContextActivityGroup(
                    sub_category=g.sub_category,
                    open_count=g.open_count,
                    avg_operating_months=g.avg_operating_months,
                )
                for g in groups
            ),
        }
    )


def _extract_context(
    response: ApiResponse[Risk],
    query: RiskQuery,
    activity: ApiResponse[MarketActivity],
) -> tuple[RiskInterpretContext, str]:
    if response.error is not None or response.data is None:
        raise ValueError("risk result unavailable")
    data = Risk.model_validate(response.data.model_dump(warnings="error"))
    expected_filters = query.model_dump(include=FILTER_FIELDS, mode="json")
    if (
        data.query.category != query.category
        or data.query.radius_m != query.radius
        or data.query.lat != query.lat
        or data.query.lng != query.lng
        or data.query.filters != expected_filters
    ):
        raise ValueError("risk result query mismatch")
    meta = response.meta
    target = data.query.as_of
    reference = date.fromisoformat(str(meta.get("data_updated_at")))
    if target > reference or meta.get("as_of") != target.isoformat():
        raise ValueError("risk result date mismatch")
    if target != effective_date(reference, MIN_OPEN_DATE, query.as_of):
        raise ValueError("risk query date mismatch")
    classification = CLASSIFICATION.validate_json(
        json.dumps(meta.get("franchise_classification"), allow_nan=False)
    )
    method = ContextMethodology()
    if isinstance(classification, EstimatedClassification):
        method = ContextMethodology(limitations=(*method.limitations, ESTIMATE_LIMIT))
    expected_meta = {
        "collected_at": None,
        "collection_reason": "source_completion_time_not_recorded",
        "source": ["R5", "R6"],
        "denominator": None,
        "event_basis": "validated_license_dates",
        "franchise_classification": classification.model_dump(mode="json"),
        "minimum_samples": {"closure": 10, "survival": 5},
        **method.model_dump(
            mode="json", exclude={"minimum_closure_sample", "minimum_survival_sample"}
        ),
    }
    if any(meta.get(k) != v or k not in meta for k, v in expected_meta.items()):
        raise ValueError("risk methodology mismatch")
    version = _DataVersion.model_validate_json(
        json.dumps(meta.get("data_version"), allow_nan=False)
    )
    if version.rule_version != RULE_VERSION:
        raise ValueError("risk rule mismatch")
    estimated = isinstance(classification, EstimatedClassification)
    reference_year = (
        classification.reference_year
        if isinstance(classification, EstimatedClassification)
        else None
    )
    if estimated != (version.brand_mapping is not None):
        raise ValueError("brand classification version mismatch")
    if estimated and (
        version.brand_mapping is None or version.brand_mapping.reference_year != reference_year
    ):
        raise ValueError("brand reference year mismatch")
    version_json = version.model_dump(mode="json")
    if version.brand_mapping is None:
        version_json.pop("brand_mapping")
    version_json["stores_batch_ids"] = sorted(str(v) for v in version.stores_batch_ids)
    version_json["activity_rule_version"] = ACTIVITY_RULE_VERSION
    version_hash = hashlib.sha256(serialize_context(version_json).encode("utf-8")).hexdigest()
    sub = query.sub_category or (
        ("cafe",) if query.category == "cafe" else ("korean", "chinese", "japanese", "western")
    )
    ordered_sub = tuple(sorted(sub))
    context = RiskInterpretContext(
        category=query.category,
        sub_category=ordered_sub,
        radius_m=query.radius,
        filters=ContextFilters(
            area=query.area,
            franchise=query.franchise,
            include_unknown_area=query.include_unknown_area,
            include_unknown_franchise=query.include_unknown_franchise,
        ),
        as_of=target,
        data_updated_at=reference,
        franchise_classification=classification.status,
        franchise_reference_year=reference_year,
        franchise_basis="reference_catalog_name_match" if estimated else None,
        indicators=tuple(_indicator(r, target, query.radius) for r in data.indicators),
        flags=ContextFlags(
            insufficient_sample=data.flags.insufficient_sample, missing=tuple(data.flags.missing)
        ),
        methodology=method,
        activity=_activity(activity, data, meta, ordered_sub, query.radius),
    )
    return context, version_hash
