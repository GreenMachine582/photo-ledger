from typer.testing import CliRunner

from photo_ledger import __version__, cli
from photo_ledger.config import Settings


def test_version():
    result = CliRunner().invoke(cli.app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_serve_binds_only_to_loopback(monkeypatch):
    calls = {}
    monkeypatch.setattr(cli.uvicorn, "run", lambda *args, **kwargs: calls.update(kwargs))
    result = CliRunner().invoke(cli.app, ["serve", "--port", "9000"])
    assert result.exit_code == 0
    assert calls["host"] == "127.0.0.1"
    assert calls["port"] == 9000


def test_runtime_data_defaults_outside_the_repo(tmp_path):
    settings = Settings(photo_ledger_data_dir=tmp_path)
    assert settings.db_path == tmp_path / "photo-ledger.db"
    assert settings.thumbnail_dir == tmp_path / "thumbnails"


def test_source_commands(tmp_path, monkeypatch):
    monkeypatch.setenv("PHOTO_LEDGER_DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "photos").mkdir()
    runner = CliRunner()

    added = runner.invoke(cli.app, ["source", "add", str(tmp_path / "photos"), "--label", "pc"])
    assert added.exit_code == 0, added.output
    assert "Mapped 'pc'" in added.stdout

    listed = runner.invoke(cli.app, ["source", "list"])
    assert "pc\tonline" in listed.stdout

    refused = runner.invoke(cli.app, ["source", "add", str(tmp_path), "--label", "all"])
    assert refused.exit_code == 1
    assert "overlaps" in refused.output

    (tmp_path / "photos").rename(tmp_path / "moved")
    assert "pc\toffline" in runner.invoke(cli.app, ["source", "list"]).stdout
    moved = runner.invoke(cli.app, ["source", "reconnect", "pc", str(tmp_path / "moved"), "--yes"])
    assert moved.exit_code == 0, moved.output
    assert "pc\tonline" in runner.invoke(cli.app, ["source", "list"]).stdout


def test_scan_commands(tmp_path, monkeypatch, fixture_tree):
    root, manifest = fixture_tree
    camera_files = sum(rel.startswith("camera/") for rel in manifest["files"])
    camera_photos = manifest["supported"]["camera"]
    monkeypatch.setenv("PHOTO_LEDGER_DATA_DIR", str(tmp_path / "data"))
    runner = CliRunner()
    for label in ("camera", "backup"):
        assert (
            runner.invoke(cli.app, ["source", "add", str(root / label), "-l", label]).exit_code == 0
        )

    created = runner.invoke(cli.app, ["scan", "create", "Old drives", "--sources", "camera,backup"])
    assert created.exit_code == 0, created.output

    ran = runner.invoke(cli.app, ["scan", "run", "Old drives"])
    assert ran.exit_code == 0, ran.output
    assert f"camera: complete. {camera_files} listed" in ran.stdout
    assert "Scan 'Old drives' is complete." in ran.stdout

    listed = runner.invoke(cli.app, ["scan", "list"])
    assert listed.stdout.startswith("Old drives\tcomplete\t")
    assert "camera" in listed.stdout and "backup" in listed.stdout

    status = runner.invoke(cli.app, ["scan", "status", "Old drives"])
    assert "backup: complete" in status.stdout
    assert "broken/truncated.jpg (decode)" in status.stdout

    verified = runner.invoke(cli.app, ["scan", "run", "Old drives", "--verify"])
    assert verified.exit_code == 0, verified.output
    assert (
        f"camera: complete. {camera_files} listed, 0 unchanged, {camera_photos} hashed (0 new)"
        in verified.stdout
    )

    exported = runner.invoke(cli.app, ["export", "csv", str(tmp_path / "out.csv")])
    assert exported.exit_code == 0, exported.output
    assert f"Wrote {len(manifest['files'])} files" in exported.stdout
    inside = runner.invoke(cli.app, ["export", "csv", str(root / "camera" / "out.csv")])
    assert inside.exit_code == 1

    matched = runner.invoke(cli.app, ["match"])
    assert matched.exit_code == 0, matched.output
    assert "threshold of 8: 5 exact, 1 name conflict, 2 similar." in matched.stdout
    assert "8 new" in matched.stdout
    assert "0 new" in runner.invoke(cli.app, ["match", "--threshold", "8"]).stdout

    missing = runner.invoke(cli.app, ["scan", "run", "nope"])
    assert missing.exit_code == 1
    assert "no scan called 'nope'" in missing.output
