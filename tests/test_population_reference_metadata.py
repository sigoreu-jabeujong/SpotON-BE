from copy import deepcopy
from datetime import date
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.models import LivingGridVersion as G
from app.models import LivingPopulationVersion as V
from app.schemas.population_reference import PublicSource
from app.services.population_reference import _metadata
from tests.test_population_public_subset import assemble, rows


def versions():
    grid = G(
        grid_version_id=UUID(int=1),
        source_crs=5179,
        row_count=1,
        input_sha256="a" * 64,
        content_sha256="b" * 64,
        grid_as_of=None,
    )
    version = V(
        version_id=UUID(int=2),
        grid_version_id=grid.grid_version_id,
        observation_date=date(2026, 11, 7),
        spatial_compatibility="unverified",
        input_sha256="c" * 64,
        content_sha256="d" * 64,
        row_count=72,
        sources={
            s: dict(
                rows=24,
                statuses=dict(observed=24, suppressed=0, missing=0),
                unlocated_rows=0,
                unlocated_grids=0,
            )
            for s in ("local", "long", "short")
        },
    )
    return version, grid


def test_metadata_only_validation_has_exact_independent_source_counts():
    version, grid = versions()
    assert _metadata(version, grid) == dict(local=(0, 0), long=(0, 0), short=(0, 0))


@pytest.mark.parametrize(
    "case",
    [
        "missing_source",
        "extra_source",
        "bool_counter",
        "count_sum",
        "unlocated",
        "sha",
        "grid_reference",
        "spatial_status",
        "source_crs",
    ],
)
def test_invalid_version_metadata_is_not_silently_treated_as_absence(case):
    version, grid = versions()
    sources = deepcopy(version.sources)
    if case == "missing_source":
        del sources["short"]
    elif case == "extra_source":
        sources["extra"] = sources["local"]
    elif case == "bool_counter":
        sources["local"]["statuses"]["missing"] = False
    elif case == "count_sum":
        version.row_count += 1
    elif case == "unlocated":
        sources["long"]["unlocated_grids"] = 1
    elif case == "sha":
        version.content_sha256 = "invalid"
    elif case == "grid_reference":
        version.grid_version_id = UUID(int=3)
    elif case == "spatial_status":
        version.spatial_compatibility = "verified"
    else:
        grid.source_crs = 4326
    version.sources = sources
    with pytest.raises(ValueError, match="population_reference_metadata"):
        _metadata(version, grid)


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "not_supported"},
        {"status": "no_data", "reason": "numeric_scope_too_large"},
        {"status": "partial", "reason": "no_source_rows"},
        {"status": "no_data", "values": assemble(rows())[0].values.model_dump()},
    ],
)
def test_public_source_status_and_reason_cannot_disagree(changes):
    data = assemble(rows())[1].model_dump()
    assert data["status"] == "no_data"
    with pytest.raises(ValidationError):
        PublicSource.model_validate(data | changes)
