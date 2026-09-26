"""Integration tests for /api/aranceles create + update-monto endpoints."""

from datetime import date

from backend.models.arancel import Arancel
from backend.models.enums import Area, ConceptoCobro, Predio


def _seed_arancel(db):
    """Insert a base arancel to update."""
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
    return arancel


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


class TestConceptoReadOnly:
    """GET /api/aranceles exposes the catalog `concepto` (CBM-01, PR 7).

    The frontend has to know which row prices the cuota social and which one
    prices a servicio charge. Exposing `concepto` is the only way to do that
    without string-matching the row name, and it must stay OUTPUT-ONLY: the
    concept is owned by the cobro service, never by a write endpoint.
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

    def test_create_ignores_a_client_supplied_concepto(self, test_client, test_db):
        """A POST must not be able to invent a catalog concept (CBM-01)."""
        resp = test_client.post(
            "/api/aranceles",
            json={
                "id": "a_injected",
                "nombre": "Inventado",
                "area": "Balseros",
                "predio": "Embalse",
                "monto": 1.0,
                "vigenteDesde": "2025-06-01",
                "historico": [],
                "concepto": "recargo",
            },
        )
        assert resp.status_code == 201
        a = test_db.query(Arancel).filter(Arancel.id == "a_injected").first()
        assert a.concepto == ConceptoCobro.AREA
        assert resp.json()["concepto"] == "area"
