from app.core.support_catalog import CATALOG_VERSION, SUPPORT_LINKS
from app.schemas.common import ApiResponse
from app.schemas.support import SupportLinks


def get_support_links() -> ApiResponse[SupportLinks]:
    """API v1.2 §4-9: general links only; district/category ranking is not applied."""
    return ApiResponse(
        data=SupportLinks(links=list(SUPPORT_LINKS)),
        meta={
            "source": ["R17"],
            "as_of": None,
            "space": None,
            "denominator": None,
            "collected_at": None,
            "data_version": None,
            "is_demo": False,
            "data_updated_at": max(link.last_checked for link in SUPPORT_LINKS).isoformat(),
            "link_catalog_version": CATALOG_VERSION,
            "prioritization": {"status": "not_applied", "reason": "general_links_only"},
        },
    )
