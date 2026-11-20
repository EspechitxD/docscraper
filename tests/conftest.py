import pytest
from fastapi.testclient import TestClient

from cpmh_backend.config import get_settings
from cpmh_backend.db import reset_db
from cpmh_backend.logging_setup import reset_logging
from cpmh_backend.main import create_app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CPMH_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CPMH_API_TOKEN", "test-token")
    monkeypatch.delenv("CPMH_ALLOW_LOCAL_NETWORK", raising=False)
    get_settings.cache_clear()
    reset_db()
    reset_logging()
    app = create_app(start_worker=False)
    with TestClient(app) as test_client:
        test_client.headers.update({"X-CPMH-Token": "test-token"})
        yield test_client
    reset_db()
    reset_logging()
    get_settings.cache_clear()
