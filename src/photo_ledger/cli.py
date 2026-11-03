"""Command line entry point. Later milestones add source, scan, match, plan, apply and undo."""

import typer
import uvicorn

from photo_ledger import __version__
from photo_ledger.config import LOCAL_HOSTS, Settings

app = typer.Typer(help="Catalogue photo backups, find duplicates and organise them safely.")


@app.callback()
def main() -> None:
    """Keep subcommands explicit, even while there are few of them."""


@app.command()
def version() -> None:
    """Print the installed version."""
    typer.echo(__version__)


@app.command()
def serve(port: int | None = typer.Option(None, help="Port on 127.0.0.1.")) -> None:
    """Run the review UI. It only ever binds to 127.0.0.1."""
    settings = Settings()
    uvicorn.run(
        "photo_ledger.web.app:create_app",
        factory=True,
        host=LOCAL_HOSTS[0],
        port=port or settings.photo_ledger_port,
    )
