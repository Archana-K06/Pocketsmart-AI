import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError

from auth import (
    authenticate_user,
    clear_auth_cookie,
    get_current_user,
    get_password_hash,
    get_token_from_request,
    session_id_from_token,
    set_auth_cookie,
    start_session,
)
from database import (
    create_user,
    get_session,
    list_recommendations,
    revoke_session,
    update_session_data,
)
from models import Token, UserCreate

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[2] / "frontend" / "templates"))

MAX_SESSION_DATA_BYTES = 10_000


@router.get("/login")
async def login_page(request: Request):
    return templates.TemplateResponse(request=request, name="login.html")


@router.get("/register")
async def register_page(request: Request):
    return templates.TemplateResponse(request=request, name="register.html")


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(user: UserCreate):
    try:
        create_user(user.username, user.email, user.full_name, get_password_hash(user.password))
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Username or email is already registered") from exc
    return {"message": "User registered successfully"}


@router.post("/token", response_model=Token)
async def login_for_access_token(
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
):
    user = authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = start_session(user)
    set_auth_cookie(response, access_token)
    return {"access_token": access_token, "token_type": "bearer"}


def _revoke_current_token(request: Request) -> None:
    session_id = session_id_from_token(get_token_from_request(request))
    if session_id:
        revoke_session(session_id)


@router.get("/logout")
async def logout(request: Request):
    _revoke_current_token(request)
    response = RedirectResponse(url="/login")
    clear_auth_cookie(response)
    return response


@router.post("/logout")
async def logout_api(request: Request):
    _revoke_current_token(request)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_auth_cookie(response)
    return response


def _minutes_since(timestamp: str) -> int:
    started = datetime.fromisoformat(timestamp)
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return int((datetime.now(timezone.utc) - started) // timedelta(minutes=1))


@router.get("/session-info")
async def session_info(request: Request, user: dict = Depends(get_current_user)):
    session = get_session(request.state.session_id) or {}
    return {
        "status": "active",
        "username": user["username"],
        "login_time": session.get("login_time"),
        "last_activity": session.get("last_activity"),
        "session_duration": _minutes_since(session["login_time"]) if session else 0,
        "user_data": session.get("user_data", {}),
    }


@router.get("/session-data")
async def session_data(request: Request, user: dict = Depends(get_current_user)):
    session = get_session(request.state.session_id) or {}
    return {
        "recommendations": len(list_recommendations(user["id"])),
        "user_data": session.get("user_data", {}),
    }


@router.post("/session-data")
async def update_session(
    data: dict[str, Any],
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Merge small key/value preferences into the current session."""
    if len(json.dumps(data, ensure_ascii=False).encode("utf-8")) > MAX_SESSION_DATA_BYTES:
        raise HTTPException(status_code=413, detail="Session data is too large")
    merged = update_session_data(request.state.session_id, data)
    return {"message": "Session data updated", "data": merged}
