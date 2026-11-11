from datetime import date
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from app.schemas.market_judgement import BoundaryJudgement
from app.schemas.nearby import NearbyQuery

MIN_CLOSURE_SAMPLE = 10
MIN_SURVIVAL_SAMPLE = 5
RiskInclude = Literal["market_change", "day_night_ratio"]
IndicatorId = Literal[
    "official_closure_rate",
    "official_risk",
    "closure_rate_12m",
    "survival_rate_1y",
    "survival_rate_3y",
    "competitor_count",
    "market_change",
    "day_night_ratio",
]
REQUIRED_IDS = (
    "official_closure_rate",
    "official_risk",
    "closure_rate_12m",
    "survival_rate_1y",
    "survival_rate_3y",
    "competitor_count",
)


class RiskQuery(NearbyQuery):
    include: tuple[RiskInclude, ...] = ()

    @field_validator("include", mode="before")
    @classmethod
    def comma_include(cls, value: Any) -> Any:
        return value.split(",") if isinstance(value, str) else value

    @field_validator("include")
    @classmethod
    def unique_include(cls, value: tuple[RiskInclude, ...]) -> tuple[RiskInclude, ...]:
        if len(value) != len(set(value)):
            raise ValueError("duplicate include")
        return value


class RiskModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, hide_input_in_errors=True, allow_inf_nan=False
    )


class ReferenceCounts(RiskModel):
    cohort_size: int = Field(ge=0)
    active: int = Field(ge=0)
    closure_num: int = Field(ge=0)
    closure_den: int = Field(ge=0)
    survival_1_num: int = Field(ge=0)
    survival_1_den: int = Field(ge=0)
    survival_3_num: int = Field(ge=0)
    survival_3_den: int = Field(ge=0)

    @model_validator(mode="after")
    def consistent_counts(self) -> Self:
        if self.closure_den != self.active + self.closure_num:
            raise ValueError("inconsistent closure partition")
        for num, den in (
            (self.closure_num, self.closure_den),
            (self.survival_1_num, self.survival_1_den),
            (self.survival_3_num, self.survival_3_den),
        ):
            if num > den or den > self.cohort_size:
                raise ValueError("inconsistent reference cohort")
        return self


class RiskIndicator(RiskModel):
    id: IndicatorId
    type: Literal["official", "reference"]
    value: int | float | None = Field(ge=0)
    unit: Literal["%", "개"] | None = None
    numerator: int | None = Field(default=None, ge=0)
    denominator: int | None = Field(default=None, ge=0)
    seoul_avg: float | None = Field(default=None, ge=0, le=100)
    seoul_avg_reason: str | None = "not_applicable"
    seoul_numerator: int | None = Field(default=None, ge=0)
    seoul_denominator: int | None = Field(default=None, ge=0)
    space: str
    period: str | None = None
    source: list[str]
    status: Literal["fact", "pending", "link_only"]
    reason: str | None
    link: str | None = None
    copy_text: None = None

    @model_validator(mode="after")
    def consistent_value(self) -> Self:
        official = self.id in {"official_closure_rate", "official_risk", "market_change"}
        if (self.type == "official") != official:
            raise ValueError("invalid indicator type")
        expected_source = (
            ["R1"]
            if self.id == "official_risk"
            else ["R2"]
            if official
            else ["R4"]
            if self.id == "day_night_ratio"
            else ["R5", "R6"]
        )
        if self.source != expected_source:
            raise ValueError("invalid indicator source")
        if (
            self.id in {"official_closure_rate", "market_change", "day_night_ratio"}
            and self.status != "pending"
        ):
            raise ValueError("unverified data cannot be activated")
        if self.status == "fact":
            if self.value is None or self.reason is not None:
                raise ValueError("fact requires a value")
        elif self.value is not None or not self.reason or self.numerator is not None:
            raise ValueError("pending indicator cannot have a value")
        if (self.status == "link_only") != (self.id == "official_risk"):
            raise ValueError("link_only is reserved for official risk")
        if (self.link is not None) != (self.status == "link_only"):
            raise ValueError("invalid link")
        for num, den in (
            (self.numerator, self.denominator),
            (self.seoul_numerator, self.seoul_denominator),
        ):
            if num is not None and den is not None and num > den:
                raise ValueError("numerator exceeds denominator")
        if self.unit == "%" and self.value is not None:
            if self.value > 100 or not self.denominator or self.numerator is None:
                raise ValueError("invalid rate")
        if self.id in {"closure_rate_12m", "survival_rate_1y", "survival_rate_3y"}:
            minimum = MIN_CLOSURE_SAMPLE if self.id == "closure_rate_12m" else MIN_SURVIVAL_SAMPLE
            if self.denominator is None or self.seoul_denominator is None or self.unit != "%":
                raise ValueError("rate requires cohorts")
            if (self.status == "fact") != (self.denominator >= minimum):
                raise ValueError("invalid sample status")
            if (self.seoul_avg is not None) != (self.seoul_denominator >= minimum):
                raise ValueError("invalid comparison sample status")
        if (self.seoul_avg is None) != (self.seoul_avg_reason is not None):
            raise ValueError("comparison requires a reason or a value")
        if self.seoul_avg is not None and (
            not self.seoul_denominator or self.seoul_numerator is None
        ):
            raise ValueError("comparison requires a cohort")
        if self.seoul_avg is None and self.seoul_numerator is not None:
            raise ValueError("unavailable comparison cannot have a numerator")
        if self.id == "competitor_count" and (
            not isinstance(self.value, int)
            or self.denominator is not None
            or self.seoul_avg is not None
            or self.seoul_avg_reason != "not_applicable"
            or self.unit != "개"
        ):
            raise ValueError("count requires an integer without a comparison")
        return self


class RiskMarket(RiskModel):
    status: Literal["unverified"] = "unverified"
    market_code: None = None
    market_name: None = None
    market_type: None = None
    also_in: list[None] = Field(default_factory=list, max_length=0)
    nearby_markets: list[None] = Field(default_factory=list, max_length=0)
    reason: Literal["boundary_period_not_verified", "boundary_version_not_selected"]
    spatial_candidate: BoundaryJudgement | None

    @model_validator(mode="after")
    def candidate_reason(self) -> Self:
        if (self.spatial_candidate is None) != (self.reason == "boundary_version_not_selected"):
            raise ValueError("invalid boundary reason")
        return self


class RiskQueryEcho(RiskModel):
    lat: float = Field(repr=False)
    lng: float = Field(repr=False)
    category: Literal["cafe", "restaurant"]
    radius_m: int
    as_of: date
    filters: dict[str, JsonValue]


class RiskFlags(RiskModel):
    insufficient_sample: bool
    missing: list[IndicatorId]


class Risk(RiskModel):
    query: RiskQueryEcho
    market: RiskMarket
    indicators: list[RiskIndicator]
    flags: RiskFlags

    @model_validator(mode="after")
    def complete_result(self) -> Self:
        ids = [r.id for r in self.indicators]
        expected_ids = [
            *REQUIRED_IDS,
            *[v for v in ("market_change", "day_night_ratio") if v in ids],
        ]
        if ids != expected_ids:
            raise ValueError("incomplete indicators")
        expected_missing = [
            r.id
            for r in self.indicators
            if r.status == "pending"
            and r.id in {"official_closure_rate", "market_change", "day_night_ratio"}
        ]
        if self.flags.missing != expected_missing:
            raise ValueError("invalid missing flags")
        small = any(
            r.status == "pending"
            for r in self.indicators
            if r.id in {"closure_rate_12m", "survival_rate_1y", "survival_rate_3y"}
        )
        if small != self.flags.insufficient_sample:
            raise ValueError("invalid sample flag")
        return self
