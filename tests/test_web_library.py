"""The library page, and removing a saved scan from the overview."""

from test_library import YEAR_LAYOUT, library_files, settle_everything
from test_scanner import snapshot
from typer.testing import CliRunner

from photo_ledger import cli
from photo_ledger.db import library as queries
from photo_ledger.library import plan


def post(web, url, **data):
    return web.post(url, data={**data, "csrf_token": web.cookies["gth_csrf"]})


def test_every_action_needs_a_csrf_token(ledger, web):
    conn, root, _ = ledger
    for url in ("/library", "/library/plan", "/library/build", "/scans/1/remove"):
        assert web.post(url, data={"path": str(root.parent), "layout": "year"}).status_code == 403
    assert queries.get(conn) is None
    assert conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0] == 1


def test_set_plan_and_build_from_the_browser(ledger, web):
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

    built = post(web, "/library/build")
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
