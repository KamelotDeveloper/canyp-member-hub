"""Idempotent additive migration for the Unidades Compartidas schema.

Adds nullable columns to an existing CANYP SQLite database:
  - membresias.rol        (RolMembresia: Titular/Integrante)
  - parcelas.categoria    (CategoriaParcela: Chica/Mediana/Especial/Grande)
  - aranceles.categoria   (optional categoria dimension, null = catch-all)

The script is IDEMPOTENT: each column is guarded by a PRAGMA table_info
check before the ALTER TABLE ADD COLUMN, and role backfill is a plain
UPDATE that matches nothing once done. Running it repeatedly is a safe no-op.

It is manual-first and additive/backward-compatible: all additions are
nullable columns, so existing rows and the live DB are unaffected.

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
]


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """Return True if `column` already exists on `table` (PRAGMA table_info)."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row[1] == column for row in rows)


def migrate(db_path: str) -> list[str]:
    """Apply the additive schema migrations to the SQLite DB at db_path.

    Args:
        db_path: Path to the target SQLite database file.

    Returns:
        A list of human-readable actions performed (or "already present").
        These are also printed by the CLI entry point.

    Raises:
        sqlite3.Error / OSError: if the database cannot be opened or altered.
    """
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

        # 2) Backfill membresias.rol from the legacy free-text `detalle`,
        #    then clear that detalle for the rows we migrated.
        # NOTE: the SQLAlchemy Enum column stores the enum NAME (e.g. "TITULAR"),
        # not the .value ("Titular"), so backfill with `role.name` while matching
        # the legacy detalle free-text by `role.value`.
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
