"""The GTH wiring: what a pin bump could break is exercised here, not just installed."""

import re


def test_home_renders_the_gth_shell(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Photo Ledger" in response.text
    assert "/gth-assets/" in response.text or "/gth-static/" in response.text
    assert "No sources mapped yet" in response.text


def test_health(client):
    assert client.get("/health").status_code == 200
    assert client.get("/health/ready").status_code == 200


def test_gth_static_assets_are_served(client):
    html = client.get("/").text
    assets = re.findall(r'(?:href|src)="(/gth-(?:assets|static)/[^"]+)"', html)
    assert assets
    for asset in assets:
        assert client.get(asset).status_code == 200, asset


def test_unknown_page_uses_the_gth_error_page(client):
    response = client.get("/nope", headers={"accept": "text/html"})
    assert response.status_code == 404
    assert "<html" in response.text.lower()


def test_page_carries_a_csrf_token_and_security_headers(client):
    response = client.get("/")
    assert "gth_csrf" in response.cookies
    assert "x-content-type-options" in response.headers


def test_api_docs_are_off(client):
    assert client.get("/docs").status_code == 404
