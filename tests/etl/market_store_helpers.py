import csv
import hashlib
import io
import zipfile
from pathlib import Path

from etl.market_stores.archive import FIELDS, SUPPORTED, TYPES


def annual_rows():
    """Synthetic rows only; no real market names/codes or official values."""
    rows = []
    for q in range(1, 5):
        for industry, label in SUPPORTED.items():
            rows.append(
                dict(
                    zip(
                        FIELDS,
                        (
                            f"2025{q}",
                            "A",
                            TYPES["A"],
                            "3110000",
                            "synthetic-market-canary",
                            industry,
                            label,
                            "1",
                            "3",
                            "0",
                            "7",
                            "450",
                            "9",
                            "2",
                        ),
                        strict=True,
                    )
                )
            )
    return rows


def make_stats_zip(
    path: Path,
    rows=None,
    *,
    encoding="cp949",
    headers=FIELDS,
    extra=None,
    member="synthetic.csv",
    content=None,
):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(headers)
    for row in annual_rows() if rows is None else rows:
        writer.writerow([row[k] for k in headers])
    data = stream.getvalue().encode(encoding) if content is None else content
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr(member, data)
        if extra:
            z.writestr(extra, b"extra")
    return hashlib.sha256(path.read_bytes()).hexdigest()
