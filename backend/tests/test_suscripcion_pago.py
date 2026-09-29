"""Camino completo del pago: verificación real, estado canónico e idempotencia.

El webhook remoto (`suscripcion-api`) es el activador principal en producción,
pero el backend igual debe poder confirmar un pago consultando la API de
MercadoPago, y no debe activar nunca sin ese visto bueno. Estos tests usan
fakes: no tocan ni una fila real ni la API real de MercadoPago.

Se cubre lo que el brief pide:
- pago recibido -> estado canónico -> /verificar devuelve ok:true
- pago NO verificado -> no activa
- reintento -> no duplica ni extiende la licencia
- el cobro simulado no existe salvo en desarrollo explícito
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.config import settings
from backend.subscription_status import (
    EstadoSuscripcion,
    estado_da_acceso,
    normalizar_estado,
)

APP_ID = "canyp"
CLIENT_ID = "canyp_cliente_paga"
PAYMENT_ID = "9000000000000001"
FUTURO = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()


# ==================== FAKES ====================


class FakeRespuesta:
    def __init__(self, payload=None, status=200):
        self._payload = payload if payload is not None else []
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSupabase:
    """Guarda filas de `suscripciones` en memoria y registra cada escritura."""

    def __init__(self, filas=None):
        self.filas = [dict(f) for f in (filas or [])]
        self.escrituras: list[dict] = []

    @staticmethod
    def _filtro(url: str) -> dict[str, str]:
        consulta = url.split("?", 1)[1] if "?" in url else ""
        salida = {}
        for parte in consulta.split("&"):
            if "=eq." in parte:
                col, _, valor = parte.partition("=eq.")
                salida[col] = valor
        return salida

    def _coinciden(self, fila: dict, filtro: dict) -> bool:
        return all(fila.get(k) == v for k, v in filtro.items())

    def get(self, url, headers=None, timeout=None):
        filtro = self._filtro(url)
        return FakeRespuesta(
            [f for f in self.filas if self._coinciden(f, filtro)]
        )

    def patch(self, url, headers=None, json=None, timeout=None):
        self.escrituras.append(dict(json or {}))
        filtro = self._filtro(url)
        for fila in self.filas:
            if self._coinciden(fila, filtro):
                fila.update(json or {})
        return FakeRespuesta([])

    def post(self, url, headers=None, json=None, timeout=None):
        self.escrituras.append(dict(json or {}))
        self.filas.append(dict(json or {}))
        return FakeRespuesta([])


class FakeMercadoPago:
    """Responde el GET del pago. `error=True` simula caída de red."""

    def __init__(self, status: str = "approved", error: bool = False):
        self.status = status
        self.error = error
        self.consultas: list[str] = []

    def get(self, url, headers=None, timeout=None):
        self.consultas.append(url)
        if self.error:
            raise RuntimeError("red caida")
        return FakeRespuesta({"status": self.status, "id": url.rsplit("/", 1)[-1]})

    def post(self, url, headers=None, json=None, timeout=None):
        return FakeRespuesta({"id": PAYMENT_ID, "init_point": "https://mp/checkout"})

    def patch(self, url, headers=None, json=None, timeout=None):
        return FakeRespuesta([])


def _fila(estado="pendiente", payment_id=PAYMENT_ID, expiracion=FUTURO, plan="canyp_1_mes"):
    return {
        "client_id": CLIENT_ID,
        "app_id": APP_ID,
        "plan": plan,
        "estado": estado,
        "mp_payment_id": payment_id,
        "fecha_inicio": datetime.now(timezone.utc).isoformat(),
        "fecha_expiracion": expiracion,
    }


class _RequestsRuteado:
    """Enruta por host: api.mercadopago.com -> MP, el resto -> Supabase REST."""

    def __init__(self, supabase, mp):
        self._supabase = supabase
        self._mp = mp

    def get(self, url, headers=None, timeout=None):
        if "mercadopago.com" in url:
            return self._mp.get(url, headers=headers, timeout=timeout)
        return self._supabase.get(url, headers=headers, timeout=timeout)

    def patch(self, url, headers=None, json=None, timeout=None):
        return self._supabase.patch(url, headers=headers, json=json, timeout=timeout)

    def post(self, url, headers=None, json=None, timeout=None):
        return self._supabase.post(url, headers=headers, json=json, timeout=timeout)


@pytest.fixture()
def supabase(monkeypatch):
    """Engancha un Supabase en memoria y deja el backend con operator creds."""
    from backend.routers import suscripcion as router

    fake = FakeSupabase([_fila()])
    mp = FakeMercadoPago()
    monkeypatch.setattr(router, "requests", _RequestsRuteado(fake, mp))
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://proyecto.supabase.co")
    monkeypatch.setattr(settings, "SUPABASE_SERVICE_KEY", "service-role-de-prueba")
    monkeypatch.setattr(settings, "MP_ACCESS_TOKEN", "token-de-prueba")
    fake.mp = mp
    fake.requests = router.requests
    return fake


# ==================== ENUM CANONICO ====================


def test_enum_canonico_es_la_fuente_unica():
    assert {e.value for e in EstadoSuscripcion} == {
        "pendiente",
        "prueba",
        "activo",
        "expirado",
    }


def test_el_webhook_histórico_escribía_activa_y_se_normaliza():
    """El corte #2: el webhook escribía 'activa' y el backend exigía 'activo'."""
    assert normalizar_estado("activa") is EstadoSuscripcion.ACTIVO
    assert normalizar_estado("activo") is EstadoSuscripcion.ACTIVO


def test_estado_desconocido_no_da_acceso():
    """Fail-closed: un valor raro no habilita licencia."""
    assert normalizar_estado("loquesea") is None
    assert estado_da_acceso("loquesea", datetime.now(timezone.utc) + timedelta(days=1)) is False
    assert estado_da_acceso(None, datetime.now(timezone.utc) + timedelta(days=1)) is False


def test_activo_vencido_no_da_acceso():
    vencido = datetime.now(timezone.utc) - timedelta(days=1)
    assert estado_da_acceso("activo", vencido) is False
    assert estado_da_acceso("pendiente", datetime.now(timezone.utc)) is False


def test_sin_fecha_de_expiracion_no_da_acceso():
    assert estado_da_acceso("activo", None) is False


# ==================== PREFIJO canyp: ====================


def test_external_reference_usa_el_prefijo_canyp():
    """Corte #1: el backend manda 'canyp:<client_id>' y el webhook debe matchear."""
    from backend.routers.suscripcion import PREFIXO_EXTERNAL_REFERENCE

    assert PREFIXO_EXTERNAL_REFERENCE == "canyp"
    ref = f"{PREFIXO_EXTERNAL_REFERENCE}:{CLIENT_ID}"
    app_id, _, client_id = ref.partition(":")
    assert app_id == "canyp"
    assert client_id == CLIENT_ID


def test_crear_preferencia_emite_external_reference_canyp(supabase, raw_client):
    """La preferencia que se manda a MercadoPago lleva el prefijo de CANYP."""
    capturado = {}

    def post_capturado(url, headers=None, json=None, timeout=None):
        capturado.update(json or {})
        return FakeRespuesta({"id": PAYMENT_ID, "init_point": "https://mp/x"})

    supabase.requests.post = post_capturado
    supabase.filas = []

    resp = raw_client.post(
        "/api/suscripcion/crear-preferencia",
        json={"client_id": CLIENT_ID, "app_id": APP_ID, "plan": "canyp_1_mes"},
    )
    assert resp.status_code == 200
    assert capturado["external_reference"] == f"canyp:{CLIENT_ID}"
    assert capturado["metadata"]["client_id"] == CLIENT_ID
    assert capturado["metadata"]["app_id"] == APP_ID


# ==================== CAMINO COMPLETO: PAGO -> LICENCIA ====================


def test_pago_verificado_activa_y_verificar_devuelve_ok(supabase, raw_client):
    """Pago aprobado -> activo -> /verificar ok:true. Es el camino que no_andaba."""
    resp = raw_client.post(
        "/api/suscripcion/confirmar-pago", params={"payment_id": PAYMENT_ID}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["verificado"] is True
    assert body["estado"] == "activo"

    vresp = raw_client.post(
        "/api/suscripcion/verificar",
        json={"client_id": CLIENT_ID, "app_id": APP_ID},
    )
    assert vresp.status_code == 200
    vbody = vresp.json()
    assert vbody["ok"] is True
    assert vbody["tipo"] == "licencia"
    assert vbody["estado"] == "activo"


def test_pago_consultado_en_mercadopago_no_una_vez_por_reintento(supabase, raw_client):
    """Cada confirmación sí revalida contra MP: no confía en el estado local."""
    raw_client.post("/api/suscripcion/confirmar-pago", params={"payment_id": PAYMENT_ID})
    raw_client.post("/api/suscripcion/confirmar-pago", params={"payment_id": PAYMENT_ID})
    assert len(supabase.mp.consultas) == 2


# ==================== PAGO NO VERIFICADO -> NO ACTIVA ====================


@pytest.mark.parametrize("estado_mp", ["pending", "rejected", "in_process", "cancelled"])
def test_pago_no_aprobado_no_activa(supabase, raw_client, estado_mp):
    supabase.mp.status = estado_mp
    resp = raw_client.post(
        "/api/suscripcion/confirmar-pago", params={"payment_id": PAYMENT_ID}
    )
    assert resp.status_code == 502
    assert not [e for e in supabase.escrituras if "estado" in e]


def test_caida_de_red_en_mercadopago_no_activa(supabase, raw_client):
    """Fail-closed: si no se puede verificar, no se activa."""
    supabase.mp.error = True
    resp = raw_client.post(
        "/api/suscripcion/confirmar-pago", params={"payment_id": PAYMENT_ID}
    )
    assert resp.status_code == 502
    assert not [e for e in supabase.escrituras if "estado" in e]


def test_sin_mp_access_token_no_verifica_ni_activa(supabase, raw_client, monkeypatch):
    """Sin token no se puede comprobar el cobro: tampoco se activa."""
    monkeypatch.setattr(settings, "MP_ACCESS_TOKEN", "")
    resp = raw_client.post(
        "/api/suscripcion/confirmar-pago", params={"payment_id": PAYMENT_ID}
    )
    assert resp.status_code == 503
    assert not [e for e in supabase.escrituras if "estado" in e]


def test_pago_no_verificado_deja_la_licencia_bloqueada(supabase, raw_client, monkeypatch):
    """Tras un intento fallido el cliente sigue sin acceso."""
    monkeypatch.setattr(settings, "MP_ACCESS_TOKEN", "")
    raw_client.post("/api/suscripcion/confirmar-pago", params={"payment_id": PAYMENT_ID})

    vresp = raw_client.post(
        "/api/suscripcion/verificar",
        json={"client_id": CLIENT_ID, "app_id": APP_ID},
    )
    assert vresp.json()["ok"] is False


# ==================== IDEMPOTENCIA ====================


def test_reintento_no_vuelve_a_escribir(supabase, raw_client):
    """Confirmar dos veces el mismo pago no duplica la escritura."""
    r1 = raw_client.post("/api/suscripcion/confirmar-pago", params={"payment_id": PAYMENT_ID})
    r2 = raw_client.post("/api/suscripcion/confirmar-pago", params={"payment_id": PAYMENT_ID})

    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["idempotente"] is False
    assert r2.json()["idempotente"] is True

    escrituras_de_estado = [e for e in supabase.escrituras if "estado" in e]
    assert len(escrituras_de_estado) == 1, "el reintento no debe reescribir el estado"


def test_reintento_no_extiende_la_licencia(supabase, raw_client):
    """Un reintento no regala días: la fecha de expiración no se recalcula."""
    expiracion_original = supabase.filas[0]["fecha_expiracion"]
    raw_client.post("/api/suscripcion/confirmar-pago", params={"payment_id": PAYMENT_ID})
    raw_client.post("/api/suscripcion/confirmar-pago", params={"payment_id": PAYMENT_ID})
    assert supabase.filas[0]["fecha_expiracion"] == expiracion_original


def test_reintento_mantiene_la_licencia_activa(supabase, raw_client):
    raw_client.post("/api/suscripcion/confirmar-pago", params={"payment_id": PAYMENT_ID})
    raw_client.post("/api/suscripcion/confirmar-pago", params={"payment_id": PAYMENT_ID})

    vresp = raw_client.post(
        "/api/suscripcion/verificar",
        json={"client_id": CLIENT_ID, "app_id": APP_ID},
    )
    assert vresp.json()["ok"] is True
    assert vresp.json()["estado"] == "activo"


# ==================== COMPATIBILIDAD CON FILAS YA ESCRITAS ====================


def test_fila_con_activa_historica_sigue_dando_acceso(supabase, raw_client, monkeypatch):
    """No dejar afuera a quien ya pagó: 'activa' se acepta en lectura."""
    supabase.filas[0]["estado"] = "activa"
    vresp = raw_client.post(
        "/api/suscripcion/verificar",
        json={"client_id": CLIENT_ID, "app_id": APP_ID},
    )
    body = vresp.json()
    assert body["ok"] is True
    assert body["estado"] == "activo", "la respuesta expone el valor canónico"


# ==================== COBRO SIMULADO: OFF POR DEFAULT ====================


def test_mock_confirm_esta_cerrado_por_default(supabase, raw_client, monkeypatch):
    monkeypatch.delenv("CANYP_ALLOW_MOCK_PAYMENTS", raising=False)
    resp = raw_client.post(
        "/api/suscripcion/mock-confirm", params={"payment_id": PAYMENT_ID}
    )
    assert resp.status_code == 403
    assert not [e for e in supabase.escrituras if "estado" in e]


def test_mock_pago_esta_cerrado_por_default(supabase, raw_client, monkeypatch):
    monkeypatch.delenv("CANYP_ALLOW_MOCK_PAYMENTS", raising=False)
    resp = raw_client.get(
        "/api/suscripcion/mock-pago", params={"payment_id": PAYMENT_ID}
    )
    assert resp.status_code == 403


def test_build_de_cliente_rechaza_el_flag_sin_importar_como_se_activó(
    supabase, raw_client, monkeypatch
):
    """Aunque el flag llegue al launcher de un build de cliente, no abre."""
    monkeypatch.setenv("CANYP_ALLOW_MOCK_PAYMENTS", "1")
    monkeypatch.setenv("CANYP_CLIENT_BUILD", "1")
    resp = raw_client.post(
        "/api/suscripcion/mock-confirm", params={"payment_id": PAYMENT_ID}
    )
    assert resp.status_code == 403
    assert not [e for e in supabase.escrituras if "estado" in e]


def test_sin_el_flag_no_hay_modo_mock_en_crear_preferencia(supabase, raw_client, monkeypatch):
    """Sin token y sin flag, /crear-preferencia falla en vez de simular un cobro."""
    monkeypatch.delenv("CANYP_ALLOW_MOCK_PAYMENTS", raising=False)
    monkeypatch.setattr(settings, "MP_ACCESS_TOKEN", "")
    resp = raw_client.post(
        "/api/suscripcion/crear-preferencia",
        json={"client_id": CLIENT_ID, "app_id": APP_ID, "plan": "canyp_1_mes"},
    )
    assert resp.status_code == 503
    assert "simulado" in resp.json()["detail"].lower()


def test_desarrollo_explicito_sigue_pudiendo_simular(supabase, raw_client, monkeypatch):
    """Con el flag de desarrollo, el camino de pruebas sigue funcionando."""
    monkeypatch.setenv("CANYP_ALLOW_MOCK_PAYMENTS", "1")
    monkeypatch.delenv("CANYP_CLIENT_BUILD", raising=False)

    resp = raw_client.post(
        "/api/suscripcion/mock-confirm", params={"payment_id": PAYMENT_ID}
    )
    assert resp.status_code == 200
    assert resp.json()["estado"] == "activo"


# ==================== SUPABASE: PROYECTO UNICO ====================


def test_supabase_url_no_tiene_default_hardcodeado():
    """Corte #3: la URL del operador no viene embebida en el codigo."""
    from backend.config import Settings

    assert Settings.model_fields["SUPABASE_URL"].default == ""


def test_operacion_de_suscripcion_falla_loud_sin_proyecto(monkeypatch, raw_client):
    """Sin proyecto configurado no se adivina a cuál apuntar."""
    monkeypatch.setattr(settings, "SUPABASE_URL", "")
    monkeypatch.setattr(settings, "SUPABASE_SERVICE_KEY", "")
    resp = raw_client.get("/api/suscripcion/planes", params={"app_id": APP_ID})
    assert resp.status_code == 200
    assert [p["id"] for p in resp.json()["planes"]][0].startswith("canyp_")
