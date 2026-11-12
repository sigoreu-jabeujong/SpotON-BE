"""Name-match estimates and their non-public version identifiers are kept distinct."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator


class BrandModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)


class PendingClassification(BrandModel):
    status: Literal["pending"] = "pending"
    reason: Literal["brand_mapping_blocked"] = "brand_mapping_blocked"


class EstimatedClassification(BrandModel):
    status: Literal["estimate"] = "estimate"
    reason: Literal["reference_catalog_name_match"] = "reference_catalog_name_match"
    reference_year: int = Field(ge=2000, le=9999)
    source: tuple[Literal["R7"]] = ("R7",)
    coverage: Literal["partial"] = "partial"
    historical_contract_verified: Literal[False] = False
    industry_mapping_verified: Literal[False] = False

    @field_validator("reference_year")
    @classmethod
    def existing_year(cls, value: int) -> int:
        if value > datetime.now(ZoneInfo("Asia/Seoul")).year:
            raise ValueError("invalid reference year")
        return value


class BrandDataVersion(BrandModel):
    catalog_version_id: UUID
    mapping_run_id: UUID
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    store_input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    catalog_rule: Literal["ftc-brand-catalog-exact-name-v2"]
    rule_version: Literal["ftc-name-exact-estimate-v1"]
    reference_year: int = Field(ge=2000, le=9999)


CLASSIFICATION = TypeAdapter(
    Annotated[PendingClassification | EstimatedClassification, Field(discriminator="status")]
)
FranchiseBasis = Literal["catalog_exact_name", "external_classification"]
ESTIMATE_LIMIT: Literal["franchise_name_match_not_contract_or_history"] = (
    "franchise_name_match_not_contract_or_history"
)
