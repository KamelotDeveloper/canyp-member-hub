"""Dialect-agnostic additive migrations for multi-user audit columns.

Unlike ``backend/migrate.py`` (SQLite-only, legacy local migrations), this runner
targets the live SQLAlchemy ``engine`` and works for BOTH SQLite and Postgres.
``Base.metadata.create_all`` only fabricates NEW tables — it never alters
existing ones — so existing local SQLite databases (and any already-created
remoto Postgres schema) need an explicit ``ALTER TABLE ... ADD COLUMN`` to gain
the audit columns.

The runner is idempotent by inspection (``sqlalchemy.inspect`` wraps
``PRAGMA table_info`` on SQLite and ``information_schema.columns`` on Postgres).
There is deliberately NO ``IF NOT EXISTS`` clause: SQLite does not support it
for ``ADD COLUMN``.
"""

from sqlalchemy import Engine, inspect, text
from sqlalchemy.engine import Inspector

# Table → audit columns to ensure exist (D7). Both columns are plain
# VARCHAR(36) nullable strings with no FK.
AUDIT_COLUMNS = {
    "socios": ("created_by", "updated_by"),
    "membresias": ("created_by", "updated_by"),
    "pagos": ("created_by", "updated_by"),
    "aranceles": ("created_by", "updated_by"),
}

# Table → extra additive columns (non-audit) to ensure exist. Nullable plain
# VARCHAR, matching the unbounded SQLAlchemy ``String`` columns on the models.
EXTRA_COLUMNS = {
    "socios": ("categoria", "numero_socio", "foto"),
}

# Table/column → SQL type override for EXTRA_COLUMNS (default "VARCHAR").
# ``foto`` is bytea on Postgres and BLOB on SQLite (LargeBinary).
EXTRA_COLUMN_TYPES = {
    ("socios", "foto"): {"postgresql": "BYTEA", "sqlite": "BLOB"},
}

# Carnet: unique index backing the socio.numero_socio uniqueness guarantee for
# tables that gained the column via ALTER (create_all builds the constraint
# from ``unique=True`` directly). NULLs are allowed, so unnumbered rows coexist.
_NUMERO_SOCIO_INDEX_SQL = (
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_socios_numero_socio "
    "ON socios (numero_socio)"
)


def _pad_expr(dialect: str) -> str:
    """SQL expression that zero-pads an integer-valued expression to 5 chars.

    Dialects diverge here: SQLite's ``SUBSTR(s, -5)`` truncates from the END of
    the string (so '00000' || '54' -> '00054'), but PostgreSQL's ``SUBSTR``
    with a negative start does NOT truncate the same way — it returns the whole
    remaining string. Postgres therefore needs ``LPAD(..., 5, '0')``.
    """
    if dialect == "postgresql":
        return "LPAD(CAST(:val AS TEXT), 5, '0')"
    return "SUBSTR('00000' || CAST(:val AS TEXT), -5)"


def _resolve_extra_column_type(table: str, column: str, dialect: str) -> str:
    """Resolve the SQL type for an extra column (fallback "VARCHAR")."""
    override = EXTRA_COLUMN_TYPES.get((table, column))
    if isinstance(override, dict):
        return override.get(dialect, "VARCHAR")
    return override or "VARCHAR"


def _add_missing_columns(
    insp: Inspector,
    engine: Engine,
    columns_map: dict[str, tuple[str, ...]],
    col_type: str,
) -> None:
    """Add each missing column from ``columns_map`` via ``ALTER TABLE``.

    Idempotent: columns already present (or tables that do not exist yet —
    ``create_all`` will create them with the columns already there) are skipped.
    """
    dialect = engine.dialect.name
    for table, columns in columns_map.items():
        if not insp.has_table(table):
            continue
        existing = {col["name"] for col in insp.get_columns(table)}
        for column in columns:
            if column in existing:
                continue
            resolved = _resolve_extra_column_type(table, column, dialect)
            with engine.begin() as conn:
                conn.execute(
                    text(f'ALTER TABLE "{table}" ADD COLUMN {column} {resolved}')
                )


def _pad_expr(dialect: str) -> str:
    """SQL expression that zero-pads an integer expression to exactly 5 chars.

    Dialects diverge: SQLite's ``SUBSTR(s, -5)`` truncates from the END of the
    string (so ``'00000' || '54'`` -> ``'00054'``), but PostgreSQL's
    ``SUBSTR`` with a negative start does not truncate the same way — it returns
    the whole remaining string (``'0000054'``). Postgres needs ``LPAD``.
    """
    if dialect == "postgresql":
        return "LPAD(CAST(:val AS TEXT), 5, '0')"
    return "SUBSTR('00000' || CAST(:val AS TEXT), -5)"


def _backfill_numero_socio(engine: Engine) -> None:
    """Assign sequential member numbers to socio rows where numero_socio is NULL.

    Numbered after ``fechaAlta`` ASC then ``id`` ASC (import order proxy),
    continuing after the highest existing number. Rows that already carry an
    explicit number are never touched, so the operation is idempotent across
    restarts and stays safe even if a bulk import later inserts NULL rows.

    The whole read+assign is a SINGLE UPDATE statement (window functions):
    against remote Postgres, the earlier row-by-row loop produced one UPDATE per
    socio, which made startup appear hung for tens of seconds. On Postgres the
    statement is serialized with the same ``pg_advisory_xact_lock`` convention
    used by the numeracion services.
    """
    insp = inspect(engine)
    if not insp.has_table("socios"):
        return
    columns = {col["name"] for col in insp.get_columns("socios")}
    if "numero_socio" not in columns:
        return

    order_by = '"fechaAlta" ASC, id ASC' if "fechaAlta" in columns else "id ASC"
    dialect = engine.dialect.name

    with engine.begin() as conn:
        if dialect == "postgresql":
            conn.execute(
                text("SELECT pg_advisory_xact_lock(:key)"),
                {"key": 0x534F4349},  # "SOCI", same key as numeracion_socio
            )

        highest = conn.execute(
            text("SELECT COALESCE(MAX(CAST(numero_socio AS INTEGER)), 0) FROM socios")
        ).scalar()

        # ROW_NUMBER() is 1-based, so the first NULL row gets :start + 1.
        pad = _pad_expr(dialect).replace(":val", "(:start + base.step)")
        statement = f"""
            WITH base AS (
                SELECT id,
                       ROW_NUMBER() OVER (ORDER BY {order_by}) AS step
                FROM socios
                WHERE numero_socio IS NULL
            )
            UPDATE socios
            SET numero_socio = {pad}
            FROM base
            WHERE socios.id = base.id
        """
        conn.execute(text(statement), {"start": highest})


def _normalize_numero_socio(engine: Engine) -> None:
    """Re-pad legacy/broken numero_socio values to exactly 5 digits.

    Idempotent safety net: numeric values that are not 5-char padded get
    re-padded (for example rows written by a backfill whose zero-padding used
    SQLite-only ``SUBSTR(s, -5)`` semantics, which on Postgres left values like
    ``'0000054'``). NULLs and non-digit custom values are preserved.
    """
    insp = inspect(engine)
    if not insp.has_table("socios"):
        return
    columns = {col["name"] for col in insp.get_columns("socios")}
    if "numero_socio" not in columns:
        return

    dialect = engine.dialect.name
    pad = _pad_expr(dialect).replace(":val", "CAST(numero_socio AS INTEGER)")
    if dialect == "postgresql":
        guard = "numero_socio ~ '^[0-9]+$'"
    else:
        guard = "numero_socio GLOB '*[0-9]*' AND numero_socio NOT GLOB '*[^0-9]*'"
    statement = f"""
        UPDATE socios
        SET numero_socio = {pad}
        WHERE numero_socio IS NOT NULL
          AND LENGTH(numero_socio) <> 5
          AND {guard}
    """
    with engine.begin() as conn:
        conn.execute(text(statement))


def run_column_migrations(engine: Engine) -> None:
    """Add missing audit + extra columns to existing tables, idempotently.

    Dialect-neutral ``ALTER TABLE "table" ADD COLUMN col <type>`` statements
    (there is deliberately NO ``IF NOT EXISTS`` clause: SQLite does not support
    it for ``ADD COLUMN``). Tables that do not exist yet are skipped —
    ``create_all`` will create them with the columns already present.

    After the carnet columns exist, socio rows with NULL ``numero_socio`` are
    backfilled (ordered by fechaAlta, id) and a unique index guarantees the
    member-number invariant for altered tables.
    """
    insp = inspect(engine)
    _add_missing_columns(insp, engine, AUDIT_COLUMNS, "VARCHAR(36)")
    _add_missing_columns(insp, engine, EXTRA_COLUMNS, "VARCHAR")

    _backfill_numero_socio(engine)
    _normalize_numero_socio(engine)

    # Fresh inspector: the one created above predates the ALTERs and its column
    # cache does not see the just-added columns.
    carnet_insp = inspect(engine)
    if carnet_insp.has_table("socios") and "numero_socio" in {
        col["name"] for col in carnet_insp.get_columns("socios")
    }:
        with engine.begin() as conn:
            conn.execute(text(_NUMERO_SOCIO_INDEX_SQL))
