import json

import pytest

from app.ai.report_catalog import ReportCatalog
from app.ai.report_narrative import (
    DraftItem,
    adverse_signals,
    conditional_tradeoffs,
    parse,
    payload,
    schema,
    validate,
)
from app.schemas.ai_report import ReportMetric


def catalog():
    def metric(key, group, value, unit):
        return ReportMetric(
            id=key,
            group=group,
            label="공공자료",
            value=value,
            display="자료 없음" if value is None else value + unit,
            unit=unit,
            status="ready",
            source_ids=["R5"],
            period="2026-11-08",
            spatial_scope="반경 500m",
            population_scope="기록",
            filter_scope="선택 조건",
            area_label="보내지 않을 주소 이름",
        )

    return ReportCatalog(
        metrics=(
            metric("closure", "risk", "13.2", "%"),
            metric("sales", "sales", "1000", "원"),
            metric("missing", "grid", None, "명"),
        ),
        candidates={"advantages": {}, "cautions": {}, "summary": {}},
        group_ids=("risk", "sales", "grid"),
        mandatory_cautions=(),
    )


def item(text="폐업률은 13.2%로 현장 상황과 함께 살펴볼 필요가 있어요.", ids=None, group=None):
    return DraftItem(text=text, evidence_ids=ids or ["closure"], group_id=group)


def test_accepts_new_model_authored_text_without_predefined_candidates():
    result = validate([item()], catalog(), "advantages")
    assert result[0].text == item().text
    assert result[0].evidence_ids == ["closure"]


def test_source_window_units_are_allowed_but_value_unit_changes_are_not():
    source = catalog()
    source.metrics[0].label = "최근 12개월 참고 폐업률"
    assert validate([item("최근 12개월 참고 폐업률은 13.2%입니다.")], source, "advantages")
    with pytest.raises(ValueError):
        validate([item("폐업률은 13.2개월입니다.")], source, "advantages")


def test_indicator_labels_are_vocabulary_but_uncited_values_are_not_evidence():
    source = catalog()
    source.metrics[1].group = "risk"
    source.metrics[1].label = "개업 1주년 생존율"
    source.metrics[1].value = "90"
    source.metrics[1].display = "90%"
    source.metrics[1].unit = "%"
    assert validate([item("개업 1주년 지표와 다른 개업 집단입니다.")], source, "advantages")
    with pytest.raises(ValueError):
        validate([item("생존율은 90%입니다.")], source, "advantages")


@pytest.mark.parametrize("unit", ["개", "건"])
def test_denominator_counts_remain_valid_without_becoming_percentage_values(unit):
    source = catalog()
    source.metrics[0].denominator = "684"
    assert validate(
        [item(f"계산 대상은 684{unit}이며 폐업률은 13.2%입니다.")], source, "advantages"
    )
    with pytest.raises(ValueError):
        validate([item("폐업률은 684%입니다.")], source, "advantages")


@pytest.mark.parametrize(
    "draft",
    [
        item("폐업률은 90%입니다."),
        item(ids=["invented"]),
        item("폐업률은 13.2원입니다."),
        item("반경은 250m입니다."),
        item("별도 수치는 17입니다."),
        item("폐업률은 -13.2%입니다."),
        item("차이는 13.2%포인트입니다."),
        item(ids=["closure", "closure"]),
        item("https://example.com"),
        item("매출을 보장합니다."),
        item("고객은 0명입니다.", ["missing"]),
        item("원자료의 두 배입니다.", group="risk"),
    ],
)
def test_rejects_unsupported_claims_and_wrong_role(draft):
    with pytest.raises(ValueError):
        validate([draft], catalog(), "advantages")


def test_summary_requires_each_group_and_group_specific_evidence():
    valid = [
        item(group="risk"),
        item("매출 참고값은 1000원입니다.", ["sales"], "sales"),
        item("공개 격자자료가 없어 판단을 보류해야 해요.", ["missing"], "grid"),
    ]
    assert len(validate(valid, catalog(), "summary")) == 3
    with pytest.raises(ValueError):
        validate(valid[:-1], catalog(), "summary")
    valid[-1] = item(group="grid")
    with pytest.raises(ValueError):
        validate(valid, catalog(), "summary")


def test_duplicate_keys_and_extra_fields_fail_closed():
    with pytest.raises(ValueError):
        parse('{"items":[],"items":[]}', catalog(), "advantages")
    with pytest.raises(ValueError):
        parse('{"items":[],"extra":"hidden"}', catalog(), "advantages")


def test_payload_contains_metrics_not_ui_names_or_predefined_choices():
    content = payload(catalog(), "summary")
    assert "보내지 않을 주소 이름" not in content and "area_label" not in content
    assert "candidates" not in json.loads(content)
    assert len(json.loads(content)["metrics"]) == 3


def adverse_catalog(local="13.2", reference="9.6"):
    from dataclasses import replace

    source = catalog()
    source.metrics[0].id = "closure_rate_12m"
    source.metrics[0].value = local
    source.metrics[0].display = "資料 없음" if local is None else local + "%"
    comparison = source.metrics[0].model_copy(
        update={"id": "closure_rate_12m_seoul", "value": reference, "display": reference + "%"}
    )
    return replace(source, metrics=source.metrics + (comparison,))


def test_cautions_require_both_sides_of_an_actual_adverse_comparison():
    source = adverse_catalog()
    assert len(adverse_signals(source)) == 1
    draft = item(
        "폐업률은 13.2%로 서울 비교값 9.6%보다 높아 영업 지속 부담에 주의할 신호입니다.",
        ["closure_rate_12m", "closure_rate_12m_seoul"],
    )
    assert validate([draft], source, "cautions")
    with pytest.raises(ValueError):
        validate([], source, "cautions")
    with pytest.raises(ValueError):
        validate([item("표본을 현장에서 확인하세요.", ["closure_rate_12m"])], source, "cautions")


@pytest.mark.parametrize("value", ["6.8", "9.6", None])
def test_no_adverse_signal_means_empty_cautions_instead_of_generic_disclaimers(value):
    source = adverse_catalog(value)
    assert adverse_signals(source) == []
    assert validate([], source, "cautions") == []
    with pytest.raises(ValueError):
        validate(
            [item("실제 고객 수가 아니므로 확인하세요.", ["closure_rate_12m"])], source, "cautions"
        )


def time_catalog(day="70031.9", night="79137.3", base=None):
    from dataclasses import replace

    source = base or catalog()
    parent = source.metrics[0].model_copy(
        update={
            "id": "population_0",
            "group": "population",
            "unit": "명",
            "spatial_scope": "검색 위치 포함 행정동",
        }
    )
    pair = tuple(
        parent.model_copy(
            update={
                "id": "population_0_" + suffix,
                "value": value,
                "display": "자료 없음" if value is None else value + "명",
                "spatial_scope": "행정동 단위",
            }
        )
        for suffix, value in (("day", day), ("night", night))
    )
    return replace(source, metrics=source.metrics + (parent,) + pair)


@pytest.mark.parametrize(
    "day,night,stronger", [("70", "79", "night"), ("79", "70", "day"), ("0", "79", "night")]
)
def test_time_direction_requires_both_opportunity_and_conditional_caution(day, night, stronger):
    source = time_catalog(day, night)
    guide = conditional_tradeoffs(source)[0]
    assert guide["stronger_period"] == stronger
    ids = ["population_0_day", "population_0_night"]
    for role in ("advantages", "cautions"):
        assert validate(
            [item("시간대별 체류 특성에 맞춘 영업 전략을 검토할 수 있어요.", ids)], source, role
        )
        with pytest.raises(ValueError):
            validate([], source, role)
        with pytest.raises(ValueError):
            validate([item("생활인구의 시간대 특성을 고려할 수 있어요.", ids[:1])], source, role)
        assert schema(source, role)["properties"]["items"]["minItems"] == 1


@pytest.mark.parametrize(
    "day,night",
    [
        ("70", "70"),
        ("0", "0"),
        (None, "70"),
        ("70", None),
        ("-1", "70"),
        ("NaN", "70"),
        ("Infinity", "70"),
    ],
)
def test_missing_equal_or_invalid_time_values_do_not_create_a_direction(day, night):
    assert conditional_tradeoffs(time_catalog(day, night)) == []


@pytest.mark.parametrize(
    "change",
    [
        {"period": "2026-10-30"},
        {"area_label": "다른 행정동"},
        {"spatial_scope": "다른 범위"},
        {"population_scope": "다른 집단"},
        {"filter_scope": "다른 필터"},
        {"status": "unavailable"},
        {"unit": "%"},
        {"display": "70031.9명", "rounded": True},
    ],
)
def test_time_comparison_rejects_scope_date_and_visible_precision_mismatches(change):
    source = time_catalog()
    for key, value in change.items():
        setattr(source.metrics[-1], key, value)
    assert conditional_tradeoffs(source) == []


def test_search_location_area_wins_and_grid_is_only_a_fallback():
    from dataclasses import replace

    source = time_catalog()
    intersect = tuple(
        m.model_copy(
            update={
                "id": m.id.replace("population_0", "population_1"),
                "spatial_scope": "반경 교차 행정동" if m.id == "population_0" else m.spatial_scope,
            }
        )
        for m in source.metrics[-3:]
    )
    grid = tuple(
        m.model_copy(
            update={
                "id": key,
                "group": "grid",
                "value": value,
                "display": value + "%",
                "unit": "%",
                "status": "partial",
            }
        )
        for m, key, value in zip(
            source.metrics[-2:], ("grid_local", "grid_local_night_share"), ("60", "40"), strict=True
        )
    )
    source = replace(source, metrics=intersect + grid + source.metrics)
    assert conditional_tradeoffs(source)[0]["evidence_ids"] == [
        "population_0_day",
        "population_0_night",
    ]
    fallback = replace(source, metrics=grid)
    guide = conditional_tradeoffs(fallback)[0]
    assert guide["stronger_period"] == "day"
    assert guide["evidence_ids"] == ["grid_local", "grid_local_night_share"]


def test_time_tradeoff_and_observed_risk_cannot_displace_one_another():
    source = time_catalog(base=adverse_catalog())
    time = item(
        "주간 중심 영업이라면 상대적인 시간대 차이를 고려할 수 있어요.",
        ["population_0_day", "population_0_night"],
    )
    risk = item(
        "폐업률이 서울 비교값보다 높아 영업 지속 부담을 시사해요.",
        ["closure_rate_12m", "closure_rate_12m_seoul"],
    )
    assert validate([time, risk], source, "cautions")
    for incomplete in ([time], [risk]):
        with pytest.raises(ValueError):
            validate(incomplete, source, "cautions")
    assert schema(source, "cautions")["properties"]["items"]["minItems"] == 2
    assert schema(source, "cautions")["properties"]["items"]["maxItems"] == 4
    four = [time] + [
        risk.model_copy(update={"text": risk.text + suffix})
        for suffix in ("첫 관점", "다른 관점", "추가 관점")
    ]
    assert len(validate(four, source, "cautions")) == 4
    with pytest.raises(ValueError):
        validate(four + [risk.model_copy(update={"text": "다섯 번째 항목"})], source, "cautions")


def test_new_entry_and_incumbent_cautions_need_actual_counts_not_sales_or_history():
    from dataclasses import replace

    source = catalog()
    counts = tuple(
        source.metrics[0].model_copy(
            update={
                "id": key,
                "group": "activity" if key != "competitor_count" else "risk",
                "value": value,
                "display": value + "건",
                "unit": "건",
            }
        )
        for key, value in (("opened", "47"), ("closed", "30"), ("competitor_count", "408"))
    )
    source = replace(source, metrics=source.metrics + counts)
    assert {g["family"] for g in conditional_tradeoffs(source)} == {"new_entries", "incumbents"}
    assert validate(
        [
            item(
                "새로 진입한다면 신규 공급과 구별되는 상품 구성을 검토할 수 있어요.",
                ["opened", "closed"],
            )
        ],
        source,
        "cautions",
    )
    assert validate(
        [
            item(
                "새로 진입한다면 기존 업체와 구별되는 포지셔닝이 필요할 수 있어요.",
                ["competitor_count"],
            )
        ],
        source,
        "cautions",
    )
    for ids in (["opened"], ["sales"]):
        with pytest.raises(ValueError):
            validate([item("임대료가 높아 경쟁에 주의해야 해요.", ids)], source, "cautions")
