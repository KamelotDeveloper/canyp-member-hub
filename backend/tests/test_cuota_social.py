"""Cuota social lifecycle (spec CS-01, CS-02, CS-05, CS-06).

Locks the three properties the rest of the change depends on:

* every socio owns exactly ONE ``CUOTA_SOCIAL`` membership and the creation is
  idempotent (CS-01, CS-02);
* the row is created automatically on socio creation, on bulk import and on
  unit-member add (CS-02);
* it carries no area/predio/parcelaId/rol, anchors on the current 10->10 window
  when the socio has no area membership, and never creates a SECOND area
  membership for a Windsurf socio (CS-05).
"""

from datetime import date, timedelta

from backend.models.enums import (
    Area,
    ConceptoMembresia,
    EstadoMembresia,
    Predio,
    RolMembresia,
    TipoParcela,
)
from backend.models.membresia import Membresia
from backend.models.parcela import Parcela
from backend.models.socio import Socio
from backend.services.cuota_social import (
    crear_cuota_social,
    cuota_de,
    ultimo_vencimiento_area,
    ventana_actual,
)


def _socio(db, socio_id="s1", **kw):
    s = Socio(
        id=socio_id,
        nombre=kw.pop("nombre", f"Socio {socio_id}"),
        dni=kw.pop("dni", f"30{socio_id:0>6}"),
        fechaAlta=date(2026, 1, 1),
        **kw,
    )
    db.add(s)
    db.commit()
    return s


def _area_m(db, mid, socio_id, *, area=Area.BALSEROS, predio=Predio.EMBALSE, dias=200,
           parcela_id=None, rol=None, estado=EstadoMembresia.ACTIVA):
    m = Membresia(
        id=mid,
        socioId=socio_id,
        area=area,
        predio=predio,
        estado=estado,
        vencimiento=date.today() + timedelta(days=dias),
        parcelaId=parcela_id,
        rol=rol,
    )
    db.add(m)
    db.commit()
    return m


class TestVentanaActual:
    """The current-window anchor is `dia10(today)`, at-or-after."""

    def test_ventana_actual_is_the_current_window(self):
        assert ventana_actual(date(2026, 9, 25)) == date(2026, 10, 10)
        assert ventana_actual(date(2026, 9, 5)) == date(2026, 9, 10)
        assert ventana_actual(date(2026, 9, 10)) == date(2026, 9, 10)

    def test_ventana_actual_always_lands_on_day_10(self):
        for dia in (1, 9, 10, 11, 30):
            assert ventana_actual(date(2026, 9, dia)).day == 10


class TestCrearCuotaSocial:
    """The row itself, and the idempotency guarantee."""

    def test_creates_one_cuota_social_row(self, test_db):
        _socio(test_db, "s1")
        cuota, created = crear_cuota_social(test_db, "s1")
        test_db.commit()
        assert created is True
        assert cuota.concepto == ConceptoMembresia.CUOTA_SOCIAL
        assert cuota.socioId == "s1"
        assert test_db.query(Membresia).count() == 1

    def test_cuota_row_has_no_area_predio_parcela_nor_rol(self, test_db):
        _socio(test_db, "s1")
        cuota, _ = crear_cuota_social(test_db, "s1")
        test_db.commit()
        assert cuota.area is None
        assert cuota.predio is None
        assert cuota.parcelaId is None
        assert cuota.rol is None
        assert cuota.estado == EstadoMembresia.ACTIVA

    def test_is_idempotent_and_does_not_duplicate(self, test_db):
        _socio(test_db, "s1")
        primera, created_1 = crear_cuota_social(test_db, "s1")
        segunda, created_2 = crear_cuota_social(test_db, "s1")
        test_db.commit()
        assert created_1 is True
        assert created_2 is False
        assert primera.id == segunda.id
        assert test_db.query(Membresia).count() == 1

    def test_idempotent_when_already_on_the_10th(self, test_db):
        """A second run in the SAME transaction must not duplicate the row.

        The application session factory uses autoflush=False, so this only holds
        because `crear_cuota_social` flushes; without it the lookup would miss
        the pending row and create a duplicate.
        """
        _socio(test_db, "s1")
        primera, _ = crear_cuota_social(test_db, "s1")
        segunda, created = crear_cuota_social(test_db, "s1")
        test_db.commit()
        assert created is False
        assert primera.id == segunda.id
        assert segunda.vencimiento == primera.vencimiento
        assert test_db.query(Membresia).count() == 1

    def test_second_call_does_not_move_the_vencimiento(self, test_db):
        """Idempotency means the existing row is returned untouched."""
        _socio(test_db, "s1")
        _area_m(test_db, "m1", "s1", dias=200)
        primera, _ = crear_cuota_social(test_db, "s1")
        # The socio's area membership is renewed afterwards; the cuota row
        # must NOT follow, because it was never re-created.
        _area_m(test_db, "m2", "s1", dias=400)
        segunda, created = crear_cuota_social(test_db, "s1")
        test_db.commit()
        assert created is False
        assert segunda.vencimiento == primera.vencimiento

    def test_socio_sin_actividad_anchors_on_current_window(self, test_db):
        """CS-06: no area membership -> the current 10->10 window."""
        _socio(test_db, "s1")
        cuota, _ = crear_cuota_social(test_db, "s1")
        test_db.commit()
        assert cuota.vencimiento == ventana_actual()

    def test_inherits_the_most_recent_area_vencimiento(self, test_db):
        _socio(test_db, "s1")
        _area_m(test_db, "m1", "s1", dias=200)  # later
        _area_m(test_db, "m2", "s1", dias=-30)  # earlier
        cuota, _ = crear_cuota_social(test_db, "s1")
        test_db.commit()
        assert cuota.vencimiento == date.today() + timedelta(days=200)

    def test_accepts_an_explicit_vencimiento(self, test_db):
        _socio(test_db, "s1")
        _area_m(test_db, "m1", "s1", dias=200)
        cuota, _ = crear_cuota_social(test_db, "s1", vencimiento=date(2026, 10, 10))
        test_db.commit()
        assert cuota.vencimiento == date(2026, 10, 10)


class TestCuotaDeYUltimoVencimiento:
    """The two read helpers the migration and the service share."""

    def test_cuota_de_returns_none_without_one(self, test_db):
        _socio(test_db, "s1")
        assert cuota_de(test_db, "s1") is None

    def test_cuota_de_ignores_area_memberships(self, test_db):
        _socio(test_db, "s1")
        _area_m(test_db, "m1", "s1")
        assert cuota_de(test_db, "s1") is None

    def test_ultimo_vencimiento_area_is_none_without_activity(self, test_db):
        _socio(test_db, "s1")
        assert ultimo_vencimiento_area(test_db, "s1") is None

    def test_ultimo_vencimiento_area_ignores_the_cuota_row(self, test_db):
        _socio(test_db, "s1")
        _area_m(test_db, "m1", "s1", dias=100)
        crear_cuota_social(test_db, "s1")
        test_db.commit()
        assert ultimo_vencimiento_area(test_db, "s1") == date.today() + timedelta(days=100)


class TestAutoCreateOnSocioCreation:
    """CS-02: creating a socio creates its cuota social, in the same commit."""

    def test_post_socio_creates_the_cuota(self, test_client, test_db):
        resp = test_client.post(
            "/api/socios",
            json={"nombre": "Nuevo Socio", "dni": "40111222"},
        )
        assert resp.status_code == 201
        socio_id = resp.json()["id"]

        cuotas = (
            test_db.query(Membresia)
            .filter(Membresia.socioId == socio_id)
            .all()
        )
        assert len(cuotas) == 1
        assert cuotas[0].concepto == ConceptoMembresia.CUOTA_SOCIAL
        assert cuotas[0].area is None
        assert cuotas[0].vencimiento == ventana_actual()

    def test_socio_create_is_idempotent_across_two_posts(self, test_client, test_db):
        """Different socios, one cuota each; a second POST never doubles one."""
        ids = []
        for dni in ("40111222", "40222333"):
            resp = test_client.post("/api/socios", json={"nombre": "X", "dni": dni})
            assert resp.status_code == 201
            ids.append(resp.json()["id"])
        total = test_db.query(Membresia).count()
        assert total == len(ids)


class TestAutoCreateOnBulkImport:
    """CS-02: an imported socio gets its cuota social inside the row savepoint."""

    def test_imported_socio_gets_one_cuota(self, test_client, test_db):
        resp = test_client.post(
            "/api/socios/import/execute",
            json={
                "rows": [
                    {
                        "skip": False,
                        "data": {
                            "nombre": "Importado Uno",
                            "dni": "50111222",
                            "telefono": "",
                            "email": "",
                            "direccion": "",
                        },
                    },
                    {
                        "skip": False,
                        "data": {
                            "nombre": "Importado Dos",
                            "dni": "50222333",
                            "telefono": "",
                            "email": "",
                            "direccion": "",
                        },
                    },
                ]
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["importados"] == 2

        for id_importado in (body["rows"][0]["id"], body["rows"][1]["id"]):
            cuotas = [
                m
                for m in test_db.query(Membresia).filter(Membresia.socioId == id_importado)
                if m.concepto == ConceptoMembresia.CUOTA_SOCIAL
            ]
            assert len(cuotas) == 1

    def test_skipped_row_creates_nothing(self, test_client, test_db):
        resp = test_client.post(
            "/api/socios/import/execute",
            json={"rows": [{"skip": True, "data": {"nombre": "Omitido", "dni": "50999999"}}]},
        )
        assert resp.status_code == 201
        assert resp.json()["omitidos"] == 1
        assert test_db.query(Membresia).count() == 0

    def test_rejected_row_leaves_no_orphan_cuota(self, test_client, test_db):
        """A row that fails rolls back its cuota too (same SAVEPOINT)."""
        resp = test_client.post(
            "/api/socios/import/execute",
            json={
                "rows": [
                    # duplicate dni within the batch -> the second row fails
                    {"skip": False, "data": {"nombre": "Uno", "dni": "50444444"}},
                    {"skip": False, "data": {"nombre": "Dos", "dni": "50444444"}},
                ]
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["importados"] == 1
        assert body["fallidos"] == 1
        # exactly one cuota: the failed row did not leave a second one behind
        assert test_db.query(Membresia).count() == 1


class TestAutoCreateOnUnitMemberAdd:
    """CS-02: adding members to a unit gives every one of them a cuota."""

    def _unidad(self, miembros=None):
        return {
            "unidades": [
                {
                    "nombre": "Cabaña Test",
                    "tipo": "cabaña",
                    "categoria": "Mediana",
                    "predio": "Almafuerte",
                    "miembros": miembros
                    if miembros is not None
                    else [
                        {
                            "rol": "Titular",
                            "vencimiento": "2026-10-10",
                            "socio": {
                                "dni": "60111222",
                                "nombre": "Titular",
                                "telefono": "",
                                "email": "",
                            },
                        },
                        {
                            "rol": "Integrante",
                            "vencimiento": "2026-10-10",
                            "socio": {
                                "dni": "60222333",
                                "nombre": "Integrante",
                                "telefono": "",
                                "email": "",
                            },
                        },
                    ],
                }
            ]
        }

    def test_every_new_unit_member_gets_a_cuota(self, test_client, test_db):
        resp = test_client.post("/api/parcelas/import", json=self._unidad())
        assert resp.status_code == 200
        assert len(resp.json()["membresias"]) == 2
        assert len(resp.json()["socios"]) == 2

        cuotas = [
            m
            for m in test_db.query(Membresia).all()
            if m.concepto == ConceptoMembresia.CUOTA_SOCIAL
        ]
        assert len(cuotas) == 2
        for cuota in cuotas:
            assert cuota.area is None
            assert cuota.parcelaId is None
            assert cuota.rol is None

    def test_existing_unit_member_still_gets_a_cuota(self, test_client, test_db):
        """The socio already has the unit's area row; the cuota is still created.

        Guards the wiring ORDER: `crear_cuota_social` must run before the
        "already a member of this unit" short-circuit.
        """
        socio = _socio(test_db, "s1", dni="60333444", nombre="Previa")
        test_db.add(
            Parcela(
                id="p1",
                nombre="Cabaña Test",
                tipo=TipoParcela.CABANA,
                predio=Predio.ALMAFUERTE,
            )
        )
        test_db.add(
            Membresia(
                id="m-previa",
                socioId=socio.id,
                area=Area.CABANEROS,
                predio=Predio.ALMAFUERTE,
                estado=EstadoMembresia.ACTIVA,
                vencimiento=date(2026, 10, 10),
                parcelaId="p1",
                rol=RolMembresia.TITULAR,
            )
        )
        test_db.commit()

        payload = self._unidad(
            miembros=[
                {
                    "rol": "Titular",
                    "vencimiento": "2026-10-10",
                    "socio": {"dni": "60333444", "nombre": "Previa", "telefono": "", "email": ""},
                }
            ]
        )
        resp = test_client.post("/api/parcelas/import", json=payload)
        assert resp.status_code == 200
        # No new area row (idempotent), but the cuota social WAS created.
        assert resp.json()["membresias"] == []
        assert cuota_de(test_db, "s1") is not None


class TestWindsurfSafety:
    """CS-05: a Windsurf membership IS the cuota social — no second area row."""

    def test_windsurf_socio_keeps_exactly_two_memberships(self, test_client, test_db):
        """1 Windsurf area row (their cuota) + 1 explicit cuota social row."""
        _socio(test_db, "s1")
        _area_m(test_db, "m1", "s1", area=Area.WINDSURF, predio=Predio.ALMAFUERTE)
        crear_cuota_social(test_db, "s1")
        test_db.commit()

        membresias = test_db.query(Membresia).filter(Membresia.socioId == "s1").all()
        assert len(membresias) == 2
        assert sum(1 for m in membresias if m.area == Area.WINDSURF) == 1
        assert sum(1 for m in membresias if m.concepto == ConceptoMembresia.CUOTA_SOCIAL) == 1

    def test_creating_a_cuota_never_invents_an_area_membership(self, test_db):
        _socio(test_db, "s1")
        _area_m(test_db, "m1", "s1", area=Area.WINDSURF, predio=Predio.ALMAFUERTE)
        crear_cuota_social(test_db, "s1")
        test_db.commit()
        areas = [
            m
            for m in test_db.query(Membresia).all()
            if m.area is not None
        ]
        assert [m.id for m in areas] == ["m1"]


class TestNullAreaCuotaRendersEverywhere:
    """The reason task 2.3 exists: a cuota row must never 500 a read path."""

    def test_dashboard_and_padron_render_a_cuota_only_socio(self, test_client, test_db):
        _socio(test_db, "s1")
        crear_cuota_social(test_db, "s1")
        test_db.commit()

        assert test_client.get("/api/dashboard/stats").status_code == 200
        assert test_client.get("/api/dashboard/alertas").status_code == 200
        assert test_client.get("/api/membresias").status_code == 200
        assert test_client.get("/api/socios").status_code == 200
        assert test_client.get("/api/socios/s1/membresias").status_code == 200


class TestConceptoServidoPorLaApi:
    """GET /api/membresias serves `concepto` (MEM-01, PR 7).

    The cobro dialog has to know which membership prices a cuota social line and
    which one an área line. Serving the concept lets it READ the answer instead
    of re-deriving it from a null `area`, which is exactly the inference this
    change exists to remove.
    """

    def test_api_serves_cuota_social_and_area_concepts(self, test_client, test_db):
        _socio(test_db, "s1")
        _area_m(test_db, "m_area", "s1", area=Area.BALSEROS, predio=Predio.EMBALSE)
        crear_cuota_social(test_db, "s1")
        test_db.commit()

        resp = test_client.get("/api/membresias")
        assert resp.status_code == 200
        by_id = {m["id"]: m for m in resp.json()}
        assert by_id["m_area"]["concepto"] == "area"
        assert by_id["m_area"]["area"] == "Balseros"
        cuota_rows = [m for m in resp.json() if m["concepto"] == "cuota social"]
        assert len(cuota_rows) == 1
        assert cuota_rows[0]["area"] is None

    def test_create_ignores_a_client_supplied_concepto(self, test_client, test_db):
        """A POST must not be able to tag a membership's concept (MEM-01)."""
        _socio(test_db, "s1")
        resp = test_client.post(
            "/api/membresias",
            json={
                "socioId": "s1",
                "area": "Balseros",
                "predio": "Embalse",
                "estado": "activa",
                "vencimiento": "2026-01-10",
                "concepto": "cuota social",
            },
        )
        assert resp.status_code == 201
        m = test_db.query(Membresia).filter(Membresia.id == resp.json()["id"]).first()
        assert m.concepto == ConceptoMembresia.AREA
        assert resp.json()["concepto"] == "area"
