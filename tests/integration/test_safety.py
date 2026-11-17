from pathlib import Path
from unittest.mock import Mock

import pytest

from app.core.config import Settings

from . import conftest
from .safety import IntegrationTargetError, check_integration_target

TEST_URL = "postgresql://dummy:DUMMY-SECRET@localhost/test"


@pytest.mark.parametrize("flag", [None, "", "0"])
def test_explicit_integration_permission_is_required(flag: str | None) -> None:
    with pytest.raises(IntegrationTargetError):
        check_integration_target(TEST_URL, None, flag)


@pytest.mark.parametrize("raw", [None, "", "postgresql://dummy:DUMMY-SECRET@remote/test"])
def test_missing_or_remote_integration_target_is_rejected(raw: str | None) -> None:
    with pytest.raises(IntegrationTargetError):
        check_integration_target(raw, None, "1")


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "[::1]", "LOCALHOST."])
def test_same_database_is_rejected_across_loopback_aliases(host: str) -> None:
    configured = f"postgresql://dummy:dummy@{host}:5432/test"
    with pytest.raises(IntegrationTargetError):
        check_integration_target(TEST_URL, configured, "1")


@pytest.mark.parametrize(
    "test_url, configured",
    [
        (TEST_URL + "?host=remote", None),
        (TEST_URL + "?dbname=other", None),
        (TEST_URL, "invalid-DUMMY-SECRET"),
    ],
)
def test_unsafe_or_uncomparable_targets_fail_without_secrets(
    test_url: str, configured: str | None
) -> None:
    with pytest.raises(IntegrationTargetError) as caught:
        check_integration_target(test_url, configured, "1")
    assert "DUMMY-SECRET" not in str(caught.value) + repr(caught.value)
    assert caught.value.__context__ is None


def test_separate_local_database_is_allowed() -> None:
    configured = "postgresql://dummy:dummy@localhost/development"
    assert check_integration_target(TEST_URL, configured, "1").database == "test"


def test_fixture_checks_dotenv_before_creating_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("DATABASE_URL=" + TEST_URL + "\n", encoding="utf-8")
    monkeypatch.setitem(Settings.model_config, "env_file", env_file)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("TEST_DATABASE_URL", TEST_URL)
    monkeypatch.setenv("SPOTON_ALLOW_DB_INTEGRATION", "1")
    engine = Mock()
    monkeypatch.setattr(conftest, "create_db_engine", engine)
    with pytest.raises(pytest.fail.Exception):
        next(conftest.temporary_database.__wrapped__())
    engine.assert_not_called()
