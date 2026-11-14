from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import MagicMock, patch

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from app import runtime
from app.core.config import Settings
from app.main import create_app
from app.services.readiness import ReadinessProbe


def settings(**kwargs: object) -> Settings:
    return Settings(_env_file=None, **kwargs)


@pytest.mark.parametrize(
    ("pool", "overflow", "workers", "budget", "valid"),
    [
        (3, 0, 1, 8, True),
        (4, 0, 1, 8, False),
        (3, 1, 1, 10, True),
        (3, 1, 1, 9, False),
        (3, 0, 2, 8, False),
        (3, 0, 2, 16, True),
    ],
)
def test_deploy_overlap_includes_readiness_connection(
    pool: int, overflow: int, workers: int, budget: int, valid: bool
) -> None:
    values = dict(
        database_pool_size=pool,
        database_max_overflow=overflow,
        web_concurrency=workers,
        database_connection_budget=budget,
    )
    if valid:
        settings(**values)
    else:
        with pytest.raises(ValidationError):
            settings(**values)


def test_expected_revision_tracks_migration_head() -> None:
    assert (
        settings().database_expected_revision
        == ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
    )


@pytest.mark.parametrize("port", ["0", "65536", "abc", "1.5", "１２３", "-1"])
def test_runtime_rejects_invalid_port(monkeypatch: pytest.MonkeyPatch, port: str) -> None:
    monkeypatch.setenv("PORT", port)
    with (
        patch.object(runtime, "Settings", return_value=settings()),
        patch.object(runtime.uvicorn, "run") as run,
    ):
        with pytest.raises(ValueError, match="PORT"):
            runtime.main()
        run.assert_not_called()


def test_runtime_binds_render_port_and_explicit_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORT", "12345")
    with (
        patch.object(runtime, "Settings", return_value=settings()),
        patch.object(runtime.uvicorn, "run") as run,
    ):
        runtime.main()
        run.assert_called_once_with(
            "app.main:app",
            host="0.0.0.0",
            port=12345,
            workers=1,
            access_log=False,
            timeout_graceful_shutdown=30,
        )


def test_probe_cache_expiration_and_close() -> None:
    probe = ReadinessProbe(settings())
    with (
        patch.object(probe, "_probe", return_value="ok") as query,
        patch("app.services.readiness.monotonic", return_value=100) as clock,
    ):
        assert probe.check() and probe.check()
        query.assert_called_once()
        clock.return_value = 111
        assert probe.check()
        assert query.call_count == 2
        probe.close()
        assert not probe.check()


def test_probe_single_flight_does_not_open_extra_connection() -> None:
    probe = ReadinessProbe(settings())
    entered, release = Event(), Event()

    def slow() -> str:
        entered.set()
        assert release.wait(3)
        return "ok"

    with patch.object(probe, "_probe", side_effect=slow) as query, ThreadPoolExecutor(2) as pool:
        task = pool.submit(probe.check)
        try:
            assert entered.wait(3)
            concurrent = pool.submit(probe.check)
            with pytest.raises(TimeoutError):
                concurrent.result(timeout=0.05)
            assert query.call_count == 1
        finally:
            release.set()
        assert task.result(timeout=3)
        assert concurrent.result(timeout=3)


def good_row() -> dict[str, object]:
    return dict(
        revisions=["0012"],
        default_read_only=True,
        connection_limit=8,
        privileged=False,
        write_role=False,
        schema_create=False,
        database_create=False,
        temporary_create=False,
        table_write=False,
        sequence_write=False,
        owns_objects=False,
    )


@pytest.mark.parametrize(
    "change",
    [
        None,
        ("revisions", ["0010"]),
        ("connection_limit", -1),
        ("default_read_only", False),
        ("privileged", True),
        ("write_role", True),
        ("schema_create", True),
        ("database_create", True),
        ("temporary_create", True),
        ("table_write", True),
        ("sequence_write", True),
        ("owns_objects", True),
    ],
)
def test_staging_requires_revision_and_effective_readonly_role(
    change: tuple[str, object] | None,
) -> None:
    row = good_row()
    if change:
        row[change[0]] = change[1]
    connection = MagicMock()
    connection.execute.return_value.fetchone.return_value = row
    with patch("app.services.readiness.psycopg.connect") as connect:
        connect.return_value.__enter__.return_value = connection
        probe = ReadinessProbe(
            settings(
                app_env="staging",
                database_url=SecretStr("postgresql://reader:fake@localhost/check"),
            )
        )
        assert probe.check() is (change is None)
        assert connection.read_only is True
        assert connect.call_args.kwargs["connect_timeout"] == 1
        connect.return_value.__exit__.assert_called_once()


def test_readiness_database_failure_is_safe_and_liveness_stays_healthy() -> None:
    app = create_app(settings(database_url=SecretStr("postgresql://reader:fake@localhost/check")))
    with (
        patch(
            "app.services.readiness.psycopg.connect",
            side_effect=psycopg.OperationalError("secret-password-host-details"),
        ),
        TestClient(app) as client,
    ):
        response = client.get("/api/ready")
        assert response.status_code == 500
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["meta"] == {}
        assert response.json()["error"]["code"] == "INTERNAL_ERROR"
        assert "secret-password-host-details" not in response.text
        assert client.get("/api/health").status_code == 200


def test_readiness_success_uses_common_envelope() -> None:
    with (
        patch.object(ReadinessProbe, "_probe", return_value="ok"),
        TestClient(create_app(settings())) as client,
    ):
        response = client.get("/api/ready")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.json() == {"data": {"status": "ok"}, "meta": {}, "error": None}


def test_http_readiness_timeout_keeps_single_flight_connection() -> None:
    import time

    entered, release = Event(), Event()

    def slow() -> str:
        entered.set()
        assert release.wait(3)
        return "ok"

    with (
        patch.object(ReadinessProbe, "_probe", side_effect=slow) as query,
        patch("app.routers.health.PROBE_TIMEOUT_SECONDS", 0.03),
        patch("app.services.readiness.PROBE_TIMEOUT_SECONDS", 0.03),
        TestClient(create_app(settings())) as client,
    ):
        try:
            start = time.monotonic()
            assert client.get("/api/ready").status_code == 500
            assert entered.is_set()
            assert time.monotonic() - start < 1
            assert client.get("/api/ready").status_code == 500
            assert query.call_count == 1
        finally:
            release.set()
