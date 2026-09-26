"""Idempotent additive migration for the CANYP schema.

Adds nullable columns to an existing CANYP SQLite database and applies
schema-level fixes such as making a column nullable.

Run manually against the live DB (after backing up):
    python -m backend.migrate

The importable core `migrate(db_path)` targets any SQLite file, which is how
tests exercise the script against throwaway temp databases without touching
the live canyp.db.
"""

import sqlite3
import sys

from backend.database import DATABASE_FILE
from backend.models.enums import RolMembresia

# (table, column, human label) additions, applied in order.
_COLUMN_ADDITIONS = [
    ("membresias", "rol", "membresias.rol"),
    ("parcelas", "categoria", "parcelas.categoria"),
    ("aranceles", "categoria", "aranceles.categoria"),
    ("pagos", "nota", "pagos.nota"),
    ("membresias", "arancelId", "membresias.arancelId"),
]


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
    conn: sqlite3.Connection, table: str, column: str
) -> str | None:
    """Recreate `table` so that `column` becomes nullable (SQLite-only).

    SQLite does not support ALTER COLUMN, so the only way to change a column
    from NOT NULL to nullable is to recreate the entire table. This function:
      1. Reads the current CREATE TABLE statement.
      2. Modifies the NOT NULL constraint on the target column.
      3. Creates a temporary ``_new_<table>`` with the updated schema.
      4. Copies all data, drops the old table, and renames the new one.
      5. Recreates any indexes that existed on the original table.

    The operation runs inside the caller's transaction. Returns a human-readable
    action string on success, or None if no change was needed.
    """
    if not _column_notnull(conn, table, column):
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

    new_sql = re.sub(
        rf"\b{column}\b\s+(\w+)\s+NOT\s+NULL",
        rf"{column} \1",
        original_sql,
        count=1,
    )
    if new_sql == original_sql:
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

    return f"{table}.{column}: converted NOT NULL -> nullable (table recreated)"


def migrate(db_path: str) -> list[str]:
    """Apply the schema migrations to the SQLite DB at db_path."""
    actions: list[str] = []
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys=ON")

        # 1) Add nullable columns if missing (guarded, idempotent).
        for table, column, label in _COLUMN_ADDITIONS:
            if _column_exists(conn, table, column):
                actions.append(f"{label}: already present")
            else:
                conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN {column} VARCHAR"
                )
                actions.append(f"{label}: added")

        # 2) Make socios.dni nullable (recreate table if needed).
        result = _recreate_table_nullable(conn, "socios", "dni")
        if result:
            actions.append(result)
        else:
            actions.append("socios.dni: already nullable")

        # 3) Backfill membresias.rol from the legacy free-text `detalle`,
        #    then clear that detalle for the rows we migrated.
        for role in RolMembresia:
            backfilled = conn.execute(
                "UPDATE membresias SET rol = ? WHERE detalle = ?",
                (role.name, role.value),
            ).rowcount
            if backfilled:
                actions.append(
                    f"membresias.rol backfilled '{role.name}' for {backfilled} row(s)"
                )
            conn.execute(
                "UPDATE membresias SET detalle = NULL WHERE detalle = ?",
                (role.value,),
            )

        conn.commit()
        return actions
    finally:
        conn.close()


def main() -> None:
    """CLI entry point (python -m backend.migrate) against the configured DB."""
    try:
        actions = migrate(DATABASE_FILE)
    except Exception as exc:  # pragma: no cover - defensive CLI boundry
        print(f"Migration failed: {exc}", file=sys.stderr)
        sys.exit(1)

    for action in actions:
        print(action)
    print("Migration complete.")
    sys.exit(0)


if __name__ == "__main__":
    main()
