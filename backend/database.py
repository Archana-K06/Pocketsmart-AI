"""Persistence layer.

Production database: **Supabase PostgreSQL**, reached through its standard
Postgres connection string (``DATABASE_URL``).  The schema is defined in
``supabase_schema.sql`` at the repository root; ``initialize_database()`` also
creates any missing tables so a fresh project still boots.

SQLite remains only as a zero-configuration fallback for local development
and the test-suite (used when ``DATABASE_URL`` is empty and the app is *not*
running in production).  Every public function keeps the same signature on
both back ends.
"""
import json
import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from dotenv import load_dotenv
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    delete,
    event,
    false,
    func,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.engine import URL, Engine, make_url

load_dotenv()  # so DATABASE_URL / DATABASE_PATH in .env are honoured

DATABASE_PATH = Path(
    os.getenv("DATABASE_PATH", str(Path(__file__).with_name("pocketsmart.sqlite3")))
)

metadata = MetaData()

users = Table(
    "users",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("username", String(64), nullable=False),
    Column("email", String(254)),
    Column("full_name", String(120)),
    Column("hashed_password", String(255), nullable=False),
    Column("disabled", Boolean, nullable=False, default=False, server_default=false()),
    Column("created_at", String(40), nullable=False),
    CheckConstraint("length(trim(username)) > 0", name="users_username_not_blank"),
)
Index("uq_users_username_lower", func.lower(users.c.username), unique=True)
Index("uq_users_email_lower", func.lower(users.c.email), unique=True)

recommendations = Table(
    "recommendations",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("category", String(20), nullable=False),
    Column("budget", Float, nullable=False),
    Column("preferences", Text, nullable=False),
    Column("result", Text, nullable=False),
    Column("timestamp", String(40), nullable=False),
    CheckConstraint("category in ('home', 'party', 'jewelry')", name="recommendations_category_check"),
    CheckConstraint("budget >= 1", name="recommendations_budget_check"),
)
Index("recommendations_user_time", recommendations.c.user_id, recommendations.c.timestamp)

# One row per issued access token (keyed by the JWT "jti" claim).  Gives us
# server-side sessions, token revocation on logout and inactivity cleanup.
sessions = Table(
    "sessions",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("login_time", String(40), nullable=False),
    Column("last_activity", String(40), nullable=False),
    Column("expires_at", String(40), nullable=False),
    Column("revoked", Boolean, nullable=False, default=False, server_default=false()),
    Column("user_data", Text, nullable=False, default="{}", server_default=text("'{}'")),
)
Index("sessions_user", sessions.c.user_id)
Index("sessions_expires_at", sessions.c.expires_at)
Index("sessions_last_activity", sessions.c.last_activity)

_engine: Engine | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _in_production() -> bool:
    """Same rule as ``auth.is_production`` (kept here to avoid a circular import)."""
    return (
        os.getenv("ENVIRONMENT", "").strip().lower() in {"production", "prod"}
        or os.getenv("RENDER", "").strip().lower() == "true"
    )


def _supabase_url_from_parts() -> str:
    """Build the Postgres URL from SUPABASE_URL + SUPABASE_DB_PASSWORD.

    Only a convenience for when ``DATABASE_URL`` is not set.  It uses the
    project's *direct* host (``db.<ref>.supabase.co``), which is IPv6-only on
    most plans; hosts without IPv6 (e.g. Render) should set ``DATABASE_URL``
    to the Supabase **Session pooler** string instead.
    """
    project_url = os.getenv("SUPABASE_URL", "").strip()
    password = os.getenv("SUPABASE_DB_PASSWORD", "")
    if not project_url or not password:
        return ""
    host = (urlparse(project_url).hostname or "").lower()
    if not host.endswith(".supabase.co"):
        return ""
    project_ref = host.split(".")[0]
    return URL.create(
        "postgresql+psycopg",
        username="postgres",
        password=password,  # URL.create quotes special characters for us
        host=f"db.{project_ref}.supabase.co",
        port=5432,
        database="postgres",
    ).render_as_string(hide_password=False)


def database_url() -> str:
    """Return the SQLAlchemy URL, normalising Supabase/Render/Heroku style URLs."""
    url = os.getenv("DATABASE_URL", "").strip() or _supabase_url_from_parts()
    if not url:
        if _in_production():
            raise RuntimeError(
                "DATABASE_URL is not set. In production the app must use Supabase PostgreSQL: "
                "paste the connection string from Supabase -> Project Settings -> Database "
                "-> Connection string (Session pooler) into DATABASE_URL."
            )
        DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{DATABASE_PATH.as_posix()}"
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def _postgres_engine(url: str) -> Engine:
    """Engine tuned for Supabase (direct, session-pooler or transaction-pooler)."""
    parsed = make_url(url)
    connect_args: dict[str, Any] = {
        # Supabase's transaction pooler (port 6543, pgbouncer) cannot keep server-side
        # prepared statements; disabling them is harmless on the other connection modes.
        "prepare_threshold": None,
        "connect_timeout": 15,
    }
    host = (parsed.host or str(parsed.query.get("host", ""))).lower()
    is_local = host in {"", "localhost", "127.0.0.1", "::1"} or host.startswith("/")
    if "sslmode" not in parsed.query and not is_local:
        connect_args["sslmode"] = "require"  # Supabase only accepts TLS connections
    return create_engine(
        url,
        connect_args=connect_args,
        pool_pre_ping=True,
        pool_recycle=300,
        pool_size=int(os.getenv("DB_POOL_SIZE", "5")),
        max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "5")),
    )


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        url = database_url()
        if url.startswith("sqlite"):
            _engine = create_engine(url, connect_args={"timeout": 10})

            @event.listens_for(_engine, "connect")
            def _enable_foreign_keys(dbapi_connection, _record):  # pragma: no cover
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys = ON")
                cursor.close()
        else:
            _engine = _postgres_engine(url)
    return _engine


def dispose_engine() -> None:
    global _engine
    if _engine is not None:
        _engine.dispose()
        _engine = None


def backend_name() -> str:
    return get_engine().dialect.name


@contextmanager
def database_connection():
    """Transactional connection: commits on success, rolls back on error."""
    with get_engine().begin() as connection:
        yield connection


def initialize_database() -> None:
    metadata.create_all(get_engine())


def ping() -> bool:
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


# --------------------------------------------------------------------- users
def create_user(
    username: str,
    email: str | None,
    full_name: str | None,
    hashed_password: str,
) -> int:
    """Insert a user. Raises ``sqlalchemy.exc.IntegrityError`` on duplicates."""
    with database_connection() as connection:
        result = connection.execute(
            insert(users).values(
                username=username,
                email=email or None,
                full_name=full_name or None,
                hashed_password=hashed_password,
                disabled=False,
                created_at=_now(),
            )
        )
        return int(result.inserted_primary_key[0])


def get_user_by_username(username: str) -> dict[str, Any] | None:
    with database_connection() as connection:
        row = connection.execute(
            select(users).where(func.lower(users.c.username) == username.lower())
        ).first()
    return dict(row._mapping) if row else None


def get_user_by_id(user_id: int) -> dict[str, Any] | None:
    with database_connection() as connection:
        row = connection.execute(select(users).where(users.c.id == user_id)).first()
    return dict(row._mapping) if row else None


# ----------------------------------------------------------- recommendations
def save_recommendation(
    recommendation_id: str,
    user_id: int,
    category: str,
    budget: float,
    preferences: dict[str, Any],
    result: str,
    timestamp: str,
) -> None:
    with database_connection() as connection:
        connection.execute(
            insert(recommendations).values(
                id=recommendation_id,
                user_id=user_id,
                category=category,
                budget=budget,
                preferences=json.dumps(preferences, ensure_ascii=False),
                result=result,
                timestamp=timestamp,
            )
        )


def _recommendation_entry(row) -> dict[str, Any]:
    entry = dict(row._mapping)
    entry["preferences"] = json.loads(entry["preferences"])
    return entry


def list_recommendations(user_id: int) -> list[dict[str, Any]]:
    """All of a user's plans, newest first."""
    with database_connection() as connection:
        rows = connection.execute(
            select(recommendations)
            .where(recommendations.c.user_id == user_id)
            .order_by(recommendations.c.timestamp.desc(), recommendations.c.id.desc())
        ).all()
    return [_recommendation_entry(row) for row in rows]


def get_recommendation(user_id: int, recommendation_id: str) -> dict[str, Any] | None:
    """One plan, only if it belongs to ``user_id``."""
    with database_connection() as connection:
        row = connection.execute(
            select(recommendations).where(
                recommendations.c.id == recommendation_id,
                recommendations.c.user_id == user_id,
            )
        ).first()
    return _recommendation_entry(row) if row else None


def clear_recommendations(user_id: int) -> int:
    with database_connection() as connection:
        result = connection.execute(
            delete(recommendations).where(recommendations.c.user_id == user_id)
        )
        return int(result.rowcount)


# ------------------------------------------------------------------ sessions
def create_session(session_id: str, user_id: int, expires_at: datetime) -> None:
    now = _now()
    with database_connection() as connection:
        connection.execute(
            insert(sessions).values(
                id=session_id,
                user_id=user_id,
                login_time=now,
                last_activity=now,
                expires_at=expires_at.isoformat(),
                revoked=False,
                user_data="{}",
            )
        )


def get_session(session_id: str) -> dict[str, Any] | None:
    with database_connection() as connection:
        row = connection.execute(select(sessions).where(sessions.c.id == session_id)).first()
    if not row:
        return None
    session = dict(row._mapping)
    try:
        session["user_data"] = json.loads(session["user_data"] or "{}")
    except json.JSONDecodeError:
        session["user_data"] = {}
    return session


def touch_session(session_id: str, expires_at: datetime | None = None) -> None:
    values: dict[str, Any] = {"last_activity": _now()}
    if expires_at is not None:
        values["expires_at"] = expires_at.isoformat()
    with database_connection() as connection:
        connection.execute(update(sessions).where(sessions.c.id == session_id).values(**values))


def update_session_data(session_id: str, data: dict[str, Any]) -> dict[str, Any]:
    session = get_session(session_id)
    merged = {**(session["user_data"] if session else {}), **data}
    with database_connection() as connection:
        connection.execute(
            update(sessions)
            .where(sessions.c.id == session_id)
            .values(user_data=json.dumps(merged, ensure_ascii=False), last_activity=_now())
        )
    return merged


def revoke_session(session_id: str) -> None:
    with database_connection() as connection:
        connection.execute(update(sessions).where(sessions.c.id == session_id).values(revoked=True))


def cleanup_sessions(idle_minutes: int = 30) -> int:
    """Delete expired, revoked-and-expired and idle sessions."""
    now = datetime.now(timezone.utc)
    idle_cutoff = (now - timedelta(minutes=idle_minutes)).isoformat()
    with database_connection() as connection:
        result = connection.execute(
            delete(sessions).where(
                (sessions.c.expires_at < now.isoformat()) | (sessions.c.last_activity < idle_cutoff)
            )
        )
        return int(result.rowcount)
