"""FastAPI app cho dashboard. Một trang điều khiển + cấu hình toàn pipeline.

Bảo mật: đăng nhập bằng dashboard_password (session cookie ký bằng
dashboard_secret_key). Đứng sau Cloudflare Tunnel khi expose ra ngoài.
"""

from __future__ import annotations

import json
import secrets as _secrets
from pathlib import Path

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from starlette.status import HTTP_303_SEE_OTHER

from ..config.settings import settings
from . import approvals, config_store, jobs

_WEB_DIR = Path(__file__).resolve().parent
_PROJECT_DIR = _WEB_DIR.parents[2]
_SCRIPTS_DIR = _PROJECT_DIR / "scripts"
_LEDGER = _PROJECT_DIR / "data/ledger.md"
_AUTO_STATE = _PROJECT_DIR / "assets/auto_state.json"

templates = Jinja2Templates(directory=str(_WEB_DIR / "templates"))


def create_app() -> FastAPI:
    app = FastAPI(title="claude-ytb dashboard")
    secret = settings.dashboard_secret_key or _secrets.token_hex(32)
    app.add_middleware(SessionMiddleware, secret_key=secret)

    static_dir = _WEB_DIR / "static"
    static_dir.mkdir(exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    _register_routes(app)
    return app


# ── Auth ──────────────────────────────────────────────────────────────────────
def _require_login(request: Request) -> bool:
    """Dependency: chuyển hướng /login nếu chưa đăng nhập."""
    if not request.session.get("auth"):
        raise _Redirect("/login")
    return True


class _Redirect(Exception):
    def __init__(self, url: str) -> None:
        self.url = url


# ── Trạng thái hiển thị ─────────────────────────────────────────────────────────
def _scripts() -> list[str]:
    if not _SCRIPTS_DIR.exists():
        return []
    return sorted(p.stem for p in _SCRIPTS_DIR.glob("*.json"))


def _ledger_tail(n: int = 12) -> list[str]:
    if not _LEDGER.exists():
        return []
    lines = [ln for ln in _LEDGER.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return lines[-n:]


def _auto_state() -> dict:
    if not _AUTO_STATE.exists():
        return {}
    try:
        return json.loads(_AUTO_STATE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _status_ctx(request: Request) -> dict:
    job = jobs.current()
    return {
        "request": request,
        "scripts": _scripts(),
        "ledger": _ledger_tail(),
        "auto_state": _auto_state(),
        "pending": approvals.list_pending(),
        "job": job,
        "dry_run": settings.dry_run,
    }


# ── Routes ──────────────────────────────────────────────────────────────────────
def _register_routes(app: FastAPI) -> None:
    @app.exception_handler(_Redirect)
    async def _redirect_handler(request: Request, exc: _Redirect):  # noqa: ANN001
        return RedirectResponse(exc.url, status_code=HTTP_303_SEE_OTHER)

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request):
        return templates.TemplateResponse(request, "login.html", {"error": ""})

    @app.post("/login")
    async def login(request: Request, password: str = Form("")):
        if not settings.dashboard_password:
            return templates.TemplateResponse(request, "login.html", {"error": "Chưa đặt DASHBOARD_PASSWORD — truy cập bị chặn."})
        if _secrets.compare_digest(password, settings.dashboard_password):
            request.session["auth"] = True
            return RedirectResponse("/", status_code=HTTP_303_SEE_OTHER)
        return templates.TemplateResponse(request, "login.html", {"error": "Sai mật khẩu."})

    @app.get("/logout")
    async def logout(request: Request):
        request.session.clear()
        return RedirectResponse("/login", status_code=HTTP_303_SEE_OTHER)

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request, _: bool = Depends(_require_login)):
        return templates.TemplateResponse(request, "dashboard.html", _status_ctx(request))

    @app.get("/partials/status", response_class=HTMLResponse)
    async def status_partial(request: Request, _: bool = Depends(_require_login)):
        return templates.TemplateResponse(request, "_status.html", _status_ctx(request))

    @app.post("/run")
    async def run(request: Request, script: str = Form(...), _: bool = Depends(_require_login)):
        jobs.run_pipeline(script)
        return RedirectResponse("/", status_code=HTTP_303_SEE_OTHER)

    @app.post("/auto")
    async def auto(request: Request, instruction: str = Form(...), _: bool = Depends(_require_login)):
        jobs.run_auto(instruction)
        return RedirectResponse("/", status_code=HTTP_303_SEE_OTHER)

    @app.post("/stop")
    async def stop(request: Request, _: bool = Depends(_require_login)):
        jobs.stop()
        return RedirectResponse("/", status_code=HTTP_303_SEE_OTHER)

    @app.post("/approve/{item_id}")
    async def approve(
        request: Request,
        item_id: int,
        decision: str = Form(...),
        instruction: str = Form(""),
        _: bool = Depends(_require_login),
    ):
        approvals.resolve(item_id, approved=(decision == "approve"), instruction=instruction)
        return RedirectResponse("/", status_code=HTTP_303_SEE_OTHER)

    @app.get("/config", response_class=HTMLResponse)
    async def config_page(request: Request, _: bool = Depends(_require_login)):
        return templates.TemplateResponse(
            request,
            "config.html",
            {
                "groups": config_store.grouped_fields(),
                "value": config_store.public_value,
                "saved": request.query_params.get("saved"),
            },
        )

    @app.post("/config")
    async def config_save(request: Request, _: bool = Depends(_require_login)):
        form = await request.form()
        changed = config_store.save(dict(form))
        return RedirectResponse(f"/config?saved={len(changed)}", status_code=HTTP_303_SEE_OTHER)


app = create_app()
