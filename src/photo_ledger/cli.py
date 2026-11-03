"""Command line entry point: sources, scans, matching, reports, plans and exports."""

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
from photo_ledger.actions import dryrun, executor, planner, recovery
from photo_ledger.collections.folders import refresh_collections
from photo_ledger.config import LOCAL_HOSTS, Settings
from photo_ledger.db import open_db
from photo_ledger.errors import PhotoLedgerError
from photo_ledger.exports import csv_export, guard
from photo_ledger.formatting import human_size
from photo_ledger.matching import pairs as pair_matching
from photo_ledger.matching import reports
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
    with catalogue() as conn:
        _echo_recovery(recovery.recover(conn))
    uvicorn.run(
        "photo_ledger.web.app:create_app",
        factory=True,
        host=LOCAL_HOSTS[0],
        port=port or settings.photo_ledger_port,
    )


@app.command()
def match(
    threshold: int | None = typer.Option(
        None,
        "--threshold",
        "-t",
        min=0,
        max=32,
        help="Largest pHash distance that counts as similar.",
    ),
) -> None:
    """Find exact duplicates, similar images and name conflicts. Only reads the catalogue."""
    settings = Settings()
    limit = settings.photo_ledger_similar_threshold if threshold is None else threshold
    with catalogue() as conn:
        collections = refresh_collections(conn, settings.photo_ledger_generic_folders)
        typer.echo(
            f"Collections from folder names: {collections.total_collections} "
            f"({collections.new_collections} new, {collections.new_folders} folders mapped)."
        )
        result = pair_matching.match(conn, limit)
        found = ", ".join(
            f"{n} {kind.replace('_', ' ')}" for kind, n in sorted(result.by_kind.items())
        )
        typer.echo(f"Matched with a similarity threshold of {limit}: {found or 'no pairs'}.")
        typer.echo(
            f"{result.new} new, {result.reopened} reopened, {result.needs_review} need review, "
            f"{result.obsolete} closed, {result.unchanged} unchanged."
        )


@app.command()
def report(
    name: str = typer.Argument(
        "summary", help=f"One of: {', '.join(reports.REPORTS)}.", metavar="NAME"
    ),
    scan: str | None = typer.Option(None, "--scan", help="Only what touches this scan's sources."),
    kind: str | None = typer.Option(None, "--kind", help="pairs: exact, similar or name_conflict."),
    status: str = typer.Option("open", "--status", help="pairs: a status, or 'all'."),
    csv_path: Path | None = typer.Option(None, "--csv", help="Write a CSV instead of printing."),
) -> None:
    """Show a read-only report: duplicates, mismatches, dates and corrupt files."""
    if name not in reports.REPORTS:
        typer.secho(
            f"Unknown report '{name}'. Choose from: {', '.join(reports.REPORTS)}.", err=True
        )
        raise typer.Exit(2)
    with catalogue() as conn:
        if name == "pairs":
            result = reports.pairs_report(
                conn, scan, kind=kind, status=None if status == "all" else status
            )
        else:
            result = reports.REPORTS[name](conn, scan)
        if csv_path is not None:
            count = guard.write_csv(conn, csv_path, result.columns, result.rows)
            typer.echo(f"Wrote {count} rows to {csv_path}")
            return
        typer.echo(f"# {result.title} ({len(result.rows)})")
        if result.note:
            typer.echo(f"# {result.note}")
        typer.echo("	".join(result.columns))
        for row in result.rows:
            typer.echo("	".join("" if value is None else str(value) for value in row))


# Plans --------------------------------------------------------------------------------------


def _echo_dry_run(result: dryrun.DryRun) -> None:
    if result.ok:
        typer.echo("Dry run: no problems. Nothing has changed yet.")
        return
    typer.secho(f"Dry run found {len(result.problems)} problem(s):", fg=typer.colors.YELLOW)
    for problem in result.problems:
        typer.echo(f"  {problem.where}: {problem.message}")


@app.command()
def plan(
    verify: bool = typer.Option(
        False, "--verify", help="Hash every file instead of checking its size and date."
    ),
) -> None:
    """Build a plan from your decisions and dry-run it. Changes nothing on disk."""
    with catalogue() as conn:
        summary = planner.build_plan(conn)
        typer.echo(
            f"Plan {summary.plan_id}: move {summary.moves} rejected copies "
            f"({human_size(summary.move_bytes)}) to quarantine."
        )
        if summary.stay:
            typer.echo(
                f"{summary.stay} rejected copies ({human_size(summary.stay_bytes)}) stay where "
                "they are, as their sources have no quarantine. "
                "Turn it on with `photo-ledger source quarantine`."
            )
        for where in summary.unsafe:
            typer.echo(f"  left alone, as no kept copy would remain: {where}")
        if summary.moves:
            result = dryrun.dry_run(conn, summary.plan_id, verify=verify)
            _echo_dry_run(result)
            if result.ok:
                typer.echo("Apply it with `photo-ledger apply`.")


def _echo_recovery(result: recovery.Recovery) -> None:
    for plan_id in result.plans:
        typer.secho(
            f"Plan {plan_id} was interrupted. Checked: {result.pending} to retry, "
            f"{result.done + result.finished} finished. Run `photo-ledger apply` to complete it.",
            fg=typer.colors.YELLOW,
        )
    for message in result.failed:
        typer.secho(f"  {message}", fg=typer.colors.RED)
    for where in result.waiting:
        typer.echo(f"  waiting for its drives to be connected: {where}")


def _echo_applied(result: executor.ApplyResult, verb: str) -> None:
    typer.echo(f"Plan {result.plan_id}: {result.done} {verb}, {len(result.failed)} failed.")
    for message in result.failed:
        typer.secho(f"  {message}", fg=typer.colors.RED)
    if result.status != "applied":
        typer.echo("The plan is incomplete. Fix the problems above and run the command again.")
        raise typer.Exit(1)


@app.command()
def apply(
    yes: bool = typer.Option(False, "--yes", "-y", help="Don't ask for confirmation."),
) -> None:
    """Move rejected copies to quarantine, as planned and dry-run. Nothing is deleted."""
    with catalogue() as conn:
        _echo_recovery(recovery.recover(conn))
        current = planner.draft(conn)
        if current is not None and not yes:
            result = dryrun.dry_run(conn, current["id"])
            _echo_dry_run(result)
            if not result.ok:
                raise typer.Exit(1)
            typer.confirm(
                f"Move {result.actions} files ({human_size(result.bytes)}) to quarantine?",
                abort=True,
            )
        _echo_applied(executor.apply(conn), "moved")
        typer.echo("Undo it with `photo-ledger undo`.")


@app.command()
def undo(
    yes: bool = typer.Option(False, "--yes", "-y", help="Don't ask for confirmation."),
) -> None:
    """Put back every file the most recent applied plan moved. Never overwrites a file."""
    with catalogue() as conn:
        if not yes:
            typer.confirm(
                "Move the most recent plan's files back where they came from?", abort=True
            )
        _echo_applied(executor.undo(conn), "restored")


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
            quarantine = f"quarantine {row['quarantine_path']}" if row["quarantine_enabled"] else ""
            typer.echo(
                f"{row['label']}\t{state}\t{row['source_type']}\t{row['root_path']}\t{volume}"
                + (f"\t{quarantine}" if quarantine else "")
            )


@source_app.command("quarantine")
def source_quarantine(
    label: str = typer.Argument(..., help="The source whose rejected copies may move."),
    path: Path | None = typer.Argument(
        None, help="An existing folder outside every source, on any device."
    ),
    off: bool = typer.Option(False, "--off", help="Turn quarantine off for this source."),
) -> None:
    """Opt a source in to moving rejected copies into a quarantine folder. Off by default."""
    if off == (path is not None):
        typer.secho("Pass either a quarantine folder or --off.", err=True)
        raise typer.Exit(2)
    with catalogue() as conn:
        source, same_volume = source_service.set_quarantine(conn, label, None if off else path)
        if off:
            typer.echo(f"Quarantine is off for '{label}'. Its rejected copies stay where they are.")
            return
        typer.echo(f"Rejected copies in '{label}' can move to {source['quarantine_path']}.")
        if same_volume is False:
            typer.echo(
                "It's on another device, so moves copy and verify each file. A folder on the "
                "source's own drive would be faster."
            )


@source_app.command("priority")
def source_priority(
    label: str = typer.Argument(..., help="The source to change."),
    priority: int = typer.Argument(..., help="Higher numbers are preferred as keepers. Default 0."),
) -> None:
    """Set how strongly keeper suggestions prefer a source's copies."""
    with catalogue() as conn:
        source = source_service.set_priority(conn, label, priority)
        typer.echo(f"'{source['label']}' now has priority {source['priority']}.")


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
        if result.status == "complete":
            typer.echo("Run `photo-ledger match` to find duplicates and similar images.")


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
                f"	{(row['last_opened_at'] or '-')[:19]}"
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
                f"{row['file_count']} files, {human_size(row['total_bytes'])}, "
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
