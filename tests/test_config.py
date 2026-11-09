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
