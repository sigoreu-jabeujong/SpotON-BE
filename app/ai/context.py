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
from app.schemas.risk import Risk, RiskIndicator, RiskQuery
from app.services.market_activity import year_cutoff
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
        context, data_version_hash = _extract_context(response, checked)
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


def _extract_context(
    response: ApiResponse[Risk],
    query: RiskQuery,
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
    version_hash = hashlib.sha256(serialize_context(version_json).encode("utf-8")).hexdigest()
    sub = query.sub_category or (
        ("cafe",) if query.category == "cafe" else ("korean", "chinese", "japanese", "western")
    )
    context = RiskInterpretContext(
        category=query.category,
        sub_category=tuple(sorted(sub)),
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
    )
    return context, version_hash
