from etl.market_sales.fields import FIELDS
from etl.market_stores.archive import SUPPORTED, TYPES
from tests.etl.market_store_helpers import make_stats_zip


def annual_sales_rows():
    """Synthetic 55-column rows; amounts and names do not represent any real market."""
    rows = []
    for q in range(1, 5):
        for industry, label in SUPPORTED.items():
            row = {k: "0" for k in FIELDS}
            row.update(
                dict(
                    zip(
                        FIELDS[:7],
                        (
                            f"2025{q}",
                            "A",
                            TYPES["A"],
                            "3110000",
                            "synthetic-sales-private-canary",
                            industry,
                            label,
                        ),
                        strict=True,
                    )
                )
            )
            row[FIELDS[7]] = "3000000001"
            row[FIELDS[8]] = "42"
            rows.append(row)
    return rows


def make_sales_zip(path, rows=None, **kwargs):
    return make_stats_zip(
        path,
        annual_sales_rows() if rows is None else rows,
        headers=kwargs.pop("headers", FIELDS),
        **kwargs,
    )
