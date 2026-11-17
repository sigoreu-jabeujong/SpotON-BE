from dataclasses import dataclass, fields
from typing import Any


@dataclass(frozen=True, slots=True)
class LocalDataRow:
    authority_code: str | None
    management_no: str | None
    business_name: str | None
    road_address: str | None
    jibun_address: str | None
    status_name: str | None
    status_code: str | None
    detail_status_name: str | None
    detail_status_code: str | None
    business_type_name: str | None
    business_kind_name: str | None
    location_area: str | None
    facility_total_scale: str | None
    license_date: str | None
    closure_date: str | None
    raw_x: str | None
    raw_y: str | None
    update_type: str | None
    update_point: str | None
    last_modified_point: str | None

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> "LocalDataRow":
        def text(key: str) -> str | None:
            value = raw.get(key)
            if value is None:
                return None
            normalized = str(value).strip()
            return normalized or None

        return cls(
            authority_code=text("OPN_ATMY_GRP_CD"),
            management_no=text("MNG_NO"),
            business_name=text("BPLC_NM"),
            road_address=text("ROAD_NM_ADDR"),
            jibun_address=text("LOTNO_ADDR"),
            status_name=text("SALS_STTS_NM"),
            status_code=text("SALS_STTS_CD"),
            detail_status_name=text("DTL_SALS_STTS_NM"),
            detail_status_code=text("DTL_SALS_STTS_CD"),
            business_type_name=text("SNTTN_BZSTAT_NM"),
            business_kind_name=text("BZSTAT_SE_NM"),
            location_area=text("LCTN_AREA"),
            facility_total_scale=text("FCLT_TOTAL_SCL"),
            license_date=text("LCPMT_YMD"),
            closure_date=text("CLSBIZ_YMD"),
            raw_x=text("CRD_INFO_X"),
            raw_y=text("CRD_INFO_Y"),
            update_type=text("DAT_UPDT_SE"),
            update_point=text("DAT_UPDT_PNT"),
            last_modified_point=text("LAST_MDFCN_PNT"),
        )

    def canonical_values(self) -> tuple[str, ...]:
        return tuple(str(getattr(self, item.name) or "") for item in fields(self))
