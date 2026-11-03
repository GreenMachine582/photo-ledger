"""Local-only protections. See web/security.py."""

import pytest
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient
from greentechhub_fastapi.auth.csrf import require_csrf

from photo_ledger.web.app import create_app


@pytest.fixture
def post_client(settings) -> TestClient:
    app = create_app(settings)
    router = APIRouter()

    @router.post("/change")
    def change() -> dict[str, bool]:
        return {"ok": True}

    app.include_router(router)
    return TestClient(app, base_url="http://127.0.0.1")


@pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.1:8765", "localhost:8765"])
def test_local_hosts_are_allowed(client, host):
    assert client.get("/health", headers={"host": host}).status_code == 200


@pytest.mark.parametrize("host", ["evil.example", "evil.example:8765", "192.168.1.5"])
def test_other_hosts_are_refused(client, host):
    assert client.get("/health", headers={"host": host}).status_code == 400


def test_cross_origin_post_is_refused(post_client):
    response = post_client.post("/change", headers={"origin": "https://evil.example"})
    assert response.status_code == 403


def test_look_alike_origin_is_refused(post_client):
    response = post_client.post("/change", headers={"origin": "http://127.0.0.1.evil.example"})
    assert response.status_code == 403


@pytest.mark.parametrize("origin", ["http://127.0.0.1:8765", "http://localhost:8765"])
def test_local_origin_post_is_allowed(post_client, origin):
    assert post_client.post("/change", headers={"origin": origin}).status_code == 200


def test_no_cors_headers_for_other_sites(client):
    response = client.get("/health", headers={"origin": "https://evil.example"})
    assert "access-control-allow-origin" not in response.headers


def test_csrf_token_round_trip(settings):
    app = create_app(settings)

    @app.post("/protected", dependencies=[Depends(require_csrf)])
    def protected() -> dict[str, bool]:
        return {"ok": True}

    # The cookie is Secure. Browsers send it to 127.0.0.1, but this test client needs https.
    client = TestClient(app, base_url="https://127.0.0.1")
    token = client.get("/").cookies["gth_csrf"]
    assert client.post("/protected").status_code == 403
    assert client.post("/protected", headers={"x-csrf-token": token}).status_code == 200
