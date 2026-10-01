"""Suscripciones CANYP — MercadoPago Checkout Pro + licencia Supabase.

Espeja el contrato de negocio de Ordo-ERP (router `/api/suscripcion`), adaptado
al stack CANYP:

- app_id CANYP = "canyp". external_reference = "canyp:<client_id>" (los valores
  nunca llevan ':' porque el webhook remoto hace split por el primer ':').
- Planes: se leen de Supabase (tabla planes_suscripcion, filtrada por app_id)
  con fallback al catálogo local (backend/pricing.py).
- Preferencia: POST a MercadoPago Checkout Pro con el token de producción.
- Licencia: GET de filas en la tabla `suscripciones` de Supabase
  (estado activo/prueba + fecha_expiracion futura). Sin Supabase o con error,
  el trial local (SQLite, 7 días, una vez por client_id) es el fallback.
- El webhook remoto (https://suscripcion-api.vercel.app/api/webhook) es quien
  activa la suscripción en Supabase al aprobarse el pago.

Los estados de `suscripciones.estado` NO se escriben como literales sueltos acá:
usan el enum canónico de backend/subscription_status.py, que es el mismo
vocabulario que el webhook remoto debe escribir. `activa` (femenino) queda
solo como sinónimo de lectura, para no dejar afuera a quien ya pagó.

El cobro simulado (/mock-pago, /mock-confirm) no activa nada salvo que se
habilite explícitamente en desarrollo (backend/dev_flags.py): en producción la
activación pasa por verificar el pago contra la API de MercadoPago y falla
cerrado si no se puede confirmar.

Los endpoints son OPEN (pre-login): la verificación de licencia y el pago
ocurren antes de que exista usuario en CANYP.
"""

import json
import re

import requests
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database import get_db
from backend.dev_flags import (
    es_build_cliente,
    mock_pagos_habilitados,
    motivo_mock_pagos_deshabilitado,
)
from backend.models.licencia_trial import LicenciaTrial, TRIAL_DAYS, fecha_fin_trial
from backend.pricing import KNOWN_APPS, PLANES_FALLBACK, get_planes_for_app
from backend.subscription_status import (
    EstadoSuscripcion,
    estado_da_acceso,
    normalizar_estado,
)

router = APIRouter(prefix="/api/suscripcion", tags=["suscripcion"])

APP_ID_DEFAULT = "canyp"

# Prefijo de CANYP en external_reference. El webhook remoto debe reconocerlo
# además del flujo `ERP-` histórico de Ordo-ERP.
PREFIXO_EXTERNAL_REFERENCE = APP_ID_DEFAULT

# API de MercadoPago para consultar el estado real de un pago.
MP_API_PAGOS = "https://api.mercadopago.com/v1/payments"
# La preferencia expone el `payment_id`: es el puente entre "la app solo tiene la
# preferencia" y "hay que verificar un pago concreto".
MP_API_PREFERENCIAS = "https://api.mercadopago.com/checkout/preferences"

# ==================== SCHEMAS ====================


class CrearPreferenciaRequest(BaseModel):
    client_id: str
    app_id: str = APP_ID_DEFAULT
    email: str | None = None  # Opcional: Checkout Pro no lo exige
    plan: str
    codigo_descuento: str | None = None


class VerificarRequest(BaseModel):
    client_id: str
    app_id: str = APP_ID_DEFAULT


class TrialRequest(BaseModel):
    client_id: str
    app_id: str = APP_ID_DEFAULT


class CodigoDescuentoRequest(BaseModel):
    codigo: str
    plan: str | None = None


# ==================== HELPERS SUPABASE ====================


def supabase_configured() -> bool:
    """True si hay URL + service key para hablar con Supabase REST."""
    return bool(
        settings.SUPABASE_URL and settings.SUPABASE_SERVICE_KEY
    )


def get_supabase_headers() -> dict:
    """Headers para Supabase REST API con Service Role Key."""
    if not supabase_configured():
        raise HTTPException(status_code=500, detail="Supabase no configurado")
    return {
        "apikey": settings.SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def get_supabase_url() -> str:
    """URL base de Supabase (sin slash final)."""
    if not settings.SUPABASE_URL:
        raise HTTPException(status_code=500, detail="SUPABASE_URL no configurado")
    return settings.SUPABASE_URL.rstrip("/")


# ==================== PLANES ====================

PRUEBA_GRATIS = {
    "id": "prueba",
    "nombre": "Prueba Gratis",
    "descripcion": "7 dias de acceso completo gratis",
    "precio": 0,
    "dias": TRIAL_DAYS,
}


def get_planes_from_supabase(app_id: str = APP_ID_DEFAULT) -> list:
    """Planes desde Supabase (remoto y modificable) o fallback local.

    app_id desconocido -> 400 (fail-loud, nunca default a otra app).
    Sin service key o con error de red -> catálogo local de la app.
    """
    if app_id not in KNOWN_APPS:
        raise HTTPException(status_code=400, detail=f"app_id invalido: {app_id}")

    if supabase_configured():
        try:
            url = (
                f"{get_supabase_url()}/rest/v1/planes_suscripcion"
                f"?select=*&activo=eq.true&app_id=eq.{app_id}"
            )
            resp = requests.get(url, headers=get_supabase_headers(), timeout=5)
            resp.raise_for_status()
            planes_supabase = resp.json()
            if planes_supabase:
                return [
                    {
                        "id": p["id"],
                        "nombre": p["nombre"],
                        "descripcion": p["descripcion"],
                        "precio": p["precio"],
                        "dias": p["dias"],
                    }
                    for p in planes_supabase
                ]
        except Exception as e:  # noqa: BLE001 - fallback local ante cualquier falla
            print(f"Error leyendo planes de Supabase: {e}")

    return get_planes_for_app(app_id)


@router.get("/planes")
def obtener_planes(app_id: str = APP_ID_DEFAULT):
    """Planes disponibles (Supabase o fallback local) para la app indicada."""
    planes = get_planes_from_supabase(app_id)
    return {"ok": True, "planes": planes, "prueba_gratis": PRUEBA_GRATIS}


# ==================== CREAR PREFERENCIA (CHECKOUT) ====================


@router.post("/crear-preferencia")
def crear_preferencia(data: CrearPreferenciaRequest):
    """Crea/actualiza la suscripcion en Supabase y genera el link de MP.

    Fase 1: si no hay MP_ACCESS_TOKEN devuelve mock con payment_url local.
    El estado 'pendiente' nunca es activo: solo el webhook real lo pasa a
    'activo' tras validar monto y plan (G2).
    """
    planes = get_planes_from_supabase(data.app_id)
    plan_info = next((p for p in planes if p["id"] == data.plan), None)
    if not plan_info:
        raise HTTPException(status_code=400, detail="Plan invalido")

    # Contrato: external_reference = `${app_id}:${client_id}`. Los valores no
    # pueden contener ':' porque el webhook hace split por el primer ':'.
    if ":" in data.client_id or ":" in data.app_id:
        raise HTTPException(
            status_code=400, detail="app_id y client_id no pueden contener ':'"
        )

    fecha_expiracion = datetime.utcnow() + timedelta(days=plan_info["dias"])

    precio_final = plan_info["precio"]
    if data.codigo_descuento:
        codigo_info = validar_codigo_supabase(data.codigo_descuento, data.plan)
        if not codigo_info:
            raise HTTPException(
                status_code=400, detail="Codigo invalido, expirado o sin usos disponibles"
            )
        descuento = int(precio_final * codigo_info["descuento_porcentaje"] / 100)
        precio_final = precio_final - descuento

    supabase_url = get_supabase_url()
    headers = get_supabase_headers()

    check_url = (
        f"{supabase_url}/rest/v1/suscripciones"
        f"?client_id=eq.{data.client_id}&app_id=eq.{data.app_id}"
    )
    try:
        check_resp = requests.get(check_url, headers=headers, timeout=10)
        check_resp.raise_for_status()
        existentes = check_resp.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error consultando Supabase: {str(e)}")

    suscripcion_data = {
        "client_id": data.client_id,
        "app_id": data.app_id,
        "email": data.email,
        "plan": data.plan,
        # G2 lifecycle: paid -> 'pendiente' (only approved payment flips to
        # 'activo'); gratis (0 o 100% descuento) mantiene 'prueba'.
        "estado": (
            EstadoSuscripcion.PRUEBA.value
            if precio_final == 0
            else EstadoSuscripcion.PENDIENTE.value
        ),
        "fecha_inicio": datetime.utcnow().isoformat(),
        "fecha_expiracion": fecha_expiracion.isoformat(),
        "mp_payment_id": None,
    }

    try:
        if existentes:
            update_url = (
                f"{supabase_url}/rest/v1/suscripciones"
                f"?client_id=eq.{data.client_id}&app_id=eq.{data.app_id}"
            )
            resp = requests.patch(update_url, headers=headers, json=suscripcion_data, timeout=10)
        else:
            create_url = f"{supabase_url}/rest/v1/suscripciones"
            resp = requests.post(create_url, headers=headers, json=suscripcion_data, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error guardando en Supabase: {str(e)}")

    if precio_final == 0:
        if data.codigo_descuento:
            consumir_codigo_descuento(data.codigo_descuento, data.plan, data.client_id)
        return {
            "success": True,
            "message": "Suscripcion gratuita activada",
            "suscripcion": suscripcion_data,
            "payment_url": None,
            "modo": "gratis",
        }

    # Sin MP_ACCESS_TOKEN antes se caía a un "modo simulado" que devolvía una
    # payment_url local y dejaba activating licencias sin cobrar. Ahora eso solo
    # existe en desarrollo explícito; en cualquier otro caso se falla loudly
    # (fail-closed) en vez de invitar al usuario a un pago que nunca ocurre.
    if not settings.MP_ACCESS_TOKEN:
        if not mock_pagos_habilitados():
            raise HTTPException(
                status_code=503,
                detail=(
                    "MercadoPago no esta configurado (falta MP_ACCESS_TOKEN) y el "
                    "cobro simulado esta deshabilitado. "
                    + motivo_mock_pagos_deshabilitado()
                ),
            )
        mock_payment_id = f"mock_{data.client_id}_{datetime.utcnow().timestamp()}"
        update_url = (
            f"{supabase_url}/rest/v1/suscripciones"
            f"?client_id=eq.{data.client_id}&app_id=eq.{data.app_id}"
        )
        requests.patch(
            update_url, headers=headers, json={"mp_payment_id": mock_payment_id}, timeout=10
        )
        payment_url = (
            f"{settings.mp_base_url}/api/suscripcion/mock-pago?payment_id={mock_payment_id}"
        )
        return {
            "success": True,
            "message": "Modo simulado (sin MP_ACCESS_TOKEN)",
            "payment_id": mock_payment_id,
            "payment_url": payment_url,
            "init_point": payment_url,
            "modo": "mock",
            "suscripcion": suscripcion_data,
        }

    mp_url = "https://api.mercadopago.com/checkout/preferences"
    mp_headers = {
        "Authorization": f"Bearer {settings.MP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    preference_data = {
        "items": [
            {
                "title": f"Suscripcion CANYP - {plan_info['nombre']}",
                "quantity": 1,
                "currency_id": "ARS",
                "unit_price": float(precio_final),
            }
        ],
        "back_urls": {
            "success": settings.mp_success_url,
            "failure": settings.mp_failure_url,
            "pending": settings.mp_pending_url,
        },
        "external_reference": f"{data.app_id}:{data.client_id}",
        "notification_url": settings.MP_NOTIFICATION_URL,
        # G1 contract: metadata permite al webhook resolver el plan correcto.
        "metadata": {
            "app_id": data.app_id,
            "client_id": data.client_id,
            "plan": data.plan,
            "email": data.email,
        },
    }
    if data.email:
        preference_data["payer"] = {"email": data.email}

    try:
        mp_resp = requests.post(mp_url, headers=mp_headers, json=preference_data, timeout=30)
        mp_resp.raise_for_status()
        mp_data = mp_resp.json()

        if data.codigo_descuento:
            consumir_codigo_descuento(data.codigo_descuento, data.plan, data.client_id)

        update_url = (
            f"{supabase_url}/rest/v1/suscripciones"
            f"?client_id=eq.{data.client_id}&app_id=eq.{data.app_id}"
        )
        _guardar_preference_id(update_url, headers, mp_data.get("id"))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generando preferencia MP: {str(e)}")

    return {
        "success": True,
        "preference_id": mp_data.get("id"),
        "payment_url": mp_data.get("init_point"),
        "init_point": mp_data.get("init_point"),
        "modo": "real",
        "suscripcion": suscripcion_data,
    }


# ==================== VERIFICAR SUSCRIPCION ====================


def _parse_iso(value: str) -> datetime:
    """ISO 8601 -> datetime UTC aware ('Z' y '+00:00' se normalizan)."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _buscar_suscripcion_supabase(client_id: str, app_id: str) -> dict | None:
    """Primera fila de `suscripciones` para (client_id, app_id), o None.

    Sin Supabase configurado (o ante error de red) devuelve None para que el
    trial local decida — nunca un 500 (local-first, como Ordo `/iniciar-sesion`).
    """
    if not supabase_configured():
        return None
    try:
        url = (
            f"{get_supabase_url()}/rest/v1/suscripciones"
            f"?client_id=eq.{client_id}&app_id=eq.{app_id}&select=*"
        )
        resp = requests.get(url, headers=get_supabase_headers(), timeout=10)
        resp.raise_for_status()
        rows = resp.json()
        return rows[0] if rows else None
    except Exception as e:  # noqa: BLE001 - degradar a trial local, nunca bloquear
        print(f"Error consultando suscripcion en Supabase: {e}")
        return None


def _marcar_expirada_supabase(client_id: str, app_id: str) -> None:
    """Actualiza a 'expirado' (idempotente) sin romper la verificación."""
    if not supabase_configured():
        return
    try:
        url = (
            f"{get_supabase_url()}/rest/v1/suscripciones"
            f"?client_id=eq.{client_id}&app_id=eq.{app_id}"
        )
        requests.patch(
            url,
            headers=get_supabase_headers(),
            json={"estado": EstadoSuscripcion.EXPIRADO.value},
            timeout=10,
        )
    except Exception:  # noqa: BLE001 - best effort
        pass


def _exigir_trial_habilitado() -> None:
    """Corta con 403 la activator local del trial en un build de cliente.

    Es la contraparte de lectura de :func:`_exigir_mock_habilitado`, y por el
    mismo motivo: el trial es estado que el cliente posee. Ambas cosas
    (simular el cobro, concederse el trial) tienen sentido en una máquina de
    desarrollo y son un agujero en la máquina de un cliente.
    """
    if not es_build_cliente():
        return
    from backend.activation import registrar_intento

    registrar_intento("trial_local_en_build_cliente", "POST /api/suscripcion/trial")
    raise HTTPException(
        status_code=403,
        detail=(
            "El periodo de prueba local no existe en un build de cliente: se "
            "reservaba contra la base de datos de la maquina, que cualquiera "
            "puede borrar y volver a pedir."
        ),
    )


def _trial_local_disponible() -> bool:
    """False en builds de cliente: el veredicto de licencia no puede ser local.

    Esta es la pieza que hace que la licencia no sea un dato del cliente. En un
    build de cliente las credenciales de operador NO están (ver
    ``backend/operator_credentials.py``: una ``service_role`` dentro del binario
    saltaría todas las RLS), así que la fila de Supabase no se puede leer y el
    sistema caía al trial local. Ese fallback era una licencia local, editable a
    mano. Acá, "no se pudo verificar" es "no hay licencia": se falla cerrado.
    """
    return not es_build_cliente()


def _sin_licencia_por_falta_de_registro() -> dict:
    """Respuesta de ``sin_licencia`` para un build de cliente sin registro.

    Distinta del ``sin_licencia`` de desarrollo a propósito: el motivo es que
    no hay fila en el registro del operador, no que nunca se compró nada. La UI
    no debería prometer un trial que este build no puede conceder.
    """
    return {
        "ok": False,
        "activo": False,
        "tipo": "ninguno",
        "estado": None,
        "error": "licencia_no_verificable",
        "mensaje": (
            "No hay licencia registrada para este equipo por el administrador. "
            "Comuníquese con el administrador para habilitarla."
        ),
    }


def _trial_vigente(
    db: Session, client_id: str, app_id: str
) -> dict | None:
    """Trial local activo y no vencido para (client_id, app_id), o None."""
    if not _trial_local_disponible():
        return None
    trial = (
        db.query(LicenciaTrial)
        .filter(
            LicenciaTrial.client_id == client_id,
            LicenciaTrial.app_id == app_id,
        )
        .first()
    )
    if not trial or not trial.activo:
        return None
    ahora = datetime.utcnow()
    if trial.fecha_fin <= ahora:
        return None
    return {
        "ok": True,
        "activo": True,
        "tipo": "trial",
        "estado": "trial",
        "fecha_fin": trial.fecha_fin.isoformat(),
        "dias_restantes": (trial.fecha_fin - ahora).days,
    }


@router.post("/verificar")
def verificar_suscripcion(data: VerificarRequest, db: Session = Depends(get_db)):
    """Chequea la licencia (Supabase) y, si no la hay, el trial local.

    - Suscripcion activa/prueba vigente     -> ok True (tipo licencia)
    - Suscripcion pendiente                 -> ok False (pago sin aprobar, G2)
      PERO un trial local vigente sigue dando acceso: el cliente puede usar
      sus 7 días de prueba mientras el webhook no confirma el pago.
    - Suscripcion vencida                   -> ok False (y marca 'expirado')
    - Trial local vigente                   -> ok True (tipo trial)
    - Sin nada                              -> ok False (sin_licencia)
    """
    sub = _buscar_suscripcion_supabase(data.client_id, data.app_id)

    if sub:
        estado_bruto = sub.get("estado")
        estado = normalizar_estado(estado_bruto)
        try:
            exp = _parse_iso(sub["fecha_expiracion"])
        except (KeyError, ValueError):
            exp = None

        # Un estado desconocido (o el sinónimo heredado 'activa' sin fecha
        # válida) NO da acceso: antes sólo se comparaba contra una tupla
        # literal y cualquier otra cosa caía en la rama de "expirada".
        if estado_da_acceso(estado_bruto, exp) and estado is not None:
            dias_restantes = (exp - datetime.now(timezone.utc)).days
            return {
                "ok": True,
                "activo": True,
                "tipo": "licencia",
                "estado": estado.value,
                "plan": sub.get("plan"),
                "fecha_expiracion": sub.get("fecha_expiracion"),
                "dias_restantes": dias_restantes,
            }

        if estado is EstadoSuscripcion.PENDIENTE:
            # Pago iniciado pero jamás aprobado: no consume el trial local.
            trial = _trial_vigente(db, data.client_id, data.app_id)
            if trial:
                return trial
            return {
                "ok": False,
                "activo": False,
                "tipo": "licencia",
                "estado": estado.value,
                "mensaje": "Pago pendiente de aprobación",
            }

        _marcar_expirada_supabase(data.client_id, data.app_id)
        return {
            "ok": False,
            "activo": False,
            "tipo": "licencia",
            "estado": EstadoSuscripcion.EXPIRADO.value,
            "error": "licencia_expirada",
            "mensaje": "La licencia ha expirado",
        }

    trial = _trial_vigente(db, data.client_id, data.app_id)
    if trial:
        return trial

    # Build de cliente: sin fila en el registro del operador no hay licencia.
    # Se corta acá ANTES de mirar la tabla de trials, que en esta máquina es un
    # archivo que el cliente puede editar o borrar para volver a "empezar".
    if not _trial_local_disponible():
        return _sin_licencia_por_falta_de_registro()

    trial_row = (
        db.query(LicenciaTrial)
        .filter(
            LicenciaTrial.client_id == data.client_id,
            LicenciaTrial.app_id == data.app_id,
        )
        .first()
    )
    if trial_row:
        # La fila existió (activada o ya desactivada): el trial está agotado.
        if trial_row.activo:
            trial_row.activo = False
            db.commit()
        return {
            "ok": False,
            "activo": False,
            "tipo": "trial",
            "estado": "expirado",
            "error": "trial_expirado",
            "mensaje": "El periodo de prueba ha finalizado",
        }

    return {
        "ok": False,
        "activo": False,
        "tipo": "ninguno",
        "estado": None,
        "error": "sin_licencia",
        "mensaje": "No hay licencia ni trial activo",
    }


# ==================== TRIAL LOCAL ====================


@router.post("/trial")
def activar_trial(data: TrialRequest, db: Session = Depends(get_db)):
    """Activa el trial local de 7 días, una sola vez por (client_id, app_id).

    Idempotente: si el trial sigue vigente devuelve su estado; si expiró
    devuelve ok=False (trial_expirado) y jamás crea otro.

    En un build de cliente devuelve 403 y no escribe nada. El trial local vive
    en la base SQLite del equipo: sin esto, "borrar la base y volver a pedir
    el trial" era un bypass sin conexión y sin límite, porque la fila que lo
    controla la guarda el cliente, no el operador. Fuera de un build de cliente
    el comportamiento no cambia.
    """
    _exigir_trial_habilitado()

    trial = (
        db.query(LicenciaTrial)
        .filter(
            LicenciaTrial.client_id == data.client_id,
            LicenciaTrial.app_id == data.app_id,
        )
        .first()
    )

    if trial:
        ahora = datetime.utcnow()
        if trial.activo and trial.fecha_fin > ahora:
            return {
                "ok": True,
                "tipo": "trial",
                "dias_restantes": (trial.fecha_fin - ahora).days,
                "fecha_fin": trial.fecha_fin.isoformat(),
            }
        if trial.activo:
            trial.activo = False
            db.commit()
        return {
            "ok": False,
            "error": "trial_expirado",
            "mensaje": "El periodo de prueba ya fue utilizado",
        }

    ahora = datetime.utcnow()
    nuevo = LicenciaTrial(
        client_id=data.client_id,
        app_id=data.app_id,
        fecha_inicio=ahora,
        fecha_fin=fecha_fin_trial(ahora),
        activo=True,
    )
    db.add(nuevo)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="El trial ya fue activado para este equipo")

    return {
        "ok": True,
        "tipo": "trial",
        "dias_restantes": TRIAL_DAYS,
        "fecha_fin": nuevo.fecha_fin.isoformat(),
    }


# ==================== CODIGO DE DESCUENTO ====================


@router.post("/codigo-descuento")
def validar_codigo(data: CodigoDescuentoRequest):
    """Valida un codigo de descuento en Supabase."""
    resultado = validar_codigo_supabase(data.codigo, data.plan)
    if not resultado:
        raise HTTPException(
            status_code=400, detail="Codigo invalido, expirado o sin usos disponibles"
        )
    return {
        "valido": True,
        "codigo": resultado["codigo"],
        "descuento_porcentaje": resultado["descuento_porcentaje"],
        "plan_objetivo": resultado["plan_objetivo"],
    }


def validar_codigo_supabase(codigo: str, plan: str | None = None):
    """Valida un codigo en Supabase; None si no es válido."""
    if not supabase_configured():
        return None
    try:
        url = f"{get_supabase_url()}/rest/v1/codigos_descuento?codigo=eq.{codigo}&select=*"
        resp = requests.get(url, headers=get_supabase_headers(), timeout=10)
        resp.raise_for_status()
        codigos = resp.json()
    except Exception:  # noqa: BLE001
        return None

    if not codigos:
        return None

    codigo_info = codigos[0]
    if codigo_info["usos_actuales"] >= codigo_info["usos_maximos"]:
        return None
    if codigo_info.get("fecha_expiracion"):
        fecha_exp = _parse_iso(codigo_info["fecha_expiracion"])
        if fecha_exp < datetime.now(timezone.utc):
            return None
    if codigo_info.get("plan_objetivo") and codigo_info["plan_objetivo"] != plan:
        return None
    return codigo_info


def consumir_codigo_descuento(codigo: str, plan: str, client_id: str) -> None:
    """Consume un codigo tras el éxito del POST a MercadoPago (D4)."""
    codigo_info = validar_codigo_supabase(codigo, plan)
    if not codigo_info:
        raise HTTPException(status_code=500, detail="Error consumiendo codigo de descuento")

    try:
        requests.patch(
            f"{get_supabase_url()}/rest/v1/codigos_descuento?codigo=eq.{codigo}",
            headers=get_supabase_headers(),
            json={"usos_actuales": codigo_info["usos_actuales"] + 1},
            timeout=10,
        ).raise_for_status()
        requests.post(
            f"{get_supabase_url()}/rest/v1/uso_codigos",
            headers=get_supabase_headers(),
            json={"codigo": codigo, "client_id": client_id, "plan": plan},
            timeout=10,
        ).raise_for_status()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error consumiendo codigo de descuento: {str(e)}")


# ==================== CONFIRMAR PAGO REAL (VERIFICADO CONTRA MP) ====================


def _decodificar_external_reference(ref: str | None) -> tuple[str, str] | None:
    """``external_reference`` -> ``(app_id, client_id)``, o None si no matchea.

    Espejo exacto de ``decodificarExternalReference`` en
    ``suscripcion-api/lib/mp-contract.mjs``: los dos lados tienen que entender
    el mismo contrato o un pago aprobado no encuentra su fila.

    - ``canyp:<client_id>`` -> ("canyp", client_id)   [CANYP]
    - ``ERP-<...>``        -> ("erp", suffix)          [legacy Ordo-ERP]

    Partido por el PRIMER ':' porque el contrato prohíbe ':' en los dos
    valores (``crear_preferencia`` lo valida).
    """
    if not ref or not isinstance(ref, str):
        return None
    valor = ref.strip()
    if not valor:
        return None
    if valor.startswith("ERP-"):
        sufijo = valor[4:].strip()
        return ("erp", sufijo) if sufijo else None
    separador = valor.find(":")
    if separador <= 0:
        return None
    app_id = valor[:separador].strip()
    client_id = valor[separador + 1 :].strip()
    if not app_id or not client_id:
        return None
    return (app_id, client_id)


def _guardar_preference_id(update_url: str, headers: dict, preference_id: str | None) -> bool:
    """Guarda el preference id en SU columna y libera ``mp_payment_id``.

    El ``id`` que devuelve MercadoPago al crear una preferencia es el de la
    PREFERENCIA, no el del pago. Guardarlo en ``mp_payment_id`` era el corte del
    camino de respaldo: ``/confirmar-pago`` busca ``?mp_payment_id=eq.<id>`` con
    el id real del pago, recibía el de la preferencia, y no encontraba la fila.
    Con el webhook caído, el usuario pagaba y la licencia no se activaba nunca.

    Retrocompatible: si la columna ``preference_id`` todavía no existe en
    Supabase, degrada a limpiar ``mp_payment_id`` sin romper la creación de la
    preferencia. Nunca guarda el preference id en ``mp_payment_id``.
    """
    if not preference_id:
        return False
    try:
        requests.patch(
            update_url,
            headers=headers,
            json={"preference_id": preference_id, "mp_payment_id": None},
            timeout=10,
        ).raise_for_status()
        return True
    except Exception as e:  # noqa: BLE001 - columna nueva ausente: degradar, no romper
        print(f"No se pudo escribir preference_id ({e}); reintento sin esa columna")

    try:
        requests.patch(
            update_url, headers=headers, json={"mp_payment_id": None}, timeout=10
        ).raise_for_status()
    except Exception as e:  # noqa: BLE001 - best effort
        print(f"No se pudo limpiar mp_payment_id tras crear la preferencia: {e}")
    return False


def _obtener_pago_mercadopago(payment_id: str) -> dict | None:
    """Pago real consultado en la API de MercadoPago, o None.

    None significa "no se pudo verificar", y quien llama tiene que fallar
    cerrado. Preferimos dejar la licencia sin activar antes que activar sin
    haber cobrado.
    """
    if not settings.MP_ACCESS_TOKEN:
        return None
    try:
        resp = requests.get(
            f"{MP_API_PAGOS}/{payment_id}",
            headers={"Authorization": f"Bearer {settings.MP_ACCESS_TOKEN}"},
            timeout=10,
        )
        resp.raise_for_status()
        pago = resp.json()
        return pago if isinstance(pago, dict) else None
    except Exception:  # noqa: BLE001 - fail-closed: sin verificación no se activa
        return None


def _expiracion_para_plan(plan: str | None, fecha_pago: str | None) -> str | None:
    """ISO de expiración para el plan, anclada al momento del pago.

    Espejo de ``calcularFechaExpiracion`` del webhook: misma fuente de duración
    (``backend/pricing.py``) y mismo ancla (el pago, no "ahora"), para que
    activen por cualquiera de los dos caminos y quede la misma fecha.

    Plan desconocido o sin catálogo -> None: el llamador conserva la fecha que
    ya tenía la fila en vez de inventar una.
    """
    dias = _dias_de_plan(plan)
    if dias is None or not fecha_pago:
        return None
    try:
        base = _parse_iso(fecha_pago)
    except (ValueError, AttributeError):
        return None
    return (base + timedelta(days=dias)).isoformat()


def _dias_de_plan(plan: str | None) -> int | None:
    """Días del plan en el catálogo local, o None si no está."""
    if not plan:
        return None
    for planes in PLANES_FALLBACK.values():
        for entrada in planes:
            if entrada["id"] == plan:
                return int(entrada["dias"])
    return None


def _buscar_fila_por(clave: str, valor: str) -> dict | None:
    """Primera fila de `suscripciones` donde `clave == valor`, o None."""
    try:
        url = f"{get_supabase_url()}/rest/v1/suscripciones?{clave}=eq.{valor}&select=*"
        resp = requests.get(url, headers=get_supabase_headers(), timeout=10)
        resp.raise_for_status()
        filas = resp.json()
    except Exception:  # noqa: BLE001
        return None
    return filas[0] if filas else None


def _activar_suscripcion_por_pago(suscripcion: dict, payment_id: str) -> bool:
    """Pasa la fila a 'activo' de forma idempotente. True si el write ocurrió.

    Idempotencia: si la fila ya está activa con el mismo ``mp_payment_id``, no
    vuelve a escribir. Esto importa porque reintentar una confirmación NO puede
    extender ``fecha_expiracion`` otra vez (el webhook remoto recomputa la
    fecha; sin este freno, cada reintento regalaría días).

    Escribe ``mp_payment_id`` en el mismo PATCH: es lo que permite que la
    próxima confirmación (y el webhook) encuentren la fila por pago.
    """
    headers = get_supabase_headers()
    supabase_url = get_supabase_url()
    app_id = suscripcion.get("app_id", APP_ID_DEFAULT)

    estado_actual = normalizar_estado(suscripcion.get("estado"))
    mismo_pago = suscripcion.get("mp_payment_id") is not None and str(
        suscripcion.get("mp_payment_id")
    ) == str(payment_id)
    if estado_actual is EstadoSuscripcion.ACTIVO and mismo_pago:
        return False

    cuerpo: dict = {"estado": EstadoSuscripcion.ACTIVO.value, "mp_payment_id": payment_id}

    # La fecha se recalcula SOLO en la primera activación de este pago, y
    # siempre desde el momento del pago, nunca desde "ahora": así el respaldo
    # por navegador y el webhook producen la misma fecha.
    expiracion = _expiracion_para_plan(
        suscripcion.get("plan"), suscripcion.get("_fecha_pago_para_expiracion")
    )
    if expiracion:
        cuerpo["fecha_expiracion"] = expiracion

    update_url = (
        f"{supabase_url}/rest/v1/suscripciones"
        f"?client_id=eq.{suscripcion['client_id']}&app_id=eq.{app_id}"
    )
    try:
        requests.patch(update_url, headers=headers, json=cuerpo, timeout=10).raise_for_status()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Error actualizando suscripcion: {str(e)}")
    return True


def _buscar_suscripcion_por_pago(payment_id: str) -> dict:
    """Fila de `suscripciones` con ese `mp_payment_id`, o 404."""
    fila = _buscar_fila_por("mp_payment_id", payment_id)
    if fila:
        return fila
    raise HTTPException(
        status_code=404, detail="Suscripcion no encontrada para este payment_id"
    )


@router.post("/confirmar-pago")
def confirmar_pago(
    payment_id: str,
    client_id: str | None = None,
    app_id: str = APP_ID_DEFAULT,
):
    """Activa la licencia solo después de VERIFICAR el pago en MercadoPago.

    Es el camino de respaldo cuando el webhook remoto no llegó. No confía en el
    `payment_id` que le manden: lo consulta en la API de MercadoPago y exige
    `status == approved`. Si la consulta no puede hacerse (sin token, sin red,
    respuesta inesperada) NO activa: devuelve 502 y deja la fila como estaba.

    La fila se localiza por este orden, para que funcione aunque el webhook
    siga caído:

    1. `mp_payment_id` (la fila ya conoce este pago).
    2. `preference_id` que devuelve MercadoPago junto al pago. Es el camino que
       hace falta cuando `/crear-preferencia` guardó el preference id: sin esto
       el respaldo devolvía 404 siempre.
    3. `client_id` + `app_id` de la `external_reference` del pago. Solo si el
       cliente no pasó `client_id`.

    Cuando la `external_reference` se puede decodificar se usa además como
    comprobación: si el `client_id` que pide el llamador no es el del pago, se
    rechaza. No es un adorno: sin eso, cualquiera que tenga un pago aprobado
    podría pedir la confirmación y escribir en la fila de otro.
    """
    if not settings.MP_ACCESS_TOKEN:
        raise HTTPException(
            status_code=503,
            detail=(
                "No se puede verificar el pago: falta MP_ACCESS_TOKEN. "
                "La licencia no se activa sin verificar el cobro."
            ),
        )

    pago = _obtener_pago_mercadopago(payment_id)
    if not pago or pago.get("status") != "approved":
        raise HTTPException(
            status_code=502,
            detail=(
                "El pago no pudo verificarse como aprobado en MercadoPago. "
                "La licencia no se activa sin confirmacion del cobro."
            ),
        )

    ref = _decodificar_external_reference(pago.get("external_reference"))
    if ref:
        ref_app_id, ref_client_id = ref
        if client_id and client_id != ref_client_id:
            raise HTTPException(
                status_code=403,
                detail=(
                    "El payment_id no corresponde a ese client_id: la licencia "
                    "de otro cliente no se activa con este pago."
                ),
            )
    else:
        ref_app_id, ref_client_id = None, None

    # --- Localización de la fila, con degradación explícita ---
    suscripcion = _buscar_fila_por("mp_payment_id", payment_id)

    if not suscripcion:
        preference_id = pago.get("preference_id")
        if preference_id:
            suscripcion = _buscar_fila_por("preference_id", str(preference_id))

    if not suscripcion:
        if not ref_client_id:
            # Sin `external_reference` legible y sin fila por pago no hay forma
            # honesta de saber a quién pertenece este pago: no se adivina.
            raise HTTPException(
                status_code=404,
                detail=(
                    "No se encontró la suscripción del pago y el pago no trae "
                    "external_reference para identificarla. Pasá client_id."
                ),
            )
        if ref_app_id and client_id is None and ref_app_id != app_id:
            raise HTTPException(
                status_code=400,
                detail=f"app_id invalido para este pago: {ref_app_id}",
            )
        suscripcion = _buscar_suscripcion_supabase(ref_client_id, ref_app_id or app_id)

    if not suscripcion:
        raise HTTPException(
            status_code=404,
            detail="Suscripcion no encontrada para este payment_id",
        )

    # La fila se localizó, pero la referencia del PAGO es la autoridad. Si la fila
    # no es de ese cliente, el pago no la activate: sin este chequeo, encontrar
    # la fila por `preference_id` alcanzaba para activar la licencia de otro.
    if ref:
        if suscripcion.get("client_id") != ref_client_id:
            raise HTTPException(
                status_code=403,
                detail=(
                    "El pago corresponde a otro cliente que el de la suscripcion "
                    "encontrada: no se activa."
                ),
            )
        fila_app_id = suscripcion.get("app_id") or app_id
        if ref_app_id != APP_ID_DEFAULT and fila_app_id != ref_app_id:
            raise HTTPException(
                status_code=403,
                detail="El pago corresponde a otra app: no se activa esta licencia.",
            )

    # `_fecha_pago_para_expiracion` viaja en el dict de la fila solo como dato
    # para el cálculo; no se escribe en Supabase.
    fila_con_ancla = dict(suscripcion)
    fila_con_ancla["_fecha_pago_para_expiracion"] = (
        pago.get("date_approved") or pago.get("date_created")
    )

    escrito = _activar_suscripcion_por_pago(fila_con_ancla, payment_id)
    return {
        "success": True,
        "verificado": True,
        "idempotente": not escrito,
        "estado": EstadoSuscripcion.ACTIVO.value,
        "suscripcion": suscripcion,
    }


@router.post("/confirmar-preferencia")
def confirmar_preferencia(
    preference_id: str,
    client_id: str | None = None,
    app_id: str = APP_ID_DEFAULT,
):
    """Resuelve un pago a partir del id de PREFERENCIA y activa la licencia.

    Por qué existe: el Checkout Pro de Tauri abre el pago en el navegador
    EXTERNO, así que la app nunca ve el `payment_id` de la URL de retorno. Lo
    único que la app guardó fue el `preference_id` de `/crear-preferencia`. Esta
    ruta cierra ese círculo: le pregunta a MercadoPago qué pago corresponde a esa
    preferencia y encadena `/confirmar-pago`, que es el que verifica y activa.

    Igual que `/confirmar-pago`, no activa por confianza: el pago se consulta en
    MercadoPago y tiene que estar `approved` Y ser de este cliente.

    `client_id` es obligatorio: sin él, un `preference_id` adivinado sería
    suficiente para tocar la licencia de cualquiera.
    """
    if not settings.MP_ACCESS_TOKEN:
        raise HTTPException(
            status_code=503,
            detail="No se puede verificar el pago: falta MP_ACCESS_TOKEN.",
        )
    if not _payment_id_de_retorno(preference_id):
        raise HTTPException(status_code=400, detail="preference_id invalido")
    if not client_id:
        raise HTTPException(
            status_code=400,
            detail="client_id es obligatorio: sin el no se puede saber a quien "
            "pertenece esta preferencia.",
        )

    try:
        resp = requests.get(
            f"{MP_API_PREFERENCIAS}/{preference_id}",
            headers={"Authorization": f"Bearer {settings.MP_ACCESS_TOKEN}"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:  # noqa: BLE001 - fail-closed
        raise HTTPException(
            status_code=502,
            detail="No se pudo consultar la preferencia en MercadoPago.",
        )

    payment_id = data.get("payment_id") if isinstance(data, dict) else None
    if not payment_id:
        # No es un error de la app: la preferencia existe pero todavía no tiene
        # pago acreditado. La app va a reintentar.
        raise HTTPException(
            status_code=404,
            detail="La preferencia todavia no tiene un pago acreditado.",
        )

    return confirmar_pago(
        payment_id=str(payment_id), client_id=client_id, app_id=app_id
    )


@router.get("/estado-pago")
def estado_pago(payment_id: str | None = None, preference_id: str | None = None):
    """Estado de la licencia de un pago. SOLO LECTURA: no activa nada.

    Es lo que consulta la pantalla de retorno del Checkout Pro para dejar de
    mostrar un JSON crudo y poder decir "confirmando" / "activa" de verdad.

    Acepta `payment_id` o `preference_id`: la app del cliente solo tiene el
    segundo, porque el pago se abrió en el navegador externo.
    """
    fila = None
    if payment_id:
        fila = _buscar_fila_por("mp_payment_id", payment_id)
    if not fila and not preference_id and payment_id and settings.MP_ACCESS_TOKEN:
        # El webhook pudo no llegar: la fila todavía no conoce este pago, pero
        # el pago sí trae el `preference_id` con el que se la encontró antes.
        pago = _obtener_pago_mercadopago(payment_id)
        if pago and pago.get("preference_id"):
            fila = _buscar_fila_por("preference_id", str(pago["preference_id"]))
    if not fila and preference_id and _payment_id_de_retorno(preference_id):
        fila = _buscar_fila_por("preference_id", preference_id)

    if not fila:
        raise HTTPException(status_code=404, detail="Pago no encontrado")

    estado_bruto = fila.get("estado")
    estado = normalizar_estado(estado_bruto)
    try:
        exp = _parse_iso(fila["fecha_expiracion"])
    except (KeyError, ValueError):
        exp = None

    activo = estado_da_acceso(estado_bruto, exp)
    return {
        "ok": True,
        "activo": activo,
        "estado": estado.value if estado else None,
        "plan": fila.get("plan"),
        "fecha_expiracion": fila.get("fecha_expiracion"),
        "dias_restantes": (exp - datetime.now(timezone.utc)).days if activo and exp else 0,
    }


# ==================== MOCK PAGO (SOLO DESARROLLO EXPLICITO) ====================


def _exigir_mock_habilitado() -> None:
    """Corta con 403 si el cobro simulado no está habilitado en desarrollo."""
    if not mock_pagos_habilitados():
        raise HTTPException(status_code=403, detail=motivo_mock_pagos_deshabilitado())


@router.get("/mock-pago")
def mock_pago(payment_id: str):
    """Simula una pagina de pago exitoso. Solo con el flag de desarrollo."""
    _exigir_mock_habilitado()
    return {
        "message": "Mock Payment Page - Simulacion de pago exitoso",
        "payment_id": payment_id,
        "instrucciones": "En produccion, esto redirigiria a MercadoPago. Para simular, hace POST a /mock-confirm",
        "confirm_url": f"{settings.mp_base_url}/api/suscripcion/mock-confirm?payment_id={payment_id}",
    }


@router.post("/mock-confirm")
def mock_confirm(payment_id: str):
    """Simula la confirmacion de un pago. SOLO desarrollo.

    Activa sin cobrar, así que está detrás del flag de desarrollo y se niega
    explícitamente en builds de cliente: en producción la activación va por
    /confirmar-pago, que verifica el pago contra MercadoPago.
    """
    _exigir_mock_habilitado()
    suscripcion = _buscar_suscripcion_por_pago(payment_id)
    escrito = _activar_suscripcion_por_pago(suscripcion, payment_id)
    return {
        "success": True,
        "message": "Pago confirmado (mock)",
        "idempotente": not escrito,
        "estado": EstadoSuscripcion.ACTIVO.value,
        "suscripcion": suscripcion,
    }


# ==================== CALLBACKS DE MP ====================

# MercadoPago devuelve el pago en la URL de retorno. Sus ids son numéricos, pero
# esto NO es una garantía: el valor viene de la query string. Antes de meterlo en
# HTML o en un script, tiene que pasar por acá.
_RE_PAYMENT_ID_OK = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _payment_id_de_retorno(payment_id: str | None) -> str | None:
    """`payment_id` de la URL de retorno si es plausible; None si no lo es."""
    if not payment_id:
        return None
    candidato = payment_id.strip()
    return candidato if _RE_PAYMENT_ID_OK.match(candidato) else None


def _pagina_estado(titulo: str, mensaje: str, tono: str, payment_id: str | None) -> HTMLResponse:
    """Pantalla de estado del retorno del Checkout Pro.

    Antes `/exito` devolvía un JSON crudo (y sin activar nada): el usuario volvía
    del pago a una pantalla que no parecía de CANYP y no le decía si su licencia
    estaba activa. Ahora la página es real y muestra "confirmando" / "activa",
    consultando `/estado-pago` hasta que la fila llegue a `activo`.

    Todo el texto es estático; el único valor que se interpola es el
    `payment_id`, ya validado por `_payment_id_de_retorno` y pasado por
    `json.dumps` para el script.
    """
    colores = {
        "ok": "#166534",
        "esperando": "#854d0e",
        "error": "#991b1b",
    }
    color = colores.get(tono, "#1f2937")
    polling = ""
    if payment_id:
        polling = (
            "<script>"
            "(function(){"
            "var id=" + json.dumps(payment_id) + ";"
            "var n=0;"
            "var t=setInterval(function(){"
            "n++;"
            "fetch('/api/suscripcion/estado-pago?payment_id='+encodeURIComponent(id))"
            ".then(function(r){return r.ok?r.json():null;})"
            ".then(function(d){if(d&&d.activo){"
            "document.getElementById('t').textContent='Tu licencia ya esta activa';"
            "document.getElementById('m').textContent='Listo. Volve a abrir CANYP y ya vas a poder entrar.';"
            "document.getElementById('c').style.color='#166534';"
            "clearInterval(t);}})"
            ".catch(function(){});"
            "if(n>40){clearInterval(t);}"
            "},3000);"
            "})();"
            "</script>"
        )
    html = (
        "<!doctype html><html lang='es'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>CANYP - " + titulo + "</title>"
        "<style>"
        "body{font-family:system-ui,sans-serif;background:#0b0b0d;color:#e5e7eb;"
        "display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}"
        ".c{max-width:32rem;padding:2rem;text-align:center}"
        "h1{font-size:1.25rem;margin:0 0 .75rem}"
        "p{color:#9ca3af;line-height:1.5;margin:0}"
        "img{margin:0 auto 1.5rem;display:block;height:4rem}"
        "</style></head><body><div class='c'>"
        "<img src='/CANYP_Almafuerte_logo.svg' alt='CANYP'>"
        "<h1 id='t'>" + titulo + "</h1>"
        "<p id='m'>" + mensaje + "</p>"
        "</div>" + polling + "</body></html>"
    )
    # El color se aplica sobre el <h1> desde el script al confirmar.
    if polling:
        html = html.replace("<h1 id='t'>", "<h1 id='c' style='color:" + color + "'>")
    return HTMLResponse(content=html, status_code=200)


@router.get("/exito")
def pago_exito(payment_id: str | None = None, status: str | None = None):
    """Callback de exito de MercadoPago (back_url).

    Volver de MercadoPago NO significa que la licencia esté activa. Antes esta
    ruta devolvía un JSON que decía "la licencia se activa al confirmarse el
    cobro" y no hacía nada: el usuario veía un JSON crudo y no tenía forma de
    saber si había pagado bien.

    Ahora, si el pago está `approved` en MercadoPago, confirma acá mismo
    (mismo camino verificado de `/confirmar-pago`) y muestra el resultado. Si el
    pago todavía no figura aprobado — MercadoPago redirige antes de que el
    crédito se refleje — la página queda en "confirmando" y se actualiza sola
    consultando `/estado-pago`.

    El frontend (LicenseGate) tiene su propio camino: son procesos distintos
    (el pago se abre en el navegador externo), por eso esta pantalla es la que
    le dice al usuario qué pasó.
    """
    pid = _payment_id_de_retorno(payment_id)

    if not pid:
        return _pagina_estado(
            "Confirmando tu pago",
            "Volvemos a verificar el pago con MercadoPago. Si la licencia se activa, "
            "vas a poder entrar a CANYP en unos instantes.",
            "esperando",
            None,
        )

    try:
        confirmar_pago(payment_id=pid)
    except HTTPException as e:
        # 404/403/502 significan "todavía no" o "no corresponde": no es un
        # error de la app para el usuario, es el estado del pago.
        if e.status_code in (403, 404, 502):
            return _pagina_estado(
                "Confirmando tu pago",
                "Estamos esperando la confirmacion del pago. Esto puede tardar unos "
                "instantes: volve a abrir CANYP en un momento.",
                "esperando",
                pid,
            )
        return _pagina_estado(
            "No pudimos confirmar el pago",
            "Volvemos a intentar en un momento. Si ya figuras con el pago hecho, "
            "escribinos y lo activamos.",
            "error",
            pid,
        )

    return _pagina_estado(
        "Tu licencia ya esta activa",
        "Listo. Volve a abrir CANYP y ya vas a poder entrar.",
        "ok",
        pid,
    )


@router.get("/fallo")
def pago_fallo():
    """Callback de fallo de MercadoPago (back_url)."""
    return {"message": "El pago ha fallado. Por favor intenta nuevamente."}


@router.get("/pendiente")
def pago_pendiente():
    """Callback de pago pendiente de MercadoPago (back_url)."""
    return {"message": "El pago esta pendiente de confirmacion."}