from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest

from app.core.config import Settings
from etl.chains import maintenance
from etl.chains.common import ChainsError, digest

G = UUID(int=1)


@pytest.mark.parametrize(
    "options",
    [
        {"action": "unknown"},
        {"action": "list", "write": True},
        {"action": "disable", "generations": (G,)},
        {"action": "prune"},
        {"action": "prune", "generations": (G, G)},
        {"action": "prune", "generations": (G, G, G, G)},
        {"action": "prune", "generations": ("invalid",)},
        {"action": "disable", "write": True},
        {"action": "disable", "write": True, "expected_plan": "x", "expected_active": "none"},
        {"action": "disable", "write": True, "expected_plan": "0" * 64, "expected_active": "bad"},
        {"action": "disable", "expected_active": "none"},
        {"action": "disable", "expected_plan": "0" * 64},
    ],
)
def test_invalid_maintenance_options_fail_before_engine(monkeypatch, options):
    def forbidden(*args):
        pytest.fail("invalid maintenance reached DB")

    monkeypatch.setattr(maintenance, "validate_local_target", forbidden)
    monkeypatch.setattr(maintenance, "create_db_engine", forbidden)
    with pytest.raises(ChainsError):
        maintenance.run(Settings(_env_file=None), **options)


def test_plan_normalizes_uuid_and_utc_without_raw_output():
    same = datetime(2026, 11, 15, 9, tzinfo=timezone(timedelta(hours=9)))
    other = datetime(2026, 11, 15, tzinfo=UTC)
    assert digest(maintenance._json({"g": G, "date": same})) == digest(
        maintenance._json({"date": other, "g": G})
    )
    with pytest.raises(ChainsError, match="timestamp"):
        maintenance._json(datetime(2026, 11, 15))
