"""Integration tests for /api/usuarios/* endpoints (user-crud spec).

Covers:
- GET /api/usuarios: list omits password_hash (id/username/created_at only)
- POST /api/usuarios: 201 create, 409 duplicate, 422 short password
- DELETE /api/usuarios/{id}: 409 last-user guard, 204 delete other, 404 unknown
- Guard sweep: every guarded route returns 401 without a token ("No autenticado")
"""

import pytest

from backend.models.usuario import Usuario

# Representative route per guarded router (design D8). Router-level guards run
# before the handler, so any matching path proves the guard is applied.
GUARDED_ROUTES = [
    ("GET", "/api/backup/status"),
    ("GET", "/api/socios"),
    ("GET", "/api/membresias"),
    ("GET", "/api/aranceles"),
    ("GET", "/api/pagos"),
    ("GET", "/api/notificaciones"),
    ("GET", "/api/parcelas"),
    ("GET", "/api/export/socios"),
    ("GET", "/api/dashboard/stats"),
    ("GET", "/api/usuarios"),
]


class TestListUsuarios:
    """GET /api/usuarios"""

    def test_list_omits_password_hash(self, test_client):
        """The list exposes id/username/created_at and never password_hash."""
        resp = test_client.get("/api/usuarios")
        assert resp.status_code == 200
        users = resp.json()
        assert isinstance(users, list)
        assert any(u["username"] == "testuser" for u in users)
        for u in users:
            assert "password_hash" not in u
            assert {"id", "username", "created_at"} <= set(u.keys())


class TestCreateUsuario:
    """POST /api/usuarios"""

    def test_create_201(self, test_client):
        """Creating a user returns 201 with the UsuarioResponse shape."""
        resp = test_client.post(
            "/api/usuarios", json={"username": "nuevo", "password": "secret123"}
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["username"] == "nuevo"
        assert "id" in body
        assert "created_at" in body
        assert "password_hash" not in body

    def test_create_duplicate_409(self, test_client):
        """A duplicate username returns 409 (the fixture already has testuser)."""
        resp = test_client.post(
            "/api/usuarios", json={"username": "testuser", "password": "secret123"}
        )
        assert resp.status_code == 409
        assert resp.json()["detail"] == "El nombre de usuario ya existe"

    def test_create_short_password_422(self, test_client):
        """A password shorter than 6 chars returns 422."""
        resp = test_client.post(
            "/api/usuarios", json={"username": "corto", "password": "ab"}
        )
        assert resp.status_code == 422
        errors = resp.json()["detail"]
        assert any(
            err["loc"] == ["body", "password"] and err["type"] == "string_too_short"
            for err in errors
        )


class TestDeleteUsuario:
    """DELETE /api/usuarios/{id}"""

    def test_delete_last_409(self, test_client, test_db):
        """Refuses to delete the last remaining user (fixture created exactly one)."""
        user = test_db.query(Usuario).filter(Usuario.username == "testuser").first()
        assert user is not None

        resp = test_client.delete(f"/api/usuarios/{user.id}")
        assert resp.status_code == 409
        assert resp.json()["detail"] == "No se puede eliminar el último usuario"

    def test_delete_other_204(self, test_client):
        """Deleting a user when others remain returns 204 and removes it."""
        created = test_client.post(
            "/api/usuarios", json={"username": "segundo", "password": "secret123"}
        )
        assert created.status_code == 201
        user_id = created.json()["id"]

        resp = test_client.delete(f"/api/usuarios/{user_id}")
        assert resp.status_code == 204

        listing = test_client.get("/api/usuarios").json()
        assert "segundo" not in [u["username"] for u in listing]

    def test_delete_unknown_404(self, test_client):
        """Deleting a non-existent user returns 404."""
        resp = test_client.delete("/api/usuarios/doesnotexist")
        assert resp.status_code == 404


class TestGuardSweep:
    """Every guarded route returns 401 without a token."""

    @pytest.mark.parametrize("method,path", GUARDED_ROUTES)
    def test_guarded_route_401_without_token(self, raw_client, method, path):
        resp = raw_client.request(method, path)
        assert resp.status_code == 401
        assert resp.json()["detail"] == "No autenticado"
