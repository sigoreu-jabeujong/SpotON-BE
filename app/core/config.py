from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import Field, SecretStr, field_validator
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
    database_connect_timeout: int = Field(default=5, ge=1, le=60)
    database_statement_timeout_ms: int = Field(default=3000, ge=1, le=60000)
    risk_boundary_version_id: UUID | None = None
    data_go_kr_service_key: SecretStr | None = None
    kakao_rest_api_key: SecretStr | None = None
    kakao_request_timeout: float = Field(default=5, ge=1, le=10)
    juso_search_key: SecretStr | None = None
    juso_coord_key: SecretStr | None = None
    llm_provider: str = "google"
    llm_model: str = "gemini-3.5-flash-lite"
    llm_api_key: SecretStr | None = None
    llm_request_timeout: float = Field(default=10, ge=1, le=60)
    llm_time_budget: float = Field(default=20, ge=1, le=120)
    llm_max_retries: int = Field(default=2, ge=0, le=5)
    llm_backoff_base: float = Field(default=1, gt=0, le=10)
    llm_backoff_max: float = Field(default=8, gt=0, le=60)
    llm_max_output_tokens: int = Field(default=2048, ge=1, le=65536)
    llm_requests_per_minute: int | None = Field(default=None, ge=1)
    llm_requests_per_day: int | None = Field(default=None, ge=1)
    interpret_requests_per_minute: int = Field(default=5, ge=1, le=10000)
    interpret_requests_per_day: int = Field(default=50, ge=1, le=100000)
    interpret_max_concurrent: int = Field(default=2, ge=1, le=16)
    cache_enabled: bool = True
    risk_cache_ttl_seconds: int = Field(default=300, ge=1, le=604800)
    ai_cache_ttl_seconds: int = Field(default=300, ge=1, le=604800)
    cache_max_entries: int = Field(default=256, ge=1, le=4096)
    cache_max_bytes: int = Field(default=4194304, ge=1024, le=67108864)

    @field_validator("llm_requests_per_minute", "llm_requests_per_day", mode="before")
    @classmethod
    def blank_limit_is_unset(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

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
