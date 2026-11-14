from datetime import date

import pytest

from etl.brands.catalog import Brand as CatalogBrand
from etl.brands.catalog import normalize_name
from etl.chains.common import ChainsError
from etl.chains.compare import compare_rows
from etl.chains.matching import ChainMatcher
from etl.chains.registry import catalog_links, extend_catalog, load_registry, registry_hash


@pytest.mark.parametrize(
    "name,key",
    [
        ("스타벅스", "starbucks-kr"),
        ("STARBUCKS", "starbucks-kr"),
        ("스타벅스 태평로점", "starbucks-kr"),
        ("스타벅스홍대입구점", "starbucks-kr"),
        ("파스쿠찌 남산트라팰리스점", "pascucci-kr"),
        ("카페파스쿠찌 서울시청점", "pascucci-kr"),
        ("(주)파리크라상 파스쿠찌 광화문점", "pascucci-kr"),
        ("(주)농심 코코이찌방야 광화문LX빌딩점", "cocoichibanya-kr"),
        ("코코이찌방야홍대와이즈파크점", "cocoichibanya-kr"),
        ("본죽", "bonjuk-kr"),
        ("본죽   강남점", "bonjuk-kr"),
        ("본죽(강남점)", "bonjuk-kr"),
        ("본죽 죽전점", "bonjuk-kr"),
        ("본죽&비빔밥 강남점", "bonjuk-bibimbap-kr"),
        ("본죽&비빔밥cafe강남점", "bonjuk-bibimbap-kr"),
    ],
)
def test_reviewed_brand_variants_are_estimates_not_operation_contracts(name, key):
    decision = ChainMatcher(load_registry()).classify(name)
    assert decision.status == "estimated" and decision.brand.key == key


@pytest.mark.parametrize(
    "name",
    [
        "본죽강남점",
        "원조본죽집",
        "본죽집",
        "본죽 비빔밥 강남점",
        "본죽 앤 비빔밥 강남점",
        "본죽 & 비빔밥 강남점",
        "스타벅스옆분식점",
        "스타벅스 커피집점",
        "스타벅스커피전문점",
        "스타벅스 강남점 판매",
        "본죽&미등록브랜드",
        "우리집스타벅스",
        "본죽이네",
        "(주)미등록법인 스타벅스 강남점",
        "스타벅스강남점\n",
        None,
        "",
        "스타벅스 " + "아" * 50 + "점",
    ],
)
def test_substrings_unknown_corporations_and_unapproved_short_concatenation_are_not_positive(name):
    assert ChainMatcher(load_registry()).classify(name).status == "unknown"


def test_alias_collision_remains_conflict_and_does_not_pick_first_brand():
    seeds = load_registry()
    duplicate = seeds[0].model_copy(update={"key": "different-chain"})
    result = ChainMatcher((*seeds, duplicate)).classify(seeds[0].aliases[0])
    assert result.status == "conflict" and result.brand is None


def catalog_row(name, management="BRD_TEST", headquarter="JNG_TEST"):
    return CatalogBrand(2025, management, headquarter, name, normalize_name(name), "외식", "한식")


def test_catalog_is_exact_only_and_approved_source_links_preserve_identity():
    seeds = load_registry()
    rows = (
        catalog_row("체인테스트"),
        catalog_row("본죽", "BRD_20080100243", "JNG_018965"),
        catalog_row("본죽&비빔밥", "BRD_20141221", "JNG_018965"),
    )
    brands = extend_catalog(seeds, rows, date(2026, 11, 15))
    matcher = ChainMatcher(brands)
    assert matcher.classify("체인테스트").status == "estimated"
    assert matcher.classify("체인테스트강남점").status == "unknown"
    assert matcher.classify("본죽").brand.key == "bonjuk-kr"
    assert matcher.classify("본죽&비빔밥").brand.key == "bonjuk-bibimbap-kr"
    assert registry_hash(tuple(reversed(brands))) == registry_hash(brands)


def test_catalog_repeated_ids_ambiguous_names_and_short_names_stay_quarantined():
    rows = (
        catalog_row("이름하나", "DUP", "HQ1"),
        catalog_row("이름둘", "DUP", "HQ2"),
        catalog_row("같은이름", "X1"),
        catalog_row("같은이름", "X2"),
        catalog_row("두자", "X3"),
    )
    matcher = ChainMatcher(extend_catalog(load_registry(), rows, date(2026, 11, 15)))
    for row in rows:
        assert matcher.classify(row.name).status == "unknown"


def test_legacy_false_is_not_negative_chain_proof_and_input_data_stays_unchanged():
    rows = [
        dict(
            source="rest_cafe",
            license_no="synthetic",
            name="스타벅스",
            category="cafe",
            sub_category="cafe",
            is_franchise=False,
            brand_id=None,
        )
    ]
    before = [r.copy() for r in rows]
    matcher = ChainMatcher(load_registry())
    report, plan = compare_rows(rows, matcher)
    assert rows == before
    assert report["status"] == {"estimated": 1}
    assert report["legacy_comparison"]["legacy_false_with_chain_estimate"] == 1
    assert plan[0]["operation_type"] == "unknown"
    assert (report, plan) == compare_rows(rows, matcher)


def test_seed_catalog_link_status_short_alias_rename_and_collision_are_visible():
    seeds = load_registry()
    present = catalog_row("본죽", "BRD_20080100243", "JNG_018965")
    report = catalog_links(seeds, (present,))
    assert report["bonjuk-kr"]["status"] == "present"
    assert report["starbucks-kr"]["status"] == "absent"
    changed = catalog_row("바뀐본죽", "BRD_20080100243", "JNG_018965")
    assert catalog_links(seeds, (changed,))["bonjuk-kr"]["status"] == "name_changed"
    with pytest.raises(ChainsError, match="approved_catalog_alias_changed"):
        extend_catalog(seeds, (changed,), date(2026, 11, 15))
    duplicate = catalog_row("본죽", "BRD_20080100243", "JNG_OTHER")
    assert catalog_links(seeds, (present, duplicate))["bonjuk-kr"]["status"] == "multiple"
    unapproved = catalog_row("스타벅스", "UNAPPROVED", "UNKNOWN")
    report = catalog_links(seeds, (unapproved,))
    assert report["starbucks-kr"]["alias_collision_rows"] == 1
    matcher = ChainMatcher(extend_catalog(seeds, (unapproved,), date(2026, 11, 15)))
    assert matcher.classify("스타벅스").reason == "seed_catalog_name_collision"


def test_legacy_brand_unchecked_and_loss_are_not_reported_as_brand_identity_agreement():
    rows = [dict(name="스타벅스", is_franchise=True), dict(name="미확인 식당", is_franchise=True)]
    report, _ = compare_rows(rows, ChainMatcher(load_registry()))
    assert report["legacy_comparison"]["legacy_positive_brand_unchecked"] == 1
    assert report["legacy_comparison"]["legacy_positive_now_unknown"] == 1
    assert "legacy_positive" not in report["legacy_comparison"]


def test_seed_review_date_is_korean_calendar_even_on_utc_hosts(monkeypatch):
    from datetime import UTC, datetime

    from etl.chains import registry

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            instant = datetime(2026, 11, 14, 16, tzinfo=UTC)
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

    monkeypatch.setattr(registry, "datetime", Clock)
    assert len(registry.load_registry()) == 5
