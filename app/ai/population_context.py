"""Project public comparisons and build a separately verified server sentence."""

import hashlib
import json
from datetime import date

from pydantic import JsonValue

from app.ai.verifier import verify_output
from app.schemas.ai_population import ContextPopulationReference
from app.schemas.common import ApiResponse
from app.schemas.population_reference import PopulationReference, PopulationReferenceQuery

RULE_VERSION = "ai-public-population-v1"
VERSION_FIELDS = (
    "format_version",
    "rule_version",
    "observation_version_id",
    "grid_version_id",
    "input_sha256",
    "content_sha256",
    "grid_input_sha256",
    "grid_content_sha256",
)
METRICS = ("day_share_pct", "night_share_pct", "day_night_ratio")
QUALITY = {
    "selected_grid_count",
    "used_grid_count",
    "grids_without_rows",
    "candidate_component_count",
    "used_component_count",
    "excluded_component_count",
    "excluded_by_hour_class",
}
REASONS = {
    "ambiguous_source_version": "같은 날짜의 자료 버전을 확인 중입니다",
    "no_observation_in_period": "선택한 기준월에 비교할 관측 자료가 없습니다",
    "scope_too_large": "현재 비교 가능한 자료량을 넘었습니다",
    "no_selected_grids": "반경 안에 선택된 격자가 없습니다",
    "no_source_rows": "반경 안에 제공된 원천 자료가 없습니다",
    "no_common_public_components": "모든 시간에 공개된 동일 구성이 없습니다",
    "numeric_scope_too_large": "현재 계산 가능한 수치 범위를 넘었습니다",
}


def _reason_text(reason: str | None) -> str:
    if reason is None or reason not in REASONS:
        raise ValueError("invalid population sentence reason")
    return REASONS[reason]


def project_population(
    response: ApiResponse[PopulationReference], query: PopulationReferenceQuery, target: date
) -> tuple[ContextPopulationReference, str]:
    if response.error is not None or response.data is None:
        raise ValueError("population evidence unavailable")
    data = PopulationReference.model_validate(response.data.model_dump(warnings="error"))
    scope = data.scope
    if (
        data.analysis_date != target
        or scope.radius_m != query.radius
        or scope.category != query.category
        or scope.sub_category != tuple(sorted(query.sub_category))
        or scope.as_of != query.as_of
        or scope.population_filter_applied is not False
        or response.meta.get("source_validation_performed") is not False
        or response.meta.get("population_total_validated") is not False
    ):
        raise ValueError("population evidence scope mismatch")
    sources = []
    for block in data.sources:
        metrics = None
        if block.values is not None:
            metrics = {
                name: getattr(block.values, name).model_dump(exclude={"value"}) for name in METRICS
            }
        sources.append(
            dict(
                source=block.source,
                status=block.status,
                reason=block.reason,
                metrics=metrics,
                quality=block.quality.model_dump(include=QUALITY),
                limitations=block.limitations,
            )
        )
    context = ContextPopulationReference.model_validate(
        dict(
            status=data.status,
            reason=data.reason,
            analysis_date=data.analysis_date,
            observation_date=data.observation_date,
            sources=tuple(sources),
        )
    )
    # Internal provenance only. Identifiers and hashes never enter the model context.
    if any(key not in response.meta for key in VERSION_FIELDS):
        raise ValueError("population provenance missing")
    metadata = {key: response.meta[key] for key in VERSION_FIELDS}
    digest = hashlib.sha256(
        json.dumps(
            {"projection_rule": RULE_VERSION, "metadata": metadata},
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()
    return context, digest


def population_sentence(context: ContextPopulationReference) -> str:
    text, evidence = _sentence(context)
    if not verify_output(
        json.dumps({"text": text}, ensure_ascii=False), context={"analysis": evidence}
    ).ok:
        raise ValueError("population sentence verification failed")
    return text


def _sentence(context: ContextPopulationReference) -> tuple[str, dict[str, JsonValue]]:
    evidence: dict[str, JsonValue] = {
        "analysis_date": context.analysis_date.isoformat(),
        "observation_date": context.observation_date.isoformat()
        if context.observation_date
        else None,
    }
    if context.status != "ready":
        return "공개 부분자료의 주야간 비교는 " + _reason_text(context.reason) + ".", evidence
    local, long, short = context.sources
    if context.observation_date is None:
        raise ValueError("population observation date missing")
    text = (
        f"관측일 {context.observation_date.isoformat()}의 "
        "공개된 동일 구성 부분자료를 별도로 확인했습니다. "
    )
    if local.metrics is None:
        text += "내국인 비교는 제공되지 않으며 " + _reason_text(local.reason) + ". "
    else:
        day, night = local.metrics.day_share_pct, local.metrics.night_share_pct
        evidence["local"] = {
            "status": local.status,
            "reason": local.reason,
            **{
                key: getattr(local.metrics, key).model_dump(
                    mode="json", include={"display", "rounded", "reason"}
                )
                for key in ("day_share_pct", "night_share_pct")
            },
        }
        if day.display is None:
            text += "내국인 공개값의 주야간 합이 모두 영이어서 비중을 계산하지 않았습니다. "
        else:
            text += (
                f"내국인 공개자료의 주간 비중은 {day.display}, 야간 비중은 {night.display}입니다. "
            )
            if any(
                metric.rounded and metric.display in ("0.0%", "100.0%") for metric in (day, night)
            ):
                text += "끝값도 반올림 표시값이며 정확한 영이나 전부를 뜻하지 않습니다. "
    for block, label in ((long, "장기체류"), (short, "단기체류")):
        text += f"{label} 외국인 원천은 " + (
            "별도 부분 비교가 있습니다. "
            if block.status == "partial"
            else _reason_text(block.reason) + ". "
        )
    if any(
        b.quality.excluded_by_hour_class.day_only or b.quality.excluded_by_hour_class.night_only
        for b in context.sources
    ):
        text += "주간 또는 야간에 치우친 제외 패턴으로 비중이 달라질 수 있습니다. "
    text += (
        "전체 인구나 실제 방문객을 대표하지 않으며 "
        "점포의 업종·면적 필터를 적용한 인구가 아닙니다. "
        "행정동별 합산과 격자의 기간 적용 기준은 미확정입니다."
    )
    return text, evidence
