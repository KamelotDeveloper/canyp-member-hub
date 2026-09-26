"""Settings endpoints (data mode + remote database URL).

Conditional auth (D9): GET/PUT are open while ``load_settings().configured`` is
False (the first-run wizard must read/write settings before any user exists),
and guarded once configured. The guard lives here — NOT in ``main.py``'s guarded
list — because the router-level guard would hard-block the bootstrap flow.
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.usuario import Usuario
from backend.security import get_current_user
from backend.settings_store import (
    DATA_MODES,
    DEFAULT_DATA_MODE,
    AppSettings,
    load_settings,
    save_settings,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])

_DATA_MODE_LABEL = " o ".join(DATA_MODES)
_REMOTO_REQUIRED_URL = "Se requiere la URL de conexión para usar el modo remoto"

# Same auto_error=False bearer as security.py, resolved only by this guard.
_bearer = HTTPBearer(auto_error=False)


def require_auth_if_configured(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> Usuario | None:
    """Conditional auth dependency (D9).

    Open while unconfigured (returns None); once configured, delegates to
    ``get_current_user`` so the 401 contract matches every other guarded route.
    """
    if not load_settings().configured:
        return None
    return get_current_user(credentials=credentials, db=db)


def _mask_database_url(url: str) -> str:
    """Mask a remote connection URL for the GET response.

    An empty URL (local mode / scrubbed pre-config) stays "". A non-empty URL
    is reduced to ``"***"`` + its last 8 characters so the client can show
    which database is configured without leaking credentials.
    """
    if not url:
        return ""
    return "***" + url[-8:]


class SettingsUpdate(BaseModel):
    """Accepted PUT body. ``databaseUrl`` is only meaningful for "remoto"."""

    dataMode: str
    databaseUrl: str | None = None


class SettingsResponse(BaseModel):
    dataMode: str
    databaseUrl: str
    configured: bool


@router.get(
    "", response_model=SettingsResponse, dependencies=[Depends(require_auth_if_configured)]
)
def get_settings() -> SettingsResponse:
    """Return current settings (never crashes — missing file == defaults).

    The remote ``databaseUrl`` is masked in the response; it is never logged.
    """
    s = load_settings()
    return SettingsResponse(
        dataMode=s.dataMode,
        databaseUrl=_mask_database_url(s.databaseUrl),
        configured=s.configured,
    )


@router.put(
    "", response_model=SettingsResponse, dependencies=[Depends(require_auth_if_configured)]
)
def update_settings(data: SettingsUpdate) -> SettingsResponse:
    """Validate and persist a mode change.

    - dataMode must be "local" or "remoto" (else 422).
    - "remoto" requires a non-empty databaseUrl (else 422).
    - Switching to "local" scrubs the stored connection URL.

    The PUT response still returns the full ``databaseUrl`` (unchanged from the
    spec); it is never logged.
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