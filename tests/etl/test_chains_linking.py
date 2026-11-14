from collections import Counter
from datetime import date

from etl.chains.linking import OutletIndex, address_keys
from etl.chains.matching import ChainMatcher
from etl.chains.registry import extend_catalog, load_registry
from tests.etl.test_chains_matching import catalog_row
from tests.etl.test_chains_semas import item, make_snapshot


def row(**changes):
    return {
        **dict(
            name="본죽강남점",
            address_road="서울특별시 강남구 테헤란로 1",
            address_jibun="서울특별시 강남구 역삼동 1",
            building_key=None,
            floor_unit="1층",
            status="open",
            close_date=None,
            open_date=date(2020, 1, 1),
            date_flag=None,
            is_temporary=False,
        ),
        **changes,
    }


def counts(values):
    return Counter(address_keys(values["address_jibun"], values["address_road"]))


def test_separate_branch_and_address_can_corroborate_short_alias_but_not_confirm():
    data = item()
    data["bizesNm"] = "본죽"
    index = OutletIndex(make_snapshot([data]), ChainMatcher(load_registry()))
    values = row()
    decision, source_id = index.corroborate(values, counts(values))
    assert decision.status == "estimated"
    assert decision.reason == "semas_address_corroborated" and source_id == data["bizesId"]


def test_same_address_without_brand_token_never_becomes_a_brand_outlet():
    data = item()
    index = OutletIndex(make_snapshot([data]), ChainMatcher(load_registry()))
    values = row(name="동네 독립 식당")
    decision, source_id = index.corroborate(values, counts(values))
    assert decision.status == "unknown" and decision.reason == "address_only_candidate"
    assert source_id is None


def test_same_building_different_floor_name_or_temporal_identity_does_not_corroborate():
    data = item()
    data["bizesNm"] = "본죽"
    index = OutletIndex(make_snapshot([data]), ChainMatcher(load_registry()))
    for changes in (
        dict(floor_unit="2층"),
        dict(floor_unit="2~3층"),
        dict(name="본죽이네 강남점"),
        dict(status="closed"),
        dict(open_date=None),
        dict(open_date=date(2026, 2, 1)),
        dict(date_flag="invalid"),
        dict(close_date=date(2026, 1, 2)),
        dict(is_temporary=True),
    ):
        values = row(**changes)
        decision, source_id = index.corroborate(values, counts(values))
        assert decision is None and source_id is None


def test_multiple_provider_or_license_records_are_not_forced_into_one_outlet():
    data = item()
    data["bizesNm"] = "본죽"
    second = {**data, "bizesId": "SYNTHETIC2"}
    values = row()
    matcher = ChainMatcher(load_registry())
    index = OutletIndex(make_snapshot([data, second]), matcher)
    decision, source_id = index.corroborate(values, counts(values))
    assert decision.status == "unknown" and source_id is None


def test_catalog_branch_needs_specific_provider_branch_and_address_not_a_global_suffix_rule():
    brands = extend_catalog(load_registry(), (catalog_row("지역체인테스트"),), date(2026, 11, 15))
    matcher = ChainMatcher(brands)
    assert matcher.classify("지역체인테스트강남점").status == "unknown"
    data = item()
    data["bizesNm"] = "지역체인테스트"
    index = OutletIndex(make_snapshot([data]), matcher)
    values = row(name="지역체인테스트강남점")
    decision, source_id = index.corroborate(values, counts(values))
    assert decision.status == "estimated" and decision.reason == "semas_address_corroborated"
    assert source_id is not None
    # Same prefix + same building is still insufficient without the same complete branch.
    bad = row(name="지역체인테스트집강남점")
    assert index.corroborate(bad, counts(bad)) == (None, None)
    index = OutletIndex(make_snapshot([data]), matcher)
    duplicate_counts = {k: 2 for k in counts(values)}
    decision, source_id = index.corroborate(values, duplicate_counts)
    assert decision.status == "unknown" and source_id is None


def test_provider_separate_branch_cannot_restore_rejected_sibling_brand_or_menu_tail():
    data = item()
    data["bizesNm"] = "본죽"
    data["brchNm"] = "앤 비빔밥 강남점"
    matcher = ChainMatcher(load_registry())
    index = OutletIndex(make_snapshot([data]), matcher)
    values = row(name="본죽 앤 비빔밥 강남점")
    assert matcher.classify(values["name"]).status == "unknown"
    assert index.corroborate(values, counts(values)) == (None, None)
