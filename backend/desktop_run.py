"""Desktop sidecar entry point for CANYP (Tauri + PyInstaller).

Runs the FastAPI app on 127.0.0.1:8000 (localhost only). When bundled with
PyInstaller it places the SQLite DB in the per-user AppData data dir so a
packaged app never writes next to the executable (Program Files is read-only
for standard users).

The path is injected through the `DATABASE_URL` env var that
``backend.database`` already honors, so nothing else changes.

Data mode (Phase 0): if the settings store says "remoto" with a connection
URL, that URL wins (DATABASE_URL = Postgres). Otherwise today's behavior is
kept unchanged: SQLite in AppData.

Run in dev:    python -m backend.desktop_run
Build (onefile):  pyinstaller --name canyp-backend --onefile --noconsole \
                    --collect-all backend backend/desktop_run.py
"""

import os
import sys

import uvicorn


def _data_dir() -> str:
    """Per-user writable directory for the SQLite DB (created on demand)."""
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    data = os.path.join(base, "CANYP", "data")
    os.makedirs(data, exist_ok=True)
    return data


def _remote_database_url_from_settings() -> str | None:
    """Read the persisted data mode; return a Postgres URL when "remoto".

    Returns None for local/unconfigured so the caller keeps SQLite defaults.
    """
    from backend.settings_store import load_settings

    settings = load_settings()
    if settings.dataMode == "remoto" and settings.databaseUrl:
        return settings.databaseUrl
    return None


def _configure_database_url() -> None:
    """Set DATABASE_URL before backend.database is imported.

    1. Explicit env override always wins (tests/dev scripts).
    2. Otherwise a persisted "remoto" mode overrides the local default.
    3. Otherwise fall back to SQLite in the per-user data dir.
    """
    if os.environ.get("DATABASE_URL"):
        return

    remote_url = _remote_database_url_from_settings()
    if remote_url:
        os.environ["DATABASE_URL"] = remote_url
        return

    db_file = os.path.join(_data_dir(), "canyp.db")
    os.environ["DATABASE_URL"] = f"sqlite:///{db_file}"


def main() -> None:
    # Critical: override DATABASE_URL BEFORE importing backend.main — database.py
    # reads the env at import time, so the sidecar must know its target database
    # (AppData SQLite by default, or Postgres when the user chose "remoto")
    # before the engine is created.
    _configure_database_url()

    from backend.main import app  # noqa: PLC0415 - import after env override

    host = os.environ.get("CANYP_HOST", "127.0.0.1")
    port = int(os.environ.get("CANYP_PORT", "8000"))
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
    sys.exit(0)