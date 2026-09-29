"""Vocabulario canónico de estados de suscripción.

Única fuente de verdad del campo ``suscripciones.estado``. Antes de este módulo
el valor lo escribía cada lado por su cuenta y no coincidían: el backend leía
``("activo", "prueba")`` mientras el webhook escribía ``activa``, así que un
pago aprobado dejaba la fila en un estado que ``/api/suscripcion/verificar``
nunca reconocía como licencia.

Los valores son exactamente los que viven en la columna ``estado`` de Supabase.
``suscripcion-api`` debe escribir estos mismos strings (contrato de
``external_reference`` documentado en ``backend/pricing.py``).

Sinónimos heredados
-------------------
``activa`` (femenino) fue lo que el webhook remoto escribió durante un tiempo.
``normalizar_estado`` lo acepta en lectura para no dejar afuera a un cliente que
ya pagó, pero la escritura canónica es ``activo``. No se usa en ningún
``PATCH``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum


class EstadoSuscripcion(str, Enum):
    """Estados canónicos de ``suscripciones.estado``."""

    #: Pago iniciado, todavía no aprobado. No habilita licencia por sí solo.
    PENDIENTE = "pendiente"
    #: Acceso gratuito (trial de 7 días o plan de precio 0). Habilita licencia.
    PRUEBA = "prueba"
    #: Pago aprobado. Habilita licencia hasta ``fecha_expiracion``.
    ACTIVO = "activo"
    #: Vencida. Lo escribe el backend al verificar; no lo resurrecta un reintento.
    EXPIRADO = "expirado"


#: Estados que dan acceso mientras ``fecha_expiracion`` esté en el futuro.
ESTADOS_CON_ACCESO: frozenset[EstadoSuscripcion] = frozenset(
    {EstadoSuscripcion.PRUEBA, EstadoSuscripcion.ACTIVO}
)

#: Sinónimos que ya pueden existir en filas escritas por versiones viejas.
#: Solo se aceptan en lectura; la escritura siempre es canónica.
SINONIMOS_HEREDADOS: dict[str, EstadoSuscripcion] = {
    "activa": EstadoSuscripcion.ACTIVO,
    "active": EstadoSuscripcion.ACTIVO,
}


def normalizar_estado(valor: str | None) -> EstadoSuscripcion | None:
    """Texto de Supabase -> ``EstadoSuscripcion``, tolerando sinónimos viejos.

    Devuelve ``None`` si el valor no es un estado conocido: un estado
    desconocido no habilita licencia (fail-closed), no se adivina.
    """
    if valor is None:
        return None
    texto = str(valor).strip().lower()
    if not texto:
        return None
    if texto in SINONIMOS_HEREDADOS:
        return SINONIMOS_HEREDADOS[texto]
    try:
        return EstadoSuscripcion(texto)
    except ValueError:
        return None


def estado_da_acceso(valor: str | None, fecha_expiracion: datetime | None) -> bool:
    """True si el estado (ya normalizado) habilita licencia y no está vencido.

    Un estado desconocido, o una fecha de expiración ausente o vencida, dan
    ``False``: activar por defecto sería justo el bug que este módulo arregla.
    """
    estado = normalizar_estado(valor)
    if estado not in ESTADOS_CON_ACCESO:
        return False
    if fecha_expiracion is None:
        return False
    return fecha_expiracion > datetime.now(timezone.utc)


__all__ = [
    "ESTADOS_CON_ACCESO",
    "EstadoSuscripcion",
    "SINONIMOS_HEREDADOS",
    "estado_da_acceso",
    "normalizar_estado",
]
