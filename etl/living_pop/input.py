from dataclasses import dataclass
from pathlib import Path
from typing import Any

from etl.living_pop.data import SOURCES, Observation, PopulationImportError, observations_hash
from etl.living_pop.grid import GridInput, load_grid
from etl.living_pop.source import Manifest, load_manifest, read_source
from etl.market_areas.archive import digest


@dataclass(frozen=True, repr=False)
class DailyInput:
    manifest: Manifest
    grid: GridInput
    rows: list[Observation]
    sources: dict[str, Any]
    input_sha256: str
    content_sha256: str


def load_input(path: Path) -> DailyInput:
    try:
        manifest = load_manifest(path)
        grid = load_grid(manifest.grid)
        grid_ids = {r["grid_id"] for r in grid.features}
        grid_pool = {g: g for g in grid_ids}
        admin_pool: dict[str, str] = {}
        rows = []
        sources = {}
        for kind in SOURCES:
            current, metadata = read_source(
                kind, manifest.sources[kind], manifest.day, grid_ids, admin_pool, grid_pool
            )
            rows.extend(current)
            sources[kind] = metadata
        rows.sort(
            key=lambda r: (
                r.source,
                r.hour,
                r.admin_code.encode("utf-8"),
                r.grid_id.encode("utf-8"),
            )
        )
        fingerprint = digest(
            dict(
                observation_date=manifest.day.isoformat(),
                sources={s: manifest.sources[s].sha256 for s in SOURCES},
            )
        )
        content = observations_hash(
            (r.payload() for r in rows), manifest.day, grid.sha256, len(rows)
        )
        return DailyInput(manifest, grid, rows, sources, fingerprint, content)
    except PopulationImportError:
        raise
    except Exception:
        raise PopulationImportError("living_pop:input_invalid") from None
