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
    "socios": ("categoria",),
}


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
    for table, columns in columns_map.items():
        if not insp.has_table(table):
            continue
        existing = {col["name"] for col in insp.get_columns(table)}
        for column in columns:
            if column in existing:
                continue
            with engine.begin() as conn:
                conn.execute(
                    text(f'ALTER TABLE "{table}" ADD COLUMN {column} {col_type}')
                )


def run_column_migrations(engine: Engine) -> None:
    """Add missing audit + extra columns to existing tables, idempotently.

    Dialect-neutral ``ALTER TABLE "table" ADD COLUMN col <type>`` statements
    (there is deliberately NO ``IF NOT EXISTS`` clause: SQLite does not support
    it for ``ADD COLUMN``). Tables that do not exist yet are skipped —
    ``create_all`` will create them with the columns already present.
    """
    insp = inspect(engine)
    _add_missing_columns(insp, engine, AUDIT_COLUMNS, "VARCHAR(36)")
    _add_missing_columns(insp, engine, EXTRA_COLUMNS, "VARCHAR")
