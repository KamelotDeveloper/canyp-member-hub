"""Tests del router de suscripciones: planes, trial local y verificación.

Todos corren 100% offline: se fuerza Supabase y MercadoPago como
desconfigurados, así los planes caen al catálogo local y la verificación
depende solo del trial en SQLite (in-memory vía conftest).
"""

from datetime import datetime, timedelta

import pytest

from backend.config import settings
from backend.models.licencia_trial import LicenciaTrial

APP_ID = "canyp"


@pytest.fixture()
def sin_supabase(monkeypatch):
    """Fuerza Supabase/MP desconfigurados para tests locales y offline."""
    monkeypatch.setattr(settings, "SUPABASE_SERVICE_KEY", "")
    monkeypatch.setattr(settings, "SUPABASE_ANON_KEY", "")
    monkeypatch.setattr(settings, "MP_ACCESS_TOKEN", "")


# ---------- Planes ----------


def test_planes_fallback_local(sin_supabase, raw_client):
    resp = raw_client.get("/api/suscripcion/planes", params={"app_id": APP_ID})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert [p["id"] for p in body["planes"]] == [
        "canyp_1_mes",
        "canyp_6_meses",
        "canyp_1_anio",
    ]
    assert body["prueba_gratis"]["dias"] == 7


def test_planes_default_canyp(sin_supabase, raw_client):
    resp = raw_client.get("/api/suscripcion/planes")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert resp.json()["planes"][0]["id"].startswith("canyp_")


def test_planes_rechaza_app_desconocida(sin_supabase, raw_client):
    resp = raw_client.get("/api/suscripcion/planes", params={"app_id": "ordo"})
    assert resp.status_code == 400


# ---------- Trial local ----------


def test_trial_se_crea_una_sola_vez(sin_supabase, raw_client, test_db):
    client_id = "canyp_111"
    r1 = raw_client.post(
        "/api/suscripcion/trial", json={"client_id": client_id, "app_id": APP_ID}
    )
    assert r1.status_code == 200
    b1 = r1.json()
    assert b1["ok"] is True and b1["tipo"] == "trial"
    assert b1["dias_restantes"] == 7

    r2 = raw_client.post(
        "/api/suscripcion/trial", json={"client_id": client_id, "app_id": APP_ID}
    )
    assert r2.status_code == 200
    assert r2.json()["ok"] is True

    assert test_db.query(LicenciaTrial).count() == 1


def test_verificar_trial_vigente(sin_supabase, raw_client):
    client_id = "canyp_trial_ok"
    raw_client.post("/api/suscripcion/trial", json={"client_id": client_id, "app_id": APP_ID})
    resp = raw_client.post(
        "/api/suscripcion/verificar", json={"client_id": client_id, "app_id": APP_ID}
    )
    assert resp.status_code == 200
    b = resp.json()
    assert b["ok"] is True and b["tipo"] == "trial" and b["activo"] is True


def test_verificar_sin_licencia(sin_supabase, raw_client):
    resp = raw_client.post(
        "/api/suscripcion/verificar",
        json={"client_id": "canyp_nuevo", "app_id": APP_ID},
    )
    assert resp.status_code == 200
    b = resp.json()
    assert b["ok"] is False and b["error"] == "sin_licencia"


def test_trial_expirado_no_se_recrea(sin_supabase, raw_client, test_db):
    client_id = "canyp_vencido"
    test_db.add(
        LicenciaTrial(
            client_id=client_id,
            app_id=APP_ID,
            fecha_inicio=datetime.utcnow() - timedelta(days=30),
            fecha_fin=datetime.utcnow() - timedelta(days=23),
            activo=True,
        )
    )
    test_db.commit()

    resp = raw_client.post(
        "/api/suscripcion/trial", json={"client_id": client_id, "app_id": APP_ID}
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is False and resp.json()["error"] == "trial_expirado"
    assert test_db.query(LicenciaTrial).count() == 1

    vresp = raw_client.post(
        "/api/suscripcion/verificar", json={"client_id": client_id, "app_id": APP_ID}
    )
    assert vresp.json()["ok"] is False and vresp.json()["error"] == "trial_expirado"


def test_verificar_pendiente_supabase_no_bloquea_trial_vigente(
    sin_supabase, raw_client, test_db, monkeypatch
):
    """Un pago 'pendiente' sin aprobar no cancela un trial local vigente."""
    from backend.routers import suscripcion as suscripcion_router

    client_id = "canyp_pendiente_con_trial"
    test_db.add(
        LicenciaTrial(
            client_id=client_id,
            app_id=APP_ID,
            fecha_inicio=datetime.utcnow() - timedelta(days=1),
            fecha_fin=datetime.utcnow() + timedelta(days=6),
            activo=True,
        )
    )
    test_db.commit()

    # Simula una fila Supabase quedada en 'pendiente' (pago nunca aprobado).
    monkeypatch.setattr(
        suscripcion_router,
        "_buscar_suscripcion_supabase",
        lambda client_id, app_id: {
            "estado": "pendiente",
            "fecha_expiracion": (datetime.utcnow() + timedelta(days=30)).isoformat(),
            "plan": "canyp_1_mes",
        },
    )

    resp = raw_client.post(
        "/api/suscripcion/verificar", json={"client_id": client_id, "app_id": APP_ID}
    )
    body = resp.json()
    assert resp.status_code == 200
    assert body["ok"] is True and body["tipo"] == "trial" and body["activo"] is True


def test_verificar_pendiente_sin_trial_bloquea(sin_supabase, raw_client, monkeypatch):
    """Sin trial vigente, un 'pendiente' sigue bloqueando el acceso (G2)."""
    from backend.routers import suscripcion as suscripcion_router

    monkeypatch.setattr(
        suscripcion_router,
        "_buscar_suscripcion_supabase",
        lambda client_id, app_id: {
            "estado": "pendiente",
            "fecha_expiracion": (datetime.utcnow() + timedelta(days=30)).isoformat(),
            "plan": "canyp_1_mes",
        },
    )

    resp = raw_client.post(
        "/api/suscripcion/verificar",
        json={"client_id": "canyp_pendiente_sin_trial", "app_id": APP_ID},
    )
    body = resp.json()
    assert body["ok"] is False and body["tipo"] == "licencia" and body["estado"] == "pendiente"


# ---------- Crear preferencia (validaciones previas a redes) ----------


def test_crear_preferencia_plan_invalido(sin_supabase, raw_client):
    resp = raw_client.post(
        "/api/suscripcion/crear-preferencia",
        json={"client_id": "c1", "app_id": APP_ID, "plan": "nada"},
    )
    assert resp.status_code == 400


def test_crear_preferencia_rechaza_dos_puntos(sin_supabase, raw_client):
    resp = raw_client.post(
        "/api/suscripcion/crear-preferencia",
        json={"client_id": "a:b", "app_id": APP_ID, "plan": "canyp_1_mes"},
    )
    assert resp.status_code == 400
    resp2 = raw_client.post(
        "/api/suscripcion/crear-preferencia",
        json={"client_id": "c1", "app_id": "a:b", "plan": "canyp_1_mes"},
    )
    assert resp2.status_code == 400


def test_crear_preferencia_app_desconocida(sin_supabase, raw_client):
    resp = raw_client.post(
        "/api/suscripcion/crear-preferencia",
        json={"client_id": "c1", "app_id": "ordo", "plan": "1_mes"},
    )
    assert resp.status_code == 400


# ---------- Callbacks MP ----------


def test_callback_mp(sin_supabase, raw_client):
    for path in ("/exito", "/fallo", "/pendiente"):
        resp = raw_client.get(f"/api/suscripcion{path}")
        assert resp.status_code == 200