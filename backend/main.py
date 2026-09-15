"""CANYP Gestión — FastAPI application."""

from contextlib import asynccontextmanager

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
    usuarios,
)
from backend.security import get_current_user


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create tables on startup, then apply additive column migrations."""
    Base.metadata.create_all(bind=engine)
    from backend.migrations import run_column_migrations

    run_column_migrations(engine)
    try:
        from backend.services.backup import run_backup_if_needed

        run_backup_if_needed(engine)
    except Exception:
        pass
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
