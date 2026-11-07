"""The library page, and removing a saved scan from the overview."""

import time

from test_library import YEAR_LAYOUT, library_files, settle_everything
from test_scanner import snapshot
from typer.testing import CliRunner

from photo_ledger import cli
from photo_ledger.db import library as queries
from photo_ledger.library import plan


def post(web, url, **data):
    return web.post(url, data={**data, "csrf_token": web.cookies["gth_csrf"]})


HTMX = {"HX-Request": "true"}


def wait_for_build(client, timeout=60):
    """Poll as the Build popup does, until the answer that reloads the page."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get("/library/build/progress", headers=HTMX)
        assert response.status_code == 200
        if "HX-Redirect" in response.headers:
            return response
        assert 'id="build-progress"' in response.text
        time.sleep(0.05)
    raise AssertionError("the build never finished")


def build_and_wait(client):
    """Start a build from the popup and wait until it reloads the page."""
    started = client.post(
        "/library/build", data={"csrf_token": client.cookies["gth_csrf"]}, headers=HTMX
    )
    assert started.status_code == 200
    return wait_for_build(client)


def test_every_action_needs_a_csrf_token(ledger, web):
    conn, root, _ = ledger
    for url in ("/library", "/library/plan", "/library/build", "/scans/1/remove"):
        assert web.post(url, data={"path": str(root.parent), "layout": "year"}).status_code == 403
    assert queries.get(conn) is None
    assert conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0] == 1


def test_set_plan_and_build_from_the_browser(ledger, app_client):
    web = app_client  # a build is a background job, which needs the app's lifespan
    conn, root, _ = ledger
    before = snapshot(root)
    folder = root.parent / "library"
    folder.mkdir()
    assert "No library yet" in web.get("/library").text
    assert 'href="/library"' in web.get("/").text

    refused = post(web, "/library", path=str(root / "camera"), layout="year")
    assert refused.status_code == 409 and "overlaps source" in refused.text
    unknown = post(web, "/library", path=str(folder), layout="sideways")
    assert unknown.status_code == 409

    saved = post(web, "/library", path=str(folder), layout="year")
    assert "Library saved" in saved.text and str(folder.resolve()) in saved.text
    assert 'data-bs-target="#build-library"' not in saved.text  # nothing planned yet

    settle_everything(conn)
    changes = conn.total_changes
    assert plan.preview(conn).to_copy == len(YEAR_LAYOUT)
    assert conn.total_changes == changes  # previewing writes nothing

    planned = post(web, "/library/plan")
    assert "Planned." in planned.text
    assert 'data-bs-target="#build-library"' in planned.text
    assert queries.counts(conn) == {"pending": len(YEAR_LAYOUT)}

    started = post(web, "/library/build")
    assert "Building." in started.text
    wait_for_build(web)
    built = web.get("/library")
    assert "Built." in built.text
    assert set(library_files(folder)) == set(YEAR_LAYOUT)
    assert queries.counts(conn) == {"done": len(YEAR_LAYOUT)}
    assert 'data-bs-target="#build-library"' not in built.text
    assert snapshot(root) == before


def test_build_is_hidden_and_refused_while_the_library_is_offline(ledger, web):
    conn, root, _ = ledger
    folder = root.parent / "library"
    folder.mkdir()
    post(web, "/library", path=str(folder), layout="year")
    settle_everything(conn)
    post(web, "/library/plan")
    folder.rmdir()

    page = web.get("/library").text
    assert "offline" in page and "isn&#39;t connected" in page
    assert 'data-bs-target="#build-library"' not in page
    refused = post(web, "/library/build")
    assert "found problems" in refused.text and "offline" in refused.text
    assert not folder.exists()
    assert queries.counts(conn).get("done", 0) == 0


def test_remove_a_scan_from_the_overview(ledger, web):
    conn, root, _ = ledger
    before = snapshot(root)
    pairs = conn.execute("SELECT COUNT(*) FROM review_pairs").fetchone()[0]
    scan_id = conn.execute("SELECT id FROM scans").fetchone()[0]
    assert f'action="/scans/{scan_id}/remove"' in web.get("/").text

    removed = post(web, f"/scans/{scan_id}/remove")
    assert "Scan removed." in removed.text
    assert conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM review_pairs").fetchone()[0] == pairs
    assert conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 2
    assert snapshot(root) == before
    assert post(web, f"/scans/{scan_id}/remove").status_code == 409


def test_scan_remove_command(ledger, settings, monkeypatch):
    monkeypatch.setenv("PHOTO_LEDGER_DATA_DIR", str(settings.photo_ledger_data_dir))
    runner = CliRunner()
    kept = runner.invoke(cli.app, ["scan", "remove", "all"], input="n\n")
    assert kept.exit_code != 0
    removed = runner.invoke(cli.app, ["scan", "remove", "all", "--yes"])
    assert removed.exit_code == 0, removed.output
    assert "Removed scan 'all'" in removed.stdout
    assert "No scans yet" in runner.invoke(cli.app, ["scan", "list"]).stdout
    missing = runner.invoke(cli.app, ["scan", "remove", "all", "--yes"])
    assert missing.exit_code == 1


def test_the_build_popup_shows_progress_then_reloads_with_the_result(
    ledger, app_client, monkeypatch
):
    from photo_ledger.actions import executor

    conn, root, _ = ledger
    folder = root.parent / "library"
    folder.mkdir()
    post(app_client, "/library", path=str(folder), layout="year")
    settle_everything(conn)
    post(app_client, "/library/plan")
    before = snapshot(root)
    seen = []
    real_build = executor.build_library

    def watched_build(conn, progress=None):
        def report(done, total, phase):
            seen.append((done, total, phase))
            progress(done, total, phase)

        return real_build(conn, progress=report)

    monkeypatch.setattr(executor, "build_library", watched_build)
    page = app_client.get("/library").text
    assert 'hx-post="/library/build"' in page and 'hx-target="#build-progress"' in page

    response = app_client.post(
        "/library/build", data={"csrf_token": app_client.cookies["gth_csrf"]}, headers=HTMX
    )
    assert response.status_code == 200
    assert 'hx-get="/library/build/progress"' in response.text
    assert 'gth-busy-button" disabled' in response.text and "Building…" in response.text
    assert 'role="progressbar"' in response.text

    done = wait_for_build(app_client)
    assert done.headers["HX-Redirect"] == "/library"
    assert "Built." in app_client.get("/library").text
    copying = [s for s in seen if s[2] == "copying"]
    assert [s[0] for s in copying] == list(range(1, len(YEAR_LAYOUT) + 1))
    assert copying[-1][1] == len(YEAR_LAYOUT)
    assert set(library_files(folder)) == set(YEAR_LAYOUT)
    assert snapshot(root) == before


def test_a_build_needs_the_csrf_token(ledger, app_client):
    assert app_client.post("/library/build").status_code == 403
    assert app_client.get("/library/build/progress", headers=HTMX).headers.get("HX-Redirect") == (
        "/library"
    )  # no build ran: the popup just reloads the page


def test_the_page_says_when_built_copies_are_gone_and_rebuilds_them(ledger, app_client):
    conn, root, _ = ledger
    folder = root.parent / "library"
    folder.mkdir()
    post(app_client, "/library", path=str(folder), layout="year")
    settle_everything(conn)
    post(app_client, "/library/plan")
    build_and_wait(app_client)
    assert set(library_files(folder)) == set(YEAR_LAYOUT)

    folder.rename(root.parent / "library-old")
    folder.mkdir()
    post(app_client, "/library", path=str(folder), layout="year")
    page = app_client.get("/library").text
    assert f"{len(YEAR_LAYOUT)} pictures built earlier are no longer in" in page

    post(app_client, "/library/plan")
    build_and_wait(app_client)
    built = app_client.get("/library").text
    assert "Built." in built and "no longer in" not in built
    assert set(library_files(folder)) == set(YEAR_LAYOUT)
