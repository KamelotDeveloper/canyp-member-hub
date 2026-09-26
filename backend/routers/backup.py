"""Backup endpoints: manual trigger + status."""

import json
from datetime import datetime, timedelta

from fastapi import APIRouter

from backend.database import engine
from backend.services.backup import (
    DEFAULT_INTERVAL_DAYS,
    get_backup_meta_path,
    run_backup_if_needed,
)

router = APIRouter(prefix="/api/backup", tags=["backup"])


@router.post("")
def create_backup_now():
    """Run a backup only when due. Skipped (no-op) when up to date."""
    result = run_backup_if_needed(engine)
    if result is None:
        return {"status": "skipped", "message": "Backup is up to date"}
    return {"status": "created", **result}


@router.get("/status")
def backup_status():
    """Last/next backup timestamps computed from the meta file."""
    last_backup: str | None = None
    meta_path = get_backup_meta_path()
    if meta_path.exists():
        try:
            with open(meta_path, "r", encoding="utf-8") as fh:
                meta = json.load(fh)
            last_backup = str(meta["last_backup"])
        except (OSError, ValueError, KeyError, TypeError):
            last_backup = None

    if last_backup:
        last = datetime.fromisoformat(last_backup)
        next_backup = (last + timedelta(days=DEFAULT_INTERVAL_DAYS)).isoformat()
        overdue = datetime.now() > last + timedelta(days=DEFAULT_INTERVAL_DAYS)
    else:
        next_backup = None
        overdue = True
    return {"last_backup": last_backup, "next_backup": next_backup, "overdue": overdue}