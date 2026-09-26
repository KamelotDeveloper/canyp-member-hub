"""Integration tests for /api/pagos endpoints and pago creation logic."""

import re

from datetime import date
from itertools import combinations

import pytest

from backend.models.enums import (
    Area,
    CategoriaParcela,
    ConceptoCobro,
    ConceptoMembresia,
    EstadoMembresia,
    Predio,
    RolMembresia,
    TipoParcela,
)
from backend.models.membresia import Membresia
from backend.models.pago import Pago, PagoItem
from backend.models.parcela import Parcela
from backend.models.socio import Socio
from backend.models.arancel import Arancel
from backend.services.numeracion import siguiente_numero_comprobante
from backend.services.renovacion import renovar_membresias
from backend.services.resolucion import (
    precio_cuota_social,
    precio_servicio,
    resolver_arancel_concepto,
    resolver_monto,
)

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
        """Membresia referenced in items gets renewed to the 10->10 anchor."""
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
        # 10->10: a payment ON the 10th covers that same window, so the anchor is
        # exactly 10/07, not "one year from now" and not a month later.
        assert m.vencimiento == date(2025, 7, 10)
        assert m.vencimiento.day == 10

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
        # 10->10: renewal fires off the pago's own fecha, anchored to the same 10/07.
        assert m.vencimiento == date(2025, 7, 10)
        assert m.vencimiento.day == 10


class TestMultiMembershipPagoIntegration:
    """RQ 14 / UNI-01: one comprobante renews the whole unit.

    PR 5 replaced "one item per membership" with "one item per ticked concept"
    (CBM-04): 3 members of the SAME unit share ONE area line, not three. The
    three memberships still all renew — the unit travels in ``membresiaIds``.
    """

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
                    }
                ],
                "membresiaIds": ["m1", "m2", "m3"],
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        # CBM-04: the same concept + the same catalog row is ONE line, whatever
        # the client submitted, and it is the titular's membership that anchors
        # it. The area arancel is per unit, so it is NOT multiplied.
        assert len(body["items"]) == 1
        assert body["items"][0]["monto"] == 10000.0
        assert body["items"][0]["concepto"] == "area"
        assert body["items"][0]["factor"] == 1.0
        assert body["membresiaIds"] == ["m1"]
        assert body["total"] == 10000.0

        items = test_db.query(PagoItem).filter(PagoItem.pagoId == body["id"]).all()
        assert len(items) == 1
        assert items[0].membresiaId == "m1"

        # All three memberships renewed (vencimiento advanced + estado activa).
        test_db.expire_all()
        for mid in ["m1", "m2", "m3"]:
            m = test_db.query(Membresia).filter(Membresia.id == mid).first()
            assert m is not None
            assert m.vencimiento > date(2025, 7, 1)
            assert m.estado == EstadoMembresia.ACTIVA


# ---------------------------------------------------------------------------
# PR 5a — multi-concept charge, server-owned amounts (CBM-04, CS-03, CS-05,
# PAG-01, ARA-01, decision #646, design D3/D4).
#
# This block is the CONTRACT of the multi-concept charge: what every concept
# must hold for the flow to be correct. The exhaustive combinatorial coverage
# (every concept x every renewal combination, unit-size edge cases, catalog
# fallbacks) is PR 5b.
# ---------------------------------------------------------------------------


CUOTA_UNIT_PRICE = 10000.0
BALSA_ARANCEL = 130000.0
CABANA_ARANCEL = 45000.0
SERVICIO_MONTO = 5000.0
RECARGO_MONTO = 10000.0
RECARGO_ID = "a_recargo"
CUOTA_PRICE_ID = "a_cuota"
SERVICIO_ID = "a_serv"
VENC_PASADO = date(2025, 6, 1)
VENC_COBRADO = date(2025, 7, 10)  # the charge is dated ON the 10th
ORDEN_CONCEPTOS = ("area", "cuota social", "servicio", "recargo")


def _seed_unidad(db, miembros: int = 4, area=Area.BALSEROS):
    """One parcel, `miembros` socios on the same area membership + cuota rows.

    Every member gets an AREA membership on the parcel and a CUOTA_SOCIAL
    membership of their own, so the charge can tick both concepts, and the four
    catalog rows it can resolve are seeded too. Module-level because the 5a
    contract tests and the 5b exhaustive matrix charge the same unit at
    different sizes; the amounts are the module constants, never literals.
    """
    predio = Predio.EMBALSE if area is Area.BALSEROS else Predio.ALMAFUERTE
    db.add(Socio(id="s1", nombre="Titular", dni="30111111", fechaAlta=date(2024, 1, 1)))
    for i in range(1, miembros):
        db.add(
            Socio(
                id=f"s{i + 1}",
                nombre=f"Integrante {i}",
                dni=f"3022222{i}",
                fechaAlta=date(2024, 1, 1),
            )
        )
    db.add(Parcela(id="pa1", nombre="Balsa", tipo=TipoParcela.BALSA, predio=predio))
    db.add(
        Arancel(
            id="a_balsa",
            nombre="Amarre y Servicios",
            area=area,
            predio=predio,
            monto=BALSA_ARANCEL,
            vigenteDesde=date(2025, 1, 1),
            historico=[],
        )
    )
    for arancel_id, nombre, monto, concepto in (
        (RECARGO_ID, "Recargo", 0.0, ConceptoCobro.RECARGO),
        (CUOTA_PRICE_ID, "Cuota social", CUOTA_UNIT_PRICE, ConceptoCobro.CUOTA_SOCIAL),
        (SERVICIO_ID, "Servicio (luz, agua)", SERVICIO_MONTO, ConceptoCobro.SERVICIO),
    ):
        db.add(
            Arancel(
                id=arancel_id,
                nombre=nombre,
                # Placeholder area/predio: resolved by concepto only, never by place.
                area=Area.GUARDERIA,
                predio=Predio.ALMAFUERTE,
                monto=monto,
                vigenteDesde=date(2025, 1, 1),
                historico=[],
                concepto=concepto,
            )
        )
    db.flush()

    for i in range(miembros):
        sid = "s1" if i == 0 else f"s{i + 1}"
        db.add(
            Membresia(
                id=f"ma{i}",
                socioId=sid,
                area=area,
                predio=predio,
                estado=EstadoMembresia.ACTIVA,
                vencimiento=VENC_PASADO,
                parcelaId="pa1",
                rol=RolMembresia.TITULAR if i == 0 else RolMembresia.INTEGRANTE,
            )
        )
        db.add(
            Membresia(
                id=f"mc{i}",
                socioId=sid,
                area=None,
                predio=None,
                estado=EstadoMembresia.ACTIVA,
                vencimiento=VENC_PASADO,
                concepto=ConceptoMembresia.CUOTA_SOCIAL,
            )
        )
    db.commit()
    return {
        "areas": [f"ma{i}" for i in range(miembros)],
        "cuotas": [f"mc{i}" for i in range(miembros)],
    }


class TestCobroMultiConcept:
    """A balsa unit: 1 titular + 3 integrantes, all past-due, one shared arancel."""

    def _seed_balsa(self, db, miembros: int = 4, area=Area.BALSEROS):
        """See the module-level ``_seed_unidad``, shared with the 5b suite."""
        return _seed_unidad(db, miembros, area)

    def _post(self, client, items, membresia_ids, total=999999.0, fecha="2025-07-10"):
        return client.post(
            "/api/pagos",
            json={
                "socioId": "s1",
                "fecha": fecha,
                "medio": "efectivo",
                "total": total,
                "items": items,
                "membresiaIds": membresia_ids,
            },
        )

    def _vencimientos(self, db):
        return {
            m.id: m.vencimiento
            for m in db.query(Membresia)
            .filter(
                Membresia.id.in_(
                    [f"ma{i}" for i in range(4)] + [f"mc{i}" for i in range(4)]
                )
            )
            .all()
        }

    # ── CBM-04 + CS-03 + PAG-01: the whole flow, one charge ────────────────

    def test_combinacion_completa_da_cuatro_items(self, test_client, test_db):
        """CBM-04 'combinación completa': balsa + servicio + cuota social + recargo.

        One POST, one receipt, four concepts. Every amount and the total come
        from the server: the client sends 1.0 for all three catalog-priced lines
        and a total of 999999, and none of that survives (D3).
        """
        ids = self._seed_balsa(test_db)
        resp = self._post(
            test_client,
            items=[
                {"arancelId": "a_balsa", "membresiaId": "ma0", "montoAplicado": 1.0, "arancelNombre": "mentira"},
                {"arancelId": CUOTA_PRICE_ID, "membresiaId": "mc0", "montoAplicado": 1.0, "arancelNombre": "mentira"},
                # No montoAplicado: the servicio line takes the catalog price.
                # Sending one is the operator's per-charge adjustment and is
                # covered by test_servicio_ajustable_no_pisa_el_catalogo.
                {"arancelId": SERVICIO_ID, "membresiaId": "ma0", "arancelNombre": "mentira"},
                {"arancelId": RECARGO_ID, "membresiaId": "ma0", "montoAplicado": 10000.0, "arancelNombre": "mentira"},
            ],
            membresia_ids=ids["areas"] + ids["cuotas"],
        )
        assert resp.status_code == 201
        body = resp.json()
        por_concepto = {i["concepto"]: i for i in body["items"]}
        assert set(por_concepto) == {"area", "cuota social", "servicio", "recargo"}
        # The area line is the titular's, unmultiplied (CS-03).
        assert por_concepto["area"]["monto"] == BALSA_ARANCEL
        assert por_concepto["area"]["factor"] == 1.0
        # Cuota social x4 members.
        assert por_concepto["cuota social"]["monto"] == CUOTA_UNIT_PRICE * 4
        assert por_concepto["cuota social"]["factor"] == 4.0
        # Servicio is per unit: catalog price, factor 1 on a 4-member unit.
        assert por_concepto["servicio"]["monto"] == SERVICIO_MONTO
        assert por_concepto["servicio"]["factor"] == 1.0
        # The recargo is its own line at the operator's figure.
        assert por_concepto["recargo"]["monto"] == 10000.0
        # PAG-01: the total is the sum of the server-resolved items, and the
        # client's total and item names are not authority.
        assert body["total"] == sum(i["monto"] for i in body["items"])
        assert body["total"] == BALSA_ARANCEL + CUOTA_UNIT_PRICE * 4 + SERVICIO_MONTO + 10000.0
        assert por_concepto["area"]["nombre"] == "Amarre y Servicios"

        # CBM-04: ticking area + cuota social renews all 8 memberships, the
        # recargo and the servicio renew nothing on their own.
        test_db.expire_all()
        venc = self._vencimientos(test_db)
        assert all(v == VENC_COBRADO for v in venc.values()), venc

    # ── CBM-03 / ARA-01: recargo is additive and never touches the catalog ──

    def test_recargo_es_aditivo_y_no_pisa_el_arancel(self, test_client, test_db):
        """A recargo is a SEPARATE line that adds up; `aranceles.monto` is sacred."""
        ids = self._seed_balsa(test_db)
        resp = self._post(
            test_client,
            items=[
                {"arancelId": "a_balsa", "membresiaId": "ma0"},
                {"arancelId": RECARGO_ID, "membresiaId": "ma0", "montoAplicado": 10000.0},
            ],
            membresia_ids=ids["areas"],
        )
        assert resp.status_code == 201
        body = resp.json()
        assert [i["concepto"] for i in body["items"]] == ["area", "recargo"]
        assert body["total"] == BALSA_ARANCEL + 10000.0
        test_db.expire_all()
        assert test_db.get(Arancel, RECARGO_ID).monto == 0.0
        assert test_db.get(Arancel, "a_balsa").monto == BALSA_ARANCEL

    def test_sin_carrier_de_recargo_es_422(self, test_client, test_db):
        """A recargo with no catalog carrier is a 422, never a broken FK.

        The carrier is resolved BY CONCEPT, so a client naming a row that does
        not exist cannot push a bad id down to `pago_items.arancelId`.
        """
        ids = self._seed_balsa(test_db)
        test_db.query(Arancel).filter(Arancel.id == RECARGO_ID).delete()
        test_db.commit()
        resp = self._post(
            test_client,
            items=[
                {
                    "arancelId": "a_inexistente",
                    "membresiaId": "ma0",
                    "concepto": "recargo",
                    "montoAplicado": 10000.0,
                }
            ],
            membresia_ids=ids["areas"],
        )
        assert resp.status_code == 422
        assert test_db.query(Pago).count() == 0
        test_db.expire_all()
        assert self._vencimientos(test_db)["ma0"] == VENC_PASADO

    # ── decision #646: SERVICIO is a catalog price, per unit ───────────────

    def test_servicio_se_resuelve_del_catalogo_por_unidad(self, test_client, test_db):
        """Catalog amount, factor 1, anchored to the unit — and it renews nothing.

        The client names a row that is NOT the servicio price: the server
        resolves the concept, never the client's id (D3).
        """
        ids = self._seed_balsa(test_db)
        resp = self._post(
            test_client,
            items=[{"arancelId": "a_balsa", "membresiaId": "ma0", "concepto": "servicio"}],
            membresia_ids=ids["areas"] + ids["cuotas"],
        )
        assert resp.status_code == 201
        body = resp.json()
        assert [i["concepto"] for i in body["items"]] == ["servicio"]
        item = body["items"][0]
        assert item["monto"] == SERVICIO_MONTO
        assert item["factor"] == 1.0
        assert item["arancelId"] == SERVICIO_ID
        # Utilities are per unit: the line hangs on the unit's membership.
        assert test_db.query(PagoItem).filter(PagoItem.pagoId == body["id"]).one().membresiaId == "ma0"
        # D4: a servicio-only charge renews NOTHING, so it cannot hand out a
        # free renewal of the 4 area + 4 cuota memberships submitted with it.
        test_db.expire_all()
        assert all(v == VENC_PASADO for v in self._vencimientos(test_db).values())

    def test_servicio_ajustable_no_pisa_el_catalogo(self, test_client, test_db):
        """A per-charge adjustment freezes on the item; the catalog keeps its price.

        This is the two-way contract of #646: the ADMIN owns the catalog price
        and the OPERATOR may adjust one charge (a metered reading), and neither
        writes over the other.
        """
        ids = self._seed_balsa(test_db)
        resp = self._post(
            test_client,
            items=[{"arancelId": SERVICIO_ID, "membresiaId": "ma0", "montoAplicado": 7300.0}],
            membresia_ids=ids["areas"],
        )
        assert resp.status_code == 201
        assert resp.json()["items"][0]["monto"] == 7300.0
        assert test_db.get(Arancel, SERVICIO_ID).monto == SERVICIO_MONTO

        # The admin edits the catalog price: the NEXT charge follows it.
        arancel = test_db.get(Arancel, SERVICIO_ID)
        arancel.monto = 6100.0
        test_db.commit()
        siguiente = self._post(
            test_client,
            items=[{"arancelId": SERVICIO_ID, "membresiaId": "ma0"}],
            membresia_ids=ids["areas"],
        )
        assert siguiente.json()["items"][0]["monto"] == 6100.0
        # ...and the first receipt is still frozen at the adjusted figure.
        assert test_client.get(f"/api/pagos/{resp.json()['id']}").json()["items"][0]["monto"] == 7300.0

    # ── CS-05: Windsurf is never double-charged ────────────────────────────

    def test_windsurf_no_agrega_item_de_area(self, test_client, test_db):
        """A Windsurf membership IS its cuota social: never a second line."""
        test_db.add(Socio(id="s1", nombre="Ana", dni="30111111", fechaAlta=date(2024, 1, 1)))
        test_db.add(
            Arancel(
                id="a_wind",
                nombre="Cuota",
                area=Area.WINDSURF,
                predio=Predio.ALMAFUERTE,
                monto=19000.0,
                vigenteDesde=date(2025, 1, 1),
                historico=[],
            )
        )
        test_db.add(
            Arancel(
                id=CUOTA_PRICE_ID,
                nombre="Cuota social",
                area=Area.GUARDERIA,
                predio=Predio.ALMAFUERTE,
                monto=CUOTA_UNIT_PRICE,
                vigenteDesde=date(2025, 1, 1),
                historico=[],
                concepto=ConceptoCobro.CUOTA_SOCIAL,
            )
        )
        test_db.flush()
        test_db.add(
            Membresia(
                id="ma0",
                socioId="s1",
                area=Area.WINDSURF,
                predio=Predio.ALMAFUERTE,
                estado=EstadoMembresia.ACTIVA,
                vencimiento=VENC_PASADO,
            )
        )
        test_db.add(
            Membresia(
                id="mc0",
                socioId="s1",
                area=None,
                predio=None,
                estado=EstadoMembresia.ACTIVA,
                vencimiento=VENC_PASADO,
                concepto=ConceptoMembresia.CUOTA_SOCIAL,
            )
        )
        test_db.commit()

        # Ticking the area for a Windsurf membership prices nothing: the charge
        # is empty, so it is a 422 and no free renewal is handed out.
        solo_area = self._post(
            test_client,
            items=[{"arancelId": "a_wind", "membresiaId": "ma0", "montoAplicado": 19000.0}],
            membresia_ids=["ma0", "mc0"],
        )
        assert solo_area.status_code == 422
        test_db.expire_all()
        assert test_db.get(Membresia, "ma0").vencimiento == VENC_PASADO

        # Ticking area + cuota social yields the cuota line ALONE, and it
        # renews the Windsurf row, because that row IS the cuota social.
        ambos = self._post(
            test_client,
            items=[
                {"arancelId": "a_wind", "membresiaId": "ma0", "montoAplicado": 19000.0},
                {"arancelId": CUOTA_PRICE_ID, "membresiaId": "mc0", "montoAplicado": 1.0},
            ],
            membresia_ids=["ma0", "mc0"],
        )
        assert ambos.status_code == 201
        body = ambos.json()
        assert [i["concepto"] for i in body["items"]] == ["cuota social"]
        # A lone Windsurf member is a unit of one: factor 1, not 2.
        assert body["items"][0]["factor"] == 1.0
        assert body["items"][0]["monto"] == CUOTA_UNIT_PRICE
        test_db.expire_all()
        assert test_db.get(Membresia, "ma0").vencimiento == VENC_COBRADO
        assert test_db.get(Membresia, "mc0").vencimiento == VENC_COBRADO

    # ── PAG-01: an empty charge is rejected ────────────────────────────────

    def test_cobro_vacio_es_422(self, test_client):
        """Zero items and zero membresiaIds: the PagoCreate validator holds."""
        resp = test_client.post(
            "/api/pagos",
            json={"socioId": "s1", "fecha": "2025-07-10", "medio": "efectivo", "total": 0.0},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# PR 5b — exhaustive multi-concept coverage.
#
# 5a locked the CONTRACT: one test per rule, on the full 4-concept charge. This
# block is the MATRIX behind that contract — every subset of the four chargeable
# concepts, the multiplier scoping, the catalog fallbacks, the recargo edge cases
# and D4 in both directions. It adds no new behaviour; it proves the contract
# holds in the combinations the cobro dialog can actually produce.
# ---------------------------------------------------------------------------

# concepto -> (the item the client sends, server amount, server factor,
#               which submitted memberships the concept renews)
LINEAS = {
    "area": ({"arancelId": "a_balsa", "membresiaId": "ma0"}, BALSA_ARANCEL, 1.0, "areas"),
    "cuota social": (
        {"arancelId": CUOTA_PRICE_ID, "membresiaId": "mc0"},
        CUOTA_UNIT_PRICE * 4,
        4.0,
        "cuotas",
    ),
    "servicio": ({"arancelId": SERVICIO_ID, "membresiaId": "ma0"}, SERVICIO_MONTO, 1.0, None),
    "recargo": (
        {"arancelId": RECARGO_ID, "membresiaId": "ma0", "montoAplicado": RECARGO_MONTO},
        RECARGO_MONTO,
        1.0,
        None,
    ),
}
# All 15 non-empty subsets, in a stable order (itertools keeps the tuple order).
SUBCONJUNTOS = [
    combo
    for n in range(1, len(ORDEN_CONCEPTOS) + 1)
    for combo in combinations(ORDEN_CONCEPTOS, n)
]


def _post_cobro(client, items, membresia_ids, total=999999.0, fecha="2025-07-10"):
    """POST a charge whose client `total` is deliberately wrong (D3)."""
    return client.post(
        "/api/pagos",
        json={
            "socioId": "s1",
            "fecha": fecha,
            "medio": "efectivo",
            "total": total,
            "items": items,
            "membresiaIds": membresia_ids,
        },
    )


def _venc(db, ids):
    """`{membresiaId: vencimiento}` for the given ids."""
    return {m.id: m.vencimiento for m in db.query(Membresia).filter(Membresia.id.in_(ids)).all()}


def _seed_cabana(db):
    """A second unit on its own parcel, priced by its OWN catch-all catalog row."""
    db.add(Socio(id="s9", nombre="Cabañero", dni="30999999", fechaAlta=date(2024, 1, 1)))
    db.add(Parcela(id="pa2", nombre="Cabaña", tipo=TipoParcela.CABANA, predio=Predio.ALMAFUERTE))
    db.add(
        Arancel(
            id="a_cab", nombre="Parcela", area=Area.CABANEROS, predio=Predio.ALMAFUERTE,
            monto=CABANA_ARANCEL, vigenteDesde=date(2025, 1, 1), historico=[],
        )
    )
    db.flush()  # the memberships below carry a real FK to this socio and parcel
    db.add(
        Membresia(
            id="mb0", socioId="s9", area=Area.CABANEROS, predio=Predio.ALMAFUERTE,
            estado=EstadoMembresia.ACTIVA, vencimiento=VENC_PASADO, parcelaId="pa2",
            rol=RolMembresia.TITULAR,
        )
    )
    db.add(
        Membresia(
            id="mc9", socioId="s9", area=None, predio=None, estado=EstadoMembresia.ACTIVA,
            vencimiento=VENC_PASADO, concepto=ConceptoMembresia.CUOTA_SOCIAL,
        )
    )
    db.commit()
    return {"areas": ["mb0"], "cuotas": ["mc9"]}


class TestCobroMultiConceptMatriz:
    """The 4 chargeable concepts on a real unit: every subset, every edge."""

    # ── CBM-04: one line per ticked concept, in all 15 combinations ────────

    @pytest.mark.parametrize("ticks", SUBCONJUNTOS, ids=lambda t: "+".join(t))
    def test_cada_combinacion_produce_sus_lineas_y_renueva_su_concepto(
        self, test_client, test_db, ticks
    ):
        """The whole concept matrix: additive total, and D4 in both directions.

        A membership renews exactly when its OWN concept was ticked and priced;
        ticking the area never renews a cuota social, ticking a recargo or a
        servicio never renews anything at all.
        """
        ids = _seed_unidad(test_db)
        enviados = ids["areas"] + ids["cuotas"]
        resp = _post_cobro(test_client, [LINEAS[c][0] for c in ticks], enviados)
        assert resp.status_code == 201
        body = resp.json()
        assert [i["concepto"] for i in body["items"]] == list(ticks)
        assert body["total"] == sum(LINEAS[c][1] for c in ticks)
        for concepto in ticks:
            item = next(i for i in body["items"] if i["concepto"] == concepto)
            assert (item["monto"], item["factor"]) == LINEAS[concepto][1:3]

        test_db.expire_all()
        venc = _venc(test_db, enviados)
        esperadas = set()
        for concepto in ticks:
            if LINEAS[concepto][3]:
                esperadas |= set(ids[LINEAS[concepto][3]])
        assert {mid for mid, v in venc.items() if v == VENC_COBRADO} == esperadas

    # ── CS-03: the area is per unit, only the cuota social scales ──────────

    @pytest.mark.parametrize("miembros", [1, 2, 4, 10])
    def test_escala_unica_la_cuota_social(self, test_client, test_db, miembros):
        """CS-03 'balsa de 4' and 'balsa de 10': the area arancel never scales."""
        ids = _seed_unidad(test_db, miembros)
        resp = _post_cobro(
            test_client,
            [LINEAS["area"][0], LINEAS["cuota social"][0]],
            ids["areas"] + ids["cuotas"],
        )
        assert resp.status_code == 201
        por_concepto = {i["concepto"]: i for i in resp.json()["items"]}
        assert (por_concepto["area"]["monto"], por_concepto["area"]["factor"]) == (BALSA_ARANCEL, 1.0)
        assert (por_concepto["cuota social"]["monto"], por_concepto["cuota social"]["factor"]) == (
            CUOTA_UNIT_PRICE * miembros,
            float(miembros),
        )
        test_db.expire_all()
        assert set(_venc(test_db, ids["areas"] + ids["cuotas"]).values()) == {VENC_COBRADO}

    def test_el_multiplicador_es_la_unidad_que_viaja_con_el_comprobante(self, test_client, test_db):
        """The factor counts the unit's members the operator actually submitted."""
        ids = _seed_unidad(test_db, miembros=4)
        # 2 of the 4 members of the parcel travel with the receipt: the cuota social
        # is charged for those 2, and the 2 left behind are neither scaled nor renewed.
        resp = _post_cobro(
            test_client,
            [LINEAS["area"][0], LINEAS["cuota social"][0]],
            ids["areas"][:2],
        )
        cuota = next(i for i in resp.json()["items"] if i["concepto"] == "cuota social")
        assert (cuota["monto"], cuota["factor"]) == (CUOTA_UNIT_PRICE * 2, 2.0)
        test_db.expire_all()
        venc = _venc(test_db, ids["areas"] + ids["cuotas"])
        assert {mid for mid, v in venc.items() if v == VENC_COBRADO} == {"ma0", "ma1"}

    def test_dos_unidades_dan_dos_lineas_de_area(self, test_client, test_db):
        """CBM-04: line identity is (concepto, arancel), so two parcels, two lines."""
        ids = _seed_unidad(test_db, miembros=2)
        cabana = _seed_cabana(test_db)
        enviados = ids["areas"] + ids["cuotas"] + cabana["areas"] + cabana["cuotas"]
        resp = _post_cobro(
            test_client,
            [
                {"arancelId": "a_balsa", "membresiaId": "ma0"},
                {"arancelId": "a_cab", "membresiaId": "mb0"},
                {"arancelId": CUOTA_PRICE_ID, "membresiaId": "mc0"},
            ],
            enviados,
        )
        assert resp.status_code == 201
        body = resp.json()
        assert [(i["concepto"], i["arancelId"]) for i in body["items"]] == [
            ("area", "a_balsa"),
            ("area", "a_cab"),
            ("cuota social", CUOTA_PRICE_ID),
        ]
        # The cuota multiplier follows the FIRST unit of the charge (CS-03).
        assert body["items"][2]["factor"] == 2.0
        assert body["total"] == BALSA_ARANCEL + CABANA_ARANCEL + CUOTA_UNIT_PRICE * 2
        test_db.expire_all()
        assert set(_venc(test_db, enviados).values()) == {VENC_COBRADO}

    def test_solo_cuota_social_no_agrega_linea_de_area(self, test_client, test_db):
        """CBM-04 'solo cuota social': no area item and no area membership renewed."""
        ids = _seed_unidad(test_db)
        resp = _post_cobro(
            test_client, [LINEAS["cuota social"][0]], ids["areas"] + ids["cuotas"]
        )
        assert resp.status_code == 201
        body = resp.json()
        assert [i["concepto"] for i in body["items"]] == ["cuota social"]
        assert body["total"] == CUOTA_UNIT_PRICE * 4
        test_db.expire_all()
        venc = _venc(test_db, ids["areas"] + ids["cuotas"])
        assert {mid for mid, v in venc.items() if v == VENC_COBRADO} == set(ids["cuotas"])

    # ── D3: the client prices nothing ──────────────────────────────────────

    def test_el_factor_y_el_monto_del_cliente_se_ignoran(self, test_client, test_db):
        """`factor` is a hint exactly like `montoAplicado`: the server decides."""
        ids = _seed_unidad(test_db)
        resp = _post_cobro(
            test_client,
            [
                {"arancelId": "a_balsa", "membresiaId": "ma0", "montoAplicado": 1.0, "factor": 99},
                {"arancelId": CUOTA_PRICE_ID, "membresiaId": "mc0", "montoAplicado": 1.0, "factor": 99},
            ],
            ids["areas"] + ids["cuotas"],
        )
        body = resp.json()
        assert [(i["monto"], i["factor"]) for i in body["items"]] == [
            (BALSA_ARANCEL, 1.0),
            (CUOTA_UNIT_PRICE * 4, 4.0),
        ]
        assert body["total"] == BALSA_ARANCEL + CUOTA_UNIT_PRICE * 4

    def test_una_linea_no_puede_preciarse_con_la_fila_de_otro_concepto(self, test_client, test_db):
        """A client naming the recargo carrier for an AREA line is corrected."""
        ids = _seed_unidad(test_db)
        resp = _post_cobro(
            test_client,
            [{"arancelId": RECARGO_ID, "membresiaId": "ma0", "concepto": "area", "montoAplicado": 5.0}],
            ids["areas"],
        )
        assert resp.status_code == 201
        item = resp.json()["items"][0]
        assert (item["arancelId"], item["monto"], item["nombre"]) == (
            "a_balsa",
            BALSA_ARANCEL,
            "Amarre y Servicios",
        )

    # ── PAG-01: amounts and factors freeze at creation ─────────────────────

    def test_los_montos_y_los_factores_quedan_congelados(self, test_client, test_db):
        """After a catalog edit the receipt still reads the original figures.

        `concepto` + `factor` are PERSISTED on every ``PagoItem`` (PAG-01), so the
        frozen receipt explains itself without re-reading the catalog.
        """
        ids = _seed_unidad(test_db)
        posted = _post_cobro(
            test_client, [LINEAS[c][0] for c in ORDEN_CONCEPTOS], ids["areas"] + ids["cuotas"]
        )
        assert posted.status_code == 201
        items = posted.json()["items"]
        original = {i["concepto"]: (i["monto"], i["factor"]) for i in items}

        test_db.expire_all()
        filas = test_db.query(PagoItem).filter(PagoItem.pagoId == posted.json()["id"]).all()
        assert {f.concepto.value: f.factor for f in filas} == {
            i["concepto"]: i["factor"] for i in items
        }
        for arancel_id, monto in (("a_balsa", 999.0), (CUOTA_PRICE_ID, 1.0), (SERVICIO_ID, 1.0)):
            test_db.get(Arancel, arancel_id).monto = monto
        test_db.commit()

        reabierto = test_client.get(f"/api/pagos/{posted.json()['id']}").json()
        assert {i["concepto"]: (i["monto"], i["factor"]) for i in reabierto["items"]} == original
        assert reabierto["total"] == sum(monto for monto, _ in original.values())

    # ── CBM-03 / ARA-01: recargo edge cases ────────────────────────────────

    @pytest.mark.parametrize("monto", [None, 0.0, -5000.0])
    def test_recargo_sin_monto_valido_es_422_y_no_persiste_nada(
        self, test_client, test_db, monto
    ):
        """A missing, zero or negative recargo amount is rejected and rolls back."""
        ids = _seed_unidad(test_db)
        item = {"arancelId": RECARGO_ID, "membresiaId": "ma0", "concepto": "recargo"}
        if monto is not None:
            item["montoAplicado"] = monto
        resp = _post_cobro(test_client, [item], ids["areas"])
        assert resp.status_code == 422
        assert test_db.query(Pago).count() == 0
        assert test_db.query(PagoItem).count() == 0
        test_db.expire_all()
        assert set(_venc(test_db, ids["areas"] + ids["cuotas"]).values()) == {VENC_PASADO}

    def test_el_recargo_resuelve_su_propia_carpeta_por_concepto(self, test_client, test_db):
        """The client's arancelId never picks the carrier; the concept does."""
        ids = _seed_unidad(test_db)
        resp = _post_cobro(
            test_client,
            [
                {
                    "arancelId": "a_balsa",
                    "membresiaId": "ma0",
                    "concepto": "recargo",
                    "montoAplicado": 8000.0,
                }
            ],
            ids["areas"],
        )
        assert resp.status_code == 201
        item = resp.json()["items"][0]
        assert (item["arancelId"], item["monto"], item["nombre"]) == (RECARGO_ID, 8000.0, "Recargo")
        assert test_db.get(Arancel, RECARGO_ID).monto == 0.0
        assert test_db.get(Arancel, "a_balsa").monto == BALSA_ARANCEL

    # ── catalog fallbacks: a missing row drops its line, never invents one ──

    @pytest.mark.parametrize(
        ("faltante", "caida"),
        [(SERVICIO_ID, "servicio"), (CUOTA_PRICE_ID, "cuota social"), ("a_balsa", "area")],
    )
    def test_un_concepto_sin_fila_de_catalogo_no_se_inventa_linea_ni_renueva(
        self, test_client, test_db, faltante, caida
    ):
        """Safety rule 1: a concept renews only after its line was produced."""
        ids = _seed_unidad(test_db)
        test_db.query(Arancel).filter(Arancel.id == faltante).delete()
        test_db.commit()
        resp = _post_cobro(
            test_client, [LINEAS[c][0] for c in ORDEN_CONCEPTOS], ids["areas"] + ids["cuotas"]
        )
        assert resp.status_code == 201
        body = resp.json()
        assert caida not in [i["concepto"] for i in body["items"]]
        assert body["total"] == sum(LINEAS[c][1] for c in ORDEN_CONCEPTOS if c != caida)

        test_db.expire_all()
        venc = _venc(test_db, ids["areas"] + ids["cuotas"])
        esperado = set()
        if caida != "area":
            esperado |= set(ids["areas"])
        if caida != "cuota social":
            esperado |= set(ids["cuotas"])
        assert {mid for mid, v in venc.items() if v == VENC_COBRADO} == esperado

    def test_solo_conceptos_sin_catalogo_es_422(self, test_client, test_db):
        """Nothing priceable and nothing to renew: PAG-01's empty charge."""
        ids = _seed_unidad(test_db)
        test_db.query(Arancel).delete()
        test_db.commit()
        resp = _post_cobro(
            test_client, [LINEAS[c][0] for c in ORDEN_CONCEPTOS], ids["areas"] + ids["cuotas"]
        )
        assert resp.status_code == 422
        assert test_db.query(Pago).count() == 0
        test_db.expire_all()
        assert set(_venc(test_db, ids["areas"] + ids["cuotas"]).values()) == {VENC_PASADO}

    def test_cuota_social_sin_membresia_del_socio_es_422(self, test_client, test_db):
        """A database with no cuota social row for the socio: never invented."""
        ids = _seed_unidad(test_db)
        test_db.query(Membresia).filter(
            Membresia.concepto == ConceptoMembresia.CUOTA_SOCIAL
        ).delete()
        test_db.commit()
        resp = _post_cobro(test_client, [LINEAS["cuota social"][0]], ids["areas"])
        assert resp.status_code == 422
        assert "cuota social" in resp.json()["detail"]
        assert test_db.query(Pago).count() == 0

    def test_un_item_sin_membresia_que_imputar_es_422(self, test_client, test_db):
        """``PagoItem.membresiaId`` is NOT NULL: a dangling id is refused."""
        resp = _post_cobro(
            test_client,
            [
                {
                    "arancelId": RECARGO_ID,
                    "membresiaId": "no-existe",
                    "concepto": "recargo",
                    "montoAplicado": 5000.0,
                }
            ],
            [],
        )
        assert resp.status_code == 422
        assert test_db.query(Pago).count() == 0

    # ── D4: the renewal set is an intersection, in both directions ─────────

    def test_cobro_solo_con_items_renueva_las_membresias_de_los_items(
        self, test_client, test_db
    ):
        """No membresiaIds: the items' own memberships are the submitted set."""
        ids = _seed_unidad(test_db)
        resp = _post_cobro(test_client, [LINEAS[c][0] for c in ORDEN_CONCEPTOS], [])
        assert resp.status_code == 201
        body = resp.json()
        assert [i["concepto"] for i in body["items"]] == list(ORDEN_CONCEPTOS)
        por_concepto = {i["concepto"]: i for i in body["items"]}
        # Only ma0 travels, so the cuota multiplier is that one member, not the 4.
        assert por_concepto["cuota social"]["factor"] == 1.0
        test_db.expire_all()
        venc = _venc(test_db, ids["areas"] + ids["cuotas"])
        assert {mid for mid, v in venc.items() if v == VENC_COBRADO} == {"ma0", "mc0"}

    def test_sin_items_se_renueva_exactamente_lo_enviado(self, test_client, test_db):
        """The historical membresiaIds-only charge still works, on a whole unit."""
        ids = _seed_unidad(test_db)
        enviados = ids["areas"] + ids["cuotas"]
        resp = _post_cobro(test_client, [], enviados)
        assert resp.status_code == 201
        body = resp.json()
        assert body["items"] == []
        assert body["total"] == 0.0
        test_db.expire_all()
        assert set(_venc(test_db, enviados).values()) == {VENC_COBRADO}

    def test_un_periodo_ya_cobrado_no_se_acorta(self, test_client, test_db):
        """CBM-01: a charge never shortens coverage that is already paid."""
        ids = _seed_unidad(test_db)
        pagado = date(2025, 9, 10)
        test_db.get(Membresia, "ma0").vencimiento = pagado
        test_db.commit()
        resp = _post_cobro(test_client, [LINEAS["area"][0]], ids["areas"])
        assert resp.status_code == 201
        test_db.expire_all()
        venc = _venc(test_db, ids["areas"])
        assert venc["ma0"] == pagado
        assert venc["ma1"] == VENC_COBRADO

    def test_dos_cobros_en_la_misma_ventana_no_avanzan(self, test_client, test_db):
        """CBM-01 'segundo cobro en el mismo mes': idempotent inside a window."""
        ids = _seed_unidad(test_db)
        assert _post_cobro(test_client, [LINEAS["area"][0]], ids["areas"], fecha="2025-07-01").status_code == 201
        assert _post_cobro(test_client, [LINEAS["area"][0]], ids["areas"], fecha="2025-07-10").status_code == 201
        test_db.expire_all()
        assert set(_venc(test_db, ids["areas"]).values()) == {VENC_COBRADO}

    # ── CS-05: a Windsurf membership IS the cuota social ────────────────────

    def test_windsurf_legacy_sin_fila_de_cuota_cobra_sobre_si_mismo(self, test_client, test_db):
        """A pre-DECISION-B database: the cuota line falls back to the Windsurf row."""
        test_db.add(Socio(id="s1", nombre="Ana", dni="30111111", fechaAlta=date(2024, 1, 1)))
        test_db.add(
            Parcela(id="pa1", nombre="Spot", tipo=TipoParcela.CABANA, predio=Predio.ALMAFUERTE)
        )
        test_db.add(
            Arancel(
                id="a_wind",
                nombre="Cuota",
                area=Area.WINDSURF,
                predio=Predio.ALMAFUERTE,
                monto=19000.0,
                vigenteDesde=date(2025, 1, 1),
                historico=[],
            )
        )
        test_db.add(
            Arancel(
                id=CUOTA_PRICE_ID,
                nombre="Cuota social",
                area=Area.GUARDERIA,
                predio=Predio.ALMAFUERTE,
                monto=CUOTA_UNIT_PRICE,
                vigenteDesde=date(2025, 1, 1),
                historico=[],
                concepto=ConceptoCobro.CUOTA_SOCIAL,
            )
        )
        test_db.flush()  # the Windsurf membership below carries a real FK to these rows
        test_db.add(
            Membresia(
                id="ma0",
                socioId="s1",
                area=Area.WINDSURF,
                predio=Predio.ALMAFUERTE,
                estado=EstadoMembresia.ACTIVA,
                vencimiento=VENC_PASADO,
                parcelaId="pa1",
                rol=RolMembresia.TITULAR,
            )
        )
        test_db.commit()

        # Ticking the area is still refused: a Windsurf row anchors no area line.
        area = _post_cobro(
            test_client, [{"arancelId": "a_wind", "membresiaId": "ma0"}], ["ma0"]
        )
        assert area.status_code == 422
        test_db.expire_all()
        assert test_db.get(Membresia, "ma0").vencimiento == VENC_PASADO

        # Ticking the cuota social charges the unit price and renews that row.
        resp = _post_cobro(
            test_client, [{"arancelId": CUOTA_PRICE_ID, "membresiaId": "ma0"}], ["ma0"]
        )
        assert resp.status_code == 201
        assert [(i["concepto"], i["monto"], i["factor"]) for i in resp.json()["items"]] == [
            ("cuota social", CUOTA_UNIT_PRICE, 1.0)
        ]
        test_db.expire_all()
        assert test_db.get(Membresia, "ma0").vencimiento == VENC_COBRADO


class TestResolucionConceptScoped:
    """PAG-01 at the resolver level: the concept tag scopes every catalog lookup."""

    def _catalog(self, db):
        """Two real area rows plus the three non-place concept rows.

        The concept rows deliberately share ``GUARDERIA``/``ALMAFUERTE`` with
        ``a_guard``, because that is the collision the concept tag exists to stop.
        """
        # id, nombre, area, predio, categoria, monto, concepto
        filas = [
            ("a_balsa", "Amarre y Servicios", Area.BALSEROS, Predio.EMBALSE, None,
             BALSA_ARANCEL, None),
            ("a_guard", "Cuota guardería chica", Area.GUARDERIA, Predio.ALMAFUERTE,
             CategoriaParcela.CHICA, 12000.0, None),
            (RECARGO_ID, "Recargo", Area.GUARDERIA, Predio.ALMAFUERTE, None, 0.0,
             ConceptoCobro.RECARGO),
            (CUOTA_PRICE_ID, "Cuota social", Area.GUARDERIA, Predio.ALMAFUERTE, None,
             CUOTA_UNIT_PRICE, ConceptoCobro.CUOTA_SOCIAL),
            (SERVICIO_ID, "Servicio (luz, agua)", Area.GUARDERIA, Predio.ALMAFUERTE, None,
             SERVICIO_MONTO, ConceptoCobro.SERVICIO),
        ]
        db.add_all(
            [
                Arancel(
                    id=arancel_id, nombre=nombre, area=area, predio=predio, categoria=categoria,
                    monto=monto, vigenteDesde=date(2025, 1, 1), historico=[], concepto=concepto,
                )
                for arancel_id, nombre, area, predio, categoria, monto, concepto in filas
            ]
        )
        db.commit()

    def test_una_fila_de_concepto_no_responde_a_un_lookup_de_area(self, test_db):
        """The non-place rows carry a placeholder area/predio; they must not answer."""
        self._catalog(test_db)
        # A guardería area lookup shares area+predio with all three concept rows.
        guarderia = resolver_monto(test_db, Area.GUARDERIA, Predio.ALMAFUERTE, CategoriaParcela.CHICA)
        assert guarderia.id == "a_guard"
        # The catch-all for that place is NOT one of them: it does not exist.
        assert resolver_monto(test_db, Area.GUARDERIA, Predio.ALMAFUERTE, None) is None

    def test_un_arancel_id_de_otro_concepto_se_rechaza(self, test_db):
        """An explicit id is accepted only when it carries the requested concept."""
        self._catalog(test_db)
        # The recargo carrier cannot price a balsa: the id is dropped, the place wins.
        balsa = resolver_monto(test_db, Area.BALSEROS, Predio.EMBALSE, None, arancel_id=RECARGO_ID)
        assert balsa.id == "a_balsa"
        # ...and an area row cannot price a recargo, which is not a place at all.
        assert (
            resolver_monto(
                test_db, Area.BALSEROS, Predio.EMBALSE, None,
                arancel_id="a_balsa", concepto=ConceptoCobro.RECARGO,
            )
            is None
        )

    def test_resolver_arancel_concepto_es_determinista(self, test_db):
        """Two rows for one concept: the lowest id wins, never an arbitrary one."""
        self._catalog(test_db)
        test_db.add(
            Arancel(
                id="a_recargo_2", nombre="Recargo (dup)", area=Area.GUARDERIA,
                predio=Predio.ALMAFUERTE, monto=0.0, vigenteDesde=date(2025, 1, 1),
                historico=[], concepto=ConceptoCobro.RECARGO,
            )
        )
        test_db.commit()
        assert resolver_arancel_concepto(test_db, ConceptoCobro.RECARGO).id == RECARGO_ID

    def test_el_precio_de_cada_concepto_viene_de_su_propia_fila(self, test_db):
        """A catalog migrated but never re-seeded: no row, no invented price."""
        self._catalog(test_db)
        assert precio_cuota_social(test_db).id == CUOTA_PRICE_ID
        assert precio_servicio(test_db).id == SERVICIO_ID
        test_db.query(Arancel).filter(Arancel.id.in_([CUOTA_PRICE_ID, SERVICIO_ID])).delete()
        test_db.commit()
        assert precio_cuota_social(test_db) is None
        assert precio_servicio(test_db) is None


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
