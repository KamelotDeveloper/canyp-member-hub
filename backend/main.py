"""CANYP Gestión — FastAPI application."""

from contextlib import asynccontextmanager
import logging
import threading

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import settings
from backend.database import Base, engine
from backend.routers import (
    aranceles,
    auth,
    backup,
    dashboard,
    export,
    membresias,
    notificaciones,
    pagos,
    parcelas,
    settings as settings_router,
    socios,
    suscripcion,
    usuarios,
)
from backend.security import get_current_user

logger = logging.getLogger("canyp.startup")


def _run_migrations_in_background() -> None:
    try:
        from backend.migrations import run_column_migrations

        run_column_migrations(engine)
    except Exception:
        # Registra el error con traceback completo (cae en el log del sidecar /
        # Tauri) en lugar de tragarlo. La app sigue sirviendo, pero ahora queda
        # rastro de QUÉ falló para poder diagnosticarlo.
        logger.exception("Error aplicando migraciones de columnas en background")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create tables on startup, then apply additive column migrations.

    Table creation stays synchronous (serving before tables exist makes every
    request fail), but the additive column migrations now run in a background
    thread: on a remote Postgres the migration chain (inspections + ALTERs +
    numero-socio backfill) can take ~20s, which must not block first paint.
    They are additive and idempotent, so a request that races them only reads
    the pre-migration schema for a short window.
    """
    import threading

    Base.metadata.create_all(bind=engine)
    threading.Thread(target=_run_migrations_in_background, daemon=True).start()

    # Run the backup in the background too so a first-run full dump (remote
    # Postgres -> SQLite, all tables reflected and refilled) never blocks the
    # server from serving. Startup stays fast even on a fresh client.
    def _backup_in_background():
        try:
            from backend.services.backup import run_backup_if_needed

            run_backup_if_needed(engine)
        except Exception:
            logger.exception("Error ejecutando el backup en background")

    threading.Thread(target=_backup_in_background, daemon=True).start()
    yield


app = FastAPI(
    title="CANYP Gestión",
    description="Club Náutico — Gestión de socios, membresías, aranceles y pagos",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
# Auth is open (login/logout/status/first-user bootstrap). Settings is included
# WITHOUT a router-level guard — its own router enforces conditional auth (D9):
# open while unconfigured, guarded once configured. Everything else is guarded (D8).
app.include_router(auth.router)

# Suscripciones/licencias (Fase 1): OPEN a propósito — el pago y la verificación
# de licencia ocurren ANTES del login (misma convicción pre-login que auth).
app.include_router(suscripcion.router)

_guarded = [Depends(get_current_user)]
app.include_router(backup.router, dependencies=_guarded)
app.include_router(socios.router, dependencies=_guarded)
app.include_router(membresias.router, dependencies=_guarded)
app.include_router(aranceles.router, dependencies=_guarded)
app.include_router(pagos.router, dependencies=_guarded)
app.include_router(notificaciones.router, dependencies=_guarded)
app.include_router(parcelas.router, dependencies=_guarded)
app.include_router(export.router, dependencies=_guarded)
app.include_router(dashboard.router, dependencies=_guarded)
app.include_router(usuarios.router, dependencies=_guarded)

app.include_router(settings_router.router)


@app.get("/api/health")
def health_check():
    """Health check endpoint."""
    return {"status": "ok"}
