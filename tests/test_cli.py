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
