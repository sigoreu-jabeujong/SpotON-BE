from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_env_overrides_dotenv_and_secrets_are_masked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / "settings.env"
    env_file.write_text("APP_ENV=local\nLLM_API_KEY=test-secret-value\n", encoding="utf-8")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    settings = Settings(_env_file=env_file)
    assert settings.app_env == "test"
    assert settings.llm_api_key is not None
    assert settings.llm_api_key.get_secret_value() == "test-secret-value"
    assert "test-secret-value" not in repr(settings)


def test_multiple_origins_are_normalized() -> None:
    settings = Settings(
        _env_file=None,
        cors_origins=" http://localhost:5173/, https://app.example, http://localhost:5173 ",
    )
    assert settings.allowed_origins == ["http://localhost:5173", "https://app.example"]


@pytest.mark.parametrize(
    "origin",
    [
        "*",
        "https://*.example",
        "https://app.example/path",
        "https://user:pass@app.example",
        "ftp://app.example",
        "http://localhost:99999",
    ],
)
def test_invalid_cors_origin_fails_startup(origin: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, cors_origins=origin)


def test_empty_origin_list_disables_cross_origin_access() -> None:
    assert Settings(_env_file=None, cors_origins="").allowed_origins == []


LLM_LIMIT_ENV_NAMES = [
    "LLM_REQUEST_TIMEOUT",
    "LLM_TIME_BUDGET",
    "LLM_MAX_RETRIES",
    "LLM_BACKOFF_BASE",
    "LLM_BACKOFF_MAX",
    "LLM_MAX_OUTPUT_TOKENS",
    "LLM_REQUESTS_PER_MINUTE",
    "LLM_REQUESTS_PER_DAY",
]


def test_llm_limit_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in LLM_LIMIT_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    settings = Settings(_env_file=None)
    assert settings.llm_request_timeout == 10
    assert settings.llm_time_budget == 20
    assert settings.llm_max_retries == 2
    assert settings.llm_backoff_base == 1
    assert settings.llm_backoff_max == 8
    assert settings.llm_max_output_tokens == 2048
    assert settings.llm_requests_per_minute is None
    assert settings.llm_requests_per_day is None


def test_blank_llm_request_limits_mean_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LLM_REQUESTS_PER_MINUTE", raising=False)
    monkeypatch.delenv("LLM_REQUESTS_PER_DAY", raising=False)
    env_file = tmp_path / "settings.env"
    env_file.write_text("LLM_REQUESTS_PER_MINUTE=\nLLM_REQUESTS_PER_DAY= \n", encoding="utf-8")
    settings = Settings(_env_file=env_file)
    assert settings.llm_requests_per_minute is None
    assert settings.llm_requests_per_day is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("llm_request_timeout", 0),
        ("llm_request_timeout", 61),
        ("llm_time_budget", 121),
        ("llm_max_retries", -1),
        ("llm_max_retries", 6),
        ("llm_backoff_base", 0),
        ("llm_backoff_max", 61),
        ("llm_max_output_tokens", 0),
        ("llm_max_output_tokens", 65537),
        ("llm_requests_per_minute", 0),
        ("llm_requests_per_day", 0),
    ],
)
def test_out_of_range_llm_limits_fail_startup(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})


POOL_ENV_NAMES = [
    "DATABASE_POOL_TIMEOUT",
    "DATABASE_POOL_SIZE",
    "DATABASE_MAX_OVERFLOW",
    "DATABASE_STATEMENT_TIMEOUT_MS",
    "DATABASE_CONNECTION_BUDGET",
    "WEB_CONCURRENCY",
]


def test_pool_wait_default_covers_cold_concurrent_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #120: a 2s pool wait failed queued cold requests; wait longer than one SQL limit."""
    for name in POOL_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    settings = Settings(_env_file=None)
    assert settings.database_pool_timeout == 10
    assert settings.database_pool_timeout > settings.database_statement_timeout_ms / 1000
    assert settings.database_pool_size == 3 and settings.database_max_overflow == 0


def test_env_example_pool_wait_matches_code_default() -> None:
    example = (Path(__file__).resolve().parents[1] / ".env.example").read_text(encoding="utf-8")
    values = [
        line.split("=", 1)[1].strip()
        for line in example.splitlines()
        if line.startswith("DATABASE_POOL_TIMEOUT=")
    ]
    assert len(values) == 1
    assert float(values[0]) == Settings.model_fields["database_pool_timeout"].default


def test_env_example_lists_llm_limit_settings() -> None:
    example = (Path(__file__).resolve().parents[1] / ".env.example").read_text(encoding="utf-8")
    names = {line.split("=", 1)[0] for line in example.splitlines() if "=" in line}
    assert set(LLM_LIMIT_ENV_NAMES) <= names
