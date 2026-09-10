"""Settings endpoints (data mode + remote database URL)."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.settings_store import DATA_MODES, DEFAULT_DATA_MODE, AppSettings, load_settings, save_settings

router = APIRouter(prefix="/api/settings", tags=["settings"])

_DATA_MODE_LABEL = " o ".join(DATA_MODES)
_REMOTO_REQUIRED_URL = "Se requiere la URL de conexión para usar el modo remoto"


class SettingsUpdate(BaseModel):
    """Accepted PUT body. ``databaseUrl`` is only meaningful for "remoto"."""

    dataMode: str
    databaseUrl: str | None = None


class SettingsResponse(BaseModel):
    dataMode: str
    databaseUrl: str
    configured: bool


@router.get("", response_model=SettingsResponse)
def get_settings() -> SettingsResponse:
    """Return current settings (never crashes — missing file == defaults)."""
    s = load_settings()
    return SettingsResponse(dataMode=s.dataMode, databaseUrl=s.databaseUrl, configured=s.configured)


@router.put("", response_model=SettingsResponse)
def update_settings(data: SettingsUpdate) -> SettingsResponse:
    """Validate and persist a mode change.

    - dataMode must be "local" or "remoto" (else 422).
    - "remoto" requires a non-empty databaseUrl (else 422).
    - Switching to "local" scrubs the stored connection URL.
    """
    if data.dataMode not in DATA_MODES:
        raise HTTPException(
            status_code=422, detail=f"dataMode debe ser {_DATA_MODE_LABEL}"
        )

    url = (data.databaseUrl or "").strip()
    if data.dataMode == "remoto" and not url:
        raise HTTPException(status_code=422, detail=_REMOTO_REQUIRED_URL)

    settings = AppSettings(
        dataMode=data.dataMode,
        databaseUrl="" if data.dataMode == "local" else url,
        configured=True,
    )
    save_settings(settings)
    return SettingsResponse(
        dataMode=settings.dataMode,
        databaseUrl=settings.databaseUrl,
        configured=settings.configured,
    )


__all__ = ["router", "SettingsUpdate", "SettingsResponse", "DEFAULT_DATA_MODE"]