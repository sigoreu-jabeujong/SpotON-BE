from datetime import date

import pytest

from etl.brands.catalog import Brand, normalize_name
from etl.chains.common import ChainsError
from etl.chains.matching import ChainMatcher
from etl.chains.registry import extend_catalog, load_registry


@pytest.mark.parametrize(
    "name,key",
    [
        ("이디야커피 강남점", "ediya-kr"),
        ("이디야강남점", "ediya-kr"),
        ("메가커피 강남점", "mega-mgc-kr"),
        ("메가MGC커피강남점", "mega-mgc-kr"),
        ("빽다방강남점", "paikdabang-kr"),
        ("(주)더본코리아 빽다방 강남점", "paikdabang-kr"),
        ("할리스 강남점", "hollys-kr"),
        ("블루보틀 강남점", "bluebottle-kr"),
        ("새마을식당 강남점", "newmaul-kr"),
        ("한신포차강남점", "hanshinpocha-kr"),
        ("역전우동0410 강남점", "udon0410-kr"),
        ("롤링파스타 강남점", "rollingpasta-kr"),
        ("미정국수0410 강남점", "mijung0410-kr"),
        ("프릳츠 도화", "fritz-kr"),
        ("하이브 프릳츠", "fritz-kr"),
        ("앤트러사이트 서교점", "anthracite-kr"),
    ],
)
def test_reviewed_brands_and_small_chains_are_estimates(name, key):
    decision = ChainMatcher(load_registry()).classify(name)
    assert decision.status == "estimated" and decision.brand.key == key


@pytest.mark.parametrize(
    "name",
    [
        "메가강남점",
        "메가커피옆분식점",
        "프릳츠 미등록지명",
        "미정국수강남점",
        "역전우동강남점",
        "우리동네이디야커피",
        "블루보틀 전문판매점",
        "(주)미승인법인 빽다방 강남점",
        "앤트러사이트 맞은편점",
    ],
)
def test_unapproved_short_names_descriptions_and_corporations_stay_unknown(name):
    assert ChainMatcher(load_registry()).classify(name).status == "unknown"


def test_distinct_catalog_subbrand_does_not_become_reviewed_parent():
    seeds = load_registry()
    name = "빽다방빵연구소"
    subbrand = Brand(
        2025, "BRD_SUBBRAND", "JNG_SUBBRAND", name, normalize_name(name), "외식", "커피"
    )
    matcher = ChainMatcher(extend_catalog(seeds, (subbrand,), date(2026, 11, 16)))
    assert matcher.classify(name).brand.origin == "ftc_exact"
    assert matcher.classify(name + "강남점").status == "unknown"
    assert matcher.classify("빽다방 강남점").brand.key == "paikdabang-kr"


def test_approved_catalog_identity_is_not_duplicated_or_overridden():
    seeds = load_registry()
    brand = next(b for b in seeds if b.key == "mega-mgc-kr")
    ref = brand.ftc_refs[0]
    name = "메가엠지씨커피(MEGA MGC COFFEE)"
    approved = Brand(2025, *ref, name, normalize_name(name), "외식", "커피")
    matcher = ChainMatcher(extend_catalog(seeds, (approved,), date(2026, 11, 16)))
    assert matcher.classify(name).brand.key == brand.key
    collision = Brand(
        2025, "BRD_UNAPPROVED", "JNG_OTHER", name, normalize_name(name), "외식", "커피"
    )
    with pytest.raises(ChainsError, match="ambiguous_reviewed_catalog_name"):
        extend_catalog(seeds, (approved, collision), date(2026, 11, 16))


def test_reviewed_seed_prefix_overlap_is_limited_to_explicit_bonjuk_family():
    seeds = load_registry()
    overlaps = {
        (parent.key, child.key)
        for parent in seeds
        if parent.branch_patterns
        for child in seeds
        if child.key != parent.key
        for alias in parent.aliases
        for other in child.aliases
        if normalize_name(other).startswith(normalize_name(alias))
    }
    assert overlaps == {("bonjuk-kr", "bonjuk-bibimbap-kr")}


@pytest.mark.parametrize(
    "name",
    [
        "이디야커피 할리스점",
        "빽다방 새마을식당점",
        "메가커피 할리스점",
        "할리스커피 빽다방점",
        "이디야커피 프릳츠점",
        "메가커피 하이브 프릳츠점",
    ],
)
def test_mixed_reviewed_brands_do_not_become_estimates(name):
    assert ChainMatcher(load_registry()).classify(name).status != "estimated"


def test_official_hollys_coffee_spelling_is_an_estimate():
    result = ChainMatcher(load_registry()).classify("할리스커피")
    assert result.status == "estimated" and result.brand.key == "hollys-kr"
