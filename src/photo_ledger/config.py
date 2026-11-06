"""Settings. Runtime data lives outside the repo, in the OS application data folder."""

import secrets
from pathlib import Path
from typing import Literal

from greentechhub_core.config import GTHBaseSettings
from platformdirs import user_data_path
from pydantic import Field

from photo_ledger.collections.folders import DEFAULT_GENERIC_FOLDERS

#: The only addresses the app answers on. See web/security.py.
LOCAL_HOSTS = ("127.0.0.1", "localhost")


def _default_data_dir() -> Path:
    return user_data_path("photo-ledger", appauthor=False)


class Settings(GTHBaseSettings):
    """Read from PHOTO_LEDGER_* style environment variables or a local .env file."""

    # GTH requires a key, but nothing here outlives the process: no sign-in, no sessions.
    secret_key: str = Field(default_factory=lambda: secrets.token_hex(32))
    #: One person on 127.0.0.1 and no sign-in. Fixed: the app has no login page to fall back on.
    auth_adapter: Literal["single_user"] = "single_user"
    photo_ledger_data_dir: Path = Field(default_factory=_default_data_dir)
    photo_ledger_port: int = 8765
    #: Largest pHash Hamming distance, out of 64 bits, that counts as a similar image.
    photo_ledger_similar_threshold: int = Field(default=8, ge=0, le=32)
    #: Folder names that never become collections, matched case-insensitively.
    photo_ledger_generic_folders: list[str] = Field(
        default_factory=lambda: list(DEFAULT_GENERIC_FOLDERS)
    )

    @property
    def db_path(self) -> Path:
        return self.photo_ledger_data_dir / "photo-ledger.db"

    @property
    def thumbnail_dir(self) -> Path:
        return self.photo_ledger_data_dir / "thumbnails"
