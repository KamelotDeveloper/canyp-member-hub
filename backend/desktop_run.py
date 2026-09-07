"""Desktop sidecar entry point for CANYP (Tauri + PyInstaller).

Runs the FastAPI app on 127.0.0.1:8000 (localhost only). When bundled with
PyInstaller it places the SQLite DB in the per-user AppData data dir so a
packaged app never writes next to the executable (Program Files is read-only
for standard users).

The path is injected through the `DATABASE_URL` env var that
``backend.database`` already honors, so nothing else changes.

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


def main() -> None:
    # Critical: override DATABASE_URL BEFORE importing backend.main — database.py
    # reads the env at import time, so the sidecar must land in AppData (not the
    # executable dir / read-only Program Files).
    if not os.environ.get("DATABASE_URL"):
        db_file = os.path.join(_data_dir(), "canyp.db")
        os.environ["DATABASE_URL"] = f"sqlite:///{db_file}"

    from backend.main import app  # noqa: PLC0415 - import after env override

    host = os.environ.get("CANYP_HOST", "127.0.0.1")
    port = int(os.environ.get("CANYP_PORT", "8000"))
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
    sys.exit(0)