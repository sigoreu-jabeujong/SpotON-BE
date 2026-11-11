import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, NoReturn

from etl.market_areas.archive import digest

RULE_VERSION = "living-pop-daily-v1"
GRID_RULE_VERSION = "living-grid-5179-v1"
SOURCES = ("local", "long", "short")


class PopulationImportError(ValueError):
    """Only fixed, non-sensitive error codes are accepted by the application."""


def fail(reason: str) -> NoReturn:
    raise PopulationImportError("living_pop:" + reason)


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


@dataclass(frozen=True, slots=True, repr=False)
class Observation:
    source: str
    hour: int
    admin_code: str
    grid_id: str
    population: Decimal | None
    value_status: str
    located: bool
    row_hash: bytes

    def payload(self) -> dict[str, Any]:
        return dict(
            source=self.source,
            hour=self.hour,
            admin_code=self.admin_code,
            grid_id=self.grid_id,
            located_grid_id=self.grid_id if self.located else None,
            population=format(self.population, ".5f") if self.population is not None else None,
            value_status=self.value_status,
            geometry_status="located" if self.located else "unlocated",
            source_row_sha256=self.row_hash.hex(),
        )


def observations_hash(
    rows: Iterable[Mapping[str, Any]],
    day: date,
    grid_hash: str,
    count: int,
    rule: str = RULE_VERSION,
) -> str:
    h = hashlib.sha256(
        canonical(
            dict(
                rule_version=rule,
                observation_date=day.isoformat(),
                grid_version_input_sha256=grid_hash,
                source_order=list(SOURCES),
                row_count=count,
            )
        )
        + b"\n"
    )
    for row in rows:
        payload = {
            k: row[k]
            for k in (
                "source",
                "hour",
                "admin_code",
                "grid_id",
                "located_grid_id",
                "population",
                "value_status",
                "geometry_status",
                "source_row_sha256",
            )
        }
        value = payload["population"]
        payload["population"] = format(Decimal(value), ".5f") if value is not None else None
        h.update(digest(payload).encode("ascii") + b"\n")
    return h.hexdigest()
