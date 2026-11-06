"""The FastAPI app: GTH wiring plus this project's local-only protections."""

from pathlib import Path

import greentechhub_ui
from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from greentechhub_fastapi import register_core, register_health, register_logging
from greentechhub_fastapi.exceptions import register_exception_handlers
from greentechhub_fastapi.flash import flash
from greentechhub_fastapi.registration.csrf import register_csrf
from greentechhub_fastapi.registration.error_pages import register_error_pages
from greentechhub_fastapi.registration.flash import register_flash
from greentechhub_fastapi.registration.jobs import register_jobs
from greentechhub_fastapi.templating import mount_static_dirs, ui_context
from greentechhub_ui.navigation import build_nav_items
from starlette.middleware.trustedhost import TrustedHostMiddleware

from photo_ledger import __version__
from photo_ledger.config import LOCAL_HOSTS, Settings
from photo_ledger.errors import PhotoLedgerError
from photo_ledger.web.htmx import HtmxRedirectMiddleware, back_path
from photo_ledger.web.routes import (
    catalogue,
    collections,
    exports,
    files,
    folders,
    home,
    library,
    match,
    plan,
    reports,
    review,
    scans,
    sources,
)
from photo_ledger.web.routes import settings as settings_routes
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
                {
                    "label": "Catalogue",
                    "children": [
                        {"label": "Sources", "url": "/sources"},
                        {"label": "Scans", "url": "/scans"},
                        {"label": "Photos", "url": "/catalogue"},
                        {"label": "Collections", "url": "/collections"},
                        {"label": "Reports", "url": "/reports"},
                    ],
                },
                {"label": "Review", "url": "/review"},
                {
                    "label": "Organise",
                    "children": [
                        {"label": "Plan", "url": "/plan"},
                        {"label": "Library", "url": "/library"},
                    ],
                },
                {"label": "Settings", "url": "/settings"},
            ]
        ),
    )
    app.state.templates = templates

    register_logging(app, settings, service="photo-ledger", version=__version__)
    register_core(app, settings)
    register_csrf(app, settings)
    register_flash(app, settings)
    # Scans run as background jobs. Shutting down cancels them, which pauses each cleanly.
    register_jobs(app, settings)
    register_health(app)
    register_exception_handlers(app)
    register_error_pages(app, settings, templates=templates)

    app.add_middleware(HtmxRedirectMiddleware)
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
    app.include_router(sources.router)
    app.include_router(folders.router)
    app.include_router(library.router)
    app.include_router(scans.router)
    app.include_router(match.router)
    app.include_router(catalogue.router)
    app.include_router(exports.router)
    app.include_router(settings_routes.router)

    @app.exception_handler(PhotoLedgerError)
    async def expected_failure(request: Request, exc: PhotoLedgerError):
        """An expected refusal, such as deciding a pair that no longer matches: say why. An
        htmx form goes back to its page, with the reason as a toast."""
        if request.headers.get("HX-Request") == "true":
            response = Response(status_code=200, headers={"HX-Redirect": back_path(request)})
            flash(response, str(exc), kind="danger")
            return response
        return templates.TemplateResponse(
            request, "notice.html", {"message": str(exc)}, status_code=409
        )

    return app
