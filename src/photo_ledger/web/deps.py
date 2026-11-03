"""Request dependencies: one catalogue connection per request."""

import sqlite3
from collections.abc import Iterator

from fastapi import Request

from photo_ledger.db import open_db


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    conn = open_db(request.app.state.settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


def render(request: Request, template: str, context: dict, status_code: int = 200):
    return request.app.state.templates.TemplateResponse(
        request, template, context, status_code=status_code
    )
