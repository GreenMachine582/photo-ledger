"""The request's database connection."""

import threading
from types import SimpleNamespace

from photo_ledger.web.deps import get_db


def test_a_request_connection_works_across_threadpool_threads(settings):
    """FastAPI opens a sync generator dependency in one worker thread and may run the endpoint
    in another, so the connection must not be tied to the thread that opened it."""
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=settings)))
    dependency = get_db(request)
    opened = {}
    thread = threading.Thread(target=lambda: opened.setdefault("conn", next(dependency)))
    thread.start()
    thread.join()

    result = {}

    def endpoint():
        result["value"] = opened["conn"].execute("SELECT 1").fetchone()[0]

    thread = threading.Thread(target=endpoint)
    thread.start()
    thread.join()
    assert result == {"value": 1}
    dependency.close()
