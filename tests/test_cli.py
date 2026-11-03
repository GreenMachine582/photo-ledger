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
