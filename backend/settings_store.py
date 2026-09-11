"""CANYP user settings persisted to a JSON file.

Controls the data mode selected by the user ("local" SQLite vs "remoto"
PostgreSQL) plus the remote connection string.

Schema (``settings.json``)::

    {"dataMode": "local" | "remoto", "databaseUrl": str, "configured": bool}

Invariant: a MISSING file == ``{dataMode: "local", databaseUrl: "", configured: false}``.
The default data mode is "local", so an unconfigured app behaves exactly like
today (SQLite) — the sidecar only switches to Postgres when an explicit
"remoto" mode with a non-empty connection URL is persisted.

Path resolution:
    - Packaged (PyInstaller): ``%APPDATA%\\CANYP\\settings.json``.
    - Dev/tests: ``canyp-settings.json`` in the current working directory, so
      tests can control it with tmp_path monkeypatching.

Atomically written (temp file + ``os.replace``).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import asdict, dataclass

DATA_MODES = ("local", "remoto")
DEFAULT_DATA_MODE = "local"

SETTINGS_FILENAME = "settings.json"
PACKAGED_SUBDIR = "CANYP"


class SettingsError(Exception):
    """Raised when settings cannot be persisted to disk."""


@dataclass
class AppSettings:
    """Decoded settings. ``configured`` is set once the first-run wizard (or
    Ajustes) saves; it never reaches the database layer."""

    dataMode: str = DEFAULT_DATA_MODE
    databaseUrl: str = ""
    configured: bool = False


def default_settings_path() -> str:
    """Resolve where settings.json lives for the current runtime."""
    if getattr(sys, "frozen", False):
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        data_dir = os.path.join(base, PACKAGED_SUBDIR)
        os.makedirs(data_dir, exist_ok=True)
        return os.path.join(data_dir, SETTINGS_FILENAME)
    return os.path.join(os.getcwd(), "canyp-settings.json")


def load_settings(path: str | None = None) -> AppSettings:
    """Load settings; a missing or malformed file falls back to defaults.

    Unknown ``dataMode`` values also fall back to "local" so old/corrupt
    files never crash the app.
    """
    path = path or default_settings_path()
    if not os.path.exists(path):
        return AppSettings()
    try:
        # utf-8-sig tolerates a UTF-8 BOM (Windows PowerShell/Notepad write one),
        # so a manually edited settings file never silently falls back to local.
        with open(path, "r", encoding="utf-8-sig") as fh:
            raw = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return AppSettings()
    return _from_dict(raw)


def save_settings(settings: AppSettings, path: str | None = None) -> None:
    """Persist settings atomically (temp file + os.replace)."""
    path = path or default_settings_path()
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=parent, prefix=".canyp-settings-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(asdict(settings), fh, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise SettingsError(f"no se pudieron guardar los ajustes en {path}")


def _from_dict(raw: dict) -> AppSettings:
    if not isinstance(raw, dict):
        return AppSettings()
    data_mode = raw.get("dataMode")
    if data_mode not in DATA_MODES:
        data_mode = DEFAULT_DATA_MODE
    return AppSettings(
        dataMode=data_mode,
        databaseUrl=str(raw.get("databaseUrl") or ""),
        configured=bool(raw.get("configured", False)),
    )