"""Null ``area``/``predio`` guards on the membresía read paths (task 2.3).

PR 1 made ``membresias.area``/``predio`` nullable because a cuota social
membership is not a physical location (spec CS-01). This module locks the
read paths that dereference those columns, so the first null-area row created
by ``crear_cuota_social`` (PR 3) cannot 500 the dashboard or the padrón.

Guarantees:
  - every ``.value`` on area/predio tolerates ``None`` (treated as "no área"),
  - the response schema accepts null for both fields,
  - memberships that DO carry an area behave exactly as before.
"""

from datetime import date, timedelta

from backend.models.enums import (
    Area,
    ConceptoMembresia,
    EstadoMembresia,
    EstadoSocioVisual,
    Predio,
    RolMembresia,
    TipoParcela,
)
from backend.models.membresia import Membresia
from backend.models.parcela import Parcela
from backend.models.socio import Socio

SIN_AREA = "Sin área"


def _socio(db, socio_id: str) -> Socio:
    s = Socio(
        id=socio_id, nombre=f"Socio {socio_id}", dni=f"30{socio_id:0>6}", fechaAlta=date(2026, 1, 1)
    )
    db.add(s)
    db.commit()
    return s


def _membresia(db, mid, socio_id, *, area, predio, vencido=False, parcela_id=None,
              concepto=ConceptoMembresia.AREA):
    m = Membresia(
        id=mid,
        socioId=socio_id,
        area=area,
        predio=predio,
        estado=EstadoMembresia.ACTIVA,
        concepto=concepto,
        vencimiento=date.today() - timedelta(days=40) if vencido else date.today() + timedelta(days=200),
        parcelaId=parcela_id,
    )
    db.add(m)
    db.commit()
    return m


class TestSchemaAcceptsNullArea:
    """`MembresiaResponse` must not reject a null area/predio row."""

    def test_list_membresias_returns_null_area(self, test_client, test_db):
        _socio(test_db, "s1")
        _membresia(test_db, "m1", "s1", area=None, predio=None)

        resp = test_client.get("/api/membresias")
        assert resp.status_code == 200
        row = next(r for r in resp.json() if r["id"] == "m1")
        assert row["area"] is None
        assert row["predio"] is None

    def test_socio_membresias_returns_null_area(self, test_client, test_db):
        _socio(test_db, "s1")
        _membresia(test_db, "m1", "s1", area=None, predio=None)

        resp = test_client.get("/api/socios/s1/membresias")
        assert resp.status_code == 200
        assert resp.json()[0]["area"] is None

    def test_get_membresia_returns_null_area(self, test_client, test_db):
        _socio(test_db, "s1")
        _membresia(test_db, "m1", "s1", area=None, predio=None)

        resp = test_client.get("/api/membresias/m1")
        assert resp.status_code == 200
        assert resp.json()["area"] is None


class TestDashboardToleratesNullArea:
    """`routers/dashboard.py` counts and alerts must survive a null area."""

    def test_stats_buckets_null_area_without_500(self, test_client, test_db):
        _socio(test_db, "s1")
        _socio(test_db, "s2")
        _membresia(test_db, "m1", "s1", area=None, predio=None)
        _membresia(test_db, "m2", "s2", area=Area.BALSEROS, predio=Predio.EMBALSE)

        resp = test_client.get("/api/dashboard/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert body["totalMembresias"] == 2
        assert body["countsByArea"][SIN_AREA] == 1
        assert body["countsByArea"][Area.BALSEROS.value] == 1

    def test_alertas_reports_null_area_without_500(self, test_client, test_db):
        _socio(test_db, "s1")
        # s1 owes cuota social and is current on it; the membership that is
        # actually overdue is a legacy null-area row.
        _membresia(test_db, "mc1", "s1", area=None, predio=None,
                   concepto=ConceptoMembresia.CUOTA_SOCIAL)
        _membresia(test_db, "m1", "s1", area=None, predio=None, vencido=True)

        resp = test_client.get("/api/dashboard/alertas")
        assert resp.status_code == 200
        alerta = next(a for a in resp.json() if a["id"] == "m1")
        assert alerta["area"] is None
        assert alerta["predio"] is None
        # The alert row is membership-level; the state served on it is the
        # socio's (EST-01), and here the socio owes nothing: "Solo cuota social".
        assert alerta["estadoSocio"] == EstadoSocioVisual.SOLO_CUOTA_SOCIAL.value


class TestParcelasGroupingToleratesNullArea:
    """`routers/membresias.py` grouping dereferences area/predio per row."""

    def test_grouping_returns_null_area_member(self, test_client, test_db):
        _socio(test_db, "s1")
        db = test_db
        db.add(
            Parcela(
                id="p1",
                nombre="Balsa 1",
                tipo=TipoParcela.BALSA,
                predio=Predio.EMBALSE,
            )
        )
        db.commit()
        # A unit member whose area was never recorded: parcelaId set, area NULL.
        _membresia(
            db,
            "m1",
            "s1",
            area=None,
            predio=None,
            parcela_id="p1",
        )
        db.add(
            Membresia(
                id="m2",
                socioId="s1",
                area=Area.BALSEROS,
                predio=Predio.EMBALSE,
                estado=EstadoMembresia.ACTIVA,
                vencimiento=date.today() + timedelta(days=30),
                parcelaId="p1",
                rol=RolMembresia.TITULAR,
            )
        )
        db.commit()

        resp = test_client.get("/api/membresias/parcelas")
        assert resp.status_code == 200
        membresias = {m["id"]: m for m in resp.json()[0]["membresias"]}
        assert membresias["m1"]["area"] is None
        assert membresias["m1"]["predio"] is None
        assert membresias["m2"]["area"] == Area.BALSEROS.value


class TestNoBehaviourChangeForAreaMembers:
    """The guard must not alter the payload of an area-carrying membership."""

    def test_area_member_payload_unchanged(self, test_client, test_db):
        _socio(test_db, "s1")
        _membresia(test_db, "m1", "s1", area=Area.WINDSURF, predio=Predio.ALMAFUERTE)

        resp = test_client.get("/api/membresias/m1")
        assert resp.status_code == 200
        body = resp.json()
        assert body["area"] == "Windsurf"
        assert body["predio"] == "Almafuerte"

        stats = test_client.get("/api/dashboard/stats").json()
        assert stats["countsByArea"]["Windsurf"] == 1
        assert stats["totalMembresias"] == 1
