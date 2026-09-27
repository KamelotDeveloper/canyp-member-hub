"""Integration tests for /api/aranceles create + update-monto endpoints."""

from datetime import date

from backend.models.arancel import Arancel
from backend.models.enums import (
    Area,
    ConceptoCobro,
    EstadoMembresia,
    Predio,
)
from backend.models.membresia import Membresia
from backend.models.pago import Pago, PagoItem
from backend.models.socio import Socio


def _seed_arancel(db, arancel_id: str = "a1", nombre: str = "Cuota Balseros Embalse"):
    """Insert a base arancel to update."""
    arancel = Arancel(
        id=arancel_id,
        nombre=nombre,
        area=Area.BALSEROS,
        predio=Predio.EMBALSE,
        monto=15000.0,
        vigenteDesde=date(2025, 1, 1),
        historico=[],
    )
    db.add(arancel)
    db.commit()
    return arancel


def _seed_socio_y_membresia(db):
    """The one socio + membership the paid-receipt scaffolding hangs off.

    Idempotent on `s1` so a test can hang a pago_item AND a membresia on the same
    arancel without colliding on `socios.dni`.
    """
    if db.query(Socio).filter(Socio.id == "s1").first() is None:
        db.add(
            Socio(id="s1", nombre="Titular", dni="30111111", fechaAlta=date(2024, 1, 1))
        )
        # Same flush-ordering workaround as `test_pagos_api._seed_unidad`: the
        # socio must be on disk before the membership FK points at it.
        db.flush()
    if db.query(Membresia).filter(Membresia.id == "m1").first() is None:
        db.add(
            Membresia(
                id="m1",
                socioId="s1",
                area=Area.BALSEROS,
                predio=Predio.EMBALSE,
                estado=EstadoMembresia.ACTIVA,
                vencimiento=date(2025, 7, 10),
            )
        )
    db.commit()


def _seed_pago_item(db, arancel_id: str, item_ids=None):
    """A paid receipt whose items point at `arancel_id` (the real FK, D5)."""
    item_ids = ["pi1"] if item_ids is None else item_ids
    _seed_socio_y_membresia(db)
    db.add(
        Pago(
            id="p1",
            numero="0001",
            socioId="s1",
            fecha=date(2025, 7, 10),
            medio="efectivo",
            total=15000.0,
        )
    )
    for item_id in item_ids:
        db.add(
            PagoItem(
                id=item_id,
                pagoId="p1",
                arancelId=arancel_id,
                membresiaId="m1",
                montoAplicado=15000.0,
                arancelNombre="Cuota",
            )
        )
    db.commit()


def _seed_membresia(db, arancel_id: str, membresia_ids=None):
    """Memberships carrying a soft `arancelId` (no FK: the guard is all we have)."""
    membresia_ids = ["m1"] if membresia_ids is None else membresia_ids
    _seed_socio_y_membresia(db)
    for membresia_id in membresia_ids:
        row = db.query(Membresia).filter(Membresia.id == membresia_id).first()
        if row is None:
            row = Membresia(
                id=membresia_id,
                socioId="s1",
                area=Area.BALSEROS,
                predio=Predio.EMBALSE,
                estado=EstadoMembresia.ACTIVA,
                vencimiento=date(2025, 7, 10),
            )
            db.add(row)
        row.arancelId = arancel_id
    db.commit()


class TestCreateArancel:
    """POST /api/aranceles — create a new arancel (201)."""

    def test_create_arancel_returns_201(self, test_client):
        resp = test_client.post(
            "/api/aranceles",
            json={
                "id": "a_new",
                "nombre": "Cuota Cabañeros Almafuerte",
                "area": "Cabañeros",
                "predio": "Almafuerte",
                "monto": 12000.0,
                "vigenteDesde": "2025-06-01",
                "historico": [],
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["id"] == "a_new"
        assert body["nombre"] == "Cuota Cabañeros Almafuerte"
        assert body["monto"] == 12000.0
        assert body["historico"] == []

    def test_created_arancel_is_persisted(self, test_client, test_db):
        test_client.post(
            "/api/aranceles",
            json={
                "id": "a_new",
                "nombre": "Cuota Guardería Embalse",
                "area": "Guardería",
                "predio": "Embalse",
                "monto": 8000.0,
                "vigenteDesde": "2025-06-01",
                "historico": [],
            },
        )
        a = test_db.query(Arancel).filter(Arancel.id == "a_new").first()
        assert a is not None
        assert a.nombre == "Cuota Guardería Embalse"
        assert a.monto == 8000.0

    def test_create_arancel_without_id_returns_201(self, test_client):
        resp = test_client.post(
            "/api/aranceles",
            json={
                "nombre": "Cuota Windsurf Almafuerte",
                "area": "Windsurf",
                "predio": "Almafuerte",
                "monto": 9000.0,
                "vigenteDesde": "2025-06-01",
                "historico": [],
            },
        )
        assert resp.status_code == 201
        assert resp.json()["id"].startswith("a")


class TestUpdateMonto:
    """PUT /api/aranceles/{id}/monto — update valor preserving historico."""

    def test_update_monto_returns_200(self, test_client, test_db):
        _seed_arancel(test_db)
        resp = test_client.put("/api/aranceles/a1/monto", json={"monto": 16000.0})
        assert resp.status_code == 200
        assert resp.json()["monto"] == 16000.0

    def test_update_monto_preserves_old_value_in_historico(self, test_client, test_db):
        _seed_arancel(test_db)
        test_client.put("/api/aranceles/a1/monto", json={"monto": 16000.0})
        a = test_db.query(Arancel).filter(Arancel.id == "a1").first()
        # Old value saved into historico before the change
        assert a.historico == [
            {"monto": 15000.0, "vigenteDesde": "2025-01-01"}
        ]
        assert a.monto == 16000.0

    def test_update_monto_missing_field_returns_422(self, test_client, test_db):
        _seed_arancel(test_db)
        resp = test_client.put("/api/aranceles/a1/monto", json={})
        assert resp.status_code == 422

    def test_update_monto_nonexistent_returns_404(self, test_client):
        resp = test_client.put("/api/aranceles/doesnotexist/monto", json={"monto": 100.0})
        assert resp.status_code == 404


class TestUpdateArancel:
    """PUT /api/aranceles/{id} — full edit of an arancel."""

    def test_update_non_monto_fields_only(self, test_client, test_db):
        """Editing nombre/area/predio must NOT touch historico."""
        _seed_arancel(test_db)
        resp = test_client.put(
            "/api/aranceles/a1",
            json={"nombre": "Cuota Balseros Embalse XL", "predio": "Almafuerte"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["nombre"] == "Cuota Balseros Embalse XL"
        # No monto change -> historico untouched, vigenteDesde untouched
        assert body["historico"] == []
        assert body["vigenteDesde"] == "2025-01-01"
        assert body["monto"] == 15000.0

    def test_update_with_monto_preserves_historico(self, test_client, test_db):
        """Changing the monto pushes the old value to historico."""
        _seed_arancel(test_db)
        resp = test_client.put(
            "/api/aranceles/a1",
            json={"nombre": "Cuota Renombrada", "monto": 22000.0},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["nombre"] == "Cuota Renombrada"
        assert body["monto"] == 22000.0
        assert body["historico"] == [{"monto": 15000.0, "vigenteDesde": "2025-01-01"}]
        assert body["vigenteDesde"] == str(date.today())

    def test_update_nonexistent_returns_404(self, test_client):
        resp = test_client.put(
            "/api/aranceles/doesnotexist",
            json={"nombre": "X"},
        )
        assert resp.status_code == 404


class TestDeleteArancel:
    """DELETE /api/aranceles/{id} — remove an arancel."""

    def test_delete_returns_204_and_removes_row(self, test_client, test_db):
        _seed_arancel(test_db)
        resp = test_client.delete("/api/aranceles/a1")
        assert resp.status_code == 204
        assert test_db.query(Arancel).filter(Arancel.id == "a1").first() is None

    def test_delete_nonexistent_returns_404(self, test_client):
        resp = test_client.delete("/api/aranceles/doesnotexist")
        assert resp.status_code == 404


class TestDeleteGuarded:
    """ReQ-007: a referenced arancel is a 409 naming the blockers, never a 500.

    `pago_items.arancelId` is a real FK and would raise an IntegrityError; the
    pre-check turns that into a legible answer. `membresias.arancelId` is a soft
    reference the database does not protect at all, so it needs the guard twice
    as much (D5).
    """

    def test_delete_referenced_by_a_pago_item_returns_409(self, test_client, test_db):
        _seed_arancel(test_db)
        _seed_pago_item(test_db, "a1")
        resp = test_client.delete("/api/aranceles/a1")
        assert resp.status_code == 409
        assert "pago_items" in resp.json()["detail"]

    def test_delete_keeps_the_referenced_row(self, test_client, test_db):
        _seed_arancel(test_db)
        _seed_pago_item(test_db, "a1")
        test_client.delete("/api/aranceles/a1")
        assert test_db.query(Arancel).filter(Arancel.id == "a1").first() is not None

    def test_delete_referenced_by_a_membresia_returns_409(self, test_client, test_db):
        """No FK here: without the pre-check this delete would succeed silently."""
        _seed_arancel(test_db)
        _seed_membresia(test_db, "a1")
        resp = test_client.delete("/api/aranceles/a1")
        assert resp.status_code == 409
        assert "membresias" in resp.json()["detail"]

    def test_detail_carries_the_count_and_the_sample_ids(self, test_client, test_db):
        _seed_arancel(test_db)
        _seed_pago_item(test_db, "a1", item_ids=["pi1", "pi2"])
        _seed_membresia(test_db, "a1", membresia_ids=["m1"])
        resp = test_client.delete("/api/aranceles/a1")
        detail = resp.json()["detail"]
        assert "2 pago_items (pi1, pi2)" in detail
        assert "1 membresias (m1)" in detail

    def test_the_sample_is_capped_at_five_ids(self, test_client, test_db):
        """The count is exact; the sample is a prefix so the detail stays short."""
        _seed_arancel(test_db)
        _seed_pago_item(test_db, "a1", item_ids=[f"pi{i}" for i in range(1, 8)])
        resp = test_client.delete("/api/aranceles/a1")
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert "7 pago_items" in detail
        assert "pi1, pi2, pi3, pi4, pi5, ..." in detail
        assert "pi6" not in detail

    def test_an_unreferenced_arancel_still_deletes(self, test_client, test_db):
        """The guard must not turn every delete into a 409 (ReQ-007)."""
        _seed_arancel(test_db)
        _seed_arancel(test_db, arancel_id="a_other", nombre="Otro")
        _seed_pago_item(test_db, "a_other")
        resp = test_client.delete("/api/aranceles/a1")
        assert resp.status_code == 204
        assert test_db.query(Arancel).filter(Arancel.id == "a1").first() is None
        assert test_db.query(Arancel).filter(Arancel.id == "a_other").first() is not None

    def test_a_db_level_fk_violation_is_a_409_not_a_500(
        self, test_client, test_db, monkeypatch
    ):
        """D5 safety net: the pre-check is bypassed here, so the FK actually fires.

        This is the branch that catches a reference nobody guarded yet — the
        reason ReQ-007 says "never a 500" and not "the pre-check is complete".
        """
        _seed_arancel(test_db)
        _seed_pago_item(test_db, "a1")
        monkeypatch.setattr(
            "backend.routers.aranceles._motivo_bloqueo", lambda db, arancel_id: None
        )
        resp = test_client.delete("/api/aranceles/a1")
        assert resp.status_code == 409
        assert test_db.query(Arancel).filter(Arancel.id == "a1").first() is not None


class TestArancelAuditColumns:
    """Audit (D7): created_by on create, updated_by on update + /monto sub-update."""

    def test_create_sets_created_by(self, test_client, current_user_id):
        resp = test_client.post(
            "/api/aranceles",
            json={
                "id": "aAud",
                "nombre": "Cuota Audit",
                "area": "Cabañeros",
                "predio": "Almafuerte",
                "monto": 10000.0,
                "vigenteDesde": "2025-06-01",
                "historico": [],
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["createdBy"] == current_user_id
        assert body["updatedBy"] is None

    def test_update_sets_updated_by(self, test_client, test_db, current_user_id):
        _seed_arancel(test_db)
        resp = test_client.put("/api/aranceles/a1", json={"nombre": "Renombrado"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["updatedBy"] == current_user_id

    def test_update_monto_sets_updated_by(self, test_client, test_db, current_user_id):
        _seed_arancel(test_db)
        resp = test_client.put("/api/aranceles/a1/monto", json={"monto": 16000.0})
        assert resp.status_code == 200
        assert resp.json()["updatedBy"] == current_user_id

    def test_pre_feature_rows_are_null(self, test_client, test_db):
        """Arancel inserted outside the router serializes null audit ids."""
        _seed_arancel(test_db)
        resp = test_client.get("/api/aranceles/a1")
        assert resp.status_code == 200
        body = resp.json()
        assert body["createdBy"] is None
        assert body["updatedBy"] is None


class TestConceptoWritable:
    """`concepto` is a writable catalog dimension (ReQ-005, D4).

    The frontend has to know which row prices the cuota social and which one
    prices a servicio charge; exposing it was read-only (CBM-01) and left the
    admin unable to create the per-place SERVICIO rows the whole change is
    about. POST and PUT now accept it and share the same validation semantics.
    """

    def test_list_serves_the_concept_of_every_row(self, test_client, test_db):
        test_db.add_all(
            [
                Arancel(
                    id="a_area",
                    nombre="Cuota Balseros Embalse",
                    area=Area.BALSEROS,
                    predio=Predio.EMBALSE,
                    monto=130000.0,
                    vigenteDesde=date(2025, 1, 1),
                    historico=[],
                    concepto=ConceptoCobro.AREA,
                ),
                Arancel(
                    id="a_cuota",
                    nombre="Cuota social",
                    area=Area.BALSEROS,
                    predio=Predio.EMBALSE,
                    monto=12000.0,
                    vigenteDesde=date(2025, 1, 1),
                    historico=[],
                    concepto=ConceptoCobro.CUOTA_SOCIAL,
                ),
            ]
        )
        test_db.commit()

        resp = test_client.get("/api/aranceles")
        assert resp.status_code == 200
        by_id = {row["id"]: row for row in resp.json()}
        assert by_id["a_area"]["concepto"] == "area"
        assert by_id["a_cuota"]["concepto"] == "cuota social"

    def test_create_persists_a_client_supplied_concepto(self, test_client, test_db):
        """A POST can now create the per-place SERVICIO row the change needs."""
        resp = test_client.post(
            "/api/aranceles",
            json={
                "id": "a_serv_guarderia",
                "nombre": "Servicio (luz)",
                "area": "Guardería",
                "predio": "Almafuerte",
                "monto": 2500.0,
                "vigenteDesde": "2025-06-01",
                "historico": [],
                "concepto": "servicio",
            },
        )
        assert resp.status_code == 201
        assert resp.json()["concepto"] == "servicio"
        a = test_db.query(Arancel).filter(Arancel.id == "a_serv_guarderia").first()
        assert a.concepto == ConceptoCobro.SERVICIO

    def test_create_without_concepto_defaults_to_area(self, test_client, test_db):
        """Omitting `concepto` gets the same default as the column (D4)."""
        resp = test_client.post(
            "/api/aranceles",
            json={
                "id": "a_default",
                "nombre": "Amarre",
                "area": "Balseros",
                "predio": "Embalse",
                "monto": 18500.0,
                "vigenteDesde": "2025-06-01",
                "historico": [],
            },
        )
        assert resp.status_code == 201
        assert resp.json()["concepto"] == "area"
        a = test_db.query(Arancel).filter(Arancel.id == "a_default").first()
        assert a.concepto == ConceptoCobro.AREA

    def test_update_retags_the_concepto(self, test_client, test_db):
        """PUT writes `concepto` too: retagging must not need a second path."""
        _seed_arancel(test_db)
        resp = test_client.put(
            "/api/aranceles/a1", json={"concepto": "servicio"}
        )
        assert resp.status_code == 200
        assert resp.json()["concepto"] == "servicio"
        test_db.expire_all()
        a = test_db.query(Arancel).filter(Arancel.id == "a1").first()
        assert a.concepto == ConceptoCobro.SERVICIO

    def test_update_with_null_concepto_returns_422(self, test_client, test_db):
        """`concepto` is NOT NULL: an explicit null is a client bug (D4)."""
        _seed_arancel(test_db)
        resp = test_client.put("/api/aranceles/a1", json={"concepto": None})
        assert resp.status_code == 422
        test_db.expire_all()
        a = test_db.query(Arancel).filter(Arancel.id == "a1").first()
        assert a.concepto == ConceptoCobro.AREA


class TestDuplicateTuple:
    """ReQ-006: a repeated `(area, predio, categoria, concepto)` is a 409.

    No UNIQUE index can cover this tuple — a NULL `categoria` never collides —
    so the guard is the router's job (D1/D4).
    """

    def _body(self, **over):
        return {
            "nombre": "Servicio (luz)",
            "area": "Balseros",
            "predio": "Embalse",
            "monto": 5000.0,
            "vigenteDesde": "2025-06-01",
            "historico": [],
            "concepto": "servicio",
            **over,
        }

    def test_duplicate_post_returns_409(self, test_client):
        assert test_client.post("/api/aranceles", json=self._body()).status_code == 201
        assert test_client.post("/api/aranceles", json=self._body()).status_code == 409

    def test_duplicate_post_keeps_a_single_row(self, test_client, test_db):
        test_client.post("/api/aranceles", json=self._body())
        test_client.post("/api/aranceles", json=self._body())
        rows = test_db.query(Arancel).all()
        assert len(rows) == 1

    def test_duplicate_post_detail_names_the_existing_row(self, test_client):
        test_client.post("/api/aranceles", json=self._body(id="a_serv_balseros"))
        resp = test_client.post("/api/aranceles", json=self._body())
        assert resp.status_code == 409
        assert resp.json()["detail"] == (
            "Ya existe un arancel con area=Balseros, predio=Embalse, "
            "categoria=—, concepto=servicio (id=a_serv_balseros)"
        )

    def test_a_different_concepto_is_not_a_duplicate(self, test_client):
        """The same place can carry an AREA and a SERVICIO row."""
        assert test_client.post("/api/aranceles", json=self._body()).status_code == 201
        resp = test_client.post("/api/aranceles", json=self._body(concepto="area"))
        assert resp.status_code == 201

    def test_a_different_categoria_is_not_a_duplicate(self, test_client):
        """The same place can carry one row per parcela category."""
        assert test_client.post(
            "/api/aranceles", json=self._body(categoria="Chica")
        ).status_code == 201
        resp = test_client.post(
            "/api/aranceles", json=self._body(categoria="Grande")
        )
        assert resp.status_code == 201

    def test_a_different_predio_is_not_a_duplicate(self, test_client):
        assert test_client.post("/api/aranceles", json=self._body()).status_code == 201
        resp = test_client.post(
            "/api/aranceles", json=self._body(predio="Almafuerte")
        )
        assert resp.status_code == 201

    def test_put_onto_an_occupied_tuple_returns_409(self, test_client, test_db):
        test_db.add_all(
            [
                Arancel(
                    id="a_serv",
                    nombre="Servicio (luz)",
                    area=Area.BALSEROS,
                    predio=Predio.EMBALSE,
                    monto=5000.0,
                    vigenteDesde=date(2025, 1, 1),
                    historico=[],
                    concepto=ConceptoCobro.SERVICIO,
                ),
                Arancel(
                    id="a_cabanero",
                    nombre="Amarre",
                    area=Area.CABANEROS,
                    predio=Predio.ALMAFUERTE,
                    monto=18000.0,
                    vigenteDesde=date(2025, 1, 1),
                    historico=[],
                ),
            ]
        )
        test_db.commit()

        resp = test_client.put(
            "/api/aranceles/a_cabanero",
            json={"area": "Balseros", "predio": "Embalse", "concepto": "servicio"},
        )
        assert resp.status_code == 409
        assert "(id=a_serv)" in resp.json()["detail"]

    def test_a_rejected_put_persists_nothing(self, test_client, test_db):
        """The 409 is raised before any mutation, so the row keeps its tuple."""
        test_db.add_all(
            [
                Arancel(
                    id="a_serv",
                    nombre="Servicio (luz)",
                    area=Area.BALSEROS,
                    predio=Predio.EMBALSE,
                    monto=5000.0,
                    vigenteDesde=date(2025, 1, 1),
                    historico=[],
                    concepto=ConceptoCobro.SERVICIO,
                ),
                Arancel(
                    id="a_cabanero",
                    nombre="Amarre",
                    area=Area.CABANEROS,
                    predio=Predio.ALMAFUERTE,
                    monto=18000.0,
                    vigenteDesde=date(2025, 1, 1),
                    historico=[],
                ),
            ]
        )
        test_db.commit()

        resp = test_client.put(
            "/api/aranceles/a_cabanero",
            json={
                "nombre": "Renombrado",
                "area": "Balseros",
                "predio": "Embalse",
                "concepto": "servicio",
            },
        )
        assert resp.status_code == 409
        test_db.expire_all()
        row = test_db.query(Arancel).filter(Arancel.id == "a_cabanero").first()
        assert row.area == Area.CABANEROS
        assert row.predio == Predio.ALMAFUERTE
        assert row.concepto == ConceptoCobro.AREA
        assert row.nombre == "Amarre"

    def test_put_onto_its_own_tuple_returns_200(self, test_client, test_db):
        """Re-saving an arancel must not collide with itself (ReQ-006)."""
        _seed_arancel(test_db)
        resp = test_client.put(
            "/api/aranceles/a1", json={"nombre": "Renombrado", "monto": 16000.0}
        )
        assert resp.status_code == 200
        assert resp.json()["nombre"] == "Renombrado"

    def test_put_onto_its_own_concepto_returns_200(self, test_client, test_db):
        """Re-affirming the same concepto is not a change of tuple."""
        test_db.add(
            Arancel(
                id="a_serv",
                nombre="Servicio (luz)",
                area=Area.BALSEROS,
                predio=Predio.EMBALSE,
                monto=5000.0,
                vigenteDesde=date(2025, 1, 1),
                historico=[],
                concepto=ConceptoCobro.SERVICIO,
            )
        )
        test_db.commit()
        resp = test_client.put(
            "/api/aranceles/a_serv", json={"concepto": "servicio", "monto": 6000.0}
        )
        assert resp.status_code == 200
        assert resp.json()["monto"] == 6000.0
