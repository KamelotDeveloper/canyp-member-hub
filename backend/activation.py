"""FRONTERA DE CONFIANZA de CANYP — la única fuente de verdad de "¿puede operar?".

El problema que este módulo cierra
---------------------------------
Durante la auditoría se confirmó que un archivo de texto escrito a mano abría la
app COMPLETA y sin licencia: con ``%APPDATA%\\CANYP\\settings.json`` en
``{"dataMode":"local","configured":false}`` el ``LicenseGate`` hacía passthrough,
el ``ClientBuildGuard`` no bloqueaba, el sidecar arrancaba sobre SQLite local y
``POST /api/auth/first-user`` creaba un admin. Resultado: el programa entero,
funcional, sin pagar y sin tocar una línea de código.

Decisión de arquitectura (del dueño, no negociable)
--------------------------------------------------
La defensa NO es ofuscar el frontend: es JavaScript plano y se parchea en
segundos. La defensa es que **el cliente no tiene los datos**. Los datos del
club viven en un Supabase del OPERADOR, al que el cliente no tiene acceso. Por
eso un build de cliente nunca puede quedarse \"jugando\" contra una base local
vacía: no hay nada que operar.

La regla, en una línea
----------------------
    En un build de cliente, la app opera contra SQLite local NUNCA.
    Si no hay una base remota válida provisionada, la instalación queda en
    estado de ESPERANDO ACTIVACIÓN: sirve la superficie de activación y nada
    más. El modo local es una herramienta de desarrollo, no un modo operativo.

Por qué cierra el bypass
------------------------
El agujero original no era \"el gate se puede apagar\": era que el estado
``configured: false`` era indistinguible, para el backend, de una instalación
legítima. Al mover la decisión al servidor y anclar la única variable que
importa (el destino de la base de datos) al archivo de ajustes del servidor, el
``settings.json`` deja de ser una palanca: cambiarlo no abre la app, sólo
cambia por qué la app está bloqueada.

Y por qué el cliente no puede routearlo: la decisión se toma con datos que el
cliente no puede fabricar por su cuenta — el modo de datos y la URL guardados en
el servidor, más el esquema real de esa URL. Un ``settings.json`` editado a mano
sí puede decir ``"dataMode":"remoto"``, pero entonces el sidecar intenta
conectar a ESA base, que no es la del club: no hay socios, no hay pagos, no hay
nada. Ver ``docs/frontera_confianza.md`` para el residual acotado de ese caso y
por qué cerrarlo requiere una decisión de producto que todavía no se tomó.

La UI no decide
---------------
``LicenseGate``/``ClientBuildGuard`` reflejan ``GET /api/activacion``. Si el
frontend dijera la verdad, bastaría con parchar el bundle. El servidor es el
que dice que no, y el servidor es el que tiene los datos.
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.engine.url import make_url
from sqlalchemy.exc import ArgumentError

from backend.dev_flags import es_build_cliente
from backend.settings_store import AppSettings, default_settings_dir, load_settings

logger = logging.getLogger("canyp.activacion")

# ---------------------------------------------------------------------------
# Códigos de motivo. Son ESTABLES: la UI los compara y los tests los afirman.
# Un motivo es la explicación de por qué una instalación no puede operar; nunca
# describe un secreto ni incluye credenciales.
# ---------------------------------------------------------------------------
MOTIVO_FUERA_DE_BUILD_CLIENTE = "fuera_de_build_cliente"
MOTIVO_LISTO = "listo"
MOTIVO_SIN_BASE_REMOTA = "sin_base_remota"
MOTIVO_BASE_REMOTA_INVALIDA = "base_remota_invalida"

# Esquemas que significan "la base está en otro lado". Todo lo demás
# (sqlite, file, en memoria) es local, aunque el JSON diga "remoto".
_ESQUEMAS_REMOTOS = frozenset(
    {
        "postgresql",
        "postgres",
        "postgresql+psycopg",
        "postgresql+psycopg2",
        "postgresql+asyncpg",
        "postgresql+pg8000",
        "postgresql+pymysql",
    }
)

MENSAJES_MOTIVO = {
    MOTIVO_FUERA_DE_BUILD_CLIENTE: (
        "Fuera de un build de cliente: la instalación opera con la base configurada."
    ),
    MOTIVO_LISTO: "Instalación activada: hay una base remota provisionada.",
    MOTIVO_SIN_BASE_REMOTA: (
        "Este equipo todavía no tiene una base de datos provisionada por el "
        "administrador. Comuníquese con el administrador para que la habilite."
    ),
    MOTIVO_BASE_REMOTA_INVALIDA: (
        "La base de datos configurada no es válida o no es remota. Comuníquese "
        "con el administrador."
    ),
}

# Tamaño máximo del registro de intentos antes de rotarlo. Un sidecar de
# escritorio no debe poder llenar el disco del cliente.
_LOG_MAX_BYTES = 1_000_000
_log_lock = threading.Lock()


@dataclass(frozen=True)
class EstadoActivacion:
    """Veredicto de la frontera de confianza para una petición.

    ``operacion_permitida`` es la ÚNICA respuesta que las rutas de dominio
    consultan. Los routers abiertos (activación, ajustes, suscripción) no la
    usan: existen precisamente para poder mostrar el estado bloqueado.
    """

    operacion_permitida: bool
    es_build_cliente: bool
    motivo: str
    mensaje: str
    data_mode: str
    configured: bool

    def a_dict_publico(self) -> dict:
        """Forma que se expone por ``GET /api/activacion``.

        No incluye la ``databaseUrl``: ni en claro ni enmascarada. La UI ya la
        recibe (enmascarada) por ``GET /api/settings`` y no la necesita para
        decidir nada.
        """
        return {
            "operacionPermitida": self.operacion_permitida,
            "esBuildCliente": self.es_build_cliente,
            "motivo": self.motivo,
            "mensaje": self.mensaje,
            "dataMode": self.data_mode,
            "configured": self.configured,
        }


# ---------------------------------------------------------------------------
# Resolución de la base remota
# ---------------------------------------------------------------------------


def es_url_remota_valida(url: str) -> bool:
    """True si ``url`` es una URL parseable de un Postgres remoto.

    Falla cerrado ante cualquier cosa que no sea eso:

    - vacía o sin esquema → False;
    - sintaxis inválida → False;
    - ``sqlite:///``, ``file:``, ``:memory:`` → **False**, aunque el JSON diga
      ``"dataMode": "remoto"``. Éste es un bypass real: declararse remoto y
      seguir operando sobre un archivo local;
    - credenciales embebidas ausentes no se imponen acá: la conexión lo dirá
      al usarla, y esta función sólo decide *dónde* se opera, no *con qué*.
    """
    candidata = (url or "").strip()
    if not candidata:
        return False
    try:
        url_analizada = make_url(candidata)
    except ArgumentError:
        return False
    return url_analizada.get_backend_name() in _ESQUEMAS_REMOTOS


def resolver_base_remota(settings: AppSettings) -> str:
    """URL remota efectiva a usar, o "" si la instalación no tiene ninguna.

    Punto único de acuerdo entre ``desktop_run`` (que arma ``DATABASE_URL``),
    la frontera de confianza (que decide si se puede operar) y los tests. Que
    los tres digan lo mismo es la mitad de la defensa: si el sidecar arranca
    en local mientras la frontera cree que hay remoto, la frontera miente.
    """
    if settings.dataMode != "remoto":
        return ""
    return (settings.databaseUrl or "").strip()


# ---------------------------------------------------------------------------
# Veredicto
# ---------------------------------------------------------------------------


def evaluar_activacion() -> EstadoActivacion:
    """Resuelve el veredicto de activación. Se lee en CADA petición.

    Deliberadamente sin caché: el archivo de ajustes lo puede cambiar el propio
    operador (o un ``PUT /api/settings`` recién hecho), y un veredicto cacheado
    que se quedó viejo es exactamente el bypass que estamos cerrando. El costo
    es leer un JSON de ~60 bytes por petición, en un sidecar de escritorio.
    """
    settings = load_settings()

    # Fuera de un build de cliente no hay frontera: development, web y tests
    # operan siempre contra la base que tengan configurada. Esta rama es la que
    # garantiza estructuralmente que el flujo de desarrollo no se rompe.
    if not es_build_cliente():
        return EstadoActivacion(
            operacion_permitida=True,
            es_build_cliente=False,
            motivo=MOTIVO_FUERA_DE_BUILD_CLIENTE,
            mensaje=MENSAJES_MOTIVO[MOTIVO_FUERA_DE_BUILD_CLIENTE],
            data_mode=settings.dataMode,
            configured=settings.configured,
        )

    base_remota = resolver_base_remota(settings)
    if not base_remota:
        return _bloqueado(settings, MOTIVO_SIN_BASE_REMOTA)
    if not es_url_remota_valida(base_remota):
        return _bloqueado(settings, MOTIVO_BASE_REMOTA_INVALIDA)
    return EstadoActivacion(
        operacion_permitida=True,
        es_build_cliente=True,
        motivo=MOTIVO_LISTO,
        mensaje=MENSAJES_MOTIVO[MOTIVO_LISTO],
        data_mode=settings.dataMode,
        configured=settings.configured,
    )


def _bloqueado(settings: AppSettings, motivo: str) -> EstadoActivacion:
    return EstadoActivacion(
        operacion_permitida=False,
        es_build_cliente=True,
        motivo=motivo,
        mensaje=MENSAJES_MOTIVO[motivo],
        data_mode=settings.dataMode,
        configured=settings.configured,
    )


# ---------------------------------------------------------------------------
# Registro de intentos
# ---------------------------------------------------------------------------


def registrar_intento(motivo: str, detalle: str = "") -> None:
    """Deja rastro de un intento de operar con la instalación bloqueada.

    Requisito del dueño: que cualquier intento de evitar el bloqueo quede
    registrado. Se escribe un log de texto aditivo en el directorio de datos
    por usuario, con marca de tiempo, motivo, ruta y un detalle que nunca
    contiene credenciales (los callers pasan motivo y ruta, no payloads).

    El registro no es una defensa —quien tiene la máquina tiene el archivo—,
    pero convierte un bypass silencioso en algo que se puede auditar después.
    """
    marca = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    linea = f"{marca} motivo={motivo}"
    if detalle:
        linea += f" detalle={detalle}"
    # Nunca un salto de línea desde el detalle: rompería el formato del log.
    linea = linea.replace("\n", " ")[:500]

    logger.warning("operacion bloqueada: %s", linea)
    try:
        _escribir_linea_de_log(linea)
    except OSError:
        # Registrar el intento nunca debe tumbar la petición: si el disco está
        # lleno o el directorio no existe, el bloqueo sigue aplicando.
        pass


def _escribir_linea_de_log(linea: str) -> None:
    directorio = default_settings_dir()
    ruta = os.path.join(directorio, "activacion-intentos.log")
    with _log_lock:
        if os.path.exists(ruta) and os.path.getsize(ruta) > _LOG_MAX_BYTES:
            os.replace(ruta, ruta + ".1")
        with open(ruta, "a", encoding="utf-8") as fh:
            fh.write(linea + "\n")


# ---------------------------------------------------------------------------
# Dependencia de FastAPI
# ---------------------------------------------------------------------------

HTTP_OPERACION_BLOQUEADA = 503
HTTP_ADMIN_NO_PERMITIDO = 403


def exigir_operacion() -> None:
    """Dependencia que se cuelga en TODAS las rutas de dominio.

    Un 503 (no un 403) porque no es un permiso denegado: la instalación todavía
    no está activada, es un estado transitorio esperando al administrador.
    La distinción importa en ``first-user``, que sí es una política (403).
    """
    estado = evaluar_activacion()
    if estado.operacion_permitida:
        return
    registrar_intento("operacion_bloqueada", estado.motivo)
    raise HTTPException(
        status_code=HTTP_OPERACION_BLOQUEADA,
        detail=estado.mensaje,
        headers={"Retry-After": "30"},
    )


def exigir_operacion_para_crear_admin() -> None:
    """Política de ``first-user``: en un build de cliente nadie crea el admin.

    El admin lo provisiona el operador, contra la base real del club. Dejarlo
    abierto convertía el endpoint en \"creo admin sin licencia\" dentro de una
    instalación sin activar.
    """
    if not es_build_cliente():
        return
    registrar_intento("first_user_en_build_cliente", "POST /api/auth/first-user")
    raise HTTPException(
        status_code=HTTP_ADMIN_NO_PERMITIDO,
        detail=(
            "En un build de cliente la cuenta de administrador la crea el "
            "administrador del sistema, no la instalación."
        ),
    )


__all__ = [
    "EstadoActivacion",
    "HTTP_ADMIN_NO_PERMITIDO",
    "HTTP_OPERACION_BLOQUEADA",
    "MENSAJES_MOTIVO",
    "MOTIVO_BASE_REMOTA_INVALIDA",
    "MOTIVO_FUERA_DE_BUILD_CLIENTE",
    "MOTIVO_LISTO",
    "MOTIVO_SIN_BASE_REMOTA",
    "es_build_cliente",
    "es_url_remota_valida",
    "evaluar_activacion",
    "exigir_operacion",
    "exigir_operacion_para_crear_admin",
    "registrar_intento",
    "resolver_base_remota",
]
