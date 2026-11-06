"""Saved scans that pause, resume and overlap.

A scan is a saved selection of sources. Running it processes each source in a *pass* with three
stages, and every stage resumes where it stopped:

1. **walk** records each file's path, size and ``mtime_ns``, saving ``resume_path`` as it goes.
   A file whose size and ``mtime_ns`` still match keeps its hash, unless the pass verifies.
   Anything else is flagged ``pending_hash``.
2. **hash** hashes the flagged files with BLAKE3, those sharing a size first, links each to its
   content and decodes only contents it hasn't seen before.
3. **reconcile** runs only after both stages finish with the source online. A file not seen in
   the pass either moved within the source, which keeps its file ID, or is marked ``missing``.

Progress is committed in batches together with ``resume_path`` and a heartbeat, so a crash
loses at most one batch, and a pass whose heartbeat has gone stale can be taken over. Work goes
to the shared catalogue rather than to the scan, so any scan reuses hashes made by another.

Nothing here writes to a source: files are only listed, stat-ed and opened for reading.
"""

import os
import sqlite3
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath

from photo_ledger.db import files as file_queries
from photo_ledger.db import now_iso, now_ns
from photo_ledger.db import scans as scan_queries
from photo_ledger.db import sources as source_queries
from photo_ledger.errors import PhotoLedgerError
from photo_ledger.scanner import hashing, metadata
from photo_ledger.scanner.walk import WalkEntry, walk
from photo_ledger.sources import service as source_service

#: A running pass whose heartbeat is older than this is treated as crashed.
STALE_AFTER_NS = 5 * 60 * 1_000_000_000
BATCH_FILES = 200
BATCH_SECONDS = 2.0
#: Statuses whose content link can be trusted while size and mtime_ns are unchanged.
REUSABLE_STATUSES = {"present", "corrupt", "unsupported", "missing"}


class ScanError(PhotoLedgerError):
    """A scan can't be created or run."""


class ScanConflict(ScanError):
    """Another scan is processing one of this scan's sources right now."""


class _SourceOffline(Exception):
    """The source's root went away mid-pass."""


@dataclass
class SourceResult:
    label: str
    status: str = "pending"
    seen: int = 0
    reused: int = 0
    hashed: int = 0
    new_contents: int = 0
    errors: int = 0
    moved: int = 0
    missing: int = 0
    content_changes: list[str] = field(default_factory=list)


@dataclass
class ScanResult:
    name: str
    status: str
    sources: list[SourceResult]


# Creating and listing --------------------------------------------------------------------------


def create_scan(conn: sqlite3.Connection, name: str, labels: list[str]) -> sqlite3.Row:
    name = name.strip()
    if not name or len(name) > 100:
        raise ScanError("A scan needs a name of 1-100 characters.")
    if scan_queries.by_name(conn, name):
        raise ScanError(f"A scan called '{name}' already exists. Run it with `scan run`.")
    labels = list(dict.fromkeys(label.strip() for label in labels if label.strip()))
    if not labels:
        raise ScanError("A scan needs at least one source.")
    source_ids = [source_service.get_source(conn, label)["id"] for label in labels]
    with conn:
        scan_queries.insert(conn, name, source_ids)
    return scan_queries.by_name(conn, name)


def get_scan(conn: sqlite3.Connection, name: str) -> sqlite3.Row:
    scan = scan_queries.by_name(conn, name)
    if scan is None:
        raise ScanError(f"There's no scan called '{name}'. See `photo-ledger scan list`.")
    return scan


def remove_scan(conn: sqlite3.Connection, name: str) -> sqlite3.Row:
    """Forget a saved scan: its progress and errors. Its sources, catalogued files, pairs and
    decisions all stay, as they belong to the catalogue rather than to the scan.

    Nothing is marked missing. A scan that is running now is refused, so a live pass never
    loses the row it reports to. Returns the removed scan.
    """
    scan = get_scan(conn, name)
    source_ids = [row["source_id"] for row in scan_queries.scan_sources(conn, scan["id"])]
    live = [
        claim
        for claim in scan_queries.live_claims(conn, source_ids, now_ns() - STALE_AFTER_NS)
        if claim["scan_id"] == scan["id"]
    ]
    if live:
        raise ScanError(f"Scan '{name}' is running. Let it finish or pause it first.")
    with conn:
        scan_queries.delete(conn, scan["id"])
    return scan


def list_scans(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return scan_queries.all_scans(conn)


def scan_progress(conn: sqlite3.Connection, scan_id: int) -> list[sqlite3.Row]:
    return scan_queries.scan_sources(conn, scan_id)


def recent_errors(conn: sqlite3.Connection, scan_id: int, limit: int = 20) -> list[sqlite3.Row]:
    return scan_queries.errors(conn, scan_id, limit)


# Running ---------------------------------------------------------------------------------------


def _stat(path: Path) -> os.stat_result:
    return os.stat(path)


def run_scan(
    conn: sqlite3.Connection,
    name: str,
    *,
    verify: bool = False,
    should_stop: Callable[[], bool] | None = None,
    progress: Callable[[str, str, int], None] | None = None,
) -> ScanResult:
    """Start or resume a scan. ``should_stop`` is polled between files to pause cleanly.

    A scan whose sources are all complete starts a new round over every source. Otherwise it
    resumes the current round, skipping the sources that already finished it. With ``verify``,
    every supported file is re-hashed, whatever its size and mtime_ns say.
    """
    scan = get_scan(conn, name)
    all_rows = scan_queries.scan_sources(conn, scan["id"])
    new_round = all(row["status"] == "complete" for row in all_rows)
    rows = [
        row
        for row in all_rows
        if new_round or row["status"] != "complete" or (verify and row["mode"] != "verify")
    ]
    previous = _claim(conn, scan, rows, new_round=new_round)
    results = []
    stopped = False
    try:
        for row in rows:
            source = source_queries.by_id(conn, row["source_id"])
            if stopped:
                break
            run = _SourceRun(conn, scan["id"], source, verify, should_stop, progress)
            results.append(run.run())
            stopped = run.stopped
    finally:
        # Hand back any source this run claimed but didn't get to.
        done = {result.label for result in results}
        for row in rows:
            if row["label"] not in done:
                before = previous[row["source_id"]]
                scan_queries.update_scan_source(
                    conn,
                    scan["id"],
                    row["source_id"],
                    status="paused" if before == "running" else before,
                )
        statuses = [r["status"] for r in scan_queries.scan_sources(conn, scan["id"])]
        status = "complete" if all(s == "complete" for s in statuses) else "paused"
        scan_queries.set_status(conn, scan["id"], status)
        conn.commit()
    return ScanResult(name=scan["name"], status=status, sources=results)


def _claim(
    conn: sqlite3.Connection, scan: sqlite3.Row, rows: list[sqlite3.Row], *, new_round: bool
) -> dict:
    """Mark sources as running, refusing any another live scan is processing.

    Returns the status to give back to each source if this run doesn't reach it: ``pending``
    in a new round, so a resumed round knows it still has to visit it.
    """
    source_ids = [row["source_id"] for row in rows]
    conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        live = scan_queries.live_claims(conn, source_ids, now_ns() - STALE_AFTER_NS)
        if live:
            busy = ", ".join(f"'{c['label']}' (scan '{c['scan_name']}')" for c in live)
            raise ScanConflict(
                f"Already being scanned: {busy}. Only one scan can process a source at a time."
            )
        previous = {row["source_id"]: "pending" if new_round else row["status"] for row in rows}
        for source_id in source_ids:
            scan_queries.update_scan_source(
                conn, scan["id"], source_id, status="running", heartbeat_at=now_ns()
            )
        scan_queries.set_status(conn, scan["id"], "running")
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return previous


class _SourceRun:
    def __init__(self, conn, scan_id, source, verify, should_stop, progress):
        self.conn = conn
        self.scan_id = scan_id
        self.source = source
        self.source_id = source["id"]
        self.root = Path(source["root_path"])
        self.verify = verify
        self.should_stop = should_stop or (lambda: False)
        self.progress = progress
        self.result = SourceResult(label=source["label"])
        self.stopped = False
        self.pass_started_at: int | None = None
        self.resume_path: str | None = None
        self.file_count = 0
        self.total_bytes = 0
        self._since_commit = 0
        self._last_commit = time.monotonic()

    # Orchestration

    def run(self) -> SourceResult:
        row = self._start_or_resume_pass()
        try:
            if not source_service.is_online(self.source):
                raise _SourceOffline
            source_queries.set_state(self.conn, self.source_id, "online")
            if row["stage"] == "walk":
                self._walk(row["resume_path"])
                if self.stopped:
                    return self._finish("paused")
                self.resume_path = None
                self._save(stage="hash")
            if scan_queries.scan_source(self.conn, self.scan_id, self.source_id)["stage"] == "hash":
                self._hash()
                if self.stopped:
                    return self._finish("paused")
                self._save(stage="done")
            self._reconcile()
            return self._finish("complete", finished_at=now_iso())
        except _SourceOffline:
            source_queries.set_state(self.conn, self.source_id, "offline")
            return self._finish("offline")
        except BaseException:
            # Keep the work done so far, and leave the pass resumable.
            self._finish("paused")
            raise

    def _start_or_resume_pass(self) -> sqlite3.Row:
        row = scan_queries.scan_source(self.conn, self.scan_id, self.source_id)
        mode = "verify" if self.verify else "incremental"
        resumable = (
            row["pass_started_at"] is not None
            and row["stage"] != "done"
            and (not self.verify or row["mode"] == "verify")
        )
        if not resumable:
            self.resume_path = None
            self._save(
                mode=mode,
                stage="walk",
                resume_path=None,
                pass_started_at=now_ns(),
                file_count=0,
                total_bytes=0,
                started_at=now_iso(),
                finished_at=None,
            )
        self.conn.commit()
        row = scan_queries.scan_source(self.conn, self.scan_id, self.source_id)
        self.pass_started_at = row["pass_started_at"]
        self.verify = row["mode"] == "verify"
        self.file_count = row["file_count"]
        self.total_bytes = row["total_bytes"]
        self.resume_path = row["resume_path"]
        return row

    def _save(self, **fields) -> None:
        values = {
            "heartbeat_at": now_ns(),
            "file_count": self.file_count,
            "total_bytes": self.total_bytes,
            "resume_path": self.resume_path,
            **fields,
        }
        scan_queries.update_scan_source(self.conn, self.scan_id, self.source_id, **values)

    def _finish(self, status: str, **fields) -> SourceResult:
        self._save(status=status, **fields)
        self.conn.commit()
        self.result.status = status
        return self.result

    def _tick(self, stage: str, **fields) -> None:
        """Commit a batch when it's big or old enough, with the resume point and a heartbeat."""
        self._since_commit += 1
        if (
            self._since_commit >= BATCH_FILES
            or time.monotonic() - self._last_commit >= BATCH_SECONDS
        ):
            self._save(**fields)
            self.conn.commit()
            self._since_commit = 0
            self._last_commit = time.monotonic()
            if self.progress:
                done = self.result.seen if stage == "walk" else self.result.hashed
                self.progress(self.source["label"], stage, done)

    def _error(self, rel_path: str, stage: str, message: str) -> None:
        scan_queries.add_error(self.conn, self.scan_id, self.source_id, rel_path, stage, message)
        self.result.errors += 1

    def _check_root(self) -> None:
        if not self.root.is_dir():
            raise _SourceOffline

    # Stage 1: walk

    def _walk(self, resume_path: str | None) -> None:
        def on_error(rel_path: str, exc: OSError) -> None:
            self._check_root()
            self._error(rel_path, "walk", f"{type(exc).__name__}: {exc}")

        try:
            for entry in walk(self.root, after=resume_path, on_error=on_error):
                if self.should_stop():
                    self.stopped = True
                    break
                self._record(entry)
                self.resume_path = entry.rel_path
                self._tick("walk")
        except OSError as exc:
            raise _SourceOffline from exc
        if self.stopped:
            self._save()
            self.conn.commit()

    def _record(self, entry: WalkEntry) -> None:
        path = PurePosixPath(entry.rel_path)
        extension = path.suffix.lower()
        supported = metadata.is_photo(path.name)
        existing = file_queries.by_path(self.conn, self.source_id, entry.rel_path)
        seen = {
            "size_bytes": entry.size_bytes,
            "mtime_ns": entry.mtime_ns,
            "birthtime_ns": entry.birthtime_ns,
            "last_seen_scan_id": self.scan_id,
            "last_seen_at": now_ns(),
        }
        self.result.seen += 1
        self.file_count += 1
        self.total_bytes += entry.size_bytes

        if existing is None:
            file_queries.insert(
                self.conn,
                source_id=self.source_id,
                rel_path=entry.rel_path,
                filename=path.name,
                extension=extension,
                status="present" if supported else "unsupported",
                pending_hash=int(supported),
                first_seen_scan_id=self.scan_id,
                first_seen_at=seen["last_seen_at"],
                **seen,
            )
            return
        if not supported:
            if existing["status"] != "unsupported":
                # Read as a photo before, like an AppleDouble sidecar: its errors no longer apply.
                scan_queries.clear_decode_errors(self.conn, self.source_id, entry.rel_path)
            file_queries.update(
                self.conn, existing["id"], status="unsupported", pending_hash=0, **seen
            )
            return
        unchanged = (existing["size_bytes"], existing["mtime_ns"]) == (
            entry.size_bytes,
            entry.mtime_ns,
        )
        if (
            unchanged
            and not self.verify
            and existing["content_id"] is not None
            and existing["status"] in REUSABLE_STATUSES
        ):
            status = existing["status"]
            content = None
            if status in ("missing", "unsupported"):
                content = file_queries.content_by_id(self.conn, existing["content_id"])
            if status == "unsupported" and metadata.needs_redecode(content):
                # Its format is read now, so hash it again to decode it.
                file_queries.update(self.conn, existing["id"], pending_hash=1, **seen)
                return
            if status == "missing":
                status = content_status(content)
            file_queries.update(self.conn, existing["id"], status=status, pending_hash=0, **seen)
            self.result.reused += 1
            return
        file_queries.update(self.conn, existing["id"], status="present", pending_hash=1, **seen)

    # Stage 2: hash

    def _hash(self) -> None:
        for file_id in file_queries.pending_hash_ids(self.conn, self.source_id):
            if self.should_stop():
                self.stopped = True
                break
            row = file_queries.by_id(self.conn, file_id)
            if row is None or not row["pending_hash"]:
                continue
            self._hash_one(row)
            self._tick("hash")
        self._save()
        self.conn.commit()

    def _hash_one(self, row: sqlite3.Row) -> None:
        rel_path = row["rel_path"]
        path = self.root / rel_path
        try:
            before = _stat(path)
            digest = hashing.hash_file(path)
            after = _stat(path)
        except OSError as exc:
            self._check_root()
            self._error(rel_path, "hash", f"{type(exc).__name__}: {exc}")
            file_queries.update(self.conn, row["id"], status="unreadable", pending_hash=0)
            return
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            self._error(rel_path, "hash", "The file changed while it was being read.")
            file_queries.update(
                self.conn,
                row["id"],
                status="changed_during_scan",
                pending_hash=0,
                size_bytes=after.st_size,
                mtime_ns=after.st_mtime_ns,
            )
            return

        content = file_queries.content_by_blake3(self.conn, digest)
        redecoded = False
        if content is None:
            info = metadata.read_image(path)
            if info.decode_error:
                self._error(rel_path, "decode", info.decode_error)
            if info.exif_error:
                self._error(rel_path, "exif", info.exif_error)
            content_id = file_queries.insert_content(
                self.conn, digest, before.st_size, asdict(info)
            )
            content = file_queries.content_by_id(self.conn, content_id)
            self.result.new_contents += 1
        elif metadata.needs_redecode(content):
            info = metadata.read_image(path)
            scan_queries.clear_decode_errors(self.conn, self.source_id, rel_path)
            if info.decode_error:
                self._error(rel_path, "decode", info.decode_error)
            if info.exif_error:
                self._error(rel_path, "exif", info.exif_error)
            file_queries.update_content(self.conn, content["id"], asdict(info))
            content = file_queries.content_by_id(self.conn, content["id"])
            redecoded = True
        if row["content_id"] is not None and row["content_id"] != content["id"]:
            self.result.content_changes.append(rel_path)

        status = content_status(content)
        if row["status"] == "unsupported" and status != "unsupported" and not redecoded:
            # Another copy of this content was read again: its old errors no longer apply.
            scan_queries.clear_decode_errors(self.conn, self.source_id, rel_path)
        update = {
            "content_id": content["id"],
            "status": status,
            "pending_hash": 0,
            "size_bytes": before.st_size,
            "mtime_ns": before.st_mtime_ns,
        }
        if self.verify:
            update["last_verified_at"] = now_iso()
        file_queries.update(self.conn, row["id"], **update)
        self.result.hashed += 1

    # Stage 3: reconcile

    def _reconcile(self) -> None:
        """Settle files not seen in this pass: moved within the source, or missing."""
        self._check_root()
        if not source_service.is_online(self.source):
            raise _SourceOffline
        unreadable = scan_queries.walk_error_paths(
            self.conn, self.scan_id, self.source_id, self.pass_started_at
        )
        arrivals: dict[int, list[sqlite3.Row]] = {}
        for row in file_queries.first_seen_since(self.conn, self.source_id, self.pass_started_at):
            arrivals.setdefault(row["content_id"], []).append(row)

        for gone in file_queries.vanished(self.conn, self.source_id, self.pass_started_at):
            if any(_inside(gone["rel_path"], folder) for folder in unreadable):
                continue  # couldn't look, so it isn't known to be gone
            moved_to = arrivals.get(gone["content_id"]) if gone["content_id"] else None
            if moved_to:
                new = moved_to.pop(0)
                # Keep the original row, and so its ID and any decisions, at the new path.
                file_queries.remove_row(self.conn, new["id"])
                file_queries.update(
                    self.conn,
                    gone["id"],
                    rel_path=new["rel_path"],
                    filename=new["filename"],
                    extension=new["extension"],
                    size_bytes=new["size_bytes"],
                    mtime_ns=new["mtime_ns"],
                    birthtime_ns=new["birthtime_ns"],
                    status=new["status"],
                    last_seen_scan_id=new["last_seen_scan_id"],
                    last_seen_at=new["last_seen_at"],
                )
                self.result.moved += 1
            else:
                file_queries.update(self.conn, gone["id"], status="missing")
                self.result.missing += 1


def _inside(rel_path: str, folder: str) -> bool:
    return not folder or rel_path == folder or rel_path.startswith(folder + "/")


def content_status(content: sqlite3.Row) -> str:
    """A file's status as its content implies: corrupt, unsupported or present."""
    if content["format"] and content["format"] not in metadata.SUPPORTED_FORMATS:
        return "unsupported"
    if content["decode_error"]:
        return "corrupt"
    return "present"
