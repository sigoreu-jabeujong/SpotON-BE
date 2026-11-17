from dataclasses import dataclass


@dataclass(frozen=True)
class DatabaseColumnSpec:
    database_type: str
    nullable: bool
    has_default: bool = False


COLUMN_SPECS = {
    "id": DatabaseColumnSpec("bigint", False, True),
    "license_no": DatabaseColumnSpec("character varying(64)", False),
    "source": DatabaseColumnSpec("character varying(32)", False),
    "gu_code": DatabaseColumnSpec("character varying(10)", True),
    "name": DatabaseColumnSpec("character varying(255)", True),
    "address_road": DatabaseColumnSpec("text", True),
    "address_jibun": DatabaseColumnSpec("text", True),
    "building_key": DatabaseColumnSpec("character varying(255)", True),
    "floor_unit": DatabaseColumnSpec("character varying(100)", True),
    "location_level": DatabaseColumnSpec("character varying(32)", True),
    "open_date": DatabaseColumnSpec("date", True),
    "close_date": DatabaseColumnSpec("date", True),
    "status": DatabaseColumnSpec("character varying(32)", True),
    "status_code": DatabaseColumnSpec("character varying(32)", True),
    "bzstat_nm": DatabaseColumnSpec("character varying(100)", True),
    "category": DatabaseColumnSpec("character varying(32)", True),
    "sub_category": DatabaseColumnSpec("character varying(32)", True),
    "seoul_induty_cd": DatabaseColumnSpec("character varying(32)", True),
    "area_m2": DatabaseColumnSpec("numeric(12,2)", True),
    "lat": DatabaseColumnSpec("numeric(10,7)", True),
    "lng": DatabaseColumnSpec("numeric(10,7)", True),
    "geom": DatabaseColumnSpec("geometry(Point,4326)", True),
    "raw_x": DatabaseColumnSpec("text", True),
    "raw_y": DatabaseColumnSpec("text", True),
    "raw_crs": DatabaseColumnSpec("character varying(64)", True),
    "coord_source": DatabaseColumnSpec("character varying(32)", True),
    "coord_flag": DatabaseColumnSpec("text", True),
    "date_flag": DatabaseColumnSpec("text", True),
    "is_temporary": DatabaseColumnSpec("boolean", True),
    "category_review_flag": DatabaseColumnSpec("boolean", True),
    "is_franchise": DatabaseColumnSpec("boolean", True),
    "brand_id": DatabaseColumnSpec("bigint", True),
    "deleted_at": DatabaseColumnSpec("timestamp with time zone", True),
    "updated_at": DatabaseColumnSpec("timestamp with time zone", False, True),
    "batch_id": DatabaseColumnSpec("uuid", True),
}

CONSTRAINT_NAMES = {
    "pk_stores",
    "uq_stores_source_license_no",
    "ck_stores_lat_range",
    "ck_stores_lng_range",
}

INDEX_SPECS = {
    "ix_stores_geom_gist": ("gist", ("geom",)),
    "ix_stores_building_key": ("btree", ("building_key",)),
    "ix_stores_category_status": ("btree", ("category", "status")),
    "ix_stores_open_date": ("btree", ("open_date",)),
    "ix_stores_close_date": ("btree", ("close_date",)),
}
