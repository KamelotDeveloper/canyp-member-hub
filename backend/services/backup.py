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

FIDELITY: "backup ok" MEANS RESTORABLE
--------------------------------------
    A dump that cannot be restored is worse than no dump, because it looks like
    insurance. Two properties are enforced here, not assumed:

* **Fidelity.** Postgres types SQLite cannot compile (``BYTEA``, native
  ``ENUM``, ``DOUBLE_PRECISION``, ``JSONB``, ``UUID``, ``ARRAY``) are
  PROJECTED to their SQLite equivalent by :func:`tipo_sqlite` instead of being
  copied verbatim. ``Table.to_metadata`` copies type objects *by reference*, so
  a reflected ``BYTEA`` reaches ``create_all`` unchanged and the SQLite compiler
  raises ``UnsupportedCompilationError`` — which is exactly how this service
  used to die on every remote backup. Any type with no declared projection
  raises :class:`TipoNoRespaldable` rather than being coerced to TEXT: a silent
  coercion would produce a dump that restores but lies.
* **Verification.** The dump is built into a temp file and only then moved into
  place. Before the move, :func:`_verificar_volcado` re-opens that file and
  compares it against the source row by row (counts AND values, keyed by
  primary key). A mismatch raises :func:`VerificacionBackupFallida` and the temp
  file is deleted, so a rejected dump never replaces a good one. A dump with no
  tables at all is rejected too: that is what a database that does not exist
  looks like, and reporting it as a backup is the failure mode this check exists
  to prevent.

FAIL-CLOSED
-----------
``estado_backup`` / ``asegurar_backup`` expose the recovery point as a single
question — *is there a restorable dump right now?* — so the HTTP layer can
refuse writes when there is not (see ``backend/middleware.py``). A failed dump
is remembered as a failure instead of disappearing, and the lifespan's
best-effort background backup still cannot take the app down: it only decides
whether writes are allowed afterwards.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import (
    ARRAY,
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum as SAEnum,
    Float,
    Integer,
    LargeBinary,
    MetaData,
    Numeric,
    String,
    Table,
    Uuid,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.types import TypeEngine

BACKUP_FILENAME = "canyp-backup.db"
META_FILENAME = "canyp-backup-meta.json"
BACKUP_SUBDIR = "backups"
PACKAGED_SUBDIR = "CANYP"
DEFAULT_INTERVAL_DAYS = 15

# Backup health states. ``ok`` is the ONLY one that permits a write.
ESTADO_OK = "ok"
ESTADO_PENDIENTE = "pendiente"
ESTADO_EN_CURSO = "en_curso"
ESTADO_FALLO = "fallo"


class BackupError(RuntimeError):
    """The backup could not be produced, so it must not be published."""


class TipoNoRespaldable(BackupError):
    """A source column type has no declared SQLite projection.

    Raised instead of coercing an unknown type to TEXT. A dump that restores
    but mangles money or a UUID is not a backup, and the operator has no way to
    tell from the outside that it happened.
    """


class VerificacionBackupFallida(BackupError):
    """The written dump does not match the source; it is rejected, not kept."""


@dataclass
class IntentoBackup:
    """The last dump attempt in this process, kept for the write gate."""

    momento: datetime
    ok: bool
    detalle: str | None = None


@dataclass
class EstadoBackup:
    """Whether a restorable dump exists right now, and why not when it doesn't."""

    estado: str
    detalle: str | None = None

    @property
    def ok(self) -> bool:
        return self.estado == ESTADO_OK


# Guarded writes: the lifespan thread, the HTTP guard and an operator pressing
# "backup" can all reach ``create_backup`` at once. Serialising the *gate* (not
# the dump) is enough — concurrent dumps write distinct temp files and the last
# ``os.replace`` wins with a file that is individually valid.
_LOCK_GATE = threading.Lock()
_INTENTO: IntentoBackup | None = None
_DUMP_EN_CURSO = False


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


# ── backup health: the question the write gate asks ─────────────────────────


def estado_backup(interval_days: int = DEFAULT_INTERVAL_DAYS) -> EstadoBackup:
    """Is there a restorable dump to fall back on right now?

    A dump on disk that is still inside the interval is a real recovery point
    even if a later attempt failed, so the file is consulted FIRST: the gate
    must not refuse a write while a good backup is sitting there.
    """
    backup_path = get_backup_db_path()
    if backup_path.exists() and not should_backup(interval_days):
        return EstadoBackup(ESTADO_OK)
    if _DUMP_EN_CURSO:
        return EstadoBackup(ESTADO_EN_CURSO, "backup en curso")
    intento = _INTENTO
    if intento is not None and not intento.ok:
        return EstadoBackup(ESTADO_FALLO, intento.detalle)
    if backup_path.exists():
        # Due, but a dump from the last cycle is still on disk and usable.
        return EstadoBackup(ESTADO_OK)
    return EstadoBackup(ESTADO_PENDIENTE, "todavía no hay ningún backup")


def asegurar_backup(source_engine) -> str | None:
    """Gate for writes: ``None`` when writing is allowed, else the reason.

    A due backup is produced on demand rather than refused, so an app left
    running past the interval never wedges itself. Only a genuine failure —
    the dump could not be written or did not verify — blocks the write.
    """
    estado = estado_backup()
    if estado.ok:
        return None
    with _LOCK_GATE:
        # Another thread may have produced the dump while we waited.
        estado = estado_backup()
        if estado.ok:
            return None
        try:
            run_backup_if_needed(source_engine)
        except Exception as exc:
            return estado_backup().detalle or f"backup falló: {exc}"
        estado = estado_backup()
        return None if estado.ok else (estado.detalle or "no hay backup restaurable")


# ── type projection: source dialect -> SQLite ───────────────────────────────


def tipo_sqlite(tipo: TypeEngine) -> TypeEngine:
    """Project a reflected source type onto one SQLite can compile and read back.

    Order matters: every branch is checked before the generic pass-throughs
    because the Postgres types are subclasses of the generic ones (``BYTEA`` of
    ``LargeBinary``, ``JSONB`` of ``JSON``, ``UUID`` of ``Uuid``, ``ENUM`` of
    ``Enum``, ``DOUBLE_PRECISION`` of ``Float``).

    Anything undeclared raises. A dump that quietly stores a type as TEXT
    restores and is wrong, and nothing downstream would notice.
    """
    # Binary: bytes -> BLOB, byte for byte.
    if isinstance(tipo, LargeBinary):
        return LargeBinary()
    # Native enum: keep the domain as a CHECK constraint, lose only the PG type.
    # `create_constraint` defaults to False in SQLAlchemy 2.0, which would drop
    # the allowed values silently: the dump would restore but no longer say
    # which states exist.
    if isinstance(tipo, SAEnum):
        valores = list(getattr(tipo, "enums", None) or [])
        return SAEnum(
            *valores,
            name=getattr(tipo, "name", None),
            native_enum=False,
            create_constraint=True,
        )
    # JSON/JSONB: SQLite stores the serialized document; SQLAlchemy round-trips it.
    if isinstance(tipo, JSON):
        return JSON()
    # UUID: SQLite has no native type; 36 chars is the canonical text form.
    if isinstance(tipo, Uuid):
        return String(36)
    # Arrays have no SQLite counterpart: keep the elements as a JSON document so
    # no value is dropped.
    if isinstance(tipo, ARRAY):
        return String()
    # Double precision is a Python float; SQLite REAL is the same 8 bytes.
    if isinstance(tipo, Float):
        return Float()
    if isinstance(tipo, DateTime):
        return DateTime()
    # Types SQLite already renders natively, passed through untouched.
    if isinstance(tipo, (String, Integer, Numeric, Boolean, Date)):
        return tipo
    raise TipoNoRespaldable(
        f"el tipo {tipo!r} no tiene proyección declarada a SQLite: no se puede "
        f"respaldar sin perder fidelidad. Declaralo en tipo_sqlite()."
    )


def _normalizar_valor(valor, tipo_destino: TypeEngine):
    """Coerce a driver value into something the SQLite column can hold.

    Deliberately narrow: only the conversions the driver actually forces
    (UUID objects, PG arrays, tz-aware timestamps). Anything unexpected is left
    alone so SQLite raises instead of the dump silently changing a value — and
    so :func:`_verificar_volcado` is the judge of whether the result is faithful.
    """
    if valor is None:
        return None
    if isinstance(valor, uuid.UUID):
        return str(valor)
    if isinstance(valor, datetime):
        # SQLite DATETIME has no offset: normalise to naive UTC so the stored
        # instant is unambiguous (the live schema uses naive timestamps, so this
        # only matters if a tz-aware column is added later). `astimezone(None)`
        # would convert to the machine's LOCAL time, which is not the same thing.
        return valor.astimezone(timezone.utc).replace(tzinfo=None) if valor.tzinfo else valor
    if isinstance(valor, (list, tuple)) and isinstance(tipo_destino, String):
        return json.dumps(list(valor), default=str)
    if isinstance(valor, Decimal) and isinstance(tipo_destino, (Float, Numeric)):
        return float(valor)
    return valor


def _proyectar_tipos(target_meta: MetaData) -> None:
    """Make the reflected schema compilable by SQLite, in place.

    ``to_metadata`` has already copied constraints, indexes and defaults by
    this point, so only types and server defaults are dealt with here.
    """
    for tabla in target_meta.tables.values():
        for columna in tabla.columns:
            proyectado = tipo_sqlite(columna.type)
            columna.type = proyectado
            # Server defaults are SCHEMA, and this schema is schema: the app
            # rebuilds it from the models on startup (`create_all` in the
            # lifespan). The dump only has to carry ROWS, and a reflected
            # Postgres default is usually DDL SQLite cannot even parse
            # (`nextval('seq'::regclass)`). Dropping it loses nothing that
            # survives a restore, and keeping it loses the whole dump.
            columna.server_default = None
            columna.default = None
            # A type learns about its table when the Column is BUILT, which is
            # why `sa.Enum` emits its CHECK from `_set_table`. The type is
            # replaced after the fact here, so it has to be re-bound or the
            # domain is dropped silently: the dump would restore the values but
            # stop saying which ones are legal, and `create_all` does not
            # retrofit constraints onto an existing table.
            enlazar = getattr(proyectado, "_set_table", None)
            if enlazar is not None:
                enlazar(columna, tabla)


# ── the dump ────────────────────────────────────────────────────────────────


def create_backup(source_engine) -> dict:
    """Dump ALL source tables into a verified SQLite file at the backup path.

    Sync source engines already point at SQLite files — skip reflection and
    copy the file instead. Postgres (or any non-SQLite source) is reflected
    table by table and re-inserted, with source types projected to SQLite ones
    and the result verified against the source before it is published.

    Raises on any failure, leaving the previous backup in place: a broken
    backup must never overwrite a working one.
    """
    global _INTENTO, _DUMP_EN_CURSO

    backup_path = get_backup_db_path()
    backup_path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp = tempfile.mkstemp(dir=str(backup_path.parent), prefix=".canyp-backup-", suffix=".db")
    os.close(fd)
    temp_path = Path(tmp)

    _DUMP_EN_CURSO = True
    try:
        if source_engine.dialect.name == "sqlite":
            _copy_sqlite_source(source_engine, temp_path)
            tablas, filas = _count_sqlite(source_engine)
        else:
            tablas, filas = _dump_via_reflection(source_engine, temp_path)
        _verificar_volcado(source_engine, temp_path, tablas, filas)
        os.replace(temp_path, backup_path)
    except Exception as exc:
        try:
            os.remove(temp_path)
        except OSError:
            pass
        _INTENTO = IntentoBackup(datetime.now(), ok=False, detalle=f"{type(exc).__name__}: {exc}")
        _DUMP_EN_CURSO = False
        raise
    _DUMP_EN_CURSO = False
    _INTENTO = IntentoBackup(datetime.now(), ok=True)
    return {"tables": tablas, "rows": filas, "path": str(backup_path)}


def run_backup_if_needed(source_engine) -> dict | None:
    """Create a backup only when due; returns the result dict or None.

    Failures propagate to the caller (the HTTP endpoint reports them) but are
    also recorded, so the write gate knows a dump is not available.
    """
    if not should_backup():
        return None
    result = create_backup(source_engine)
    save_backup_meta()
    return result


def _copy_sqlite_source(source_engine, temp_path: Path) -> None:
    """Fast path: same file format, so copy the (WAL-checkpointed) file."""
    source_file = source_engine.url.database
    # Existence is checked BEFORE connecting on purpose: opening a SQLite URL
    # CREATES the file, so checking afterwards would happily "back up" a
    # database that was never there — an empty dump that reports success.
    if not source_file or not os.path.exists(source_file):
        raise FileNotFoundError(f"source SQLite file not found: {source_file}")
    with source_engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
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
    """Reflect every source table and recreate + refill it in SQLite.

    The source is read through a single REPEATABLE READ snapshot: the dump is
    assembled row by row, and a write landing halfway through would otherwise
    produce a torn snapshot that no row count would catch.
    """
    target_engine = create_engine(f"sqlite:///{temp_path}")
    try:
        table_names = inspect(source_engine).get_table_names()
        source_meta = MetaData()
        for name in table_names:
            Table(name, source_meta, autoload_with=source_engine)

        target_meta = MetaData()
        for source_table in source_meta.tables.values():
            source_table.to_metadata(target_meta)
        # The whole point: reflected Postgres types are NOT SQLite types.
        _proyectar_tipos(target_meta)
        target_meta.create_all(target_engine)

        rows: dict[str, int] = {}
        with _snapshot_consistente(source_engine) as source_conn:
            with target_engine.connect() as target_conn:
                raw = target_conn.connection.driver_connection
                cursor = raw.cursor()
                cursor.execute("PRAGMA foreign_keys=OFF")
                cursor.close()
                try:
                    for name in table_names:
                        tabla_origen = source_meta.tables[name]
                        tabla_destino = target_meta.tables[name]
                        source_rows = source_conn.execute(tabla_origen.select()).fetchall()
                        if source_rows:
                            destino_cols = {c.name: c.type for c in tabla_destino.columns}
                            payload = [
                                {
                                    clave: _normalizar_valor(valor, destino_cols.get(clave))
                                    for clave, valor in dict(fila._mapping).items()
                                }
                                for fila in source_rows
                            ]
                            target_conn.execute(tabla_destino.insert(), payload)
                        rows[name] = len(source_rows)
                    target_conn.commit()
                finally:
                    cursor = raw.cursor()
                    cursor.execute("PRAGMA foreign_keys=ON")
                    cursor.close()
        return len(table_names), rows
    finally:
        target_engine.dispose()


def _snapshot_consistente(source_engine):
    """Source connection pinned to a REPEATABLE READ snapshot when supported."""
    conn = source_engine.connect()
    try:
        return conn.execution_options(isolation_level="REPEATABLE READ")
    except Exception:
        return conn


# ── verification: the dump must be restorable before it is published ────────


def _canonico(valor):
    """Reduce a value to something comparable across drivers and dialects.

    SQLite hands back a Python ``float`` for a REAL, a ``str`` for a native-less
    enum and a ``bytes`` for a BLOB; the source hands back the driver's own
    types. Comparing canonical forms proves the VALUE survived, not just the
    row count.
    """
    if valor is None:
        return ("nulo",)
    if isinstance(valor, bool):
        return ("bool", valor)
    if isinstance(valor, (int, float, Decimal)):
        return ("num", float(valor))
    if isinstance(valor, (bytes, bytearray, memoryview)):
        return ("bytes", bytes(valor))
    if isinstance(valor, datetime):
        return ("fecha", valor.isoformat())
    if isinstance(valor, date):
        return ("fecha", valor.isoformat())
    if isinstance(valor, str):
        return ("texto", valor)
    if isinstance(valor, (dict, list)):
        return ("json", json.dumps(valor, sort_keys=True, default=str))
    return ("repr", repr(valor))


def _verificar_volcado(source_engine, temp_path: Path, tablas: int, filas: dict) -> None:
    """Re-open the written dump and prove it matches the source.

    Row counts for every table, and for the reflected path every value too.
    The SQLite fast path is a byte copy of the source file, so counts are the
    meaningful check there (there is nothing to translate).
    """
    verify_engine = create_engine(f"sqlite:///{temp_path}")
    try:
        with verify_engine.connect() as conn:
            presentes = inspect(verify_engine).get_table_names()
            if not filas or not presentes:
                # A dump with no tables is what a database that does not exist
                # looks like. Publishing it would report "backup ok" over an
                # empty file and unblock writes with no recovery point.
                raise VerificacionBackupFallida(
                    "el dump no tiene ninguna tabla: la base de origen está vacía "
                    "o no existe. No se publica un backup sin datos."
                )
            if len(presentes) != tablas:
                raise VerificacionBackupFallida(
                    f"el dump tiene {len(presentes)} tablas y la base {tablas}"
                )
            for name, esperado in filas.items():
                obtained = conn.execute(text(f"SELECT COUNT(*) FROM {name}")).scalar() or 0
                if obtained != esperado:
                    raise VerificacionBackupFallida(
                        f"'{name}': el dump tiene {obtained} filas y la base {esperado}"
                    )
            if source_engine.dialect.name != "sqlite":
                _verificar_valores(source_engine, conn, filas)
    finally:
        verify_engine.dispose()


def _verificar_valores(source_engine, target_conn, filas: dict) -> None:
    """Compare every value of every row, keyed by primary key.

    The dump is read through the SAME projected types it was written with, so
    SQLite hands back real ``datetime``/``bool``/``dict`` objects instead of the
    raw strings stored on disk. Without that, a faithful dump would look like a
    mismatch and a lossy one would look faithful.
    """
    source_meta = MetaData()
    target_meta = MetaData()
    for name in filas:
        Table(name, source_meta, autoload_with=source_engine)
        source_meta.tables[name].to_metadata(target_meta)
    _proyectar_tipos(target_meta)

    with _snapshot_consistente(source_engine) as source_conn:
        for name in filas:
            tabla_origen = source_meta.tables[name]
            tabla_destino = target_meta.tables[name]
            pk = [c.name for c in tabla_origen.primary_key.columns]
            origen = {
                tuple(_canonico(fila._mapping[c]) for c in pk): {
                    c.name: _canonico(fila._mapping[c.name]) for c in tabla_origen.columns
                }
                for fila in source_conn.execute(tabla_origen.select()).fetchall()
            }
            destino = {
                tuple(_canonico(fila._mapping[c]) for c in pk): {
                    c.name: _canonico(fila._mapping[c.name]) for c in tabla_destino.columns
                }
                for fila in target_conn.execute(tabla_destino.select()).fetchall()
            }

            if set(origen) != set(destino):
                faltantes = list(set(origen) - set(destino))[:3]
                extra = list(set(destino) - set(origen))[:3]
                raise VerificacionBackupFallida(
                    f"'{name}': las claves no coinciden. "
                    f"faltan {faltantes}, sobran {extra}"
                )
            for clave, fila_origen in origen.items():
                fila_destino = destino[clave]
                for columna, valor in fila_origen.items():
                    if fila_destino.get(columna) != valor:
                        raise VerificacionBackupFallida(
                            f"'{name}' {clave}: la columna '{columna}' no se respaldó "
                            f"igual (origen {valor}, dump {fila_destino.get(columna)})"
                        )
