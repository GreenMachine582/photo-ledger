"""The FastAPI app: GTH wiring plus this project's local-only protections."""

from pathlib import Path

import greentechhub_ui
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from greentechhub_fastapi import register_core, register_health, register_logging
from greentechhub_fastapi.exceptions import register_exception_handlers
from greentechhub_fastapi.registration.csrf import register_csrf
from greentechhub_fastapi.registration.error_pages import register_error_pages
from greentechhub_fastapi.templating import mount_static_dirs, ui_context
from greentechhub_ui.navigation import build_nav_items
from starlette.middleware.trustedhost import TrustedHostMiddleware

from photo_ledger import __version__
from photo_ledger.config import LOCAL_HOSTS, Settings
from photo_ledger.errors import PhotoLedgerError
from photo_ledger.web.routes import collections, files, home, plan, reports, review
from photo_ledger.web.security import LocalOriginMiddleware

WEB_DIR = Path(__file__).parent


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="Photo Ledger", version=__version__, docs_url=None, redoc_url=None)
    app.state.settings = settings

    templates = Jinja2Templates(directory=WEB_DIR / "templates", context_processors=[ui_context])
    greentechhub_ui.install(
        templates.env,
        service_name="Photo Ledger",
        nav_items=build_nav_items(
            custom_items=[
                {"label": "Overview", "url": "/"},
                {"label": "Review", "url": "/review"},
                {"label": "Collections", "url": "/collections"},
                {"label": "Reports", "url": "/reports"},
                {"label": "Plan", "url": "/plan"},
            ]
        ),
    )
    app.state.templates = templates

    register_logging(app, settings, service="photo-ledger", version=__version__)
    register_core(app, settings)
    register_csrf(app, settings)
    register_health(app)
    register_exception_handlers(app)
    register_error_pages(app, settings, templates=templates)

    # Added last so they run first, before anything else sees the request.
    app.add_middleware(LocalOriginMiddleware)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(LOCAL_HOSTS))

    mount_static_dirs(app, greentechhub_ui.static_dirs())
    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
    app.include_router(home.router)
    app.include_router(review.router)
    app.include_router(files.router)
    app.include_router(collections.router)
    app.include_router(reports.router)
    app.include_router(plan.router)

    @app.exception_handler(PhotoLedgerError)
    async def expected_failure(request: Request, exc: PhotoLedgerError):
        """An expected refusal, such as deciding a pair that no longer matches: say why."""
        return templates.TemplateResponse(
            request, "notice.html", {"message": str(exc)}, status_code=409
        )

    return app
