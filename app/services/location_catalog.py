"""An explicit content catalog, not environment-specific source UUIDs."""

import hashlib
from functools import lru_cache
from pathlib import Path

from app.schemas.location_reference import LocationCatalog


@lru_cache(maxsize=1)
def load_catalog() -> LocationCatalog:
    return LocationCatalog.model_validate_json(
        Path(__file__).with_name("location_reference_catalog.json").read_bytes()
    )


def catalog_digest(catalog: LocationCatalog) -> str:
    return hashlib.sha256(catalog.model_dump_json().encode()).hexdigest()
