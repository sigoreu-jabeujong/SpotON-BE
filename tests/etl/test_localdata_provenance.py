from dataclasses import replace
from datetime import date
from uuid import uuid4

import pytest

from etl.localdata.provenance import import_batch, source_reference_date
from tests.etl.test_localdata_snapshot import collection


@pytest.mark.parametrize(
    "value,expected,reason",
    [
        (None, None, "missing_source_update"),
        ("private-update", None, "invalid_source_update"),
        ("20261112000000", None, "future_source_update"),
        ("19591111000000", None, "invalid_source_update"),
        ("2026-11-10 11:59:59", date(2026, 11, 10), None),
        ("20261110000000", date(2026, 11, 10), None),
    ],
)
def test_source_date_never_uses_file_or_database_time(value, expected, reason) -> None:
    original = collection()
    source = replace(
        original, rows=tuple(replace(row, update_point=value) for row in original.rows)
    )
    assert source_reference_date(source) == (expected, reason)
    batch = import_batch(source, uuid4())
    assert batch.data_updated_at == expected
    assert batch.recorded_at.tzinfo is not None
    assert len(batch.rows_sha256) == 64
    assert batch.input_sha256 is None


def test_one_bad_timestamp_does_not_silently_expand_or_truncate_source_date() -> None:
    original = collection()
    rows = (
        replace(original.rows[0], update_point="20261110000000"),
        replace(original.rows[1], update_point="invalid-update-canary"),
    )
    assert source_reference_date(replace(original, rows=rows)) == (None, "invalid_source_update")
