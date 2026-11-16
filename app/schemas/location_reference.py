"""Location-linked source values; independent from historical Risk and whole population."""

from datetime import date
from decimal import ROUND_HALF_UP, Context, Decimal, localcontext
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.population_reference import PopulationReferenceQuery

Status = Literal["ready", "partial", "no_data", "pending", "not_supported"]
Reason = Literal[
    "partial_source_rows",
    "population_source_not_released",
    "admin_boundary_unmatched",
    "source_not_loaded",
    "ambiguous_source_version",
    "outside_coverage",
    "no_spatial_overlap",
    "no_source_rows",
    "source_value_null",
    "mixed_unavailable_reasons",
    "no_data_in_analysis_period",
    "no_complete_day",
    "zero_night_population",
    "mapping_conflict",
    "scope_too_large",
]
Relation = Literal["contains_point", "intersects_radius"]
TimeRelation = Literal["same_period", "earlier_reference", "later_reference"]
TimeMode = Literal["latest_reference", "analysis_period"]
Sha = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class LocationReferenceQuery(PopulationReferenceQuery):
    time_mode: TimeMode = "latest_reference"


class ReferenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)


class Fingerprint(ReferenceModel):
    source_dataset: str = Field(min_length=1, max_length=32)
    rule_version: str = Field(min_length=1, max_length=128)
    input_sha256: Sha
    content_sha256: Sha
    row_count: int = Field(gt=0)


class SalesCatalog(ReferenceModel):
    source_year: int = Field(ge=2000, le=2099)
    sales: Fingerprint
    boundary: Fingerprint
    stores: Fingerprint

    @model_validator(mode="after")
    def datasets_match(self) -> Self:
        if (
            self.sales.source_dataset,
            self.boundary.source_dataset,
            self.stores.source_dataset,
        ) != (
            "OA-15572",
            "OA-15560",
            "OA-15577",
        ):
            raise ValueError("invalid location catalog")
        return self


class AdminObservation(Fingerprint):
    observation_date: date


class AdminCatalog(ReferenceModel):
    boundary: Fingerprint
    observations: tuple[AdminObservation, ...] = Field(min_length=1, max_length=40)
    code_system: Literal["mois_admin8_reference"] = "mois_admin8_reference"
    source_series: Literal["seoul_250m_admin_local"] = "seoul_250m_admin_local"

    @model_validator(mode="after")
    def unique_days(self) -> Self:
        if (
            self.boundary.source_dataset != "OA-22160"
            or any(v.source_dataset != "OA-23016" for v in self.observations)
            or len({v.observation_date for v in self.observations}) != len(self.observations)
        ):
            raise ValueError("invalid admin catalog")
        return self


class LocationCatalog(ReferenceModel):
    format_version: Literal["location-reference-catalog-v1"] = "location-reference-catalog-v1"
    sales: SalesCatalog | None = None
    population: AdminCatalog | None = None


class SourceNumber(ReferenceModel):
    value: str = Field(pattern=r"^(0|[1-9][0-9]*)$")
    display: str = Field(min_length=1)
    unit: Literal["KRW_source_reported"] = "KRW_source_reported"
    rounded: Literal[False] = False
    exact_zero: bool

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.display != f"{int(self.value):,}원" or self.exact_zero != (self.value == "0"):
            raise ValueError("invalid source number")
        if int(self.value) > 2**63 - 1:
            raise ValueError("invalid source number")
        return self


class SalesItem(ReferenceModel):
    store_reference: dict[str, Any] | None = None
    per_store_metric: dict[str, Any] | None = None
    average_contribution: dict[str, Any] | None = None
    market_code: str = Field(pattern=r"^[0-9]{7}$")
    market_name: str
    market_type: Literal["alley", "developed", "traditional_market", "tourism_zone"]
    spatial_relation: Relation
    industry_code: str = Field(pattern=r"^CS10000[1-4]$|^CS100010$")
    industry_name: str
    source_quarter: str | None = Field(default=None, pattern=r"^20[0-9]{2}[1-4]$")
    period_end_after_analysis: bool = False
    temporal_relation: TimeRelation | None = None
    metric: SourceNumber | None = None
    status: Literal["ready", "no_data"]
    reason: Reason | None = None
    amount_basis: Literal["source_reported"] = "source_reported"
    amount_period_status: Literal["unverified"] = "unverified"
    selection_reason: Literal["latest_numeric_row", "analysis_period"]
    provenance_ref: Literal["sales"] = "sales"
    excluded_source_rows: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.status == "ready":
            if self.metric is None or self.source_quarter is None or self.reason is not None:
                raise ValueError("invalid sales item")
        elif self.metric is not None or self.reason is None:
            raise ValueError("invalid sales item")
        return self


class SalesBlock(ReferenceModel):
    per_store_average: dict[str, Any] | None = None
    status: Status
    reason: Reason | None = None
    items: tuple[SalesItem, ...] = ()
    excluded_count: int = Field(default=0, ge=0)
    excluded_counts: dict[str, int] = Field(default_factory=dict)
    reason_counts: dict[Reason, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.per_store_average is not None:
            from app.services.per_store_sales import metric
            from app.services.sales_distribution import distribution
            from app.services.store_weighted_sales import store_weighted_distribution

            avg = self.per_store_average
            has_distribution = "representative_method" in avg or "distribution" in avg
            if has_distribution and "distribution" not in avg:
                raise ValueError("missing representative distribution")
            if has_distribution and avg.get("representative_method") not in (
                "median_of_reference_per_store_ratios_v1",
                "pooled_sales_over_total_stores_v1",
                "store_weighted_median_v1",
            ):
                raise ValueError("invalid representative method")
            weighted = avg.get("representative_method") == "store_weighted_median_v1"
            if weighted and "store_weighted_distribution" not in avg:
                raise ValueError("missing weighted distribution projection")
            pooled = (
                weighted or avg.get("representative_method") == "pooled_sales_over_total_stores_v1"
            )
            expected_basis = (
                "store_weighted_histogram_v1"
                if weighted
                else "each_sales_over_group_total_stores_v1"
            )
            if pooled and avg.get("graph_basis") != expected_basis:
                raise ValueError("invalid pooled graph basis")
            if avg["listed_item_count"] != len(self.items) or (
                avg["included_item_count"] + sum(avg["excluded_counts"].values()) != len(self.items)
            ):
                raise ValueError("invalid average coverage")
            group_quarters = [g["source_quarter"] for g in avg["groups"]]
            expected_quarters = {i.source_quarter for i in self.items if i.metric}
            if (
                len(group_quarters) != len(set(group_quarters))
                or set(group_quarters) != expected_quarters
            ):
                raise ValueError("invalid distribution quarters")
            for item in self.items:
                ref = item.store_reference
                expected_metric = None
                if item.metric and ref and ref.get("status") == "ready":
                    count = ref.get("total_stores")
                    if (
                        not isinstance(count, str)
                        or not count.isascii()
                        or not count.isdigit()
                        or str(int(count)) != count
                        or not 0 <= int(count) <= 2**31 - 1
                    ):
                        raise ValueError("invalid member store count")
                    if ref.get("source_quarter") != item.source_quarter:
                        raise ValueError("invalid member store quarter")
                    if int(count) > 0:
                        expected_metric = metric(int(item.metric.value), int(count))
                if item.per_store_metric != expected_metric:
                    raise ValueError("invalid item per-store projection")
            for group in avg["groups"]:
                if weighted and "store_weighted_distribution" not in group:
                    raise ValueError("missing group weighted distribution")
                if ("distribution" in group) != has_distribution:
                    raise ValueError("inconsistent distribution format")
                keys = group["included_item_keys"]
                used = [
                    i
                    for i in self.items
                    if any(
                        (i.market_code, i.source_quarter, i.industry_code)
                        == (k["market_code"], k["source_quarter"], k["industry_code"])
                        for k in keys
                    )
                ]
                if len(used) != len(keys) or len(used) != group["included_item_count"]:
                    raise ValueError("invalid average membership")
                candidates = [
                    i
                    for i in self.items
                    if i.metric and i.source_quarter == group["source_quarter"]
                ]
                eligible = [i for i in candidates if i.per_store_metric is not None]
                if used != eligible or group["candidate_item_count"] != len(candidates):
                    raise ValueError("invalid distribution eligibility")
                if group["candidate_item_count"] != len(used) + sum(
                    group["excluded_counts"].values()
                ):
                    raise ValueError("invalid group coverage")
                if used:
                    pairs = []
                    for item in used:
                        reference = item.store_reference
                        if (
                            item.metric is None
                            or reference is None
                            or reference.get("status") != "ready"
                            or not isinstance(reference.get("total_stores"), str)
                            or not reference["total_stores"].isdigit()
                            or int(reference["total_stores"]) <= 0
                            or item.source_quarter != group["source_quarter"]
                        ):
                            raise ValueError("invalid distribution member")
                        pair = (int(item.metric.value), int(reference["total_stores"]))
                        if item.per_store_metric != metric(*pair):
                            raise ValueError("invalid member per-store value")
                        if group["source_quarter"] == avg["primary_quarter"] and (
                            not item.average_contribution
                            or item.average_contribution.get("status") != "included"
                        ):
                            raise ValueError("invalid primary member contribution")
                        if group["source_quarter"] != avg["primary_quarter"] and (
                            not item.average_contribution
                            or item.average_contribution.get("status") != "different_quarter"
                        ):
                            raise ValueError("invalid other-quarter contribution")
                        pairs.append(pair)
                    expected_distribution = distribution(pairs)
                    if weighted and group.get(
                        "store_weighted_distribution"
                    ) != store_weighted_distribution(pairs):
                        raise ValueError("invalid store weighted distribution")
                    if has_distribution and (
                        group.get("distribution") != expected_distribution
                        or expected_distribution is None
                        or expected_distribution["sample_count"] != len(used)
                    ):
                        raise ValueError("invalid sales distribution")
                    s = sum(int(i.metric.value) for i in used if i.metric)
                    n = sum(
                        int(i.store_reference["total_stores"]) for i in used if i.store_reference
                    )
                    if (group["total_sales"], group["total_store_count"], group["metric"]) != (
                        str(s),
                        str(n),
                        metric(s, n),
                    ):
                        raise ValueError("invalid average value")
                    if pooled and group.get("contributions") != [
                        dict(
                            market_code=i.market_code,
                            industry_code=i.industry_code,
                            source_quarter=i.source_quarter,
                            metric=metric(int(i.metric.value), n),
                        )
                        for i in used
                        if i.metric
                    ]:
                        raise ValueError("invalid pooled contributions")
                elif group["metric"] is not None or group.get("distribution") is not None:
                    raise ValueError("invalid empty average")
                elif pooled and group.get("contributions") != []:
                    raise ValueError("invalid empty contributions")
                if weighted and not used and group.get("store_weighted_distribution") is not None:
                    raise ValueError("invalid empty weighted distribution")
            primary = next(
                (g for g in avg["groups"] if g["source_quarter"] == avg["primary_quarter"]), None
            )
            projection_keys = ["metric", "total_sales", "total_store_count"]
            if avg["included_item_count"] != (primary["included_item_count"] if primary else 0):
                raise ValueError("invalid primary count projection")
            if has_distribution:
                projection_keys.append("distribution")
            if weighted:
                projection_keys.append("store_weighted_distribution")
            if pooled and avg.get("contributions") != (primary["contributions"] if primary else []):
                raise ValueError("invalid contribution projection")
            for key in projection_keys:
                if avg[key] != (primary[key] if primary else None):
                    raise ValueError("invalid average projection")
        if (self.status == "ready") != (self.reason is None):
            raise ValueError("invalid sales block")
        if self.excluded_count != sum(self.excluded_counts.values()) or any(
            v < 0 for v in self.excluded_counts.values()
        ):
            raise ValueError("invalid excluded counts")
        if any(v <= 0 for v in self.reason_counts.values()) or sum(
            self.reason_counts.values()
        ) != sum(row.reason is not None for row in self.items):
            raise ValueError("invalid reason counts")
        return self


class PopulationNumber(ReferenceModel):
    value: str | None = Field(pattern=r"^(0|[1-9][0-9]*)(\.[0-9]{1,80})?$")
    display: str | None
    unit: Literal["estimated_people_hourly_mean", "ratio", "pct_of_local_hourly_population"]
    rounded: bool
    exact_zero: bool
    reason: Literal["zero_night_population", "zero_population_total"] | None = None

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.value is None:
            if self.display is not None or self.rounded or self.exact_zero or self.reason is None:
                raise ValueError("invalid population number")
            return self
        value = Decimal(self.value)
        places = 5 if self.unit == "ratio" else 1
        with localcontext(Context(prec=80, rounding=ROUND_HALF_UP)):
            shown = value.quantize(Decimal(1).scaleb(-places))
        suffix = (
            "명"
            if self.unit == "estimated_people_hourly_mean"
            else "%"
            if self.unit == "pct_of_local_hourly_population"
            else ""
        )
        if (
            self.reason is not None
            or self.exact_zero != value.is_zero()
            or self.rounded != (shown != value)
            or self.display != f"{shown:,.{places}f}{suffix}"
        ):
            raise ValueError("invalid population number")
        return self


class AdminPopulationItem(ReferenceModel):
    area_ref: Sha
    area_name: str
    spatial_relation: Relation
    spatial_unit: Literal["admin_dong"] = "admin_dong"
    observation_date: date
    source_month: str = Field(pattern=r"^20[0-9]{2}(0[1-9]|1[0-2])$")
    temporal_relation: TimeRelation
    population_scope: Literal["local"] = "local"
    mean_24h: PopulationNumber | None
    status: Literal["ready", "no_data"]
    reason: Reason | None
    selection_reason: Literal["latest_complete_day", "analysis_period"]
    observed_hours: int = Field(ge=0, le=24)
    source_hours: int = Field(ge=0, le=24)
    provenance_ref: str


class AdminDayNightItem(ReferenceModel):
    area_ref: Sha
    observation_date: date
    population_scope: Literal["local"] = "local"
    mean_day: PopulationNumber | None
    mean_night: PopulationNumber | None
    day_night_ratio: PopulationNumber | None
    day_share_pct: PopulationNumber | None
    night_share_pct: PopulationNumber | None
    hour_rule: Literal["spoton_06_18_v1"] = "spoton_06_18_v1"
    status: Literal["ready", "partial", "no_data"]
    reason: Reason | None
    provenance_ref: str


class AdminPopulationBlock(ReferenceModel):
    status: Status = "pending"
    reason: Reason | None = "population_source_not_released"
    items: tuple[AdminPopulationItem, ...] = ()


class AdminDayNightBlock(ReferenceModel):
    status: Status = "pending"
    reason: Reason | None = "population_source_not_released"
    items: tuple[AdminDayNightItem, ...] = ()


class LocationReference(ReferenceModel):
    requested_as_of: str | None
    analysis_as_of: date
    time_mode: TimeMode
    sales: SalesBlock
    living_population: AdminPopulationBlock = Field(default_factory=AdminPopulationBlock)
    day_night: AdminDayNightBlock = Field(default_factory=AdminDayNightBlock)
