"""htmx-posted forms, such as the busy-button forms, get full page loads after they finish.

A state-changing route answers with a 303 redirect, which a plain form follows. An htmx request
would follow it inside the XHR and swap nothing, so ``HtmxRedirectMiddleware`` turns it into a
200 with ``HX-Redirect``, and htmx loads the page itself. The flash cookie on the response then
shows as a toast there. ``back_path`` is where an expected refusal sends an htmx request back to.
"""

from urllib.parse import urlsplit

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from photo_ledger.config import LOCAL_HOSTS


def is_htmx(headers: dict[bytes, bytes]) -> bool:
    return headers.get(b"hx-request") == b"true" and b"hx-boosted" not in headers


class HtmxRedirectMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not is_htmx(dict(scope["headers"])):
            await self.app(scope, receive, send)
            return

        async def send_redirect(message: Message) -> None:
            if message["type"] == "http.response.start" and message["status"] == 303:
                headers = [
                    (b"hx-redirect", value) if key.lower() == b"location" else (key, value)
                    for key, value in message["headers"]
                ]
                message = {**message, "status": 200, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_redirect)


def back_path(request: Request) -> str:
    """The page an htmx request came from, if it's this app's own; else the overview."""
    referer = urlsplit(request.headers.get("referer", ""))
    if referer.hostname not in LOCAL_HOSTS or not referer.path.startswith("/"):
        return "/"
    return referer.path + (f"?{referer.query}" if referer.query else "")
