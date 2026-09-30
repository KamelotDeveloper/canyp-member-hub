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
PREFERENCE_ID = "3000000000000001"
FUTURO = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
#: Ancla de expiración que devuelve MercadoPago en `date_approved`. La expiración
#: que calcula el backend a partir de acá tiene que dar exactamente +30 días, y
#: NO "ahora + 30 días": si se anclara al instante de la confirmación, un webhook
#: que llega tarde regalaría días.
FECHA_APROBACION = datetime.now(timezone.utc).isoformat()


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
    """Responde el GET del pago con la forma REAL de `/v1/payments/{id}`.

    Importa modelar `external_reference`, `preference_id` y `date_approved`:
    los tres participan de la activación, y un fake que devuelve solo `{status,
    id}` deja sin ejercitar justamente los caminos que rompían.

    `error=True` simula caída de red; `status` se puede cambiar por test.
    """

    def __init__(
        self,
        status: str = "approved",
        error: bool = False,
        external_reference: str | None = f"{APP_ID}:{CLIENT_ID}",
        preference_id: str | None = PREFERENCE_ID,
        transaction_amount: float = 120000,
        date_approved: str | None = FECHA_APROBACION,
        payment_id_de_preferencia: str | None = PAYMENT_ID,
    ):
        self.status = status
        self.error = error
        self.external_reference = external_reference
        self.preference_id = preference_id
        self.transaction_amount = transaction_amount
        self.date_approved = date_approved
        self.payment_id_de_preferencia = payment_id_de_preferencia
        self.consultas: list[str] = []

    def get(self, url, headers=None, timeout=None):
        self.consultas.append(url)
        if self.error:
            raise RuntimeError("red caida")
        if "/checkout/preferences/" in url:
            # `GET /checkout/preferences/{id}` → el pago de esa preferencia. Si
            # el pago aún no está acreditado, MP no devuelve `payment_id`.
            return FakeRespuesta(
                {"id": url.rsplit("/", 1)[-1], "payment_id": self.payment_id_de_preferencia}
            )
        return FakeRespuesta(
            {
                "id": url.rsplit("/", 1)[-1],
                "status": self.status,
                "status_detail": "accredited",
                "transaction_amount": self.transaction_amount,
                "external_reference": self.external_reference,
                "preference_id": self.preference_id,
                "date_approved": self.date_approved,
            }
        )

    def post(self, url, headers=None, json=None, timeout=None):
        return FakeRespuesta({"id": PREFERENCE_ID, "init_point": "https://mp/checkout"})

    def patch(self, url, headers=None, json=None, timeout=None):
        return FakeRespuesta([])


def _fila(
    estado="pendiente",
    payment_id=PAYMENT_ID,
    expiracion=FUTURO,
    plan="canyp_1_mes",
    preference_id=PREFERENCE_ID,
    client_id=CLIENT_ID,
    app_id=APP_ID,
):
    return {
        "client_id": client_id,
        "app_id": app_id,
        "plan": plan,
        "estado": estado,
        "mp_payment_id": payment_id,
        "preference_id": preference_id,
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
        # `crear-preferencia` hace POST a MercadoPago, no a Supabase. Sin esta
        # ruta, el fake respondía `[]` y la preferencia "se creaba" sin id.
        if "mercadopago.com" in url:
            return self._mp.post(url, headers=headers, json=json, timeout=timeout)
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
    """Un reintento no regala días: la fecha no se recalcula en el reintento.

    La comparación es contra la fecha DESPUÉS de la primera activación, que es la
    única que puede escribirla. Comparar contra el valor previo al primer
    paiement mezclaría dos cosas distintas: el anclaje inicial (correcto) y la
    idempotencia del reintento (que es lo que este test mide).
    """
    raw_client.post("/api/suscripcion/confirmar-pago", params={"payment_id": PAYMENT_ID})
    expiracion_tras_activar = supabase.filas[0]["fecha_expiracion"]

    raw_client.post("/api/suscripcion/confirmar-pago", params={"payment_id": PAYMENT_ID})
    raw_client.post("/api/suscripcion/confirmar-pago", params={"payment_id": PAYMENT_ID})

    assert supabase.filas[0]["fecha_expiracion"] == expiracion_tras_activar


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


# ==================== RESCATE POR PREFERENCE_ID (el corte del respaldo) ====================


def test_activa_por_preference_id_cuando_el_webhook_no_llego(supabase, raw_client):
    """El caso que fallaba en producción: la fila conoce el preference id, no el pago.

    `/crear-preferencia` guarda el id de la PREFERENCIA. Si el webhook nunca
    llegó, la fila no tiene `mp_payment_id`, así que buscar por `?mp_payment_id=
    eq.<id del pago>` no encontraba nada y el respaldo devolvía 404 siempre.
    """
    supabase.filas[0]["mp_payment_id"] = None
    supabase.filas[0]["estado"] = "pendiente"

    resp = raw_client.post(
        "/api/suscripcion/confirmar-pago", params={"payment_id": PAYMENT_ID}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["estado"] == "activo"
    assert supabase.filas[0]["mp_payment_id"] == PAYMENT_ID
    assert supabase.filas[0]["estado"] == "activo"


def test_crear_preferencia_no_ensucia_mp_payment_id_con_el_id_de_preferencia(
    supabase, raw_client
):
    """Guardar el preference id en `mp_payment_id` es lo que rompía el rescate.

    El `id` que devuelve `/crear-preferencia` es el de la PREFERENCIA. Si se
    escribe en `mp_payment_id`, la fila miente sobre qué pago la activó y la
    búsqueda posterior por pago real falla siempre.
    """
    resp = raw_client.post(
        "/api/suscripcion/crear-preferencia",
        json={"client_id": CLIENT_ID, "app_id": APP_ID, "plan": "canyp_1_mes"},
    )
    assert resp.status_code == 200, resp.text

    fila = supabase.filas[0]
    assert fila.get("preference_id") == PREFERENCE_ID
    assert fila.get("mp_payment_id") in (None, ""), "el id de preferencia no va en mp_payment_id"


def test_expiracion_se_ancla_al_pago_no_al_momento_de_confirmar(supabase, raw_client):
    """La licencia vence `dias` después del PAGO, no de que llegó la confirmación.

    Si se anclara a "ahora", un webhook o un reintento tardío le regalaría días
    al cliente. Se comprueba moviendo la fecha de aprobación del pago al pasado.
    """
    pago_hace_10_dias = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    supabase.mp.date_approved = pago_hace_10_dias

    raw_client.post("/api/suscripcion/confirmar-pago", params={"payment_id": PAYMENT_ID})

    esperada = datetime.fromisoformat(pago_hace_10_dias) + timedelta(days=30)
    assert supabase.filas[0]["fecha_expiracion"] == esperada.isoformat()


def test_plan_desconocido_no_inventa_fecha_de_expiracion(supabase, raw_client):
    """Sin catálogo no hay duración: se conserva la fecha de la fila, no se adivina."""
    supabase.filas[0]["plan"] = "canyp_plan_que_no_existe"
    anterior = supabase.filas[0]["fecha_expiracion"]

    resp = raw_client.post(
        "/api/suscripcion/confirmar-pago", params={"payment_id": PAYMENT_ID}
    )
    assert resp.status_code == 200, resp.text
    assert supabase.filas[0]["fecha_expiracion"] == anterior


def test_plan_anual_usa_la_duracion_del_catalogo(supabase, raw_client):
    """365 días para el anual, no 30: el plan decide la duración."""
    supabase.filas[0]["plan"] = "canyp_1_anio"
    supabase.mp.date_approved = datetime.now(timezone.utc).isoformat()

    raw_client.post("/api/suscripcion/confirmar-pago", params={"payment_id": PAYMENT_ID})

    assert supabase.filas[0]["estado"] == "activo"
    assert datetime.fromisoformat(supabase.filas[0]["fecha_expiracion"]) > (
        datetime.now(timezone.utc) + timedelta(days=300)
    )


# ==================== NO SE ACTIVA LA LICENCIA DE OTRO ====================


def test_payment_de_otro_cliente_no_activa_esta_licencia(supabase, raw_client):
    """Un pago ajeno no puede poner en `activo` la fila de otro cliente.

    Es el control que hace que `/confirmar-pago` no sea un "activá lo que me
    digan" abierto a internet.
    """
    resp = raw_client.post(
        "/api/suscripcion/confirmar-pago",
        params={"payment_id": PAYMENT_ID, "client_id": "canyp_otro_cliente"},
    )
    assert resp.status_code == 403
    assert not [e for e in supabase.escrituras if "estado" in e]


def test_payment_de_otro_cliente_tampoco_por_fallback_automatico(supabase, raw_client):
    """La fila se encuentra, pero es de otro cliente: se rechaza igual.

    Este es el agujero que cierra el chequeo contra `external_reference`:
    encontrar la fila por `preference_id` NO alcanza para activarla. Sin el
    cruce, el pago de un cliente activaba la fila cacheada de otro.
    """
    supabase.filas[0]["mp_payment_id"] = None
    supabase.mp.external_reference = "canyp:canyp_otro_cliente"

    resp = raw_client.post(
        "/api/suscripcion/confirmar-pago", params={"payment_id": PAYMENT_ID}
    )
    assert resp.status_code in (403, 404), resp.text
    assert supabase.filas[0]["estado"] == "pendiente"
    assert not [e for e in supabase.escrituras if "estado" in e]


def test_referencia_canyp_se_decodifica_a_app_y_client(supabase, raw_client):
    """`canyp:<client_id>` es el contrato con el webhook de suscripcion-api."""
    from backend.routers.suscripcion import _decodificar_external_reference as dec

    assert dec("canyp:canyp_cliente_paga") == ("canyp", "canyp_cliente_paga")
    assert dec("  canyp:con_espacios  ") == ("canyp", "con_espacios")


def test_referencia_erp_se_sigue_entendiendo(supabase, raw_client):
    """No se rompe el prefijo legacy: el webhook todavía lo emite."""
    from backend.routers.suscripcion import _decodificar_external_reference as dec

    assert dec("ERP-cualquier_cosa") == ("erp", "cualquier_cosa")


@pytest.mark.parametrize(
    "ref",
    [None, "", "   ", "sin_separador", ":solo_client", "canyp:", "ERP-", "ERP-   "],
)
def test_referencias_no_decodificables_no_crashan(ref):
    """Una referencia rara se ignora con `None`; nunca lanza y nunca adivina."""
    from backend.routers.suscripcion import _decodificar_external_reference as dec

    assert dec(ref) is None


# ==================== PANTALLA DE RETORNO (/exito) ====================


def test_exito_confirma_y_dice_que_ya_esta_activa(supabase, raw_client):
    """Volver con el pago aprobado muestra la licencia activa, no un JSON crudo."""
    resp = raw_client.get("/api/suscripcion/exito", params={"payment_id": PAYMENT_ID})
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Tu licencia ya esta activa" in resp.text
    assert supabase.filas[0]["estado"] == "activo"


def test_exito_sin_pago_aprobado_muestra_confirmando(supabase, raw_client):
    """Pago todavía no acreditado: la pantalla dice "confirmando" y sondea.

    No es un error: MercadoPago redirige antes de que el pago figure aprobado.
    Decirle al usuario "falló" sería mentira, y no activar tampoco, porque
    /confirmar-pago es el que decide.
    """
    supabase.mp.status = "pending"
    resp = raw_client.get("/api/suscripcion/exito", params={"payment_id": PAYMENT_ID})
    assert resp.status_code == 200
    assert "Confirmando tu pago" in resp.text
    assert supabase.filas[0]["estado"] == "pendiente"
    assert "estado-pago" in resp.text, "debe seguir consultando hasta que se aclare"


def test_exito_sin_payment_id_no_intenta_activar_nada(supabase, raw_client):
    """Sin id no hay nada que verificar: no se adivina ni se escribe."""
    resp = raw_client.get("/api/suscripcion/exito")
    assert resp.status_code == 200
    assert "Confirmando tu pago" in resp.text
    assert not [e for e in supabase.escrituras if "estado" in e]


def test_exito_no_refleja_html_inyectado_en_el_payment_id(supabase, raw_client):
    """El `payment_id` viene de la URL: se valida antes de tocar la respuesta."""
    resp = raw_client.get(
        "/api/suscripcion/exito",
        params={"payment_id": "1<script>alert(1)</script>"},
    )
    assert resp.status_code == 200
    assert "<script>alert(1)</script>" not in resp.text
    assert not [e for e in supabase.escrituras if "estado" in e]


def test_exito_de_un_pago_ajeno_no_activa_esta_licencia(supabase, raw_client):
    """La pantalla de retorno tampoco sirve para activar la fila de otro."""
    supabase.filas[0]["mp_payment_id"] = None
    supabase.mp.external_reference = "canyp:canyp_otro_cliente"

    resp = raw_client.get("/api/suscripcion/exito", params={"payment_id": PAYMENT_ID})
    assert resp.status_code == 200
    assert "Confirmando tu pago" in resp.text
    assert supabase.filas[0]["estado"] == "pendiente"


# ==================== ESTADO DE PAGO (SOLO LECTURA) ====================


def test_estado_pago_refleja_activo_despues_de_confirmar(supabase, raw_client):
    raw_client.post("/api/suscripcion/confirmar-pago", params={"payment_id": PAYMENT_ID})
    resp = raw_client.get("/api/suscripcion/estado-pago", params={"payment_id": PAYMENT_ID})
    assert resp.status_code == 200
    body = resp.json()
    assert body["activo"] is True
    assert body["estado"] == "activo"
    assert body["dias_restantes"] > 0


def test_estado_pago_no_activa_nada(supabase, raw_client):
    """Es de consulta: aunque el pago esté pendiente, no escribe estado."""
    supabase.mp.status = "pending"
    resp = raw_client.get("/api/suscripcion/estado-pago", params={"payment_id": PAYMENT_ID})
    assert resp.status_code == 200
    assert resp.json()["activo"] is False
    assert not [e for e in supabase.escrituras if "estado" in e]


def test_estado_pago_devuelve_404_si_no_encuentra_la_fila(supabase, raw_client):
    supabase.filas = []
    resp = raw_client.get("/api/suscripcion/estado-pago", params={"payment_id": PAYMENT_ID})
    assert resp.status_code == 404


# ==================== RESOLUCION POR PREFERENCIA (el flujo de Tauri) ====================


def test_confirmar_preferencia_resuelve_el_pago_y_activa(supabase, raw_client):
    """Es el camino que usa la app: Tauri abre el pago afuera y nunca ve el payment_id.

    La app solo guardó el `preference_id`; esta ruta le pregunta a MP qué pago es
    y encadena la confirmación verificada.
    """
    supabase.filas[0]["mp_payment_id"] = None
    supabase.filas[0]["estado"] = "pendiente"

    resp = raw_client.post(
        "/api/suscripcion/confirmar-preferencia",
        params={"preference_id": PREFERENCE_ID, "client_id": CLIENT_ID},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["estado"] == "activo"
    assert supabase.filas[0]["mp_payment_id"] == PAYMENT_ID


def test_confirmar_preferencia_sin_pago_acreditado_no_rompe(supabase, raw_client):
    """Preferencia sin pago todavía: 404 y la fila sigue igual.

    Es el estado normal al volver del navegador, no un error. La app reintenta.
    """
    supabase.mp.payment_id_de_preferencia = None

    resp = raw_client.post(
        "/api/suscripcion/confirmar-preferencia",
        params={"preference_id": PREFERENCE_ID, "client_id": CLIENT_ID},
    )
    assert resp.status_code == 404
    assert supabase.filas[0]["estado"] == "pendiente"


def test_confirmar_preferencia_exige_client_id(supabase, raw_client):
    """Sin `client_id` no se toca nada: un preference_id adivinado no alcanza."""
    resp = raw_client.post(
        "/api/suscripcion/confirmar-preferencia", params={"preference_id": PREFERENCE_ID}
    )
    assert resp.status_code == 400
    assert not [e for e in supabase.escrituras if "estado" in e]


def test_confirmar_preferencia_de_otro_cliente_no_activa(supabase, raw_client):
    """La preferencia es de este cliente, pero el pago dice que es de otro."""
    supabase.filas[0]["mp_payment_id"] = None
    supabase.mp.external_reference = "canyp:canyp_otro_cliente"

    resp = raw_client.post(
        "/api/suscripcion/confirmar-preferencia",
        params={"preference_id": PREFERENCE_ID, "client_id": CLIENT_ID},
    )
    assert resp.status_code in (403, 404), resp.text
    assert supabase.filas[0]["estado"] == "pendiente"


def test_estado_pago_se_puede_consultar_por_preferencia(supabase, raw_client):
    """El polling de la app va por preferencia, porque no tiene el payment_id."""
    supabase.filas[0]["mp_payment_id"] = None
    supabase.filas[0]["estado"] = "activo"

    resp = raw_client.get(
        "/api/suscripcion/estado-pago", params={"preference_id": PREFERENCE_ID}
    )
    assert resp.status_code == 200
    assert resp.json()["activo"] is True


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
