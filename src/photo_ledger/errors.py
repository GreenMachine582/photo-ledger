"""Errors the CLI reports as a message and exit code, rather than a traceback."""


class PhotoLedgerError(Exception):
    """Base class for expected, user-facing failures."""
