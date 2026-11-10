from dataclasses import asdict
from typing import Any

from geoalchemy2.elements import WKTElement
from sqlalchemy import Connection, func, text
from sqlalchemy.dialects.postgresql import insert

from app.models import Store
from etl.localdata.constants import Source
from etl.localdata.pipeline import StoreRecord

UNIQUE_CONSTRAINT = "uq_stores_source_license_no"
UPDATE_COLUMNS = (
    "gu_code",
    "name",
    "address_road",
    "address_jibun",
    "open_date",
    "close_date",
    "status",
    "status_code",
    "bzstat_nm",
    "category",
    "sub_category",
    "seoul_induty_cd",
    "area_m2",
    "lat",
    "lng",
    "geom",
    "raw_x",
    "raw_y",
    "raw_crs",
    "coord_source",
    "coord_flag",
    "date_flag",
    "is_temporary",
    "category_review_flag",
    "batch_id",
)


class RepositoryContractError(RuntimeError):
    pass


def _payload(record: StoreRecord) -> dict[str, Any]:
    payload = asdict(record)
    if record.lng is not None and record.lat is not None:
        payload["geom"] = WKTElement(f"POINT({record.lng} {record.lat})", srid=4326)
    else:
        payload["geom"] = None
    return payload


def _verify_contract(connection: Connection) -> None:
    exists = connection.scalar(
        text(
            "SELECT EXISTS("
            "SELECT 1 FROM pg_constraint "
            "WHERE conrelid = 'stores'::regclass AND conname = :constraint AND contype = 'u'"
            ")"
        ),
        {"constraint": UNIQUE_CONSTRAINT},
    )
    if exists is not True:
        raise RepositoryContractError("stores 유일 제약을 확인할 수 없습니다")


def upsert_records(
    connection: Connection,
    source: Source,
    records: list[StoreRecord] | tuple[StoreRecord, ...],
    *,
    chunk_size: int = 1000,
) -> int:
    if connection.in_transaction():
        raise RepositoryContractError("새 트랜잭션을 시작할 수 있는 연결이 필요합니다")
    if chunk_size < 1:
        raise ValueError("chunk_size는 1 이상이어야 합니다")
    if any(record.source != source.value for record in records):
        raise RepositoryContractError("source가 다른 레코드를 함께 적재할 수 없습니다")
    keys = [(record.source, record.license_no) for record in records]
    if len(keys) != len(set(keys)):
        raise RepositoryContractError("upsert 전에 중복 키를 제거해야 합니다")

    affected = 0
    with connection.begin():
        _verify_contract(connection)
        connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": f"spoton:localdata:{source.value}"},
        )
        for offset in range(0, len(records), chunk_size):
            payloads = [_payload(record) for record in records[offset : offset + chunk_size]]
            if not payloads:
                continue
            statement = insert(Store).values(payloads)
            statement = statement.on_conflict_do_update(
                constraint=UNIQUE_CONSTRAINT,
                set_={
                    **{column: getattr(statement.excluded, column) for column in UPDATE_COLUMNS},
                    "updated_at": func.now(),
                },
            )
            connection.execute(statement)
            # psycopg/SQLAlchemy의 ON CONFLICT rowcount는 실행 방식에 따라 0이 될 수 있다.
            # 입력 키는 위에서 유일함을 검증하므로 성공한 payload 수가 처리 행 수다.
            affected += len(payloads)
    return affected
