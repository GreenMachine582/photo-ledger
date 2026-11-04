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
from photo_ledger.db import library as library_queries
from photo_ledger.db import open_db
from photo_ledger.errors import PhotoLedgerError
from photo_ledger.exports import csv_export, guard
from photo_ledger.formatting import human_size
from photo_ledger.library import dates as library_dates
from photo_ledger.library import plan as library_plan
from photo_ledger.library import settings as library_settings
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
library_app = typer.Typer(help="Build a clean library from settled pictures. Originals stay put.")
app.add_typer(library_app, name="library")
date_app = typer.Typer(help="Capture dates you set by hand. Originals are never changed.")
app.add_typer(date_app, name="date")


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


# Library ------------------------------------------------------------------------------------


@library_app.command("set")
def library_set(
    folder: Path = typer.Argument(..., help="An existing folder outside every source."),
    layout: str = typer.Option(
        "year", "--layout", help="year (YYYY/Collection/) or original (source/path)."
    ),
) -> None:
    """Choose the library's folder and layout. Creates nothing until you build."""
    with catalogue() as conn:
        library = library_settings.set_library(conn, folder, layout)
        typer.echo(f"The library is {library['root_path']}, in the '{library['layout']}' layout.")
        typer.echo("Preview it with `photo-ledger library plan`.")


def _echo_library_plan(summary: library_plan.LibraryPlan) -> None:
    typer.echo(
        f"To copy: {summary.to_copy} pictures ({human_size(summary.to_copy_bytes)}). "
        f"Already in the library: {summary.already}."
    )
    if summary.waiting:
        typer.echo(
            f"{summary.waiting} pictures wait for review, as they still have open, skipped "
            "or changed pairs."
        )
    if summary.corrupt:
        typer.echo(f"{summary.corrupt} pictures are left out, as no copy of them can be decoded.")
    for path in summary.no_longer_chosen:
        typer.echo(f"  in the library but no longer chosen, and left there: {path}")


@library_app.command("status")
def library_status() -> None:
    """Where the library is, whether it's connected and how much of it is built."""
    with catalogue() as conn:
        library = library_settings.get_library(conn)
        state = "online" if library_settings.library_online(library) else "offline"
        typer.echo(f"{library['root_path']}\t{state}\t{library['layout']} layout")
        counts = library_queries.counts(conn)
        typer.echo(", ".join(f"{counts.get(s, 0)} {s}" for s in ("done", "pending", "failed")))


@library_app.command("plan")
def library_plan_command() -> None:
    """Preview what a build would copy, and dry-run it. Changes nothing on disk."""
    with catalogue() as conn:
        _echo_library_plan(library_plan.plan_library(conn))
        _echo_dry_run(_library_dry_run(conn))


def _library_dry_run(conn: sqlite3.Connection) -> dryrun.DryRun:
    result = dryrun.DryRun(0)
    result.problems = library_plan.check_library(conn)
    return result


@library_app.command("build")
def library_build(
    yes: bool = typer.Option(False, "--yes", "-y", help="Don't ask for confirmation."),
) -> None:
    """Copy each settled picture into the library, verified by hash. Never changes an original."""
    with catalogue() as conn:
        _echo_recovery(recovery.recover(conn))
        summary = library_plan.plan_library(conn)
        _echo_library_plan(summary)
        pending = sum(library_queries.counts(conn).get(s, 0) for s in ("pending", "failed"))
        if pending:
            checked = _library_dry_run(conn)
            _echo_dry_run(checked)
            if not checked.ok:
                raise typer.Exit(1)
            if not yes:
                typer.confirm(f"Copy {pending} pictures into the library?", abort=True)
        else:
            typer.echo("Nothing new to copy. Checking sidecars and dates.")
        result = executor.build_library(conn)
        typer.echo(
            f"Copied {result.copied} pictures, {len(result.failed)} failed. "
            f"Wrote {result.sidecars} sidecars and set {result.dates} file dates."
        )
        for path in result.kept_sidecars:
            typer.echo(f"  left alone, as it was edited or written elsewhere: {path}")
        for message in result.failed:
            typer.secho(f"  {message}", fg=typer.colors.RED)
        if result.status != "complete":
            raise typer.Exit(1)


@date_app.command("set")
def date_set(
    where: str = typer.Argument(..., help="The photo, as <source label>/<path in the source>."),
    value: str = typer.Argument(..., help="YYYY-MM-DD, or YYYY-MM-DDTHH:MM[:SS]."),
) -> None:
    """Give an undated or misdated photo its capture date. Never changes the original."""
    with catalogue() as conn:
        taken = library_dates.set_date(conn, where, value)
        typer.echo(
            f"{where} was taken {taken}, for every copy. `photo-ledger library build` applies it "
            "to the library copy and its sidecar."
        )


@date_app.command("clear")
def date_clear(
    where: str = typer.Argument(..., help="The photo, as <source label>/<path in the source>."),
) -> None:
    """Forget a date you set, going back to the photo's EXIF date, or none."""
    with catalogue() as conn:
        if library_dates.clear_date(conn, where):
            typer.echo(f"Forgot the date you set for {where}.")
        else:
            typer.echo(f"{where} had no date set by hand.")


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


@source_app.command("rename")
def source_rename(
    label: str = typer.Argument(..., help="The source to rename."),
    new_label: str = typer.Argument(..., help="Its new label."),
) -> None:
    """Give a source a new label. Nothing on disk changes."""
    with catalogue() as conn:
        source = source_service.rename_source(conn, label, new_label)
        typer.echo(f"'{label}' is now '{source['label']}'.")


@source_app.command("forget")
def source_forget(
    label: str = typer.Argument(..., help="The source to remove from the ledger."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Don't ask for confirmation."),
) -> None:
    """Remove a source from the ledger. Its folder and files are left exactly as they are."""
    with catalogue() as conn:
        usage = source_service.forget_usage(conn, label)
        if not yes:
            typer.confirm(
                f"Forget '{label}': {usage['files']} catalogued files, {usage['pairs']} exact "
                f"pairs and {usage['decisions']} decisions on them"
                + (
                    f", and {usage['undone_plan_actions']} entries in undone plans' journals"
                    if usage["undone_plan_actions"]
                    else ""
                )
                + "? The folder isn't touched.",
                abort=True,
            )
        source_service.forget_source(conn, label)
        typer.echo(f"Forgot '{label}'. Its folder is unchanged; map it again to bring it back.")


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


@scan_app.command("remove")
def scan_remove(
    name: str = typer.Argument(..., help="The saved scan to remove."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Don't ask for confirmation."),
) -> None:
    """Remove a saved scan. Its sources, catalogued files and decisions all stay."""
    with catalogue() as conn:
        engine.get_scan(conn, name)
        if not yes:
            typer.confirm(
                f"Remove scan '{name}'? Its sources, catalogued files and decisions stay.",
                abort=True,
            )
        engine.remove_scan(conn, name)
        typer.echo(f"Removed scan '{name}'. Nothing on disk changed.")


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
