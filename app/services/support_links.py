from app.core.errors import AppError
from app.core.support_catalog import CATALOG_VERSION, DISTRICT_CONTACTS, SUPPORT_LINKS
from app.core.support_sources import MSS_NOTICE_DATE, MSS_NOTICE_URL
from app.db.dependencies import NO_STORE
from app.schemas.common import ApiMeta, ApiResponse, ErrorCode
from app.schemas.support import SupportLinks, SupportLinksQuery


def get_support_links(query: SupportLinksQuery | None = None) -> ApiResponse[SupportLinks]:
    """Show the published district contact first; category never implies eligibility."""
    links = list(SUPPORT_LINKS)
    meta: ApiMeta = {
        "source": ["R17"],
        "as_of": None,
        "space": None,
        "denominator": None,
        "collected_at": None,
        "data_version": None,
        "is_demo": False,
        "link_catalog_version": CATALOG_VERSION,
        "prioritization": {"status": "not_applied", "reason": "general_links_only"},
    }
    if query is not None and query.sigungu is not None:
        contacts = [item.link for item in DISTRICT_CONTACTS if query.sigungu in item.districts]
        if len(contacts) != 1:
            raise AppError(ErrorCode.INTERNAL_ERROR, headers=NO_STORE)
        links.insert(0, contacts[0])
        meta["prioritization"] = {
            "status": "applied",
            "reason": "district_contact_first",
            "category_applied": False,
        }
        meta["district_contact_source"] = {
            "url": MSS_NOTICE_URL,
            "published_on": MSS_NOTICE_DATE,
            "checked_on": contacts[0].last_checked.isoformat(),
            "page": 25,
            "table": "annex_2",
        }
    meta["data_updated_at"] = max(link.last_checked for link in links).isoformat()
    return ApiResponse(
        data=SupportLinks(links=links),
        meta=meta,
    )
