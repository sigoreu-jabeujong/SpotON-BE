from datetime import UTC, datetime

from etl.brands.catalog import PAGE_SIZE, build_catalog, canonical


def item(identifier="00001", name="예시카페", industry="외식", **changes):
    return {
        "jngBizCrtraYr": "2025",
        "brandMnno": identifier,
        "jnghdqrtrsMnno": "HQ_00001",
        "brandNm": name,
        "indutyLclasNm": industry,
        "indutyMlsfcNm": "synthetic",
        "corpNm": "PRIVATE_CORP_CANARY",
        "jnghdqrtrsRprsvNm": "PRIVATE_PERSON_CANARY",
        "brno": "PRIVATE_BUSINESS_CANARY",
        **changes,
    }


def response(items=None, number=1, total=None, **changes):
    items = items if items is not None else [item()]
    return {
        "resultCode": "00",
        "resultMsg": "normal",
        "numOfRows": str(PAGE_SIZE),
        "pageNo": str(number),
        "totalCount": total if total is not None else len(items),
        "items": items,
        **changes,
    }


def catalog(items=None):
    raw = canonical(response(items))
    return build_catalog(2025, (raw,), raw, datetime.now(UTC))
