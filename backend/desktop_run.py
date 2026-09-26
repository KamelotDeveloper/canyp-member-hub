"""Desktop sidecar entry point for CANYP (Tauri + PyInstaller).

Runs the FastAPI app on 127.0.0.1 on the port given by the CANYP_PORT env var
(injected by Tauri at startup; defaults to 8000 in bare dev runs). When
bundled with PyInstaller it places the SQLite DB in the per-user AppData data
dir so a packaged app never writes next to the executable (Program Files is
read-only for standard users).

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

    Client builds (``CANYP_CLIENT_BUILD == "1"``) may only run local while
    the app is NOT yet configured: the first-run wizard needs a live backend
    to let the administrator provision the remoto settings (the only path to
    a configured client is remoto — the UI offers no local option and PUT
    /api/settings rejects it). A client that is ALREADY configured must never
    resolve to local; if it somehow does (edited settings.json), refuse to
    start so the installer fails closed with a clear message instead of
    silently serving a local database.
    """
    CLIENT_BUILD = os.environ.get("CANYP_CLIENT_BUILD") == "1"

    if os.environ.get("DATABASE_URL"):
        return

    from backend.settings_store import load_settings

    settings = load_settings()
    if settings.dataMode == "remoto" and settings.databaseUrl:
        os.environ["DATABASE_URL"] = settings.databaseUrl
        return

    if CLIENT_BUILD and settings.configured:
        print(
            "CANYP: configuración de cliente inválida — "
            "este build requiere el modo remoto. Contacte al administrador.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    db_file = os.path.join(_data_dir(), "canyp.db")
    os.environ["DATABASE_URL"] = f"sqlite:///{db_file}"


def main() -> None:
    # PyInstaller builds with console=False leave sys.stdout/sys.stderr as None,
    # and uvicorn's logging setup calls stream.isatty() while configuring the
    # "default" formatter — crashing with AttributeError on None. Point them at
    # devnull so the sidecar starts; a real piped stream (Tauri forwarder) is
    # still used when the OS provides one.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")

    # Critical: override DATABASE_URL BEFORE importing backend.main — database.py
    # reads the env at import time, so the sidecar must know its target database
    # (AppData SQLite by default, or Postgres when the user chose "remoto")
    # before the engine is created.
    _configure_database_url()

    from backend.main import app  # noqa: PLC0415 - import after env override

    host = os.environ.get("CANYP_HOST", "127.0.0.1")
    port = int(os.environ.get("CANYP_PORT", "8000"))
    # Pin the protocol implementations to the pure-Python options. uvicorn's
    # "auto" defaults try to import the C extensions httptools (http) and
    # websockets/wsproto (ws), which are NOT bundled in the PyInstaller build
    # and crash the sidecar on startup with ImportError/AttributeError. h11 is
    # pure Python and is a real dependency. The app is plain REST, so no
    # websocket support is needed.
    uvicorn.run(app, host=host, port=port, log_level="info", http="h11", ws="none")


if __name__ == "__main__":
    main()
    sys.exit(0)