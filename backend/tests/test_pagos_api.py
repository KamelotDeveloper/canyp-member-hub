"""Integration tests for /api/pagos endpoints and pago creation logic."""

import re

from datetime import date

from backend.models.enums import Area, EstadoMembresia, Predio
from backend.models.membresia import Membresia
from backend.models.pago import Pago, PagoItem
from backend.models.socio import Socio
from backend.models.arancel import Arancel
from backend.services.numeracion import siguiente_numero_comprobante
from backend.services.renovacion import renovar_membresias

_UUID_HEX = re.compile(r"^p[0-9a-f]{32}$")


def _seed_pago_prereqs(db):
    """Insert the socio + membresia + arancel a pago needs."""
    socio = Socio(
        id="s1",
        nombre="Pedro Martínez",
        dni="25333444",
        telefono="3515551234",
        email="pedro@test.com",
        direccion="Av. Rivadavia 500",
        fechaAlta=date(2024, 3, 1),
        activo=True,
    )
    db.add(socio)
    db.flush()  # ensure socio exists before FK references

    membresia = Membresia(
        id="m1",
        socioId="s1",
        area=Area.BALSEROS,
        predio=Predio.EMBALSE,
        estado=EstadoMembresia.ACTIVA,
        vencimiento=date(2025, 6, 15),
    )
    db.add(membresia)

    arancel = Arancel(
        id="a1",
        nombre="Cuota Balseros Embalse",
        area=Area.BALSEROS,
        predio=Predio.EMBALSE,
        monto=15000.0,
        vigenteDesde=date(2025, 1, 1),
        historico=[],
    )
    db.add(arancel)
    db.commit()


class TestPagoCreation:
    """Test payment creation with items and numbering."""

    def test_create_pago_with_item(self, test_db):
        """Create a pago with one item and verify stored correctly."""
        _seed_pago_prereqs(test_db)

        numero = siguiente_numero_comprobante(test_db)
        pago = Pago(
            id="p1",
            numero=numero,
            socioId="s1",
            fecha=date(2025, 7, 1),
            medio="efectivo",
            total=15000.0,
        )
        test_db.add(pago)
        test_db.flush()

        item = PagoItem(
            id="pi1",
            pagoId="p1",
            arancelId="a1",
            membresiaId="m1",
            montoAplicado=15000.0,
            arancelNombre="Cuota Balseros Embalse",
        )
        test_db.add(item)
        test_db.commit()
        test_db.refresh(pago)

        assert pago.numero == "0001-00000001"
        assert pago.total == 15000.0
        assert pago.socioId == "s1"

    def test_create_pago_triggers_renewal(self, test_db):
        """After payment, membership vencimiento should be renewed."""
        _seed_pago_prereqs(test_db)

        pago = Pago(
            id="p1",
            numero="0001-00000001",
            socioId="s1",
            fecha=date(2025, 7, 1),
            medio="transferencia",
            total=15000.0,
        )
        test_db.add(pago)
        test_db.commit()

        # Renew membership
        renovar_membresias(test_db, ["m1"], pago.fecha)

        test_db.expire_all()
        m = test_db.query(Membresia).filter(Membresia.id == "m1").first()
        assert m.estado == EstadoMembresia.ACTIVA
        assert m.vencimiento > date(2025, 7, 1)

    def test_sequential_numbering(self, test_db):
        """Multiple pagos get sequential numbers."""
        _seed_pago_prereqs(test_db)

        for i in range(1, 4):
            numero = siguiente_numero_comprobante(test_db)
            pago = Pago(
                id=f"p{i}",
                numero=numero,
                socioId="s1",
                fecha=date(2025, 7, i),
                medio="efectivo",
                total=1000.0 * i,
            )
            test_db.add(pago)
            test_db.commit()

        pagos = test_db.query(Pago).order_by(Pago.numero).all()
        assert len(pagos) == 3
        assert pagos[0].numero == "0001-00000001"
        assert pagos[1].numero == "0002-00000002"
        assert pagos[2].numero == "0003-00000003"

    def test_pago_api_list(self, test_client, test_db):
        """Test the pagos list endpoint via TestClient."""
        _seed_pago_prereqs(test_db)

        pago = Pago(
            id="p1",
            numero="0001-00000001",
            socioId="s1",
            fecha=date(2025, 7, 1),
            medio="efectivo",
            total=15000.0,
        )
        test_db.add(pago)
        test_db.flush()
        item = PagoItem(
            id="pi1",
            pagoId="p1",
            arancelId="a1",
            membresiaId="m1",
            montoAplicado=15000.0,
            arancelNombre="Cuota Balseros Embalse",
        )
        test_db.add(item)
        test_db.commit()

        resp = test_client.get("/api/pagos")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["numero"] == "0001-00000001"

    def test_pago_api_get_by_id(self, test_client, test_db):
        """Test getting a single pago by id."""
        _seed_pago_prereqs(test_db)

        pago = Pago(
            id="p1",
            numero="0001-00000001",
            socioId="s1",
            fecha=date(2025, 7, 1),
            medio="efectivo",
            total=15000.0,
        )
        test_db.add(pago)
        test_db.commit()

        resp = test_client.get("/api/pagos/p1")
        assert resp.status_code == 200
        assert resp.json()["id"] == "p1"

    def test_pago_api_get_nonexistent_returns_404(self, test_client):
        resp = test_client.get("/api/pagos/nonexistent")
        assert resp.status_code == 404

    def test_pago_list_filter_by_socio(self, test_client, test_db):
        """Filter pagos by socioId."""
        _seed_pago_prereqs(test_db)

        # Create socio s2 and a pago for s2
        socio2 = Socio(
            id="s2",
            nombre="Otro Socio",
            dni="30999999",
            fechaAlta=date(2024, 1, 1),
        )
        test_db.add(socio2)
        test_db.commit()

        for i, socio_id in enumerate(["s1", "s1", "s2"]):
            pago = Pago(
                id=f"p{i+1}",
                numero=f"{i+1:04d}-{i+1:08d}",
                socioId=socio_id,
                fecha=date(2025, 7, i + 1),
                medio="efectivo",
                total=1000.0,
            )
            test_db.add(pago)
        test_db.commit()

        resp = test_client.get("/api/pagos", params={"socioId": "s1"})
        assert resp.status_code == 200
        assert len(resp.json()) == 2


class TestPagoCreateApi:
    """POST /api/pagos with typed items/membresiaIds via the API."""

    def test_create_pago_with_items_returns_201(self, test_client, test_db):
        """POST with items must persist PagoItem rows (not drop them)."""
        _seed_pago_prereqs(test_db)
        resp = test_client.post(
            "/api/pagos",
            json={
                "id": "p_api",
                "socioId": "s1",
                "fecha": "2025-07-10",
                "medio": "efectivo",
                "total": 15000.0,
                "items": [
                    {
                        "arancelId": "a1",
                        "membresiaId": "m1",
                        "montoAplicado": 15000.0,
                        "arancelNombre": "Cuota Balseros Embalse",
                    }
                ],
                "membresiaIds": ["m1"],
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["numero"] == "0001-00000001"
        assert len(body["items"]) == 1
        assert body["items"][0]["nombre"] == "Cuota Balseros Embalse"
        assert body["items"][0]["monto"] == 15000.0

        items = test_db.query(PagoItem).filter(PagoItem.pagoId == body["id"]).all()
        assert len(items) == 1
        assert items[0].arancelId == "a1"
        assert items[0].montoAplicado == 15000.0

    def test_create_pago_with_items_triggers_renewal(self, test_client, test_db):
        """Membresia referenced in items gets renewed."""
        _seed_pago_prereqs(test_db)
        test_client.post(
            "/api/pagos",
            json={
                "id": "p_api",
                "socioId": "s1",
                "fecha": "2025-07-10",
                "medio": "efectivo",
                "total": 15000.0,
                "items": [
                    {
                        "arancelId": "a1",
                        "membresiaId": "m1",
                        "montoAplicado": 15000.0,
                        "arancelNombre": "Cuota Balseros Embalse",
                    }
                ],
                "membresiaIds": ["m1"],
            },
        )
        test_db.expire_all()
        m = test_db.query(Membresia).filter(Membresia.id == "m1").first()
        assert m.vencimiento > date(2025, 7, 10)

    def test_create_pago_without_client_id_returns_generated_id(self, test_client, test_db):
        """POST without an id must succeed and echo a server-generated id."""
        _seed_pago_prereqs(test_db)
        resp = test_client.post(
            "/api/pagos",
            json={
                "socioId": "s1",
                "fecha": "2025-07-10",
                "medio": "efectivo",
                "total": 15000.0,
                "items": [
                    {
                        "arancelId": "a1",
                        "membresiaId": "m1",
                        "montoAplicado": 15000.0,
                        "arancelNombre": "Cuota Balseros Embalse",
                    }
                ],
                "membresiaIds": ["m1"],
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert _UUID_HEX.match(body["id"])
        assert test_db.get(Pago, body["id"]) is not None

    def test_create_pago_ignores_client_sent_id(self, test_client, test_db):
        """A client-sent id must be ignored (server keeps authority)."""
        _seed_pago_prereqs(test_db)
        resp = test_client.post(
            "/api/pagos",
            json={
                "id": "pcliente-123",
                "socioId": "s1",
                "fecha": "2025-07-10",
                "medio": "efectivo",
                "total": 15000.0,
                "items": [
                    {
                        "arancelId": "a1",
                        "membresiaId": "m1",
                        "montoAplicado": 15000.0,
                        "arancelNombre": "Cuota Balseros Embalse",
                    }
                ],
                "membresiaIds": ["m1"],
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["id"] != "pcliente-123"
        assert _UUID_HEX.match(body["id"])
        assert test_db.get(Pago, "pcliente-123") is None

    def test_create_pago_with_membresiaIds_only(self, test_client, test_db):
        """POST with membresiaIds but no items is valid and renews membership."""
        _seed_pago_prereqs(test_db)
        resp = test_client.post(
            "/api/pagos",
            json={
                "id": "p_api",
                "socioId": "s1",
                "fecha": "2025-07-10",
                "medio": "tarjeta",
                "total": 15000.0,
                "membresiaIds": ["m1"],
            },
        )
        assert resp.status_code == 201
        # No PagoItem rows since no items sent — membership still renewed
        test_db.expire_all()
        m = test_db.query(Membresia).filter(Membresia.id == "m1").first()
        assert m.vencimiento > date(2025, 7, 10)


class TestMultiMembershipPagoIntegration:
    """RQ 14: one createPago with 3 items renews 3 DISTINCT memberships."""

    def _seed_three_members(self, db):
        """3 socios + 3 membresias (all past-due) + 1 shared arancel."""
        socios = [
            Socio(id="s1", nombre="Ana", dni="30111111", fechaAlta=date(2024, 1, 1)),
            Socio(id="s2", nombre="Luis", dni="30222222", fechaAlta=date(2024, 1, 1)),
            Socio(id="s3", nombre="Pedro", dni="30333333", fechaAlta=date(2024, 1, 1)),
        ]
        db.add_all(socios)
        db.flush()

        arancel = Arancel(
            id="a1",
            nombre="Cuota Cabañeros Almafuerte",
            area=Area.CABANEROS,
            predio=Predio.ALMAFUERTE,
            monto=10000.0,
            vigenteDesde=date(2025, 1, 1),
            historico=[],
        )
        db.add(arancel)

        venc = date(2025, 6, 1)  # in the past → renewal must advance all three
        for i, sid in enumerate(["s1", "s2", "s3"], start=1):
            db.add(
                Membresia(
                    id=f"m{i}",
                    socioId=sid,
                    area=Area.CABANEROS,
                    predio=Predio.ALMAFUERTE,
                    estado=EstadoMembresia.ACTIVA,
                    vencimiento=venc,
                )
            )
        db.commit()

    def test_create_pago_renews_all_three_memberships(self, test_client, test_db):
        self._seed_three_members(test_db)
        resp = test_client.post(
            "/api/pagos",
            json={
                "id": "p_unit",
                "socioId": "s1",
                "fecha": "2025-07-01",
                "medio": "efectivo",
                "total": 30000.0,
                "items": [
                    {
                        "arancelId": "a1",
                        "membresiaId": "m1",
                        "montoAplicado": 10000.0,
                        "arancelNombre": "Cuota Cabañeros Almafuerte",
                    },
                    {
                        "arancelId": "a1",
                        "membresiaId": "m2",
                        "montoAplicado": 10000.0,
                        "arancelNombre": "Cuota Cabañeros Almafuerte",
                    },
                    {
                        "arancelId": "a1",
                        "membresiaId": "m3",
                        "montoAplicado": 10000.0,
                        "arancelNombre": "Cuota Cabañeros Almafuerte",
                    },
                ],
                "membresiaIds": ["m1", "m2", "m3"],
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert len(body["items"]) == 3
        assert sorted(body["membresiaIds"]) == ["m1", "m2", "m3"]

        # Each PagoItem carries its OWN distinct membresiaId (never a shared id).
        items = test_db.query(PagoItem).filter(PagoItem.pagoId == body["id"]).all()
        assert len(items) == 3
        assert sorted(it.membresiaId for it in items) == ["m1", "m2", "m3"]

        # All three memberships renewed (vencimiento advanced + estado activa).
        test_db.expire_all()
        for mid in ["m1", "m2", "m3"]:
            m = test_db.query(Membresia).filter(Membresia.id == mid).first()
            assert m is not None
            assert m.vencimiento > date(2025, 7, 1)
            assert m.estado == EstadoMembresia.ACTIVA


class TestPagoSchemaOpenApi:
    """PagoCreate schema must publish items/membresiaIds to OpenAPI."""

    def test_pagocreate_exposes_items_and_membresiaids(self, test_client):
        schema = test_client.get("/openapi.json").json()["components"]["schemas"]
        pago_create = schema.get("PagoCreate", {})
        assert "items" in pago_create.get("properties", {})
        assert "membresiaIds" in pago_create.get("properties", {})


class TestPagoAuditColumns:
    """Audit (D7): created_by on create; updated_by never written (no update endpoint)."""

    def _post_pago(self, test_client):
        resp = test_client.post(
            "/api/pagos",
            json={
                "socioId": "s1",
                "fecha": "2025-07-10",
                "medio": "efectivo",
                "total": 15000.0,
                "items": [
                    {
                        "arancelId": "a1",
                        "membresiaId": "m1",
                        "montoAplicado": 15000.0,
                        "arancelNombre": "Cuota Balseros Embalse",
                    }
                ],
                "membresiaIds": ["m1"],
            },
        )
        assert resp.status_code == 201
        return resp

    def test_create_sets_created_by(self, test_client, test_db, current_user_id):
        _seed_pago_prereqs(test_db)
        body = self._post_pago(test_client).json()
        assert body["createdBy"] == current_user_id
        assert body["updatedBy"] is None

    def test_pre_feature_rows_are_null(self, test_client, test_db):
        """Pago inserted outside the router (legacy) serializes null audit ids."""
        _seed_pago_prereqs(test_db)
        pago = Pago(
            id="pLegacy",
            numero="9999-00009999",
            socioId="s1",
            fecha=date(2025, 7, 1),
            medio="efectivo",
            total=15000.0,
        )
        test_db.add(pago)
        test_db.commit()

        resp = test_client.get("/api/pagos/pLegacy")
        assert resp.status_code == 200
        body = resp.json()
        assert body["createdBy"] is None
        assert body["updatedBy"] is None
