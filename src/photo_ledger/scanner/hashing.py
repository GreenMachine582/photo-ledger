"""Content hashing. Only a BLAKE3 hash proves two files hold the same content."""

from pathlib import Path

from blake3 import blake3

CHUNK_BYTES = 1 << 20


def hash_file(path: Path) -> str:
    """The BLAKE3 hex digest of a file, read in chunks. Opens the file read-only."""
    hasher = blake3()
    with open(path, "rb") as handle:
        while chunk := handle.read(CHUNK_BYTES):
            hasher.update(chunk)
    return hasher.hexdigest()
