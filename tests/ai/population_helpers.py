from datetime import date
from decimal import Decimal

from app.analysis.population_public_subset import PublicRow, assemble_public_subset
from app.schemas.population_reference import SOURCES, PopulationReferenceQuery
from app.services.population_reference import _response

TARGET = date(2026, 11, 8)


def population_response(query=None, *, status="ready", day="2", night="1", foreign=False):
    query = query or PopulationReferenceQuery(lat=0, lng=0, category="cafe")
    observation = None if status == "no_data" else date(2026, 11, 7)
    sources = ()
    if status == "ready":
        rows = tuple(
            PublicRow(
                source,
                "가가00000000",
                "11110530",
                hour,
                "observed",
                Decimal(day if 6 <= hour <= 17 else night),
            )
            for source in (SOURCES if foreign else ("local",))
            for hour in range(24)
        )
        sources = assemble_public_subset(
            frozenset({"가가00000000"}),
            rows,
            {s: (0, 0) for s in SOURCES},
            grid_as_of_known=False,
        )
    return _response(query, TARGET, observation, status, sources=sources)
