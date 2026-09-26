"""Integration tests for /api/notificaciones endpoints."""

import re

from datetime import date

from backend.models.notificacion import Notificacion
from backend.models.socio import Socio

_UUID_HEX = re.compile(r"^n[0-9a-f]{32}$")


def _seed_socio(db, socio_id="s1"):
    socio = Socio(
        id=socio_id,
        nombre="Pedro Martínez",
        dni=f"2533344{socio_id[1:]}",
        fechaAlta=date(2024, 1, 1),
    )
    db.add(socio)
    db.commit()


class TestNotificacionCreate:
    def test_create_without_client_id_returns_generated_id(self, test_client, test_db):
        _seed_socio(test_db)
        resp = test_client.post(
            "/api/notificaciones",
            json={
                "socioId": "s1",
                "canal": "email",
                "fecha": "2025-07-01",
                "motivo": "Recordatorio de vencimiento",
                "mensaje": "Su membresía vence pronto.",
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert len(body) == 1
        assert _UUID_HEX.match(body[0]["id"])
        assert body[0]["socioId"] == "s1"
        stored = test_db.get(Notificacion, body[0]["id"])
        assert stored is not None

    def test_client_sent_id_is_ignored(self, test_client, test_db):
        _seed_socio(test_db)
        resp = test_client.post(
            "/api/notificaciones",
            json={
                "id": "ncliente-123",
                "socioId": "s1",
                "canal": "whatsapp",
                "fecha": "2025-07-01",
                "motivo": "Mensaje",
                "mensaje": "Hola.",
            },
        )
        assert resp.status_code == 201
        body = resp.json()[0]
        assert body["id"] != "ncliente-123"
        assert _UUID_HEX.match(body["id"])
        assert test_db.get(Notificacion, "ncliente-123") is None

    def test_bulk_create_without_ids_returns_generated_ids(self, test_client, test_db):
        for sid in ("s1", "s2"):
            _seed_socio(test_db, sid)
        resp = test_client.post(
            "/api/notificaciones",
            json=[
                {
                    "socioId": "s1",
                    "canal": "email",
                    "fecha": "2025-07-01",
                    "motivo": "A",
                    "mensaje": "Uno",
                },
                {
                    "socioId": "s2",
                    "canal": "whatsapp",
                    "fecha": "2025-07-01",
                    "motivo": "B",
                    "mensaje": "Dos",
                },
            ],
        )
        assert resp.status_code == 201
        assert len(resp.json()) == 2
        assert len({n["id"] for n in resp.json()}) == 2
        assert all(_UUID_HEX.match(n["id"]) for n in resp.json())


class TestNotificacionList:
    def test_list_filters_by_socio(self, test_client, test_db):
        _seed_socio(test_db)
        test_client.post(
            "/api/notificaciones",
            json=[
                {
                    "socioId": "s1",
                    "canal": "email",
                    "fecha": "2025-07-01",
                    "motivo": "A",
                    "mensaje": "Uno",
                }
            ],
        )
        resp = test_client.get("/api/notificaciones", params={"socioId": "s1"})
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        resp_other = test_client.get("/api/notificaciones", params={"socioId": "nobody"})
        assert resp_other.status_code == 200
        assert resp_other.json() == []