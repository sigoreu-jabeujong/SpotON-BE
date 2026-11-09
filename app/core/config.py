from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    app_env: Literal["local", "test", "staging", "production"] = "local"
    cors_origins: str = "http://localhost:5173"
    database_url: SecretStr | None = None
    data_go_kr_service_key: SecretStr | None = None
    kakao_rest_api_key: SecretStr | None = None
    juso_search_key: SecretStr | None = None
    juso_coord_key: SecretStr | None = None
    llm_provider: str = "google"
    llm_model: str = "gemini-3.5-flash-lite"
    llm_api_key: SecretStr | None = None

    @field_validator("cors_origins")
    @classmethod
    def validate_cors_origins(cls, value: str) -> str:
        origins: list[str] = []
        for item in value.split(","):
            origin = item.strip().rstrip("/")
            if not origin:
                continue
            try:
                parsed = urlsplit(origin)
                port = parsed.port
            except ValueError:
                raise ValueError("CORS_ORIGINS에는 올바른 HTTP origin을 지정하세요") from None
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or "*" in origin
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path
                or parsed.query
                or parsed.fragment
                or (port is not None and port == 0)
            ):
                raise ValueError("CORS_ORIGINS에는 경로 없는 HTTP origin만 지정하세요")
            if origin not in origins:
                origins.append(origin)
        return ",".join(origins)

    @property
    def allowed_origins(self) -> list[str]:
        return self.cors_origins.split(",") if self.cors_origins else []


@lru_cache
def get_settings() -> Settings:
    return Settings()
