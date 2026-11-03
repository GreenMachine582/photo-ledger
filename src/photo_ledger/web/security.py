"""Browser protections for an app on 127.0.0.1.

Localhost is not a complete boundary: any website you visit can make your browser
send requests here. Host validation stops DNS rebinding, and the Origin check refuses
state-changing requests from other sites. CSRF tokens (register_csrf and require_csrf)
sit on top of these, and CORS stays closed because no origins are configured.
"""

from urllib.parse import urlsplit

from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from photo_ledger.config import LOCAL_HOSTS

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class LocalOriginMiddleware:
    """Refuse state-changing requests whose Origin isn't this machine."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] not in SAFE_METHODS:
            headers = {key.lower(): value for key, value in scope["headers"]}
            origin = headers.get(b"origin", b"").decode("latin-1")
            if origin and urlsplit(origin).hostname not in LOCAL_HOSTS:
                response = PlainTextResponse("Cross-origin request refused", status_code=403)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
