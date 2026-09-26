"""Suscripciones CANYP — MercadoPago Checkout Pro + licencia Supabase.

Espeja el contrato de negocio de Ordo-ERP (router `/api/suscripcion`), adaptado
al stack CANYP:

- app_id CANYP = "canyp". external_reference = "canyp:<client_id>" (los valores
  nunca llevan ':' porque el webhook remoto hace split por el primer ':').
- Planes: se leen de Supabase (tabla planes_suscripcion, filtrada por app_id)
  con fallback al catálogo local (backend/pricing.py).
- Preferencia: POST a MercadoPago Checkout Pro con el token de producción.
  Sin token -> modo mock (payment_url local).
- Licencia: GET de filas en la tabla `suscripciones` de Supabase
  (estado activo/prueba + fecha_expiracion futura). Sin Supabase o con error,
  el trial local (SQLite, 7 días, una vez por client_id) es el fallback.
- El webhook remoto (https://suscripcion-api.vercel.app/api/webhook) es quien
  activa la suscripción en Supabase al aprobarse el pago. NO se toca.

Los endpoints son OPEN (pre-login): la verificación de licencia y el pago
ocurren antes de que exista usuario en CANYP.
"""

import requests
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database import get_db
from backend.models.licencia_trial import LicenciaTrial, TRIAL_DAYS, fecha_fin_trial
from backend.pricing import KNOWN_APPS, get_planes_for_app

router = APIRouter(prefix="/api/suscripcion", tags=["suscripcion"])

APP_ID_DEFAULT = "canyp"

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
    return bool(settings.SUPABASE_URL and settings.SUPABASE_SERVICE_KEY)


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
        "estado": "prueba" if precio_final == 0 else "pendiente",
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

    if not settings.MP_ACCESS_TOKEN:
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
        requests.patch(
            update_url, headers=headers, json={"mp_payment_id": mp_data.get("id")}, timeout=10
        )
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
        requests.patch(url, headers=get_supabase_headers(), json={"estado": "expirado"}, timeout=10)
    except Exception:  # noqa: BLE001 - best effort
        pass


def _trial_vigente(
    db: Session, client_id: str, app_id: str
) -> dict | None:
    """Trial local activo y no vencido para (client_id, app_id), o None."""
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
        estado = sub.get("estado")
        try:
            exp = _parse_iso(sub["fecha_expiracion"])
        except (KeyError, ValueError):
            exp = None

        if estado in ("activo", "prueba") and exp is not None and exp > datetime.now(timezone.utc):
            dias_restantes = (exp - datetime.now(timezone.utc)).days
            return {
                "ok": True,
                "activo": True,
                "tipo": "licencia",
                "estado": estado,
                "plan": sub.get("plan"),
                "fecha_expiracion": sub.get("fecha_expiracion"),
                "dias_restantes": dias_restantes,
            }

        if estado == "pendiente":
            # Pago iniciado pero jamás aprobado: no consume el trial local.
            trial = _trial_vigente(db, data.client_id, data.app_id)
            if trial:
                return trial
            return {
                "ok": False,
                "activo": False,
                "tipo": "licencia",
                "estado": estado,
                "mensaje": "Pago pendiente de aprobación",
            }

        _marcar_expirada_supabase(data.client_id, data.app_id)
        return {
            "ok": False,
            "activo": False,
            "tipo": "licencia",
            "estado": "expirado",
            "error": "licencia_expirada",
            "mensaje": "La licencia ha expirado",
        }

    trial = _trial_vigente(db, data.client_id, data.app_id)
    if trial:
        return trial

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
    """
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


# ==================== MOCK PAGO (SOLO PARA PRUEBAS) ====================


@router.get("/mock-pago")
def mock_pago(payment_id: str):
    """Simula una pagina de pago exitoso para pruebas (sin MP_ACCESS_TOKEN)."""
    return {
        "message": "Mock Payment Page - Simulacion de pago exitoso",
        "payment_id": payment_id,
        "instrucciones": "En produccion, esto redirigiria a MercadoPago. Para simular, hace POST a /mock-confirm",
        "confirm_url": f"{settings.mp_base_url}/api/suscripcion/mock-confirm?payment_id={payment_id}",
    }


@router.post("/mock-confirm")
def mock_confirm(payment_id: str):
    """Simula la confirmacion de un pago (Fase 1, sin webhooks reales)."""
    supabase_url = get_supabase_url()
    headers = get_supabase_headers()

    url = f"{supabase_url}/rest/v1/suscripciones?mp_payment_id=eq.{payment_id}&select=*"
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        suscripciones = resp.json()
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=404, detail="Pago no encontrado")

    if not suscripciones:
        raise HTTPException(status_code=404, detail="Suscripcion no encontrada para este payment_id")

    sub = suscripciones[0]
    update_url = (
        f"{supabase_url}/rest/v1/suscripciones"
        f"?client_id=eq.{sub['client_id']}&app_id=eq.{sub.get('app_id', APP_ID_DEFAULT)}"
    )
    try:
        requests.patch(update_url, headers=headers, json={"estado": "activo"}, timeout=10).raise_for_status()
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=500, detail="Error actualizando suscripcion")

    return {"success": True, "message": "Pago confirmado (mock)", "estado": "activo", "suscripcion": sub}


# ==================== CALLBACKS DE MP (PLACEHOLDERS) ====================


@router.get("/exito")
def pago_exito():
    """Callback de exito de MercadoPago (back_url)."""
    return {"message": "Pago exitoso. Tu suscripcion ha sido activada."}


@router.get("/fallo")
def pago_fallo():
    """Callback de fallo de MercadoPago (back_url)."""
    return {"message": "El pago ha fallado. Por favor intenta nuevamente."}


@router.get("/pendiente")
def pago_pendiente():
    """Callback de pago pendiente de MercadoPago (back_url)."""
    return {"message": "El pago esta pendiente de confirmacion."}