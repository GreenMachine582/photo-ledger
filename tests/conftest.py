import make_fixtures
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


@pytest.fixture
def fixture_tree(tmp_path):
    """Generated photos under ``tmp_path/photos``, with the manifest from make_fixtures."""
    root = tmp_path / "photos"
    return root, make_fixtures.build(root)


@pytest.fixture
def ledger(settings, fixture_tree):
    """The fixtures mapped, scanned, matched and given collections in the app's own database."""
    from photo_ledger import sources
    from photo_ledger.collections.folders import refresh_collections
    from photo_ledger.matching.pairs import match
    from photo_ledger.scanner.engine import create_scan, run_scan

    root, manifest = fixture_tree
    conn = open_db(settings.db_path)
    for label in manifest["sources"]:
        sources.add_source(conn, root / label, label)
    create_scan(conn, "all", manifest["sources"])
    run_scan(conn, "all")
    refresh_collections(conn)
    match(conn)
    yield conn, root, manifest
    conn.close()


@pytest.fixture
def app_client(settings):
    """A client inside its lifespan, so its event loop (and the scan jobs on it) keeps running."""
    with TestClient(create_app(settings), base_url="https://127.0.0.1") as client:
        client.get("/")
        yield client


@pytest.fixture
def mapped(settings, fixture_tree):
    """The fixture sources mapped in the app's database, not yet scanned."""
    from photo_ledger import sources

    root, manifest = fixture_tree
    conn = open_db(settings.db_path)
    try:
        for label in manifest["sources"]:
            sources.add_source(conn, root / label, label)
    finally:
        conn.close()
    return root, manifest


@pytest.fixture
def web(settings) -> TestClient:
    """A client over https, so the Secure CSRF cookie round-trips as it does in a browser."""
    client = TestClient(create_app(settings), base_url="https://127.0.0.1")
    client.get("/")
    return client
