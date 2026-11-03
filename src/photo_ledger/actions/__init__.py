"""Planner, dry run, executor and recovery. Only ``executor.py`` ever changes a source folder.

Nothing here imports FastAPI, so the CLI can plan, apply and undo without the web layer.
"""

from photo_ledger.errors import PhotoLedgerError


class PlanError(PhotoLedgerError):
    """A plan can't be built, checked, applied or undone."""


__all__ = ["PlanError"]
