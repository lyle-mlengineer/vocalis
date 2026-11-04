from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


def _page(request: Request, page: str, title: str, **context) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name=f"{page}.html",
        context={
            "title": title,
            "page": page,
            "firebase_config": request.app.state.frontend_firebase_config,
            **context,
        },
    )


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def home(request: Request):
    return _page(request, "home", "Vocalis — voices designed by AI")


@router.get("/studio", response_class=HTMLResponse, include_in_schema=False)
def studio(request: Request):
    return _page(request, "studio", "Voice studio")


@router.get("/voices", response_class=HTMLResponse, include_in_schema=False)
def voices_page(request: Request):
    return _page(request, "voices", "Your voice library")


@router.get("/playground", response_class=HTMLResponse, include_in_schema=False)
def playground_page(request: Request):
    return _page(request, "playground", "Voice playground")


@router.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
def dashboard_page(request: Request):
    return _page(request, "dashboard", "Your dashboard")


@router.get("/billing", response_class=HTMLResponse, include_in_schema=False)
def billing_page(request: Request):
    return _page(request, "billing", "Credits & billing")


@router.get("/login", response_class=HTMLResponse, include_in_schema=False)
def login_page(request: Request):
    return _page(request, "auth", "Sign in", auth_mode="login")


@router.get("/register", response_class=HTMLResponse, include_in_schema=False)
def register_page(request: Request):
    return _page(request, "auth", "Create your account", auth_mode="register")


@router.get("/pricing", response_class=HTMLResponse, include_in_schema=False)
def pricing_page(request: Request):
    return _page(request, "pricing", "Simple, flexible pricing")


@router.get("/faq", response_class=HTMLResponse, include_in_schema=False)
def faq_page(request: Request):
    return _page(request, "faq", "Frequently asked questions")
