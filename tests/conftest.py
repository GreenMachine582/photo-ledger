import pytest
from fastapi.testclient import TestClient

from photo_ledger.config import Settings
from photo_ledger.db import open_db
from photo_ledger.web.app import create_app


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(photo_ledger_data_dir=tmp_path)


@pytest.fixture
def client(settings) -> TestClient:
    return TestClient(create_app(settings), base_url="http://127.0.0.1")


@pytest.fixture
def db(tmp_path):
    conn = open_db(tmp_path / "data" / "photo-ledger.db")
    yield conn
    conn.close()
