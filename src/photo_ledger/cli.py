"""Command line entry point. Later milestones add match, plan, apply and undo."""

import signal
import sqlite3
import threading
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
from photo_ledger.exports import csv_export
from photo_ledger.scanner import engine

app = typer.Typer(help="Catalogue photo backups, find duplicates and organise them safely.")
source_app = typer.Typer(help="Map folders and drives to scan. Mapping never changes them.")
scan_app = typer.Typer(help="Saved scans of one or more sources. Scanning only reads files.")
app.add_typer(source_app, name="source")
export_app = typer.Typer(help="Export the catalogue. Exports never write to a source.")
app.add_typer(scan_app, name="scan")
app.add_typer(export_app, name="export")


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


# Scans --------------------------------------------------------------------------------------


def _size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


@scan_app.command("create")
def scan_create(
    name: str = typer.Argument(..., help="A name for the scan."),
    source_labels: str = typer.Option(
        ..., "--sources", "-s", help="Comma-separated source labels, such as old-pc,usb-1."
    ),
) -> None:
    """Save a scan of one or more sources. Run it with `scan run`."""
    with catalogue() as conn:
        scan = engine.create_scan(conn, name, source_labels.split(","))
        typer.echo(
            f"Created scan '{scan['name']}'. Start it with `photo-ledger scan run \"{name}\"`."
        )


@scan_app.command("run")
def scan_run(
    name: str = typer.Argument(..., help="The scan to start or resume."),
    verify: bool = typer.Option(
        False, "--verify", help="Re-hash every file instead of trusting size and modified time."
    ),
) -> None:
    """Start or resume a scan. Press Ctrl+C to pause it after the current file."""
    stop = threading.Event()

    def pause(_signum, _frame):
        if stop.is_set():
            raise KeyboardInterrupt
        stop.set()
        typer.echo("Pausing after the current file. Press Ctrl+C again to stop at once.", err=True)

    def progress(label: str, stage: str, done: int) -> None:
        verb = "listed" if stage == "walk" else "hashed"
        typer.echo(f"  {label}: {done} {verb}", err=True)

    with catalogue() as conn:
        previous = signal.signal(signal.SIGINT, pause)
        try:
            result = engine.run_scan(
                conn, name, verify=verify, should_stop=stop.is_set, progress=progress
            )
        finally:
            signal.signal(signal.SIGINT, previous)
        for source in result.sources:
            typer.echo(
                f"{source.label}: {source.status}. {source.seen} listed, "
                f"{source.reused} unchanged, {source.hashed} hashed ({source.new_contents} new), "
                f"{source.moved} moved, {source.missing} missing, {source.errors} errors"
            )
            for rel_path in source.content_changes:
                typer.echo(f"  content changed: {rel_path}")
        if not result.sources:
            typer.echo("Nothing to do.")
        offline = [s.label for s in result.sources if s.status == "offline"]
        if offline:
            typer.echo(
                f"Offline: {', '.join(offline)}. Nothing in them was marked missing. "
                "Reconnect them and run the scan again."
            )
        typer.echo(f"Scan '{result.name}' is {result.status}.")


@scan_app.command("list")
def scan_list() -> None:
    """List saved scans."""
    with catalogue() as conn:
        rows = engine.list_scans(conn)
        if not rows:
            typer.echo("No scans yet. Create one with `photo-ledger scan create`.")
        for row in rows:
            typer.echo(
                f"{row['name']}	{row['status']}	{row['source_labels']}"
                f"	{row['last_opened_at'] or '-'}"
            )


@scan_app.command("status")
def scan_status(name: str = typer.Argument(..., help="The scan to show.")) -> None:
    """Show each source's progress in a scan, and its most recent errors."""
    with catalogue() as conn:
        scan = engine.get_scan(conn, name)
        typer.echo(f"Scan '{scan['name']}': {scan['status']}")
        for row in engine.scan_progress(conn, scan["id"]):
            where = f", after {row['resume_path']}" if row["resume_path"] else ""
            typer.echo(
                f"  {row['label']}: {row['status']} ({row['mode']}, stage {row['stage']}{where}). "
                f"{row['file_count']} files, {_size(row['total_bytes'])}, "
                f"{row['error_count']} errors"
            )
        recent = engine.recent_errors(conn, scan["id"])
        if recent:
            typer.echo("Recent errors:")
            for error in recent:
                typer.echo(
                    f"  {error['label']}/{error['rel_path']} ({error['stage']}): {error['message']}"
                )


# Exports ------------------------------------------------------------------------------------


@export_app.command("csv")
def export_csv(
    out: Path = typer.Argument(..., help="The CSV file to write, outside every source."),
    scan: str | None = typer.Option(None, "--scan", help="Only the sources in this scan."),
) -> None:
    """Write one row per catalogued file, with its hash, dates and image details."""
    with catalogue() as conn:
        count = csv_export.export_files(conn, out, scan_name=scan)
        typer.echo(f"Wrote {count} files to {out}")
