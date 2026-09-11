"""SQLAlchemy engine, session, and Base.

Engine creation is dialect-aware:

- SQLite URLs (default local mode): ``check_same_thread=False`` plus a
  ``PRAGMA journal_mode=WAL`` / ``PRAGMA foreign_keys=ON`` listener.
- PostgreSQL URLs (``postgresql://`` or ``postgresql+driver://``, chosen via
  Ajustes → remoto): ``pool_pre_ping=True`` with a small pool suited to a
  desktop sidecar (pool_size=5, max_overflow=5). No SQLite-only options are
  passed, and psycopg is never imported here — SQLAlchemy lazy-loads the
  driver on first connect.

Note: ``backend/migrate.py`` remains SQLite-only (legacy local migrations).
The Postgres schema is created fresh via ``Base.metadata.create_all`` at
startup (``backend/main.py`` lifespan), never through migrate.py.
"""

import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DATABASE_FILE = os.path.join(os.path.dirname(__file__), "..", "canyp.db")
# Optional override for test/alternate databases, e.g.:
#   $env:DATABASE_URL = "sqlite:///canyp-test.db"
# The packaged sidecar (desktop_run.py) sets this from persisted settings.
DATABASE_URL = os.environ.get("DATABASE_URL") or f"sqlite:///{os.path.abspath(DATABASE_FILE)}"


def _is_postgres(url: str) -> bool:
    """True for postgresql:// and postgresql+driver:// URLs."""
    return url.startswith("postgresql")


def _normalize_postgres_url(url: str) -> str:
    """Force the declared psycopg 3 driver for bare ``postgresql://`` URLs
    (SQLAlchemy 2.x still defaults bare ``postgresql://`` to psycopg2)."""
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def _build_engine(database_url: str):
    """Dialect-aware engine factory (SQLite vs PostgreSQL)."""
    if _is_postgres(database_url):
        return create_engine(
            _normalize_postgres_url(database_url),
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=5,
        )
    return create_engine(database_url, connect_args={"check_same_thread": False})


engine = _build_engine(DATABASE_URL)


if not _is_postgres(DATABASE_URL):

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()