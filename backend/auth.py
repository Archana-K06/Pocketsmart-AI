from datetime import datetime, timedelta, timezone
import os
import secrets
import uuid
from typing import Optional

from fastapi import HTTPException, Request, status
from jose import jwt
from jose.exceptions import JWTError
from passlib.context import CryptContext
from dotenv import load_dotenv

from database import (
    create_session,
    get_session,
    get_user_by_username,
    touch_session,
)

load_dotenv()


def is_production() -> bool:
    """True on Render (RENDER=true) or when ENVIRONMENT=production."""
    return (
        os.getenv("ENVIRONMENT", "").strip().lower() in {"production", "prod"}
        or os.getenv("RENDER", "").strip().lower() == "true"
    )


def _load_secret_key() -> str:
    secret = os.getenv("SECRET_KEY", "").strip()
    if secret:
        return secret
    if is_production():
        raise RuntimeError(
            "SECRET_KEY must be set in production. Generate one with: "
            'python -c "import secrets; print(secrets.token_urlsafe(48))"'
        )
    # Local development only: sessions are invalidated on every restart.
    return secrets.token_urlsafe(32)


SECRET_KEY = _load_secret_key()
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
ACCESS_TOKEN_COOKIE = "access_token"
# A session that is not used for this long is removed by the cleanup task.
SESSION_IDLE_MINUTES = int(os.getenv("SESSION_IDLE_MINUTES", "30"))
_ACTIVITY_WRITE_INTERVAL = timedelta(seconds=60)

password_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return password_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return password_context.hash(password)


def authenticate_user(username: str, password: str) -> dict | None:
    user = get_user_by_username(username)
    if user is None or user["disabled"] or not verify_password(password, user["hashed_password"]):
        return None
    return user


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    payload = data.copy()
    expire_at = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=15))
    payload.update({"exp": expire_at})
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def start_session(user: dict) -> str:
    """Create a server-side session and return the signed access token for it."""
    session_id = uuid.uuid4().hex
    lifetime = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    create_session(session_id, user["id"], datetime.now(timezone.utc) + lifetime)
    return create_access_token({"sub": user["username"], "jti": session_id}, lifetime)


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def get_token_from_request(request: Request) -> str | None:
    authorization = request.headers.get("authorization", "")
    bearer_token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else None
    return request.cookies.get(ACCESS_TOKEN_COOKIE) or bearer_token


def get_current_user(request: Request) -> dict:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )
    token = get_token_from_request(request)
    if not token:
        raise credentials_error
    try:
        claims = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError as exc:
        raise credentials_error from exc
    username, session_id = claims.get("sub"), claims.get("jti")
    if not isinstance(username, str) or not username or not isinstance(session_id, str):
        raise credentials_error

    session = get_session(session_id)
    now = datetime.now(timezone.utc)
    if session is None or session["revoked"] or _parse_time(session["expires_at"]) < now:
        raise credentials_error
    user = get_user_by_username(username)
    if user is None or user["disabled"] or user["id"] != session["user_id"]:
        raise credentials_error

    request.state.session_id = session_id
    # Sliding session: re-issue the cookie once half of the lifetime is used,
    # so an active user is not signed out in the middle of a form.
    lifetime = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    expires_at = _parse_time(session["expires_at"])
    if expires_at - now < lifetime / 2:
        new_expiry = now + lifetime
        touch_session(session_id, new_expiry)
        request.state.refreshed_token = create_access_token(
            {"sub": user["username"], "jti": session_id}, lifetime
        )
    elif now - _parse_time(session["last_activity"]) > _ACTIVITY_WRITE_INTERVAL:
        touch_session(session_id)
    return user


# ------------------------------------------------------------------ cookies
def cookie_secure() -> bool:
    configured = os.getenv("COOKIE_SECURE", "").strip().lower()
    if configured:
        return configured == "true"
    return is_production()


def cookie_samesite() -> str:
    value = os.getenv("COOKIE_SAMESITE", "lax").strip().lower()
    return value if value in {"lax", "strict", "none"} else "lax"


def set_auth_cookie(response, token: str) -> None:
    response.set_cookie(
        key=ACCESS_TOKEN_COOKIE,
        value=token,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        secure=cookie_secure(),
        samesite=cookie_samesite(),
        path="/",
    )


def clear_auth_cookie(response) -> None:
    response.delete_cookie(
        ACCESS_TOKEN_COOKIE,
        path="/",
        secure=cookie_secure(),
        httponly=True,
        samesite=cookie_samesite(),
    )


def session_id_from_token(token: str | None) -> str | None:
    """Read the session id from a (possibly expired) token we issued."""
    if not token:
        return None
    try:
        claims = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM], options={"verify_exp": False})
    except JWTError:
        return None
    session_id = claims.get("jti")
    return session_id if isinstance(session_id, str) else None
