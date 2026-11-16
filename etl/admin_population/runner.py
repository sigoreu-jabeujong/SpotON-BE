"""Explicit local-only writer; preview never opens a database or creates files."""

import json
from datetime import date
from pathlib import Path

from sqlalchemy import Connection, select

from app.core.config import Settings
from app.db.session import create_db_engine
from app.models.admin_population import AdminBoundaryVersion as B
from app.models.admin_population import AdminPopulationVersion as V
from app.schemas.location_reference import AdminCatalog, AdminObservation, Fingerprint
from etl.admin_population.data import Prepared, prepare
from etl.admin_population.repository import Saved, save
from etl.localdata.runner import check_local_database, validate_local_target


def catalog(connection: Connection, saved: Saved) -> AdminCatalog:
    boundary = (
        connection.execute(select(B.__table__).where(B.version_id == saved.boundary_id))
        .mappings()
        .one()
    )
    population = (
        connection.execute(select(V.__table__).where(V.version_id == saved.population_id))
        .mappings()
        .one()
    )
    return AdminCatalog(
        boundary=Fingerprint(**{k: boundary[k] for k in Fingerprint.model_fields}),
        observations=(
            AdminObservation(**{k: population[k] for k in AdminObservation.model_fields}),
        ),
    )


def write_quarantine(data: Prepared, path: Path) -> None:
    # A failed DB transaction can retain the exact source evidence; identical retries
    # reuse it, while different contents and symlinks are rejected without overwrites.
    payload = json.dumps(
        {
            "date": data.observation_date.isoformat(),
            "source_sha256": data.population_input,
            "boundary_sha256": data.boundary_input,
            "excluded_rows": data.excluded,
        },
        ensure_ascii=True,
    ).encode()
    try:
        with path.open("xb") as output:
            output.write(payload)
    except FileExistsError:
        if path.is_symlink() or path.read_bytes() != payload:
            raise ValueError("admin_population:quarantine_conflict") from None


def run_import(
    population: Path,
    population_sha: str,
    boundary: Path,
    boundary_sha: str,
    day: date,
    *,
    write: bool = False,
    quarantine: Path | None = None,
    settings: Settings | None = None,
) -> dict[str, object]:
    data = prepare(population, population_sha, boundary, boundary_sha, day)
    summary: dict[str, object] = {
        "status": "preview",
        "observation_date": day.isoformat(),
        "areas": len(data.areas),
        "rows": len(data.rows),
        "excluded_rows": len(data.excluded),
        "database_access": False,
    }
    if not write:
        return summary
    settings = settings or Settings()
    validate_local_target(settings)
    if data.excluded and quarantine is None:
        raise ValueError("admin_population:quarantine_required")
    engine = create_db_engine(settings)
    try:
        with engine.begin() as connection:
            check_local_database(connection)
            if quarantine is not None:
                write_quarantine(data, quarantine)
            saved = save(connection, data)
            summary.update(
                status="reused" if saved.reused else "imported",
                database_access=True,
                catalog=catalog(connection, saved).model_dump(mode="json"),
            )
    finally:
        engine.dispose()
    return summary
