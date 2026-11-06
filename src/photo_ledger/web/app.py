"""The FastAPI app: GTH wiring plus this project's local-only protections."""

from pathlib import Path

import greentechhub_ui
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from greentechhub_fastapi import register_core, register_health, register_logging
from greentechhub_fastapi.audit import AuditViews
from greentechhub_fastapi.auth.csrf import require_csrf
from greentechhub_fastapi.exceptions import register_exception_handlers
from greentechhub_fastapi.flash import flash
from greentechhub_fastapi.notifications import NotificationViews, notifications_nav_item
from greentechhub_fastapi.registration.audit import register_audit
from greentechhub_fastapi.registration.auth import register_auth
from greentechhub_fastapi.registration.csrf import register_csrf
from greentechhub_fastapi.registration.error_pages import register_error_pages
from greentechhub_fastapi.registration.flash import register_flash
from greentechhub_fastapi.registration.jobs import register_jobs
from greentechhub_fastapi.registration.notifications import register_notifications
from greentechhub_fastapi.templating import mount_static_dirs, ui_context
from greentechhub_ui.navigation import build_nav_items
from starlette.middleware.trustedhost import TrustedHostMiddleware

from photo_ledger import __version__
from photo_ledger.config import LOCAL_HOSTS, Settings
from photo_ledger.db.activity import SqliteAuditStore, SqliteNotificationStore
from photo_ledger.errors import PhotoLedgerError
from photo_ledger.web.errors import describe
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


class ActivityViews(AuditViews):
    """The activity log as the Activity page: what was scanned, applied, undone and built."""

    url = "/activity"
    title = "Activity"
    icon = "clock-history"


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
                {"label": "Activity", "url": "/activity"},
                {"label": "Settings", "url": "/settings"},
                notifications_nav_item(),
            ]
        ),
    )
    app.state.templates = templates

    register_logging(app, settings, service="photo-ledger", version=__version__)
    register_core(app, settings)
    register_csrf(app, settings)
    # One person on 127.0.0.1: every request is that person, so notifications and the activity
    # log work without a sign-in. The app binds to 127.0.0.1 only (see web/security.py).
    register_auth(app, settings)
    register_flash(app, settings)
    # Scans run as background jobs. Shutting down cancels them, which pauses each cleanly. A scan
    # records its own outcome (scanner/jobs.py), since a paused scan isn't a "finished" job.
    register_jobs(app, settings, audit=False)
    register_audit(
        app,
        settings,
        store=SqliteAuditStore(settings.db_path),
        views=ActivityViews(templates=templates, permission=None),
    )
    register_notifications(app, settings, store=SqliteNotificationStore(settings.db_path))
    # Mounted here, not through register_notifications, so marking notices read needs the CSRF
    # token like every other state-changing route. require_csrf lets the GET routes through.
    app.include_router(
        NotificationViews(templates=templates).router(), dependencies=[Depends(require_csrf)]
    )
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

    def refuse(request: Request, message: str, status_code: int) -> Response:
        """Say why something was refused. An htmx form goes back to its page, with the reason
        as a toast. A plain form or link gets the notice page."""
        if request.headers.get("HX-Request") == "true":
            response = Response(status_code=200, headers={"HX-Redirect": back_path(request)})
            flash(response, message, kind="danger")
            return response
        return templates.TemplateResponse(
            request, "notice.html", {"message": message}, status_code=status_code
        )

    @app.exception_handler(PhotoLedgerError)
    async def expected_failure(request: Request, exc: PhotoLedgerError):
        """An expected refusal, such as deciding a pair that no longer matches."""
        return refuse(request, str(exc), 409)

    @app.exception_handler(RequestValidationError)
    async def unreadable_form(request: Request, exc: RequestValidationError):
        """A missing or malformed field or link id, named in a sentence instead of FastAPI's
        JSON. It replaces greentechhub-fastapi's JSON handler: this app has no JSON API."""
        return refuse(request, describe(exc), 422)

    return app
