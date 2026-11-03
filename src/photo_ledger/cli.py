"""Command line entry point. Later milestones add match, plan, apply and undo."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import typer
import uvicorn

from photo_ledger import __version__
from photo_ledger import sources as source_service
from photo_ledger.config import LOCAL_HOSTS, Settings
from photo_ledger.db import open_db
from photo_ledger.errors import PhotoLedgerError

app = typer.Typer(help="Catalogue photo backups, find duplicates and organise them safely.")
source_app = typer.Typer(help="Map folders and drives to scan. Mapping never changes them.")
app.add_typer(source_app, name="source")


@app.callback()
def main() -> None:
    """Keep subcommands explicit, even while there are few of them."""


@contextmanager
def catalogue() -> Iterator[sqlite3.Connection]:
    """Open the catalogue, and turn expected failures into a message and exit code 1."""
    conn = None
    try:
        conn = open_db(Settings().db_path)
        yield conn
    except PhotoLedgerError as exc:
        typer.secho(str(exc), err=True, fg=typer.colors.RED)
        raise typer.Exit(1) from exc
    finally:
        if conn is not None:
            conn.close()


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


# Sources ------------------------------------------------------------------------------------


@source_app.command("add")
def source_add(
    path: Path = typer.Argument(..., help="Folder or drive root to map."),
    label: str = typer.Option(..., "--label", "-l", help="A short, unique name for it."),
) -> None:
    """Map a folder or drive. A folder inside, or containing, another source is refused."""
    with catalogue() as conn:
        source = source_service.add_source(conn, path, label)
        details = ", ".join(
            str(value)
            for value in (source["source_type"], source["device_label"], source["filesystem"])
            if value and value != "unknown"
        )
        typer.echo(
            f"Mapped '{source['label']}' at {source['root_path']}"
            + (f" ({details})" if details else "")
        )


@source_app.command("list")
def source_list() -> None:
    """List sources, and whether each is online now."""
    with catalogue() as conn:
        rows = source_service.list_sources(conn)
        if not rows:
            typer.echo(
                "No sources yet. Add one with `photo-ledger source add <path> --label <name>`."
            )
        for row in rows:
            state = "online" if source_service.refresh_state(conn, row) else "offline"
            volume = row["device_label"] or row["volume_id"] or ""
            typer.echo(
                f"{row['label']}\t{state}\t{row['source_type']}\t{row['root_path']}\t{volume}"
            )


@source_app.command("reconnect")
def source_reconnect(
    label: str = typer.Argument(..., help="The source to reconnect."),
    new_root: Path | None = typer.Argument(
        None, help="Its new root. Found automatically if left out."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Don't ask for confirmation."),
) -> None:
    """Point a source at its new drive letter or mount path, after checking the volume."""
    with catalogue() as conn:
        source = source_service.get_source(conn, label)
        if new_root is None:
            new_root = source_service.find_new_root(source)
            if new_root is None:
                raise source_service.SourceError(
                    f"Couldn't find the volume for '{label}'. Connect it, or pass its new root."
                )
        if not yes:
            typer.confirm(f"Move '{label}' from {source['root_path']} to {new_root}?", abort=True)
        updated = source_service.reconnect(conn, label, new_root)
        typer.echo(f"'{label}' now points at {updated['root_path']}")
