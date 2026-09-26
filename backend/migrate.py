"""Idempotent additive migration for the CANYP schema.

Adds nullable columns to an existing CANYP SQLite database and applies
schema-level fixes such as making a column nullable.

Run manually against the live DB (after backing up):
    python -m backend.migrate

Preview the plan without writing anything (writes NOTHING, always safe):
    python -m backend.migrate --dry-run

The importable core `migrate(db_path, dry_run=False)` targets any SQLite file,
which is how tests exercise the script against throwaway temp databases without
touching the live canyp.db.

ORDERING (load-bearing, see design D6/D7)
------------------------------------------
The `membresias` table is recreated to make `area`/`predio` nullable BEFORE any
new `membresias` column is added. `_recreate_table_nullable` copies rows
positionally with ``INSERT INTO _new_x SELECT * FROM x``: if a column were added
first, the source would have one more column than the staging table (whose
schema is derived from the ORIGINAL CREATE statement) and the copy would abort
with "table _new_membresias has N columns but M values were supplied". Every
DDL step therefore runs before the first DML step, which also keeps the
``PRAGMA foreign_keys=OFF`` window inside the recreate effective (that PRAGMA is
a no-op inside an open transaction).
"""

import argparse
import sqlite3
import sys

from backend.database import DATABASE_FILE
from backend.models.enums import ConceptoCobro, ConceptoMembresia, RolMembresia

# (table, column, human label, SQL type) additions, applied in order. Every
# column is added as a NULLABLE column — never NOT NULL — so the ADD COLUMN
# always succeeds on a populated table; the NOT NULL contract lives in the ORM
# model and is upheld by the backfills below.
_COLUMN_ADDITIONS = [
    ("membresias", "rol", "membresias.rol", "VARCHAR"),
    ("parcelas", "categoria", "parcelas.categoria", "VARCHAR"),
    ("aranceles", "categoria", "aranceles.categoria", "VARCHAR"),
    ("pagos", "nota", "pagos.nota", "VARCHAR"),
    ("membresias", "arancelId", "membresias.arancelId", "VARCHAR"),
    ("membresias", "concepto", "membresias.concepto", "VARCHAR"),
    ("pago_items", "concepto", "pago_items.concepto", "VARCHAR"),
    ("pago_items", "factor", "pago_items.factor", "FLOAT"),
    ("aranceles", "concepto", "aranceles.concepto", "VARCHAR"),
    (
        "parcelas",
        "cuotaSocialIncluida",
        "parcelas.cuotaSocialIncluida",
        "BOOLEAN",
    ),
]

# (table, columns) to make nullable via table rebuild, applied in order.
# membresias.area/predio go nullable because a cuota social membership is not a
# physical location (CS-01). Both are rebuilt in ONE pass: two rebuilds would
# copy the rows twice for no reason.
_NULLABLE_REBUILDS = [
    ("membresias", ("area", "predio")),
    ("socios", ("dni",)),
]

# (table, column, value) NULL -> value backfills, applied in order. Values are
# SQLAlchemy Enum NAMES (SQLite and Postgres both store the name, never the
# display value), so hydration resolves them back to the enum members.
_BACKFILLS = [
    ("membresias", "concepto", ConceptoMembresia.AREA.name),
    ("pago_items", "concepto", ConceptoCobro.AREA.name),
    ("pago_items", "factor", 1.0),
    ("aranceles", "concepto", ConceptoCobro.AREA.name),
    ("parcelas", "cuotaSocialIncluida", 0),
]


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    """Return True if `table` exists (a DB predating it is left alone)."""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _will_be_added(table: str, column: str) -> bool:
    """True if `column` is one of the columns this migration would add.

    A dry run must plan against the schema as it WILL be (after its own ADD
    COLUMN steps), otherwise every backfill would silently report "nothing to
    do" on precisely the legacy databases that need migrating.
    """
    return any(
        planned_table == table and planned_column == column
        for planned_table, planned_column, _label, _type in _COLUMN_ADDITIONS
    )


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """Return True if `column` already exists on `table` (PRAGMA table_info)."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row[1] == column for row in rows)


def _column_notnull(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """Return True if `column` on `table` has NOT NULL constraint."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    for row in rows:
        if row[1] == column:
            return bool(row[3])  # notnull is the 4th field
    return False


def _recreate_table_nullable(
    conn: sqlite3.Connection, table: str, columns: str | tuple[str, ...]
) -> str | None:
    """Recreate `table` so that every column in `columns` becomes nullable.

    SQLite does not support ALTER COLUMN, so the only way to change a column
    from NOT NULL to nullable is to recreate the entire table. This function:
      1. Reads the current CREATE TABLE statement.
      2. Modifies the NOT NULL constraint on the target column(s).
      3. Creates a temporary ``_new_<table>`` with the updated schema.
      4. Copies all data, drops the old table, and renames the new one.
      5. Recreates any indexes that existed on the original table.

    Step 4 copies rows POSITIONALLY (``INSERT INTO _new_x SELECT * FROM x``), so
    every column the caller wants to add later MUST be added AFTER this returns.

    Returns the list of columns whose NOT NULL constraint was actually dropped,
    or None when no change was needed. The caller owns the human-readable
    message so that dry-run wording never has to be derived from a real one.
    """
    targets = (columns,) if isinstance(columns, str) else tuple(columns)
    pending = [c for c in targets if _column_notnull(conn, table, c)]
    if not pending:
        return None

    # 1. Get the original CREATE TABLE statement.
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    if row is None:
        return None
    original_sql: str = row[0]

    # 2. Rewrite: change "column TYPE NOT NULL" to "column TYPE".
    import re

    new_sql = original_sql
    converted: list[str] = []
    for column in pending:
        # The type token may carry a length/precision ("VARCHAR(9)"), which a
        # bare \w+ cannot match -- without it the rewrite silently no-ops on
        # exactly the columns this migration needs (membresias.area/predio).
        stripped = re.sub(
            rf"\b{column}\b\s+(\w+(?:\s*\([^)]*\))?)\s+NOT\s+NULL",
            rf"{column} \1",
            new_sql,
            count=1,
        )
        if stripped != new_sql:
            new_sql = stripped
            converted.append(column)
    if not converted:
        return None  # pattern didn't match; nothing to do

    new_table = f"_new_{table}"

    # Replace the table name with the temporary staging table.
    new_sql = re.sub(
        rf"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+{table}\b",
        f"CREATE TABLE IF NOT EXISTS {new_table}",
        new_sql,
        count=1,
    )
    # Fallback: plain CREATE TABLE (without IF NOT EXISTS).
    if new_table not in new_sql:
        new_sql = re.sub(
            rf"CREATE\s+TABLE\s+{table}\b",
            f"CREATE TABLE {new_table}",
            new_sql,
            count=1,
        )

    new_table = f"_new_{table}"

    # 3. Collect existing indexes for this table.
    indexes = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=?",
        (table,),
    ).fetchall()

    # 4. Apply. FK enforcement is temporarily disabled during the table
    #    recreation (SQLite legacy_alter_table pattern) so that DROP TABLE
    #    does not fail because other tables reference socios.id.
    old_fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        conn.execute(f"DROP TABLE IF EXISTS {new_table}")
        conn.execute(new_sql)
        conn.execute(f"INSERT INTO {new_table} SELECT * FROM {table}")
        conn.execute(f"DROP TABLE {table}")
        conn.execute(f"ALTER TABLE {new_table} RENAME TO {table}")
    finally:
        conn.execute(f"PRAGMA foreign_keys={int(old_fk)}")

    # 5. Recreate indexes.
    for (idx_sql,) in indexes:
        if idx_sql:
            # Replace the old table name in the index SQL just in case.
            conn.execute(idx_sql)

    return converted


def _add_column(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    sql_type: str,
    label: str,
    dry_run: bool,
) -> str:
    """Add `column` to `table` as a nullable column, or report its state."""
    if not _table_exists(conn, table):
        return f"{label}: skipped (table absent)"
    if _column_exists(conn, table, column):
        return f"{label}: already present"
    if dry_run:
        return f"{label}: would be added (nullable {sql_type})"
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}")
    return f"{label}: added"


def _backfill_null(
    conn: sqlite3.Connection, table: str, column: str, value, dry_run: bool
) -> str | None:
    """Fill NULL `column` values with `value`. Idempotent by construction.

    Returns None when there is nothing to do (column/table absent, or no NULL
    rows), so a second run reports no work at all.
    """
    if not _table_exists(conn, table):
        return None
    if _column_exists(conn, table, column):
        pending = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {column} IS NULL"
        ).fetchone()[0]
    elif dry_run and _will_be_added(table, column):
        # The column does not exist yet, so every existing row counts as NULL.
        # A dry run must plan against the schema as it WILL be, otherwise the
        # backfill would report "nothing to do" on the very DBs that need it.
        pending = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    else:
        return None
    if not pending:
        return None
    if dry_run:
        return f"{table}.{column}: would backfill {pending} row(s) to {value!r}"
    updated = conn.execute(
        f"UPDATE {table} SET {column} = ? WHERE {column} IS NULL", (value,)
    ).rowcount
    return f"{table}.{column}: backfilled {updated} row(s) to {value!r}"


def _backfill_rol_from_detalle(conn: sqlite3.Connection, dry_run: bool) -> list[str]:
    """Migrate the legacy free-text `detalle` role into `rol`, then clear it.

    `rol` is a SQLAlchemy Enum column, so it stores the member NAME
    ('TITULAR'), not the display value ('Titular').
    """
    actions: list[str] = []
    for role in RolMembresia:
        if dry_run:
            pending = conn.execute(
                "SELECT COUNT(*) FROM membresias WHERE detalle = ?", (role.value,)
            ).fetchone()[0]
        else:
            pending = conn.execute(
                "UPDATE membresias SET rol = ? WHERE detalle = ?",
                (role.name, role.value),
            ).rowcount
        if pending:
            actions.append(
                f"membresias.rol backfilled '{role.name}' for {pending} row(s)"
            )
        if not dry_run:
            conn.execute(
                "UPDATE membresias SET detalle = NULL WHERE detalle = ?",
                (role.value,),
            )
    return actions


def migrate(db_path: str, dry_run: bool = False) -> list[str]:
    """Apply the schema migrations to the SQLite DB at db_path.

    With `dry_run=True` NOTHING is written: the plan (column additions, table
    rebuilds and backfill counts) is computed from read-only inspection and
    returned as "would ..." actions instead of being applied.

    Every step is guarded and idempotent, so a second run reports no work.
    """
    actions: list[str] = []
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys=ON")

        # 1) Rebuilds first. A rebuild copies rows POSITIONALLY from the
        #    ORIGINAL column set, so it must precede every ADD COLUMN on that
        #    table (see the module docstring). It also must precede all DML:
        #    the rebuild needs `PRAGMA foreign_keys=OFF`, which SQLite ignores
        #    inside an open transaction.
        for table, columns in _NULLABLE_REBUILDS:
            label = f"{table}.{','.join(columns)}"
            pending = [c for c in columns if _column_notnull(conn, table, c)]
            if not pending:
                actions.append(f"{label}: already nullable")
                continue
            names = ",".join(pending)
            if dry_run:
                # Report only: the rebuild itself must never run in a dry run.
                actions.append(
                    f"{table}.{names}: would convert NOT NULL -> nullable "
                    "(dry run, table not rebuilt)"
                )
                continue
            converted = _recreate_table_nullable(conn, table, pending)
            if not converted:
                actions.append(f"{label}: already nullable")
            else:
                actions.append(
                    f"{table}.{','.join(converted)}: converted NOT NULL -> "
                    "nullable (table recreated)"
                )

        # 2) Add nullable columns if missing (guarded, idempotent).
        for table, column, label, sql_type in _COLUMN_ADDITIONS:
            actions.append(
                _add_column(conn, table, column, sql_type, label, dry_run)
            )

        # 3) Backfills.
        actions.extend(_backfill_rol_from_detalle(conn, dry_run))
        for table, column, value in _BACKFILLS:
            result = _backfill_null(conn, table, column, value, dry_run)
            if result:
                actions.append(result)

        if dry_run:
            conn.rollback()
        else:
            conn.commit()
        return actions
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> None:
    """CLI entry point (python -m backend.migrate) against the configured DB."""
    parser = argparse.ArgumentParser(
        prog="migrate",
        description="Idempotent additive schema migration for the CANYP SQLite DB.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the migration plan and write nothing",
    )
    args = parser.parse_args(argv)

    try:
        actions = migrate(DATABASE_FILE, dry_run=args.dry_run)
    except Exception as exc:  # pragma: no cover - defensive CLI boundry
        print(f"Migration failed: {exc}", file=sys.stderr)
        sys.exit(1)

    for action in actions:
        print(action)
    if args.dry_run:
        print("Dry run complete. No changes were written.")
    else:
        print("Migration complete.")
    sys.exit(0)


if __name__ == "__main__":
    main()
