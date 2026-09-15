"""Integration tests for /api/socios CRUD endpoints."""

from datetime import date

from backend.models.membresia import Membresia
from backend.models.pago import Pago


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


class TestSociosNullableTextFields:
    """Regression: a socio with NULL text fields must serialize without 500.

    SocioCreate allows dni/telefono/email/direccion to be omitted (None), but
    SocioResponse inherited them as mandatory strings from SocioBase. One socio
    with a NULL field broke the serialization of the ENTIRE /api/socios list
    with ResponseValidationError.
    """

    def test_create_without_dni_serializes(self, test_client):
        resp = test_client.post(
            "/api/socios",
            json={
                "id": "sNull1",
                "nombre": "Sin DNI",
                "activo": True,
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["nombre"] == "Sin DNI"
        assert body["dni"] is None

    def test_list_with_null_dni_does_not_break_list(self, test_client):
        test_client.post(
            "/api/socios",
            json={
                "id": "sNull2",
                "nombre": "Sin Datos",
                "activo": True,
            },
        )
        test_client.post(
            "/api/socios",
            json={**SOCIO_PAYLOAD, "id": "sNull3", "nombre": "Completo"},
        )
        resp = test_client.get("/api/socios")
        assert resp.status_code == 200
        socios = resp.json()
        assert len(socios) == 2
        by_id = {s["id"]: s for s in socios}
        assert by_id["sNull2"]["dni"] is None
        assert by_id["sNull3"]["dni"] == "30123456"


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


class TestDeleteSocioConPagos:
    """Contable: a socio with payments cannot be deleted (409) — darlo de baja en su lugar."""

    def _seed_socio_con_pago(self, test_client, test_db):
        """Create socio + membresia + arancel + pago for deletion tests."""
        test_client.post(
            "/api/socios",
            json={
                "id": "sPagos",
                "nombre": "Socio Con Pagos",
                "dni": "91000001",
                "telefono": "",
                "email": "",
                "direccion": "",
                "activo": True,
            },
        )
        test_client.post(
            "/api/membresias",
            json={
                "id": "mPagos",
                "socioId": "sPagos",
                "area": "Balseros",
                "predio": "Embalse",
                "estado": "activa",
                "vencimiento": "2026-12-31",
                "rol": "Titular",
            },
        )
        test_client.post(
            "/api/aranceles",
            json={
                "id": "aPagos",
                "nombre": "Cuota Socio Con Pagos",
                "area": "Balseros",
                "predio": "Embalse",
                "monto": 10000.0,
                "vigenteDesde": "2026-01-01",
            },
        )
        resp = test_client.post(
            "/api/pagos",
            json={
                "id": "pPagos",
                "socioId": "sPagos",
                "fecha": "2026-02-01",
                "medio": "efectivo",
                "total": 10000.0,
                "items": [
                    {
                        "arancelId": "aPagos",
                        "membresiaId": "mPagos",
                        "montoAplicado": 10000.0,
                        "arancelNombre": "Cuota Socio Con Pagos",
                    }
                ],
                "membresiaIds": ["mPagos"],
            },
        )
        assert resp.status_code == 201

    def test_delete_socio_con_pagos_returns_409(self, test_client, test_db):
        """Deleting a socio with payments is rejected to preserve the comprobante history."""
        self._seed_socio_con_pago(test_client, test_db)

        resp = test_client.delete("/api/socios/sPagos")
        assert resp.status_code == 409
        assert "pagos" in resp.json()["detail"].lower()

        # Socio still exists and history is intact
        assert test_client.get("/api/socios/sPagos").status_code == 200
        assert test_db.query(Pago).filter(Pago.socioId == "sPagos").count() == 1
        assert test_db.query(Membresia).filter(Membresia.socioId == "sPagos").count() == 1

    def test_delete_socio_sin_pagos_permite(self, test_client):
        """A socio without payments can still be deleted normally."""
        test_client.post(
            "/api/socios",
            json={
                "id": "sSinPagos",
                "nombre": "Socio Sin Pagos",
                "dni": "91000002",
                "telefono": "",
                "email": "",
                "direccion": "",
                "activo": True,
            },
        )
        resp = test_client.delete("/api/socios/sSinPagos")
        assert resp.status_code == 204
        assert test_client.get("/api/socios/sSinPagos").status_code == 404


class TestSocioAuditColumns:
    """Audit (D7): created_by on create, updated_by on update, pre-feature null."""

    def test_create_sets_created_by(self, test_client, current_user_id):
        resp = test_client.post("/api/socios", json=SOCIO_PAYLOAD)
        assert resp.status_code == 201
        body = resp.json()
        assert body["createdBy"] == current_user_id
        assert body["updatedBy"] is None

    def test_update_sets_updated_by(self, test_client, current_user_id):
        test_client.post("/api/socios", json=SOCIO_PAYLOAD)
        resp = test_client.put("/api/socios/s100", json={"nombre": "Renombrado"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["createdBy"] == current_user_id
        assert body["updatedBy"] == current_user_id

    def test_pre_feature_rows_are_null(self, test_client, test_db):
        """Rows inserted outside the router (no operator) serialize null audit ids."""
        from backend.models.socio import Socio

        socio = Socio(
            id="sLegacy",
            nombre="Legacy",
            dni="30999988",
            fechaAlta=date(2024, 1, 1),
        )
        test_db.add(socio)
        test_db.commit()
        resp = test_client.get("/api/socios/sLegacy")
        assert resp.status_code == 200
        body = resp.json()
        assert body["createdBy"] is None
        assert body["updatedBy"] is None
