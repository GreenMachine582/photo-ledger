"""Small display helpers shared by the CLI and the web pages."""

from datetime import UTC, datetime


def human_size(num_bytes: int | None) -> str:
    if num_bytes is None:
        return ""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def file_date(mtime_ns: int | None) -> str:
    if mtime_ns is None:
        return ""
    return datetime.fromtimestamp(mtime_ns / 1e9, tz=UTC).strftime("%Y-%m-%d %H:%M UTC")
