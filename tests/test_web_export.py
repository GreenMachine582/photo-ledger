"""Downloading the catalogue as CSV from the browser."""

import csv
import io

from test_scanner import snapshot

from photo_ledger.exports import csv_export


def rows(response):
    return list(csv.reader(io.StringIO(response.text)))


def test_the_download_matches_the_cli_export(ledger, web, tmp_path):
    conn, root, manifest = ledger
    before = snapshot(root)
    response = web.get("/export/catalogue.csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    downloaded = rows(response)
    assert downloaded[0] == list(csv_export.COLUMNS)
    assert len(downloaded) - 1 == len(manifest["files"])

    out = tmp_path / "out.csv"
    csv_export.export_files(conn, out)
    with open(out, newline="", encoding="utf-8") as handle:
        assert list(csv.reader(handle)) == downloaded
    assert snapshot(root) == before  # nothing written near a source


def test_a_scan_narrows_the_download(ledger, web):
    conn, _, _ = ledger
    conn.execute("INSERT INTO scans (name, created_at) VALUES ('none', '2026-01-01')")
    conn.commit()
    assert len(rows(web.get("/export/catalogue.csv?scan=none"))) == 1  # the header alone
    assert len(rows(web.get("/export/catalogue.csv?scan=all"))) > 1


def test_the_photos_and_reports_pages_link_to_it(ledger, web):
    assert 'href="/export/catalogue.csv"' in web.get("/catalogue").text
    assert 'href="/export/catalogue.csv"' in web.get("/reports").text
