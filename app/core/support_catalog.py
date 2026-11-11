"""API v1.2 §4-9 / data specification §2.3 D-08: quarterly manual link review."""

from datetime import date

from app.schemas.support import SupportLink

CATALOG_VERSION = "support-links-v1"
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
