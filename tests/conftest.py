from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def client() -> Iterator[TestClient]:
    settings = Settings(_env_file=None, app_env="test", cors_origins="http://localhost:5173")
    with TestClient(create_app(settings)) as test_client:
        yield test_client
