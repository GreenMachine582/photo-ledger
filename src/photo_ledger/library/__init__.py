"""The destination library: which pictures go in, where, and whether it's ready to build.

Everything here only reads files and writes to the catalogue. Copying into the library is the
executor's job (``actions/executor.py``). No FastAPI, so the CLI works without the web layer.
"""

from photo_ledger.errors import PhotoLedgerError


class LibraryError(PhotoLedgerError):
    """The library can't be set up or built as asked."""


__all__ = ["LibraryError"]
