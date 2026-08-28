"""Shared pytest fixtures for CANYP backend tests."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base, get_db
from backend.main import app

# Force model registration with Base.metadata before any create_all.
import backend.models  # noqa: F401


@pytest.fixture()
def test_db():
    """In-memory SQLite engine per test — fully isolated.

    Uses StaticPool so all sessions share one connection (and therefore
    one in-memory database) even across threads.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _fk(dbapi_conn, _rec):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def test_client(test_db: Session):
    """FastAPI TestClient with DB dependency overridden."""

    def _override():
        try:
            yield test_db
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()
