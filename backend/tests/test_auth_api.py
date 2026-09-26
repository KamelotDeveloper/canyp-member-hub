"""Integration tests for /api/auth/* endpoints (user-auth spec).

Covers:
- POST /api/auth/login: 200 ok, 401 wrong password, 401 unknown user (identical bodies)
- POST /api/auth/logout: 200 always
- GET /api/auth/status: both states (no users, users exist)
- POST /api/auth/first-user: 201 ok, 409 users exist, 409 race (IntegrityError), 422 short pw
- Token lifecycle: expired, malformed, missing → exact 401 messages
"""

from datetime import datetime, timedelta, timezone

import jwt as pyjwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from backend.database import get_db
from backend.models.usuario import Usuario
from backend.security import SECRET_KEY, ALGORITHM, create_access_token, hash_password


# ── Helpers ──────────────────────────────────────────────────────────────

def _make_expired_token() -> str:
    """Create a JWT with exp in the past."""
    now = datetime.now(timezone.utc)
    return pyjwt.encode(
        {
            "sub": "fake-id",
            "username": "fake",
            "iat": now - timedelta(hours=2),
            "exp": now - timedelta(hours=1),
        },
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


def _make_malformed_token() -> str:
    return "not.a.jwt"


def _make_valid_token_nonexistent_user() -> str:
    """Valid JWT format but sub references a user not in DB."""
    return create_access_token("nonexistent-user-id", "ghost")


# ── Guard dependency client (for testing get_current_user 401 messages) ──

@pytest.fixture()
def guard_client(test_db, raw_client):
    """A TestClient with one protected route using get_current_user.

    In Phase 1 no routers have router-level guards, so we exercise
    get_current_user through this minimal protected endpoint.
    """
    from backend.security import get_current_user

    _app = FastAPI()

    @_app.get("/_protected")
    def _protected(user=Depends(get_current_user)):
        return {"id": user.id}

    def _override():
        try:
            yield test_db
        finally:
            pass

    _app.dependency_overrides[get_db] = _override
    return TestClient(_app)


# ── Tests ────────────────────────────────────────────────────────────────

class TestLogin:
    """POST /api/auth/login"""

    def test_login_ok(self, test_db, raw_client):
        """Successful login returns a JWT token."""
        test_db.add(Usuario(
            username="alice",
            password_hash=hash_password("secret123"),
        ))
        test_db.commit()

        resp = raw_client.post("/api/auth/login", json={
            "username": "alice",
            "password": "secret123",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert "token" in body
        payload = pyjwt.decode(body["token"], SECRET_KEY, algorithms=[ALGORITHM])
        assert payload["username"] == "alice"

    def test_login_wrong_password_401(self, test_db, raw_client):
        test_db.add(Usuario(
            username="alice",
            password_hash=hash_password("secret123"),
        ))
        test_db.commit()

        resp = raw_client.post("/api/auth/login", json={
            "username": "alice",
            "password": "wrongpassword",
        })
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Credenciales inválidas"

    def test_login_unknown_user_401_identical_body(self, test_db, raw_client):
        """Unknown user and wrong password produce identical 401 bodies (no enumeration)."""
        test_db.add(Usuario(
            username="alice",
            password_hash=hash_password("secret123"),
        ))
        test_db.commit()

        wrong_pass_resp = raw_client.post("/api/auth/login", json={
            "username": "alice",
            "password": "wrongpassword",
        })
        unknown_user_resp = raw_client.post("/api/auth/login", json={
            "username": "bobnotexist",
            "password": "secret123",
        })

        assert wrong_pass_resp.status_code == 401
        assert unknown_user_resp.status_code == 401
        assert wrong_pass_resp.json() == unknown_user_resp.json()

    def test_login_short_password_401_not_422(self, test_db, raw_client):
        """Short password triggers 401 not 422 — proves LoginRequest has no min_length oracle."""
        test_db.add(Usuario(
            username="alice",
            password_hash=hash_password("secret123"),
        ))
        test_db.commit()

        resp = raw_client.post("/api/auth/login", json={
            "username": "alice",
            "password": "ab",
        })
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Credenciales inválidas"


class TestLogout:
    """POST /api/auth/logout"""

    def test_logout_200(self, raw_client):
        resp = raw_client.post("/api/auth/logout")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestStatus:
    """GET /api/auth/status"""

    def test_status_no_users(self, raw_client):
        resp = raw_client.get("/api/auth/status")
        assert resp.status_code == 200
        assert resp.json() == {"users_exist": False}

    def test_status_users_exist(self, test_db, raw_client):
        test_db.add(Usuario(
            username="first",
            password_hash=hash_password("secret123"),
        ))
        test_db.commit()

        resp = raw_client.get("/api/auth/status")
        assert resp.status_code == 200
        assert resp.json() == {"users_exist": True}


class TestFirstUser:
    """POST /api/auth/first-user"""

    def test_first_user_201(self, raw_client):
        """Creating the first user returns 201 with token and user."""
        resp = raw_client.post("/api/auth/first-user", json={
            "username": "admin",
            "password": "secret123",
        })
        assert resp.status_code == 201
        body = resp.json()
        assert "token" in body
        user = body["user"]
        assert user["username"] == "admin"
        assert "id" in user
        assert "created_at" in user
        # Verify token decodes
        payload = pyjwt.decode(body["token"], SECRET_KEY, algorithms=[ALGORITHM])
        assert payload["sub"] == user["id"]
        assert payload["username"] == user["username"]

    def test_first_user_409_when_users_exist(self, test_db, raw_client):
        """Once a user exists, first-user returns 409."""
        test_db.add(Usuario(
            username="existing",
            password_hash=hash_password("secret123"),
        ))
        test_db.commit()

        resp = raw_client.post("/api/auth/first-user", json={
            "username": "another",
            "password": "secret123",
        })
        assert resp.status_code == 409
        assert resp.json()["detail"] == "Ya existe un usuario en el sistema"

    def test_first_user_409_race_integrity_error(self, test_db, raw_client, monkeypatch):
        """Simulate race: count==0 passes but commit hits UNIQUE → 409.

        We monkeypatch Session.commit to raise IntegrityError once,
        simulating a concurrent insert of the same username.
        """
        from sqlalchemy.exc import IntegrityError
        from sqlalchemy.orm import Session as SessionClass

        original_commit = SessionClass.commit

        call_count = {"n": 0}

        def racy_commit(self):
            call_count["n"] += 1
            if call_count["n"] == 1:
                # The endpoint's db.commit() — simulate UNIQUE violation
                raise IntegrityError(
                    "INSERT INTO usuarios ...",
                    {},
                    Exception("UNIQUE constraint failed"),
                )
            # Subsequent commits (rollback won't call commit again)
            return original_commit(self)

        monkeypatch.setattr(SessionClass, "commit", racy_commit)

        resp = raw_client.post("/api/auth/first-user", json={
            "username": "race_user",
            "password": "secret123",
        })
        assert resp.status_code == 409
        assert resp.json()["detail"] == "El nombre de usuario ya existe"

    def test_first_user_422_short_password(self, raw_client):
        """Password < 6 chars returns 422."""
        resp = raw_client.post("/api/auth/first-user", json={
            "username": "admin",
            "password": "short",
        })
        assert resp.status_code == 422
        errors = resp.json()["detail"]
        assert any(
            err["loc"] == ["body", "password"] and err["type"] == "string_too_short"
            for err in errors
        )

    def test_first_user_422_empty_username(self, raw_client):
        """Empty username returns 422."""
        resp = raw_client.post("/api/auth/first-user", json={
            "username": "",
            "password": "secret123",
        })
        assert resp.status_code == 422


class TestTokenLifecycle:
    """get_current_user 401 messages via a protected endpoint."""

    def test_missing_token_401(self, guard_client):
        """No Authorization header → 'No autenticado'."""
        resp = guard_client.get("/_protected")
        assert resp.status_code == 401
        assert resp.json()["detail"] == "No autenticado"

    def test_empty_bearer_401(self, guard_client):
        """Empty Bearer value → 'No autenticado'."""
        resp = guard_client.get(
            "/_protected",
            headers={"Authorization": "Bearer "},
        )
        assert resp.status_code == 401
        assert resp.json()["detail"] == "No autenticado"

    def test_expired_token_401(self, guard_client):
        """Expired JWT → 'Token expirado'."""
        token = _make_expired_token()
        resp = guard_client.get(
            "/_protected",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Token expirado"

    def test_malformed_token_401(self, guard_client):
        """Malformed JWT → 'Token inválido'."""
        resp = guard_client.get(
            "/_protected",
            headers={"Authorization": f"Bearer {_make_malformed_token()}"},
        )
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Token inválido"

    def test_valid_token_unknown_user_401(self, guard_client):
        """Valid JWT format but user not in DB → 'Credenciales inválidas'."""
        token = _make_valid_token_nonexistent_user()
        resp = guard_client.get(
            "/_protected",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Credenciales inválidas"

    def test_valid_token_known_user_200(self, test_db, guard_client):
        """Valid token for existing user → 200 with user id."""
        user = Usuario(
            username="authuser",
            password_hash=hash_password("secret123"),
        )
        test_db.add(user)
        test_db.commit()
        test_db.refresh(user)

        token = create_access_token(user.id, user.username)
        resp = guard_client.get(
            "/_protected",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == user.id
