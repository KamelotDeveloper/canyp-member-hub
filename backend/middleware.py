"""Write gate: no domain write goes through without a restorable dump behind it.

A desktop sidecar pointed at a remote Postgres has no local copy of the data.
If a dump cannot be produced, a bad write is unrecoverable — there is nothing
to roll back to. So the question "is there a dump right now?" is answered
before the request mutates anything (``services/backup.asegurar_backup``), and a
missing dump becomes a 503 with the reason instead of a silent success.

WHAT IS NOT GATED
-----------------
* Reads, ``OPTIONS``/``HEAD`` — a stale backup must not stop the operator from
  READING the data they need to diagnose the problem.
* Operational routes (``/api/backup``, ``/api/settings``, ``/api/auth``,
  ``/api/suscripcion``, ``/api/health``). Gating them would be self-defeating:
  the repair button, the data-mode switch that gets you back to a local file,
  and login must keep working while the backup is broken.

The gate is ON by default and off for an in-memory database, which has nothing
to back up by definition (that is what the test suite runs on). Tests that
exercise the gate itself turn it back on explicitly.
"""

from __future__ import annotations

import logging

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from backend.services import backup as backup_service

logger = logging.getLogger("canyp.backup")

# Paths that stay writable no matter what the backup is doing: repair, data-mode
# switch, identity and licensing. See the module docstring for the reasoning.
RUTAS_LIBERADAS = (
    "/api/backup",
    "/api/settings",
    "/api/auth",
    "/api/suscripcion",
    "/api/health",
)

METODOS_ESCRITURA = frozenset({"POST", "PUT", "PATCH", "DELETE"})

_GUARD_ACTIVO = True


def desactivar_guard() -> None:
    """Turn the gate off process-wide (test suite: the DB is ephemeral)."""
    global _GUARD_ACTIVO
    _GUARD_ACTIVO = False


def activar_guard() -> None:
    """Turn the gate back on (tests that assert the gate's behaviour)."""
    global _GUARD_ACTIVO
    _GUARD_ACTIVO = True


def _es_efimera(url) -> bool:
    """True for a database with no file behind it (``:memory:``)."""
    database = url.database
    return not database or database == ":memory:"


class BackupGuardMiddleware(BaseHTTPMiddleware):
    """Refuse mutating requests while there is no restorable backup."""

    def __init__(self, app, engine):
        super().__init__(app)
        self._engine = engine

    async def dispatch(self, request, call_next):
        if not self._debe_chequear(request):
            return await call_next(request)
        motivo = backup_service.asegurar_backup(self._engine)
        if motivo is not None:
            logger.error("Escritura bloqueada: %s", motivo)
            return JSONResponse(
                status_code=503,
                content={
                    "detail": (
                        "No se puede guardar: no hay un backup restaurable. "
                        f"{motivo}. Volvé a intentarlo cuando el backup funcione; "
                        "no se perdió nada."
                    ),
                    "motivo": motivo,
                },
            )
        return await call_next(request)

    def _debe_chequear(self, request) -> bool:
        if not _GUARD_ACTIVO:
            return False
        if _es_efimera(self._engine.url):
            return False
        if request.method.upper() not in METODOS_ESCRITURA:
            return False
        return not request.url.path.startswith(RUTAS_LIBERADAS)
