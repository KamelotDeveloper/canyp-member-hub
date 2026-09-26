"""Shared pytest fixtures for CANYP backend tests.

Default (fast path): in-memory SQLite with a StaticPool (one shared
connection, fully isolated per test).

Postgres support: set TEST_DATABASE_URL to a postgresql:// URL to run the
whole suite against a live Postgres (schema is dropped/recreated per test):

    $env:TEST_DATABASE_URL="postgresql://user:pass@localhost/canyp_test" ; python -m pytest

The default CI/plain run needs NO Postgres — SQLite remains the default.
"""

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base, get_db
from backend.main import app
from backend.models.usuario import Usuario
from backend.security import create_access_token, hash_password

# Force model registration with Base.metadata before any create_all.
import backend.models  # noqa: F401

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")


def _run_against_postgres() -> bool:
    return TEST_DATABASE_URL.startswith("postgresql")


@pytest.fixture()
def test_db():
    """Isolated engine per test.

    SQLite: :memory: StaticPool. Postgres (TEST_DATABASE_URL): creates and
    drops the schema per test so tests stay isolated from each other.
    """
    if _run_against_postgres():
        engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
    else:
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
def raw_client(test_db: Session):
    """FastAPI TestClient with DB dependency overridden (no auth headers).

    This is the original test_client — zero call-site churn for existing tests.
    """

    def _override():
        try:
            yield test_db
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture()
def auth_headers(test_db: Session) -> dict[str, str]:
    """Create a test user and return Bearer authorization headers."""
    user = Usuario(
        username="testuser",
        password_hash=hash_password("testpass123"),
    )
    test_db.add(user)
    test_db.commit()
    test_db.refresh(user)

    token = create_access_token(user.id, user.username)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def test_client(raw_client: TestClient, auth_headers: dict[str, str]) -> TestClient:
    """TestClient with auth headers attached by default.

    Callers can still override per-request headers when needed.
    """
    raw_client.headers.update(auth_headers)
    return raw_client


@pytest.fixture()
def current_user_id(test_db: Session, auth_headers: dict[str, str]) -> str:
    """The id of the test user created by ``auth_headers`` (for audit asserts)."""
    user = test_db.query(Usuario).filter(Usuario.username == "testuser").first()
    return user.id
