"""Database setup.

SQLite, deliberately. The alternative -- Postgres -- means Docker or a local
install before anyone can run this, and every extra setup step is another chance
the project does not start on someone else's machine. SQLite is a file.

Everything goes through SQLAlchemy rather than raw SQL, so moving to Postgres
later is a connection-string change rather than a rewrite.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

_DEFAULT_DB = Path(__file__).resolve().parents[1] / "field_estimate.db"


def _normalize_url(url: str) -> str:
    """Fix the connection-string dialects hosting providers hand out.

    Neon, Supabase, Render and Heroku all print URLs beginning `postgres://`,
    which SQLAlchemy does not recognise -- it wants an explicit driver. Rewriting
    it here means the URL can be pasted straight from the provider's dashboard
    without anyone having to know that.
    """
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


DATABASE_URL = _normalize_url(
    os.environ.get("FIELD_ESTIMATE_DATABASE_URL", f"sqlite:///{_DEFAULT_DB}")
)

IS_SQLITE = DATABASE_URL.startswith("sqlite")

_engine_options: dict = {}
if IS_SQLITE:
    # SQLite otherwise refuses to use a connection across threads, and FastAPI
    # serves sync endpoints from a thread pool.
    _engine_options["connect_args"] = {"check_same_thread": False}
else:
    # Free-tier Postgres (Neon, Supabase) suspends the database when idle, which
    # leaves pooled connections dead. Without pre-ping, the first request after a
    # quiet period fails instead of transparently reconnecting -- which is exactly
    # the request a visitor makes when they open the link.
    _engine_options["pool_pre_ping"] = True
    _engine_options["pool_recycle"] = 300

engine = create_engine(DATABASE_URL, **_engine_options)


@event.listens_for(engine, "connect")
def _enable_foreign_keys(dbapi_connection, _record):
    """SQLite ignores foreign keys unless asked, which silently permits orphans.

    Postgres enforces them without being told.
    """
    if IS_SQLITE:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_session():
    """FastAPI dependency: one session per request, always closed."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
