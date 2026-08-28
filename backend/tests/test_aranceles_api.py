"""Integration tests for /api/aranceles create + update-monto endpoints."""

from datetime import date

from backend.models.arancel import Arancel
from backend.models.enums import Area, Predio


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
