import json

import pytest

from app.ai.report_catalog import ReportCatalog
from app.ai.report_narrative import DraftItem, parse, payload, validate
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
    result = validate([item()], catalog(), "cautions")
    assert result[0].text == item().text
    assert result[0].evidence_ids == ["closure"]


def test_source_window_units_are_allowed_but_value_unit_changes_are_not():
    source = catalog()
    source.metrics[0].label = "최근 12개월 참고 폐업률"
    assert validate([item("최근 12개월 참고 폐업률은 13.2%입니다.")], source, "cautions")
    with pytest.raises(ValueError):
        validate([item("폐업률은 13.2개월입니다.")], source, "cautions")


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
        validate([draft], catalog(), "cautions")


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
