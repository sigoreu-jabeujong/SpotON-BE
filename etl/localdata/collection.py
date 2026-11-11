from dataclasses import dataclass, field
from datetime import datetime

from etl.localdata.constants import Source
from etl.localdata.dto import LocalDataRow


@dataclass(frozen=True, slots=True)
class AuthorityStats:
    gu_code: str
    total_count: int
    page_count: int
    row_count: int


@dataclass(frozen=True, slots=True)
class CollectedSource:
    source: Source
    collected_at: datetime  # Naive KST, fixed for deterministic replay.
    authorities: tuple[AuthorityStats, ...]
    rows: tuple[LocalDataRow, ...] = field(repr=False)
    request_count: int = 0
