"""Database engine + session.

Cross-compatible by design:

- **SQLite** (default) — zero-config local dev; a file at ``./compliance.db``.
- **Postgres** — set ``DATABASE_URL`` to a Postgres connection string (as managed hosts
  like Render provide). Data survives redeploys and the app can run multiple instances.

Managed hosts hand out URLs like ``postgres://…`` or ``postgresql://…`` with no driver;
:func:`normalize_database_url` rewrites those to the explicit ``postgresql+psycopg://``
driver (psycopg 3) SQLAlchemy needs. JSON columns become native ``JSONB`` on Postgres
(see ``models.py``).
"""
from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


def normalize_database_url(url: str) -> str:
    """Rewrite a bare Postgres URL to the psycopg driver SQLAlchemy expects.

    ``postgres://…`` and ``postgresql://…`` (the shapes managed hosts hand out) both
    become ``postgresql+psycopg://…``. Everything else — SQLite, an already-qualified
    driver — is returned unchanged.
    """
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


DATABASE_URL = normalize_database_url(os.getenv("DATABASE_URL", "sqlite:///./compliance.db"))
IS_SQLITE = DATABASE_URL.startswith("sqlite")

engine = create_engine(
    DATABASE_URL,
    # SQLite needs this to be used across FastAPI's threads.
    connect_args={"check_same_thread": False} if IS_SQLITE else {},
    # Managed Postgres closes idle connections; pre-ping avoids handing out a dead one.
    pool_pre_ping=not IS_SQLITE,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency: yield a session and always close it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    # Import models so they register on Base before create_all.
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
