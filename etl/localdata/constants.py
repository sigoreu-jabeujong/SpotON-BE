from enum import StrEnum


class Source(StrEnum):
    GENERAL_RESTAURANT = "general_restaurant"
    REST_CAFE = "rest_cafe"


# 공식 Swagger 1.0.0 (2026-11-10 확인)
# https://www.data.go.kr/data/15154916/openapi.do
# https://www.data.go.kr/data/15154921/openapi.do
SOURCE_ENDPOINTS: dict[Source, str] = {
    Source.GENERAL_RESTAURANT: "https://apis.data.go.kr/1741000/general_restaurants/info",
    Source.REST_CAFE: "https://apis.data.go.kr/1741000/rest_cafes/info",
}
PAGE_SIZE = 100
# Live responses use 0; retain 00 for the previously documented/fixture format.
SUCCESS_RESULT_CODES = frozenset({"0", "00"})

# 공공데이터포털 공식 공지 NOTICE_0000000004824 첨부자료
# 개방자치단체코드_영업상태코드_행정체제개편반영_20260702.xlsx
SEOUL_AUTHORITY_CODES: dict[str, str] = {
    "3000000": "종로구",
    "3010000": "중구",
    "3020000": "용산구",
    "3030000": "성동구",
    "3040000": "광진구",
    "3050000": "동대문구",
    "3060000": "중랑구",
    "3070000": "성북구",
    "3080000": "강북구",
    "3090000": "도봉구",
    "3100000": "노원구",
    "3110000": "은평구",
    "3120000": "서대문구",
    "3130000": "마포구",
    "3140000": "양천구",
    "3150000": "강서구",
    "3160000": "구로구",
    "3170000": "금천구",
    "3180000": "영등포구",
    "3190000": "동작구",
    "3200000": "관악구",
    "3210000": "서초구",
    "3220000": "강남구",
    "3230000": "송파구",
    "3240000": "강동구",
}
