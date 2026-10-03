import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from auth import SESSION_IDLE_MINUTES, is_production, get_current_user, set_auth_cookie
from database import (
    backend_name,
    cleanup_sessions,
    clear_recommendations,
    get_recommendation,
    initialize_database,
    list_recommendations,
    ping,
)
from planner_service import create_plan
from routers import auth, home, jewelry, party

logger = logging.getLogger("pocketsmart")

PROJECT_DIR = Path(__file__).resolve().parent
# The UI (Jinja2 templates + static assets) lives in the sibling frontend/ folder.
FRONTEND_DIR = PROJECT_DIR.parent / "frontend"
templates = Jinja2Templates(directory=str(FRONTEND_DIR / "templates"))

DEFAULT_CORS_ORIGINS = "http://localhost:8000,http://127.0.0.1:8000,http://localhost:3000,http://localhost:5173"
SESSION_CLEANUP_INTERVAL_SECONDS = 300


async def _session_cleanup_loop() -> None:
    """Background task: remove sessions idle for SESSION_IDLE_MINUTES (SRS 3.4)."""
    while True:
        await asyncio.sleep(SESSION_CLEANUP_INTERVAL_SECONDS)
        try:
            removed = await asyncio.to_thread(cleanup_sessions, SESSION_IDLE_MINUTES)
            if removed:
                logger.info("Removed %s expired session(s)", removed)
        except Exception:
            logger.exception("Session cleanup failed")


@asynccontextmanager
async def lifespan(application: FastAPI):
    initialize_database()
    cleanup_task = asyncio.create_task(_session_cleanup_loop())
    try:
        yield
    finally:
        cleanup_task.cancel()
        with suppress(asyncio.CancelledError):
            await cleanup_task


app = FastAPI(title="PocketSmart: AI Budget Planner", lifespan=lifespan)

# CORS: explicit origins only (never "*" together with credentials).  The app
# serves its own pages, so this only matters for a separately hosted frontend.
_cors_origins = [
    origin.strip().rstrip("/")
    for origin in os.getenv("CORS_ORIGINS", DEFAULT_CORS_ORIGINS).split(",")
    if origin.strip() and origin.strip() != "*"
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)


@app.middleware("http")
async def session_cookie_and_security_headers(request: Request, call_next):
    response = await call_next(request)
    refreshed_token = getattr(request.state, "refreshed_token", None)
    if refreshed_token:
        set_auth_cookie(response, refreshed_token)  # sliding session
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    return response


@app.exception_handler(StarletteHTTPException)
async def friendly_unauthorized(request: Request, exc: StarletteHTTPException):
    """Browsers that open a private page without a session go to /login.

    The status stays 401 (APIs and tests rely on it); only the body differs.
    """
    wants_html = "text/html" in request.headers.get("accept", "")
    if exc.status_code == 401 and wants_html and not request.url.path.startswith("/api/"):
        return HTMLResponse(
            '<!doctype html><meta charset="utf-8">'
            '<meta http-equiv="refresh" content="0;url=/login?expired=1">'
            '<title>Sign in required</title><p>Your session has ended. '
            '<a href="/login?expired=1">Sign in again</a>.</p>',
            status_code=401,
            headers=exc.headers,
        )
    return await http_exception_handler(request, exc)


app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR / "static")), name="static")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return RedirectResponse(url="/static/favicon.svg")


class RecommendationDetailsRequest(BaseModel):
    category: Literal["home", "party", "jewelry"] = "home"
    budget: float = Field(ge=1, le=50000000)
    preferences: dict[str, Any] = Field(default_factory=dict)


@app.get("/")
async def root(request: Request):
    return templates.TemplateResponse(request=request, name="home.html")


@app.get("/dashboard")
async def dashboard(request: Request, user: dict = Depends(get_current_user)):
    return templates.TemplateResponse(request=request, name="dashboard.html", context={"username": user["username"]})


@app.get("/history")
async def history_page(request: Request, user: dict = Depends(get_current_user)):
    return templates.TemplateResponse(request=request, name="history.html", context={"username": user["username"]})


@app.get("/startup")
async def startup_status():
    """Health/status endpoint (also used as the Render health check)."""
    database_ok = ping()
    return {
        "status": "running" if database_ok else "degraded",
        "message": "PocketSmart AI is operational" if database_ok else "Database unavailable",
        "ai_enabled": bool(os.getenv("GEMINI_API_KEY", "").strip()),
        "database": {"backend": backend_name(), "ok": database_ok},
        "environment": "production" if is_production() else "development",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/me")
async def current_user(user: dict = Depends(get_current_user)):
    return {"username": user["username"], "full_name": user["full_name"]}


@app.get("/api/history")
async def get_history_api(user: dict = Depends(get_current_user)):
    history = list_recommendations(user["id"])
    return {"total": len(history), "history": history}


@app.delete("/api/history")
async def clear_history_api(user: dict = Depends(get_current_user)):
    deleted = clear_recommendations(user["id"])
    return {"message": "History cleared successfully", "deleted": deleted}


@app.get("/recommendation-details/{recommendation_id}")
async def recommendation_details(recommendation_id: str, user: dict = Depends(get_current_user)):
    """Full stored plan; 404 for unknown ids *and* for other users' plans."""
    entry = get_recommendation(user["id"], recommendation_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    try:
        full_result = json.loads(entry["result"])
    except json.JSONDecodeError:
        full_result = {"raw": entry["result"]}
    return {
        "id": entry["id"],
        "timestamp": entry["timestamp"],
        "type": entry["category"],
        "category": entry["category"],
        "budget": entry["budget"],
        "input": entry["preferences"],
        "full_result": full_result,
    }


@app.post("/recommendations-details")
async def recommendations_details(
    data: RecommendationDetailsRequest,
    user: dict = Depends(get_current_user),
):
    payload = {**data.preferences, "budget": data.budget}
    return create_plan(user, data.category, payload, data.preferences)


app.include_router(auth.router)
app.include_router(home.router)
app.include_router(party.router)
app.include_router(jewelry.router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app:app",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        reload=not is_production(),
    )
