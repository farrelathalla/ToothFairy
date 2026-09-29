"""SQLAlchemy engine, session factory, declarative Base, and the FastAPI DB dependency."""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

# For SQLite we need check_same_thread=False so the background job worker thread can
# use its own session on the same file.
_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

# Ensure the sqlite parent dir exists before the engine opens the file.
_sqlite_path = settings.sqlite_path
if _sqlite_path is not None:
    _sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    _db_url = f"sqlite:///{_sqlite_path}"
else:
    _db_url = settings.database_url

engine = create_engine(_db_url, connect_args=_connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a request-scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables. Import models for side effects before calling in app startup/seed."""
    # Models are imported here (lazily) so their tables register on Base.metadata.
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
