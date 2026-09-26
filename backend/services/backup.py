"""Local full-database backup service.

The sidecar keeps a single SQLite dump of ALL data: ``backups/canyp-backup.db``
in the same location family as ``settings_store`` (``%APPDATA%/CANYP/backups/``
when packaged, ``cwd/backups/`` in dev/tests). A meta file
(``canyp-backup-meta.json``) records the last run; a new dump is only produced
when the interval (default 15 days) has elapsed. Files are written atomically
(temp file + ``os.replace``).

The dump works against any source dialect (local SQLite or remote Postgres):
tables are reflected, recreated, and fully re-inserted into the target SQLite
file. When the source is already SQLite the file is just copied (fast path).
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import MetaData, Table, create_engine, inspect, text

BACKUP_FILENAME = "canyp-backup.db"
META_FILENAME = "canyp-backup-meta.json"
BACKUP_SUBDIR = "backups"
PACKAGED_SUBDIR = "CANYP"
DEFAULT_INTERVAL_DAYS = 15


def get_backup_dir() -> Path:
    """Resolve the backup directory for the current runtime, creating it."""
    if getattr(sys, "frozen", False):
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        backup_dir = Path(base) / PACKAGED_SUBDIR / BACKUP_SUBDIR
    else:
        backup_dir = Path(os.getcwd()) / BACKUP_SUBDIR
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def get_backup_db_path() -> Path:
    """Where the (single, overwritten) SQLite backup lives."""
    return get_backup_dir() / BACKUP_FILENAME


def get_backup_meta_path() -> Path:
    """JSON meta file storing ``{"last_backup": "ISO timestamp"}``."""
    return get_backup_dir() / META_FILENAME


def should_backup(interval_days: int = DEFAULT_INTERVAL_DAYS) -> bool:
    """True when no meta exists or the last backup is >= interval_days old.

    A missing/corrupt meta file counts as "never backed up".
    """
    meta_path = get_backup_meta_path()
    if not meta_path.exists():
        return True
    try:
        with open(meta_path, "r", encoding="utf-8") as fh:
            meta = json.load(fh)
        last = datetime.fromisoformat(str(meta["last_backup"]))
    except (OSError, ValueError, KeyError, TypeError):
        return True
    return datetime.now() - last >= timedelta(days=interval_days)


def save_backup_meta() -> None:
    """Persist the current ISO timestamp atomically to the meta file."""
    meta_path = get_backup_meta_path()
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=str(meta_path.parent), prefix=".canyp-backup-meta-", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"last_backup": datetime.now().isoformat()}, fh)
        os.replace(tmp, meta_path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def create_backup(source_engine) -> dict:
    """Dump ALL source tables into a fresh SQLite file at the backup path.

    Sync source engines already point at SQLite files — skip reflection and
    copy the file instead. Postgres (or any non-SQLite source) is reflected
    table by table and re-inserted. Foreign keys are disabled on the target
    while inserting so rows can be written in any order.
    """
    backup_path = get_backup_db_path()
    backup_path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp = tempfile.mkstemp(dir=str(backup_path.parent), prefix=".canyp-backup-", suffix=".db")
    os.close(fd)
    temp_path = Path(tmp)

    try:
        if source_engine.dialect.name == "sqlite":
            _copy_sqlite_source(source_engine, temp_path)
            tables, rows = _count_sqlite(source_engine)
        else:
            tables, rows = _dump_via_reflection(source_engine, temp_path)
        os.replace(temp_path, backup_path)
    except Exception:
        try:
            os.remove(temp_path)
        except OSError:
            pass
        raise

    return {"tables": tables, "rows": rows, "path": str(backup_path)}


def run_backup_if_needed(source_engine) -> dict | None:
    """Create a backup only when due; returns the result dict or None."""
    if not should_backup():
        return None
    result = create_backup(source_engine)
    save_backup_meta()
    return result


def _copy_sqlite_source(source_engine, temp_path: Path) -> None:
    """Fast path: same file format, so copy the (WAL-checkpointed) file."""
    with source_engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
    source_file = source_engine.url.database
    if not source_file or not os.path.exists(source_file):
        raise FileNotFoundError(f"source SQLite file not found: {source_file}")
    shutil.copy2(source_file, temp_path)


def _count_sqlite(source_engine) -> tuple[int, dict]:
    """Row counts per table (cheap SELECT count(*) on the SQLite fast path)."""
    table_names = inspect(source_engine).get_table_names()
    rows: dict[str, int] = {}
    with source_engine.connect() as conn:
        for name in table_names:
            rows[name] = conn.execute(
                text(f"SELECT COUNT(*) FROM {name}")
            ).scalar() or 0
    return len(table_names), rows


def _dump_via_reflection(source_engine, temp_path: Path) -> tuple[int, dict]:
    """Reflect every source table and recreate + refill it in SQLite."""
    target_engine = create_engine(f"sqlite:///{temp_path}")
    try:
        table_names = inspect(source_engine).get_table_names()
        source_meta = MetaData()
        for name in table_names:
            Table(name, source_meta, autoload_with=source_engine)

        target_meta = MetaData()
        for source_table in source_meta.tables.values():
            source_table.to_metadata(target_meta)
        target_meta.create_all(target_engine)

        rows: dict[str, int] = {}
        with target_engine.connect() as target_conn, source_engine.connect() as source_conn:
            raw = target_conn.connection.driver_connection
            cursor = raw.cursor()
            cursor.execute("PRAGMA foreign_keys=OFF")
            cursor.close()
            try:
                for name in table_names:
                    source_rows = source_conn.execute(source_meta.tables[name].select()).fetchall()
                    if source_rows:
                        target_conn.execute(
                            target_meta.tables[name].insert(),
                            [dict(row._mapping) for row in source_rows],
                        )
                    rows[name] = len(source_rows)
                target_conn.commit()
            finally:
                cursor = raw.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()
        return len(table_names), rows
    finally:
        target_engine.dispose()