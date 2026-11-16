"""Transactional writes with immutable replay; caller owns target/role and transaction."""

from dataclasses import dataclass
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import Connection, insert, select, text

from app.models.admin_population import (
    CODE_SYSTEM,
)
from app.models.admin_population import (
    AdminArea as A,
)
from app.models.admin_population import (
    AdminBoundaryVersion as B,
)
from app.models.admin_population import (
    AdminPopulationHour as H,
)
from app.models.admin_population import (
    AdminPopulationVersion as V,
)
from etl.admin_population.data import BOUNDARY_RULE, POPULATION_RULE, Prepared, population_digest

NORMALIZED = (
    "ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_Transform("
    "ST_SetSRID(ST_GeomFromGeoJSON(:geometry_json),5181),4326)),3))"
)


@dataclass(frozen=True)
class Saved:
    boundary_id: UUID
    population_id: UUID
    reused: bool


def save(connection: Connection, data: Prepared) -> Saved:
    if population_digest(list(data.rows)) != data.population_content:
        raise ValueError("admin_population:prepared_content_drift")
    quality = {
        status: sum(r["value_status"] == status for r in data.rows)
        for status in ("observed", "suppressed", "missing")
    }
    quality.update(
        boundary_without_observations=data.boundary_without_observations,
        unmatched_code_count=data.unmatched_code_count,
    )
    connection.exec_driver_sql("SET LOCAL lock_timeout='5s'")
    connection.exec_driver_sql("SET LOCAL statement_timeout='60s'")
    connection.execute(text("SELECT pg_advisory_xact_lock(1900013)"))
    old = (
        connection.execute(
            select(B.__table__).where(
                B.input_sha256 == data.boundary_input,
                B.rule_version == BOUNDARY_RULE,
            )
        )
        .mappings()
        .one_or_none()
    )
    bid = cast(UUID, old["version_id"]) if old else uuid4()
    if old:
        if old["content_sha256"] != data.boundary_content or old["row_count"] != len(data.areas):
            raise ValueError("admin_population:boundary_drift")
        stored = list(
            connection.execute(
                select(A.admin_code, A.admin_name, A.source_feature_sha256).where(
                    A.boundary_version_id == bid
                )
            ).mappings()
        )
        expected = [
            {k: a[k] for k in ("admin_code", "admin_name", "source_feature_sha256")}
            for a in data.areas
        ]
        if sorted([dict(r) for r in stored], key=lambda r: r["admin_code"]) != expected:
            raise ValueError("admin_population:boundary_drift")
    else:
        connection.execute(
            insert(B).values(
                version_id=bid,
                source_dataset="OA-22160",
                source_url="https://data.seoul.go.kr/dataList/OA-22160/S/1/datasetView.do",
                code_system=CODE_SYSTEM,
                source_crs=5181,
                input_sha256=data.boundary_input,
                content_sha256=data.boundary_content,
                rule_version=BOUNDARY_RULE,
                row_count=len(data.areas),
            )
        )
        connection.execute(
            text(
                "INSERT INTO admin_areas "
                "(boundary_version_id,admin_code,code_system,admin_name,"
                "source_feature_sha256,geom,geometry_repaired) "
                f"VALUES "
                f"(:bid,:admin_code,:code_system,:admin_name,:source_feature_sha256,{NORMALIZED},"
                "NOT ST_IsValid(ST_SetSRID(ST_GeomFromGeoJSON(:geometry_json),5181)))"
            ),
            [dict(a, bid=bid, code_system=CODE_SYSTEM) for a in data.areas],
        )
    # Reproduce the normalized source shape when replaying, not merely its row count.
    for area in data.areas if old else ():
        equal = connection.scalar(
            text(
                f"SELECT ST_Equals(geom,{NORMALIZED}) FROM admin_areas WHERE "
                f"boundary_version_id=:bid AND admin_code=:admin_code"
            ),
            dict(area, bid=bid),
        )
        if equal is not True:
            raise ValueError("admin_population:geometry_drift")
    version = (
        connection.execute(
            select(V.__table__).where(
                V.input_sha256 == data.population_input,
                V.rule_version == POPULATION_RULE,
                V.observation_date == data.observation_date,
                V.source == "local",
                V.boundary_version_id == bid,
            )
        )
        .mappings()
        .one_or_none()
    )
    vid = cast(UUID, version["version_id"]) if version else uuid4()
    if version:
        stored_rows = [
            dict(r)
            for r in connection.execute(
                select(
                    H.admin_code,
                    H.hour,
                    H.population,
                    H.value_status,
                    H.source_row_sha256,
                ).where(H.version_id == vid)
            ).mappings()
        ]
        if (
            version["content_sha256"] != data.population_content
            or version["member_sha256"] != data.member_sha
            or version["row_count"] != len(data.rows)
            or version["source_row_count"] != data.source_rows
            or version["excluded_rows"] != len(data.excluded)
            or version["quality"] != quality
            or len(stored_rows) != len(data.rows)
            or population_digest(stored_rows) != data.population_content
        ):
            raise ValueError("admin_population:observation_drift")
    else:
        connection.execute(
            insert(V).values(
                version_id=vid,
                boundary_version_id=bid,
                code_system=CODE_SYSTEM,
                source_dataset="OA-23016",
                source_url="https://data.seoul.go.kr/dataList/OA-23016/S/1/datasetView.do",
                source_series="seoul_250m_admin_local",
                source="local",
                observation_date=data.observation_date,
                input_sha256=data.population_input,
                member_sha256=data.member_sha,
                content_sha256=data.population_content,
                rule_version=POPULATION_RULE,
                row_count=len(data.rows),
                source_row_count=data.source_rows,
                excluded_rows=len(data.excluded),
                quality=quality,
            )
        )
        connection.execute(
            insert(H),
            [
                dict(
                    r,
                    version_id=vid,
                    boundary_version_id=bid,
                    code_system=CODE_SYSTEM,
                    source="local",
                    observation_date=data.observation_date,
                )
                for r in data.rows
            ],
        )
    return Saved(bid, vid, bool(version))
