"""Separación de credenciales: instalación vs. privilegio del operador.

Supuesto de diseño confirmado por el dueño: los datos de suscripciones/licencias
viven en un proyecto Supabase que administra el OPERADOR, y el cliente NO tiene
acceso a ese proyecto. Por lo tanto ninguna credencial de ese proyecto puede
viajar dentro del binario que se distribuye.

Este módulo es la única fuente de verdad de esa clasificación. No lee ni
imprime valores: sólo nombres de variables.

Dos dominios
------------
OPERADOR (nunca se distribuyen, nunca se escriben en disco del cliente):
    SUPABASE_SERVICE_KEY  -> role=service_role; salta TODAS las RLS de las tablas
                             de suscripciones/planes/códigos. Es la credencial
                             más peligrosa del sistema.
    MP_ACCESS_TOKEN       -> token de la cuenta de producción de MercadoPago.
                             Permite crear preferencias de cobro reales.

INSTALACIÓN (propia de cada club, la define el usuario, no es del operador):
    DATABASE_URL          -> la base del club. La elige el cliente en el wizard
                             DataModeWizard / PUT /api/settings. En modo remoto
                             es un Postgres del club, no del operador.
    JWT_SECRET            -> firma los tokens de sesión del club.
    CANYP_PORT            -> puerto del sidecar; lo inyecta el launcher Tauri.

Configuración del operador (no secreta por sí misma, pero identifica sus
proyectos; puede tener valor por defecto y no habilita nada por sí sola):
    SUPABASE_URL, MP_NOTIFICATION_URL

Ausencia de credencial = fallo explícito
----------------------------------------
``verificar_credenciales_operador`` convierte la ausencia en un error con
nombre de variable y motivo, nunca en un default inseguro ni en un log del
valor. Se invoca desde ``backend.desktop_run.main`` (el sidecar empaquetado),
que es el proceso que se distribuye.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.config import Settings

DOMINIO_OPERADOR = "operador"
DOMINIO_INSTALACION = "instalacion"


@dataclass(frozen=True)
class Credencial:
    """Una credencial clasificada. ``motivo`` explica qué se rompe sin ella."""

    nombre: str
    dominio: str
    motivo: str
    secreta: bool = True

    @property
    def es_de_operador(self) -> bool:
        return self.dominio == DOMINIO_OPERADOR


# Inventario único. Agregar una credencial de operador acá la hace obligatoria
# en los builds del operador y prohibida en los builds de cliente.
CREDENCIALES: tuple[Credencial, ...] = (
    Credencial(
        "SUPABASE_SERVICE_KEY",
        DOMINIO_OPERADOR,
        "lectura y escritura de suscripciones, planes y codigos de descuento",
    ),
    Credencial(
        "MP_ACCESS_TOKEN",
        DOMINIO_OPERADOR,
        "creacion de preferencias de cobro en MercadoPago",
    ),
    Credencial(
        "DATABASE_URL",
        DOMINIO_INSTALACION,
        "acceso a la base del club (la define el cliente en el asistente)",
        secreta=False,
    ),
    Credencial(
        "JWT_SECRET",
        DOMINIO_INSTALACION,
        "emision de los tokens de sesion del club",
    ),
)

CREDENCIALES_OPERADOR: tuple[Credencial, ...] = tuple(
    c for c in CREDENCIALES if c.es_de_operador
)


class FaltanCredencialesOperador(RuntimeError):
    """Arranque sin una credencial de privilegio del operador.

    El mensaje nombra las variables faltantes y qué se rompe; jamas incluye su
    valor.
    """

    def __init__(self, faltantes: list[Credencial], *, fuga_en_build_cliente: bool = False):
        self.faltantes = list(faltantes)
        self.fuga_en_build_cliente = fuga_en_build_cliente
        super().__init__(self.construir_mensaje())

    def construir_mensaje(self) -> str:
        nombres = ", ".join(c.nombre for c in self.faltantes)
        if self.fuga_en_build_cliente:
            return (
                "CANYP: este build de cliente trae credenciales de privilegio del "
                f"operador ({nombres}). Eso no puede distribuirse: la "
                "service_role de Supabase salta todas las RLS y el token de "
                "MercadoPago cobra de la cuenta del operador. Revisar el "
                "empaquetado (spec de PyInstaller) y volver a compilar."
            )
        detalle = "\n".join(
            f"  - {c.nombre}: {c.motivo}" for c in self.faltantes
        )
        return (
            "CANYP: faltan credenciales de privilegio del operador y el cobro de "
            "suscripciones no puede funcionar:\n"
            f"{detalle}\n"
            "Definalas en el entorno del proceso que lanza el sidecar o en "
            "backend/.env (archivo local, ignorado por git, NUNCA empaquetado). "
            "No se registran sus valores en ningun log."
        )


def _valor(settings: Settings, nombre: str) -> str:
    return str(getattr(settings, nombre, "") or "").strip()


def credenciales_operador_ausentes(settings: Settings) -> list[Credencial]:
    """Credenciales de operador sin valor en la configuración actual."""
    return [c for c in CREDENCIALES_OPERADOR if not _valor(settings, c.nombre)]


def credenciales_de_operador_presentes(settings: Settings) -> list[Credencial]:
    """Credenciales de operador presentes en la configuración actual."""
    return [c for c in CREDENCIALES_OPERADOR if _valor(settings, c.nombre)]


def verificar_credenciales_operador(settings: Settings, *, es_build_cliente: bool) -> None:
    """Punto de arranque del sidecar. Falla fuerte, nunca en silencio.

    - Build de cliente (``CANYP_CLIENT_BUILD=1``): las credenciales de operador
      NO deben existir. Si existen, es una regresión de empaquetado y se corta
      el arranque, porque un binario con la service_role dentro regala control
      de las tablas de suscripciones a quien lo instale.
    - Build del operador (dev o compilacion propia): las credenciales de
      operador son obligatorias. Si falta alguna se corta el arranque con un
      mensaje que dice cual falta y por que, en vez de degradar en silencio a un
      cobro simulado o a un trial local.
    """
    if es_build_cliente:
        presentes = credenciales_de_operador_presentes(settings)
        if presentes:
            raise FaltanCredencialesOperador(presentes, fuga_en_build_cliente=True)
        return

    ausentes = credenciales_operador_ausentes(settings)
    if ausentes:
        raise FaltanCredencialesOperador(ausentes)


__all__ = [
    "CREDENCIALES",
    "CREDENCIALES_OPERADOR",
    "Credencial",
    "DOMINIO_INSTALACION",
    "DOMINIO_OPERADOR",
    "FaltanCredencialesOperador",
    "credenciales_de_operador_presentes",
    "credenciales_operador_ausentes",
    "verificar_credenciales_operador",
]
