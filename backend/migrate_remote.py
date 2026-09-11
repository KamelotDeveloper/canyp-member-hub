"""One-way idempotent migration of the local SQLite DB (canyp.db) to remote PostgreSQL (Supabase).

Run from the repository root so the ``backend`` package imports work:

    python backend/migrate_remote.py [--check] [--replace]

Behaviour
---------
- Reads the persisted settings (``canyp-settings.json`` in cwd) via
  ``backend.settings_store.load_settings``. A migration is only allowed when
  ``dataMode == "remoto"`` and ``databaseUrl`` is non-empty.
- Targets are overridable for local testing via env vars; when overridden,
  the settings/mode validation is skipped so tests never touch the cloud:

    MIGRATE_SOURCE_URL=sqlite:///.../source.db
    MIGRATE_TARGET_URL=sqlite:///.../target.db

  The script itself still defaults to the real settings for production use.
- Before copying, a consistent SQLite snapshot is written to
  ``backups/migracion-<YYYYMMDD-HHMMSS>/`` (``VACUUM INTO``, with a DBAPI
  ``backup()`` fallback) plus a small readme.
- ``--check`` connects to the target, reports per-table row counts for source
  and target, and prints a compact ``tabla | origen | nube`` table.
- Full mode creates the schema via ``Base.metadata.create_all`` and copies rows
  in FK-safe order using chunked ``executemany`` (500 rows), committing once per
  table so a mid-run failure is recoverable. Existing target rows are skipped
  unless ``--replace`` deletes them first (FK-safe reverse order).
- Dates: modern rows are ISO strings handled by the SQLAlchemy ``Date`` type.
  If a legacy row holds a non-ISO string, the row is re-read raw and parsed with
  ``dateutil`` best-effort; unparseable rows are skipped and reported visibly.
- Money is ``Float``; that is the existing domain design and is preserved as-is.

SECURITY: ``databaseUrl`` (and any part of it) is NEVER printed, logged,
written, or otherwise surfaced. All diagnostics are generic; error messages
carry only the exception class name. Env overrides are also never printed.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

from dateutil import parser as dateutil_parser
from sqlalchemy import JSON, Boolean, Date, create_engine, func, insert, inspect, select
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.sql.schema import Table

# Make ``backend`` importable regardless of how the script is invoked.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.database import Base  # noqa: E402
from backend.settings_store import load_settings  # noqa: E402
import backend.models  # noqa: E402, F401  (registers every model on Base.metadata)

# NOTE: money is Float in the domain model; preserved as-is, never changed here.

DEFAULT_DB_FILE = REPO_ROOT / "canyp.db"
CHUNK_SIZE = 500
BACKUPS_DIR = REPO_ROOT / "backups"


class MigrationError(Exception):
    """Generic, secret-free failure surfaced to the user."""


# ---------------------------------------------------------------------------
# Engines
# ---------------------------------------------------------------------------


def _normalize_postgres_url(url: str) -> str:
    """Force the declared psycopg 3 driver for bare ``postgresql://`` URLs
    (SQLAlchemy 2.x still defaults bare ``postgresql://`` to psycopg2)."""
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def _build_source_engine(url: str) -> Engine:
    """Source is local SQLite in practice; the env override keeps it testable."""
    return create_engine(url, connect_args={"check_same_thread": False})


def _build_target_engine(url: str) -> Engine:
    """Target engine with pool_pre_ping; Postgres gets a small desktop-side pool."""
    if url.startswith("postgresql"):
        return create_engine(
            _normalize_postgres_url(url),
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=5,
        )
    return create_engine(url, pool_pre_ping=True, connect_args={"check_same_thread": False})


# ---------------------------------------------------------------------------
# Backup (pre-migration snapshot)
# ---------------------------------------------------------------------------


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _sqlite_quote(path: str) -> str:
    return path.replace("'", "''")


def _verify_snapshot(snapshot: Path) -> None:
    if not snapshot.exists() or snapshot.stat().st_size == 0:
        raise IOError("snapshot vacía o ausente")
    conn = sqlite3.connect(str(snapshot))
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
        if row[0] != "ok":
            raise IOError(f"integridad del snapshot: {row[0]}")
    finally:
        conn.close()


def create_pre_migration_backup(source_engine: Engine) -> Path:
    """Consistent SQLite snapshot via ``VACUUM INTO``; DBAPI ``backup()`` fallback."""
    ts = _timestamp()
    backup_dir = BACKUPS_DIR / f"migracion-{ts}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    snapshot = backup_dir / "canyp-pre-migracion.db"

    done = False
    try:
        raw = source_engine.raw_connection()
        try:
            raw.isolation_level = None  # autocommit: VACUUM can't run in a transaction
            cur = raw.cursor()
            cur.execute(f"VACUUM INTO '{_sqlite_quote(str(snapshot))}'")
            cur.close()
            raw.commit()
        finally:
            raw.close()
        _verify_snapshot(snapshot)
        done = True
    except Exception:
        done = False

    if not done:
        src_raw = source_engine.raw_connection()
        try:
            dest = sqlite3.connect(str(snapshot))
            try:
                src_raw.backup(dest)
            finally:
                dest.close()
            _verify_snapshot(snapshot)
        finally:
            src_raw.close()

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    readme = backup_dir / "readme.txt"
    readme.write_text(
        "Copia de seguridad previa a la migración a la base remota.\n"
        f"Fecha: {now}\n"
        "Origen local: canyp.db\n"
        "Este snapshot consistente se tomó antes de migrar los datos a PostgreSQL (Supabase).\n",
        encoding="utf-8",
    )
    return backup_dir


# ---------------------------------------------------------------------------
# Reading source rows (typed first; raw fallback normalizes legacy values)
# ---------------------------------------------------------------------------

_DATE_FALLBACK_EXC = (ValueError, TypeError, OverflowError, IndexError)


def _normalize_date(value: Any) -> datetime.date | None:
    """Best-effort date normalization: ISO first, then dateutil, or raise."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = str(value)
    try:
        return date.fromisoformat(raw)
    except ValueError:
        pass
    try:
        return dateutil_parser.parse(raw).date()
    except (ValueError, OverflowError, TypeError):
        raise ValueError(f"fecha no reconocida: {raw!r}") from None


def _coerce_bool(value: Any) -> Any:
    if value in (True, 1, "1", "t", "true", "TRUE"):
        return True
    if value in (False, 0, "0", "f", "false", "FALSE", ""):
        return False
    return bool(value)


def _read_typed(src_conn: Connection, table: Table) -> list[dict[str, Any]]:
    """Read every row through the Table, letting SQLAlchemy apply Date/JSON/Enum handling."""
    rows: list[dict[str, Any]] = []
    result = src_conn.execution_options(yield_per=CHUNK_SIZE).execute(select(table))
    for row in result.mappings():
        rows.append(dict(row))
    result.close()
    return rows


def _read_raw_normalized(src_conn: Connection, table: Table) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Legacy fallback: raw driver read with per-cell normalization.

    Successful rows come back ready for the target INSERT. Rows whose cells
    cannot be normalized (e.g. an unrecognizable date) are isolated here and
    returned as failures so the caller can report them without aborting.
    """
    col_types = {c.name: c.type for c in table.columns}
    date_cols = {n for n, t in col_types.items() if isinstance(t, Date)}
    json_cols = {n for n, t in col_types.items() if isinstance(t, JSON)}
    bool_cols = {n for n, t in col_types.items() if isinstance(t, Boolean)}
    pk_cols = [c.name for c in table.primary_key.columns]

    result = src_conn.exec_driver_sql(f'SELECT * FROM "{table.name}"')
    found = list(result.keys())
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for rec in result.mappings():
        row: dict[str, Any] = {}
        problem: str | None = None
        for name in table.columns.keys():
            if name not in found:
                raise MigrationError(f"columna '{name}' ausente en el origen")
            value = rec[name]
            if value is None:
                row[name] = None
                continue
            try:
                if name in date_cols:
                    row[name] = _normalize_date(value)
                elif name in json_cols:
                    row[name] = json.loads(value) if isinstance(value, str) else value
                elif name in bool_cols:
                    row[name] = _coerce_bool(value)
                else:
                    row[name] = value
            except (ValueError, TypeError, OverflowError, IndexError) as exc:
                problem = f"columna '{name}': {exc}"
                break
        if problem is not None:
            pk_value = " | ".join(str(rec.get(c, "?")) for c in pk_cols)
            failures.append({"tabla": table.name, "id": pk_value, "error": problem})
            continue
        rows.append(row)
    result.close()
    return rows, failures


def _load_source_rows(source_engine: Engine, table: Table) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Typed read preferred; falls back to raw normalization for legacy data shapes."""
    with source_engine.connect() as conn:
        try:
            return _read_typed(conn, table), []
        except _DATE_FALLBACK_EXC:
            return _read_raw_normalized(conn, table)


# ---------------------------------------------------------------------------
# Copying to target
# ---------------------------------------------------------------------------


def _insert_batched(target_engine: Engine, table: Table, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    stmt = insert(table)
    inserted = 0
    with target_engine.connect() as conn:
        with conn.begin():  # explicit transaction; committed once per table
            for i in range(0, len(rows), CHUNK_SIZE):
                conn.execute(stmt, rows[i : i + CHUNK_SIZE])
                inserted += min(CHUNK_SIZE, len(rows) - i)
    return inserted


def _delete_all_rows(target_engine: Engine, tables: list[Table]) -> None:
    inspector = inspect(target_engine)
    with target_engine.connect() as conn:
        with conn.begin():
            for table in reversed(tables):  # FK-safe reverse order
                if inspector.has_table(table.name):
                    conn.execute(table.delete())


# ---------------------------------------------------------------------------
# Counting / reporting
# ---------------------------------------------------------------------------


def _count(engine: Engine, table: Table) -> int:
    with engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(table)).scalar_one()


def _table_has_rows(engine: Engine, table: Table) -> bool:
    """Fresh inspect() per call: the inspector cache would go stale across create_all."""
    if not inspect(engine).has_table(table.name):
        return False
    return _count(engine, table) > 0


def _target_count_or_dash(target_engine: Engine, table: Table) -> str:
    if not inspect(target_engine).has_table(table.name):
        return "-"
    return str(_count(target_engine, table))


def _print_counts_table(rows: list[tuple[str, ...]]) -> None:
    header = ("tabla", "origen", "nube")
    widths = [len(h) for h in header]
    for r in rows:
        for i, v in enumerate(r):
            if i >= len(widths):
                widths.append(len(str(v)))
            widths[i] = max(widths[i], len(str(v)))
    print(" | ".join(h.ljust(widths[i]) for i, h in enumerate(header)))
    print("-+-".join("-" * w for w in widths))
    for r in rows:
        print(" | ".join(str(v).ljust(widths[i]) for i, v in enumerate(r)))


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------


def run_check(source_engine: Engine, target_engine: Engine, override_target: bool) -> int:
    # Target reachability first: report success/failure WITHOUT connection details.
    try:
        with target_engine.connect():
            pass
    except Exception as exc:
        print(f"No se pudo conectar con la base remota ({type(exc).__name__}).")
        return 1
    print("conexión a Supabase OK" if not override_target else "conexión al destino OK")

    rows: list[tuple[str, str, str]] = []
    for table in Base.metadata.sorted_tables:
        src = _count(source_engine, table)
        dst = _target_count_or_dash(target_engine, table)
        rows.append((table.name, str(src), dst))
    print("\nConteo por tabla:")
    _print_counts_table(rows)
    return 0


def run_migrate(
    source_engine: Engine,
    target_engine: Engine,
    replace: bool,
    override_target: bool,
) -> int:
    # Pre-migration backup is mandatory risk mitigation; abort if it cannot be made.
    try:
        backup_dir = create_pre_migration_backup(source_engine)
    except MigrationError as exc:
        print(f"No se pudo crear la copia de seguridad previa: {exc}.")
        return 1
    except Exception as exc:
        print(f"No se pudo crear la copia de seguridad previa ({type(exc).__name__}). Abortando.")
        return 1
    print(f"Copia de seguridad previa creada en {backup_dir}")

    try:
        with target_engine.connect():
            pass
    except Exception as exc:
        print(f"No se pudo conectar con la base remota ({type(exc).__name__}).")
        return 1
    print("conexión a Supabase OK" if not override_target else "conexión al destino OK")

    tables = list(Base.metadata.sorted_tables)

    print("Creando el esquema en la base remota...")
    try:
        Base.metadata.create_all(bind=target_engine)
    except Exception as exc:
        print(f"No se pudo crear el esquema remoto ({type(exc).__name__}).")
        return 1

    if replace:
        print("--replace: eliminando los datos existentes en la base remota...")
        try:
            _delete_all_rows(target_engine, tables)
        except Exception as exc:
            print(f"No se pudieron limpiar los datos remotos ({type(exc).__name__}).")
            return 1

    copied_counts: dict[str, int] = {}
    skipped: list[str] = []
    failures: list[dict[str, Any]] = []

    for table in tables:
        src_count = _count(source_engine, table)
        target_has_rows = _table_has_rows(target_engine, table)
        if target_has_rows and not replace:
            skipped.append(table.name)
            copied_counts[table.name] = src_count
            print(f"Tabla omitida '{table.name}': ya tiene datos en la base remota.")
            continue

        try:
            rows, table_failures = _load_source_rows(source_engine, table)
            inserted = _insert_batched(target_engine, table, rows)
        except Exception as exc:
            print(
                f"Error copiando la tabla '{table.name}' ({type(exc).__name__}). "
                "La migración quedó interrumpida; las tablas ya copiadas se conservan. "
                "Revisá el error indicado y volvé a ejecutar."
            )
            return 1
        copied_counts[table.name] = src_count
        failures.extend(table_failures)
        print(f"Tabla '{table.name}': {inserted} filas copiadas.")

    if failures:
        print("\nFilas omitidas por datos no normalizables (revisá el origen):")
        for f in failures:
            print(f"  {f['tabla']} id={f['id']}: {f['error']}")

    # Final verification: per-table target vs source counts.
    print("\nVerificación final: tabla | origen | nube | estado")
    ok = True
    verify_rows: list[tuple[str, str, str, str]] = []
    for table in tables:
        name = table.name
        src = copied_counts.get(name, _count(source_engine, table))
        dst = _count(target_engine, table)
        if name in skipped:
            estado = "SALTEADA"
        elif src == dst:
            estado = "OK"
        else:
            estado = "DIFERENCIA"
            ok = False
        verify_rows.append((name, str(src), str(dst), estado))
    _print_counts_table(verify_rows)

    if skipped and not failures:
        print(
            f"Tablas omitidas (ya tenían datos en la nube): {', '.join(skipped)}. "
            "Usá --replace para reemplazarlas."
        )
    if ok:
        print("Migración finalizada correctamente.")
        return 0
    print("La migración finalizó con diferencias de conteo. Revisá el informe anterior.")
    return 1


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="migrate_remote", description=__doc__)
    parser.add_argument("--check", action="store_true", help="solo verificación de conexión y conteos")
    parser.add_argument("--replace", action="store_true", help="reemplazar filas existentes en la base remota")
    args = parser.parse_args(argv)

    # Resolve source/target URLs. Env overrides exist only for LOCAL tests; the
    # production default reads persisted settings.
    override_target = bool(os.environ.get("MIGRATE_TARGET_URL"))
    source_url = os.environ.get("MIGRATE_SOURCE_URL") or f"sqlite:///{DEFAULT_DB_FILE.as_posix()}"
    target_url = os.environ.get("MIGRATE_TARGET_URL") or ""

    if not override_target:
        settings = load_settings()
        if settings.dataMode != "remoto" or not settings.databaseUrl:
            print(
                "No está configurado el modo remoto en los ajustes, o falta la URL "
                "de la base de datos. Abortando."
            )
            return 1
        target_url = settings.databaseUrl

    if not os.environ.get("MIGRATE_SOURCE_URL") and not DEFAULT_DB_FILE.exists():
        print(f"No se encontró la base local {DEFAULT_DB_FILE.name} en la raíz del proyecto.")
        return 1

    source_engine = _build_source_engine(source_url)
    target_engine = _build_target_engine(target_url)

    try:
        if args.check:
            return run_check(source_engine, target_engine, override_target)
        return run_migrate(source_engine, target_engine, args.replace, override_target)
    except SystemExit:
        raise
    except Exception as exc:  # last-resort guard: no traceback, no secrets
        print(f"Error inesperado ({type(exc).__name__}). No se expone ningún detalle de conexión.")
        return 1
    finally:
        source_engine.dispose()
        target_engine.dispose()


if __name__ == "__main__":
    sys.exit(main())