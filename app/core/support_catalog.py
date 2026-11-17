"""API v1.2 §4-9 / data specification §2.3 D-08: quarterly manual link review."""

from dataclasses import dataclass
from datetime import date

from app.core.support_sources import MSS_NOTICE_URL
from app.schemas.support import SupportLink

CATALOG_VERSION = "support-links-v2"
CHECKED_ON = date(2026, 11, 12)
SUPPORT_LINKS = (
    SupportLink(
        id="seoulsbdc",
        org_name="서울시 자영업지원센터",
        title="창업·경영 상담 안내",
        description="공식 홈페이지에서 창업·경영 상담과 지원 안내를 확인하세요.",
        url="https://www.seoulsbdc.or.kr/main.do",
        type="consulting",
        region="서울",
        last_checked=CHECKED_ON,
    ),
    SupportLink(
        id="seoulsbdc-edu",
        org_name="소상공인아카데미",
        title="창업·경영 교육 안내",
        description="예비창업자·소상공인을 위한 교육 과정과 수강 안내를 확인하세요.",
        url="https://edu.seoulsbdc.or.kr/main/index.jsp",
        type="support_program",
        region="서울",
        last_checked=CHECKED_ON,
    ),
    SupportLink(
        id="seoul-small-business",
        org_name="서울시 소상공인 지원사업 안내",
        title="서울시 지원사업 안내",
        description="서울시 소상공인 종합지원 사업과 기관별 안내를 확인하세요.",
        url="https://news.seoul.go.kr/economy/small-business-supports",
        type="support_program",
        region="서울",
        last_checked=CHECKED_ON,
    ),
    SupportLink(
        id="sbiz24",
        org_name="소상공인24",
        title="소상공인 지원사업 통합 안내",
        description="전국 소상공인 지원사업 공고와 신청 안내를 확인하세요.",
        url="https://www.sbiz24.kr",
        type="support_program",
        region="전국",
        last_checked=CHECKED_ON,
    ),
)


@dataclass(frozen=True)
class DistrictContact:
    districts: frozenset[str]
    link: SupportLink


def _contact(
    identifier: str, center: str, phone: str, districts: tuple[str, ...]
) -> DistrictContact:
    return DistrictContact(
        districts=frozenset(districts),
        link=SupportLink(
            id="semas-seoul-" + identifier,
            org_name="소상공인시장진흥공단 " + center,
            title=center + " 지역센터 연락처 안내",
            description=(
                "2026년 공고 별표2 기준 관할: "
                + "·".join(districts)
                + ". 전화: "
                + phone
                + ". 연결된 공고의 첨부 PDF 25쪽을 확인하세요."
            ),
            url=MSS_NOTICE_URL,
            type="consulting",
            region="서울",
            last_checked=CHECKED_ON,
        ),
    )


DISTRICT_CONTACTS = (
    _contact("jungbu", "서울중부센터", "02-720-4711", ("중구", "종로구", "성북구", "동대문구")),
    _contact("dongbu", "서울동부센터", "02-2215-0981", ("광진구", "성동구", "강동구", "중랑구")),
    _contact("seobu", "서울서부센터", "02-839-8311", ("강서구", "양천구", "영등포구")),
    _contact("nambu", "서울남부센터", "02-585-8622", ("강남구", "서초구", "송파구")),
    _contact("bukbu", "서울북부센터", "02-990-9101", ("노원구", "도봉구", "강북구")),
    _contact("dongjak", "서울동작센터", "02-3482-6686", ("동작구", "용산구")),
    _contact("gwanak", "서울관악센터", "02-889-9262", ("관악구", "구로구", "금천구")),
    _contact("seodaemun", "서울서대문센터", "02-323-2915", ("서대문구", "은평구", "마포구")),
)
