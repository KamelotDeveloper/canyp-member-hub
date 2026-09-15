"""CANYP Gestión — FastAPI application."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
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
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create tables on startup."""
    Base.metadata.create_all(bind=engine)
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
app.include_router(auth.router)
app.include_router(backup.router)
app.include_router(socios.router)
app.include_router(membresias.router)
app.include_router(aranceles.router)
app.include_router(pagos.router)
app.include_router(notificaciones.router)
app.include_router(parcelas.router)
app.include_router(export.router)
app.include_router(dashboard.router)
app.include_router(settings_router.router)


@app.get("/api/health")
def health_check():
    """Health check endpoint."""
    return {"status": "ok"}
