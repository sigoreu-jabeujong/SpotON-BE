import csv
import hashlib
import io
from datetime import UTC, datetime

from etl.market_changes.source import CHANGES, FIELDS, load_source
from etl.market_stores.archive import TYPES

RETRIEVED = datetime(2026, 9, 11, tzinfo=UTC)
NOW = datetime(2026, 11, 12, tzinfo=UTC)


def annual_change_rows(year=2025):
    """Synthetic values deliberately do not imply the official classification formula."""
    return [
        dict(
            zip(
                FIELDS,
                (
                    f"{year}{q}",
                    "A",
                    TYPES["A"],
                    f"399999{i}",
                    "synthetic-market-canary",
                    code,
                    name,
                    "1",
                    "2",
                    "3",
                    "4",
                ),
                strict=True,
            )
        )
        for q in range(1, 5)
        for i, (code, name) in enumerate(CHANGES.items())
    ]


def make_change_csv(path, rows=None, *, headers=FIELDS, encoding="cp949", content=None):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(headers)
    for row in annual_change_rows() if rows is None else rows:
        writer.writerow([row.get(h, "") for h in headers])
    data = content if content is not None else stream.getvalue().encode(encoding)
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def load_change(path, sha, year=2025):
    return load_source(path, sha, year, RETRIEVED, now=NOW)
