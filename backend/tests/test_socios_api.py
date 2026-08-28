"""Integration tests for /api/socios CRUD endpoints."""

from datetime import date


SOCIO_PAYLOAD = {
    "id": "s100",
    "nombre": "Carlos García",
    "dni": "30123456",
    "telefono": "3512345678",
    "email": "carlos@test.com",
    "direccion": "Calle Belgrano 123, Córdoba",
    "fechaAlta": "2024-01-15",
    "activo": True,
}


class TestSociosCRUD:
    """Full CRUD lifecycle for socios."""

    def test_create_socio(self, test_client):
        resp = test_client.post("/api/socios", json=SOCIO_PAYLOAD)
        assert resp.status_code == 201
        body = resp.json()
        assert body["id"] == "s100"
        assert body["nombre"] == "Carlos García"
        assert body["dni"] == "30123456"

    def test_get_socio(self, test_client):
        test_client.post("/api/socios", json=SOCIO_PAYLOAD)
        resp = test_client.get("/api/socios/s100")
        assert resp.status_code == 200
        assert resp.json()["dni"] == "30123456"

    def test_list_socios(self, test_client):
        test_client.post("/api/socios", json=SOCIO_PAYLOAD)
        test_client.post(
            "/api/socios",
            json={**SOCIO_PAYLOAD, "id": "s101", "dni": "30999999", "nombre": "Ana López"},
        )
        resp = test_client.get("/api/socios")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_update_socio(self, test_client):
        test_client.post("/api/socios", json=SOCIO_PAYLOAD)
        resp = test_client.put(
            "/api/socios/s100",
            json={"nombre": "Carlos García Updated", "email": "new@test.com"},
        )
        assert resp.status_code == 200
        assert resp.json()["nombre"] == "Carlos García Updated"
        assert resp.json()["email"] == "new@test.com"
        # Unchanged fields stay the same
        assert resp.json()["dni"] == "30123456"

    def test_delete_socio(self, test_client):
        test_client.post("/api/socios", json=SOCIO_PAYLOAD)
        resp = test_client.delete("/api/socios/s100")
        assert resp.status_code == 204
        # Verify gone
        resp = test_client.get("/api/socios/s100")
        assert resp.status_code == 404

    def test_get_nonexistent_returns_404(self, test_client):
        resp = test_client.get("/api/socios/nonexistent")
        assert resp.status_code == 404

    def test_update_nonexistent_returns_404(self, test_client):
        resp = test_client.put(
            "/api/socios/nonexistent", json={"nombre": "Nope"}
        )
        assert resp.status_code == 404

    def test_delete_nonexistent_returns_404(self, test_client):
        resp = test_client.delete("/api/socios/nonexistent")
        assert resp.status_code == 404


class TestSociosSearch:
    """Search by nombre or dni."""

    def test_search_by_nombre(self, test_client):
        test_client.post(
            "/api/socios", json=SOCIO_PAYLOAD
        )
        test_client.post(
            "/api/socios",
            json={**SOCIO_PAYLOAD, "id": "s101", "dni": "30999999", "nombre": "María González"},
        )
        resp = test_client.get("/api/socios", params={"search": "Carlos"})
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["nombre"] == "Carlos García"

    def test_search_by_dni(self, test_client):
        test_client.post("/api/socios", json=SOCIO_PAYLOAD)
        resp = test_client.get("/api/socios", params={"search": "30123"})
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["dni"] == "30123456"

    def test_search_no_results(self, test_client):
        test_client.post("/api/socios", json=SOCIO_PAYLOAD)
        resp = test_client.get("/api/socios", params={"search": "ZZZZ"})
        assert resp.status_code == 200
        assert len(resp.json()) == 0


class TestSociosFrontendPayload:
    """Reproduce the real frontend payload: no id, no fechaAlta.

    The frontend sends {nombre, dni, telefono, email, direccion, activo} and
    expects the server to generate id and default fechaAlta to today.
    """

    def test_create_without_id_generates_one(self, test_client):
        resp = test_client.post(
            "/api/socios",
            json={
                "nombre": "Frontend Socio",
                "dni": "40111222",
                "telefono": "",
                "email": "",
                "direccion": "",
                "activo": True,
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["id"]
        assert body["id"].startswith("s")

    def test_create_without_fechaalta_defaults_today(self, test_client):
        resp = test_client.post(
            "/api/socios",
            json={
                "nombre": "Sin Fecha",
                "dni": "40222333",
                "telefono": "",
                "email": "",
                "direccion": "",
                "activo": True,
            },
        )
        assert resp.status_code == 201
        assert resp.json()["fechaAlta"] == date.today().isoformat()

    def test_create_with_explicit_fechaalta_preserved(self, test_client):
        resp = test_client.post(
            "/api/socios",
            json={
                "nombre": "Con Fecha",
                "dni": "40333444",
                "telefono": "",
                "email": "",
                "direccion": "",
                "fechaAlta": "2023-05-01",
                "activo": True,
            },
        )
        assert resp.status_code == 201
        assert resp.json()["fechaAlta"] == "2023-05-01"


class TestSociosEdgeCases:
    """Edge cases and constraints."""

    def test_duplicate_dni_rejection(self, test_client):
        """Duplicate DNI should fail at DB level (unique constraint).
        The router doesn't catch IntegrityError, so TestClient raises it."""
        test_client.post("/api/socios", json=SOCIO_PAYLOAD)
        import pytest
        with pytest.raises(Exception, match="UNIQUE"):
            # Same DNI, different id — triggers IntegrityError
            test_client.post(
                "/api/socios",
                json={**SOCIO_PAYLOAD, "id": "s200"},
            )

    def test_create_with_minimal_fields(self, test_client):
        """Create socio with only required fields (id, nombre, dni)."""
        resp = test_client.post(
            "/api/socios",
            json={
                "id": "s300",
                "nombre": "Minimal Socio",
                "dni": "20111222",
                "telefono": "",
                "email": "",
                "direccion": "",
                "fechaAlta": "2025-06-01",
                "activo": True,
            },
        )
        assert resp.status_code == 201
        assert resp.json()["nombre"] == "Minimal Socio"
