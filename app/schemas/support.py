from datetime import date
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.support_sources import MSS_NOTICE_URL
from app.schemas.geocode import Category
from etl.localdata.constants import SEOUL_AUTHORITY_CODES

SEOUL_DISTRICTS = frozenset(SEOUL_AUTHORITY_CODES.values())
OFFICIAL_HOSTS = frozenset(
    {"www.seoulsbdc.or.kr", "edu.seoulsbdc.or.kr", "news.seoul.go.kr", "www.sbiz24.kr"}
)


class SupportLinksQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    sigungu: str | None = None
    category: Category | None = None

    @field_validator("sigungu")
    @classmethod
    def seoul_district(cls, value: str | None) -> str | None:
        if value is not None and value not in SEOUL_DISTRICTS:
            raise ValueError("unsupported district")
        return value


class SupportLink(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, hide_input_in_errors=True)

    id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    org_name: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    url: str
    type: Literal["consulting", "support_program"]
    region: Literal["서울", "전국"]
    last_checked: date

    @field_validator("url")
    @classmethod
    def official_https_url(cls, value: str) -> str:
        if value == MSS_NOTICE_URL:
            return value
        if (
            any(ord(char) <= 32 or ord(char) == 127 for char in value)
            or "?" in value
            or "#" in value
        ):
            raise ValueError("unsupported link")
        parts = urlsplit(value)
        if (
            parts.scheme != "https"
            or not parts.netloc.isascii()
            or parts.netloc.lower() not in OFFICIAL_HOSTS
        ):
            raise ValueError("unsupported link")
        return value


class SupportLinks(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    links: list[SupportLink]
