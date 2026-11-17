from datetime import date

import pytest

from etl.admin_population.data import prepare
from etl.admin_population.runner import run_import
from tests.etl.admin_population_helpers import boundary_zip, population_zip


def test_preparation_quarantines_unmatched_codes_and_preserves_masks(tmp_path):
    pop, boundary = tmp_path / "p.zip", tmp_path / "b.zip"
    psha = population_zip(pop, patches={("11110530", 0): "*", ("11110530", 1): ""})
    bsha = boundary_zip(boundary)
    data = prepare(pop, psha, boundary, bsha, date(2026, 10, 31))
    assert len(data.rows) == len(data.excluded) == 24
    assert [r["value_status"] for r in data.rows[:2]] == ["suppressed", "missing"]
    assert data.source_rows == 48
    assert all(r["population"] is None for r in data.rows[:2])
    before = set(tmp_path.iterdir())
    result = run_import(pop, psha, boundary, bsha, date(2026, 10, 31))
    assert result["database_access"] is False
    assert set(tmp_path.iterdir()) == before
    with pytest.raises(ValueError):
        prepare(pop, psha, boundary, bsha, date(2026, 10, 30))


@pytest.mark.parametrize("value", ["NaN", "1e3", "1.000001", "1000000000000000", "-1"])
def test_write_preparation_rejects_values_without_precision_loss(tmp_path, value):
    pop, boundary = tmp_path / "p.zip", tmp_path / "b.zip"
    psha = population_zip(pop, patches={("11110530", 0): value})
    bsha = boundary_zip(boundary)
    with pytest.raises(ValueError):
        prepare(pop, psha, boundary, bsha, date(2026, 10, 31))


def test_quarantine_retry_reuses_identical_evidence_but_never_overwrites(tmp_path):
    from etl.admin_population.runner import write_quarantine

    pop, boundary = tmp_path / "p.zip", tmp_path / "b.zip"
    psha, bsha = population_zip(pop), boundary_zip(boundary)
    data = prepare(pop, psha, boundary, bsha, date(2026, 10, 31))
    path = tmp_path / "quarantine.json"
    write_quarantine(data, path)
    before = path.read_bytes()
    write_quarantine(data, path)
    assert path.read_bytes() == before
    path.write_text("different evidence", encoding="utf-8")
    with pytest.raises(ValueError, match="quarantine_conflict"):
        write_quarantine(data, path)
    assert path.read_text(encoding="utf-8") == "different evidence"
