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


class TestDeleteSocioCascade:
    """Delete socio with Titular promotion logic."""

    def _create_unit_with_titular_and_integrantes(self, test_client, titular_id="sTit", integrante_id="sInt"):
        """Helper: create a parcela + titular + integrante."""
        test_client.post(
            "/api/parcelas",
            json={
                "id": "pDel",
                "nombre": "Cabaña Test",
                "tipo": "cabaña",
                "predio": "Almafuerte",
            },
        )
        for sid, nombre, dni, rol in [
            (titular_id, "Titular Test", "90000001", "Titular"),
            (integrante_id, "Integrante Test", "90000002", "Integrante"),
        ]:
            test_client.post(
                "/api/socios",
                json={
                    "id": sid,
                    "nombre": nombre,
                    "dni": dni,
                    "telefono": "",
                    "email": "",
                    "direccion": "",
                    "activo": True,
                },
            )
            test_client.post(
                "/api/membresias",
                json={
                    "id": f"m{sid}",
                    "socioId": sid,
                    "area": "Cabañeros",
                    "predio": "Almafuerte",
                    "estado": "activa",
                    "vencimiento": "2026-12-31",
                    "rol": rol,
                    "parcelaId": "pDel",
                },
            )

    def test_delete_titular_promotes_integrante(self, test_client):
        """Deleting the Titular socio promotes the first Integrante to Titular."""
        self._create_unit_with_titular_and_integrantes(test_client)

        resp = test_client.delete("/api/socios/sTit")
        assert resp.status_code == 204

        # Titular socio is gone
        resp = test_client.get("/api/socios/sTit")
        assert resp.status_code == 404

        # Integrante socio still exists
        resp = test_client.get("/api/socios/sInt")
        assert resp.status_code == 200

        # The integrante's membership is now Titular
        resp = test_client.get("/api/socios/sInt/membresias")
        assert resp.status_code == 200
        membresias = resp.json()
        assert len(membresias) == 1
        assert membresias[0]["rol"] == "Titular"

    def test_delete_titular_no_integrante_leaves_no_titular(self, test_client):
        """Deleting a Titular with no other members just removes the unit."""
        test_client.post(
            "/api/parcelas",
            json={
                "id": "pSolo",
                "nombre": "Balsa Solitaria",
                "tipo": "balsa",
                "predio": "Embalse",
            },
        )
        test_client.post(
            "/api/socios",
            json={
                "id": "sSolo",
                "nombre": "Solitario",
                "dni": "80000001",
                "telefono": "",
                "email": "",
                "direccion": "",
                "activo": True,
            },
        )
        test_client.post(
            "/api/membresias",
            json={
                "id": "mSolo",
                "socioId": "sSolo",
                "area": "Balseros",
                "predio": "Embalse",
                "estado": "activa",
                "vencimiento": "2026-12-31",
                "rol": "Titular",
                "parcelaId": "pSolo",
            },
        )

        resp = test_client.delete("/api/socios/sSolo")
        assert resp.status_code == 204

        # Socio and membership gone
        resp = test_client.get("/api/socios/sSolo")
        assert resp.status_code == 404

    def test_delete_non_titular_socio(self, test_client):
        """Deleting a non-Titular socio removes their memberships and socio."""
        self._create_unit_with_titular_and_integrantes(test_client)

        resp = test_client.delete("/api/socios/sInt")
        assert resp.status_code == 204

        # Integrante gone
        resp = test_client.get("/api/socios/sInt")
        assert resp.status_code == 404

        # Titular still exists and retains Titular role
        resp = test_client.get("/api/socios/sTit")
        assert resp.status_code == 200
        resp = test_client.get("/api/socios/sTit/membresias")
        assert resp.status_code == 200
        membresias = resp.json()
        assert len(membresias) == 1
        assert membresias[0]["rol"] == "Titular"

    def test_delete_titular_with_multiple_units(self, test_client):
        """Deleting a socio who is Titular in multiple units promotes in each."""
        # Unit 1
        test_client.post(
            "/api/parcelas",
            json={
                "id": "pU1",
                "nombre": "Cabaña A",
                "tipo": "cabaña",
                "predio": "Almafuerte",
            },
        )
        # Unit 2
        test_client.post(
            "/api/parcelas",
            json={
                "id": "pU2",
                "nombre": "Cabaña B",
                "tipo": "cabaña",
                "predio": "Almafuerte",
            },
        )

        socio_multi = {
            "id": "sMulti",
            "nombre": "Multi Titular",
            "dni": "70000001",
            "telefono": "",
            "email": "",
            "direccion": "",
            "activo": True,
        }
        test_client.post("/api/socios", json=socio_multi)

        integrantes = [
            ("sIntA", "Integrante A", "70000010", "pU1", "mIntA"),
            ("sIntB", "Integrante B", "70000011", "pU2", "mIntB"),
        ]
        for sid, nombre, dni, pid, mid in integrantes:
            test_client.post(
                "/api/socios",
                json={
                    "id": sid,
                    "nombre": nombre,
                    "dni": dni,
                    "telefono": "",
                    "email": "",
                    "direccion": "",
                    "activo": True,
                },
            )
            test_client.post(
                "/api/membresias",
                json={
                    "id": f"mMulti_{sid}",
                    "socioId": sid,
                    "area": "Cabañeros",
                    "predio": "Almafuerte",
                    "estado": "activa",
                    "vencimiento": "2026-12-31",
                    "rol": "Integrante",
                    "parcelaId": pid,
                },
            )

        # Titular memberships in both units
        for pid, mid in [("pU1", "mMultiU1"), ("pU2", "mMultiU2")]:
            test_client.post(
                "/api/membresias",
                json={
                    "id": mid,
                    "socioId": "sMulti",
                    "area": "Cabañeros",
                    "predio": "Almafuerte",
                    "estado": "activa",
                    "vencimiento": "2026-12-31",
                    "rol": "Titular",
                    "parcelaId": pid,
                },
            )

        resp = test_client.delete("/api/socios/sMulti")
        assert resp.status_code == 204

        # Both integrantes promoted
        for sid, _, _, _, _ in integrantes:
            resp = test_client.get(f"/api/socios/{sid}/membresias")
            assert resp.status_code == 200
            membresias = resp.json()
            assert len(membresias) == 1
            assert membresias[0]["rol"] == "Titular"
