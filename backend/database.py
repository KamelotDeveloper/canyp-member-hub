"""SQLAlchemy engine, session, and Base."""

import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DATABASE_FILE = os.path.join(os.path.dirname(__file__), "..", "canyp.db")
# Optional override for test/alternate databases, e.g.:
#   $env:DATABASE_URL = "sqlite:///canyp-test.db"
DATABASE_URL = os.environ.get("DATABASE_URL") or f"sqlite:///{os.path.abspath(DATABASE_FILE)}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


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
