"""The landing page. M1 onwards replaces it with the Sources and Overview pages."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    return request.app.state.templates.TemplateResponse(request, "home.html", {})
