"""Superficie de activación: el veredicto que la UI refleja.

Un único endpoint abierto (pre-login, sin ``Depends(get_current_user)``) que
expone el veredicto de ``backend.activation``. Está abierto a propósito y por
la misma convicción que ``/api/auth/status`` y ``/api/suscripcion/*``: el
cliente tiene que poder preguntar "¿estoy activado?" ANTES de tener usuario, y
la respuesta no revela nada que el usuario no sepa ya.

Lo que este router NO hace es decidir nada. Si este endpoint dijera "permitido"
no significaría que la app abre: las rutas de dominio preguntan
``activation.exigir_operacion`` por su cuenta. Este endpoint es un espejo, no
un interruptor — si el frontend mintiera, el backend seguiría negando.
"""

from fastapi import APIRouter

from backend.activation import evaluar_activacion

router = APIRouter(prefix="/api/activacion", tags=["activacion"])


@router.get("")
def estado_de_activacion() -> dict:
    """Veredicto de activación de esta instalación.

    Devuelve siempre 200, incluso cuando la operación está bloqueada: que la
    instalación no esté activada es un estado normal de la máquina de estados,
    no un error de la consulta. El 503 vive en las rutas de dominio.
    """
    return evaluar_activacion().a_dict_publico()


__all__ = ["router"]
