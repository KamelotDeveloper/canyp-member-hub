"""Tests for the dialect-agnostic audit-column migration runner.

Exercises ``backend.migrations.run_column_migrations`` against throwaway SQLite
engines: a legacy schema missing the audit columns, a fresh schema, and a
partial schema (missing some tables). These tests never touch the live canyp.db.
"""

from sqlalchemy import create_engine, inspect, text

from backend.migrations import run_column_migrations

AUDIT_TABLES = ["socios", "membresias", "pagos", "aranceles"]
AUDIT_COLS = ("created_by", "updated_by")


def _make_engine(tmp_path, tables=None):
    """Create a SQLite engine with the given tables (id-only minimal schema)."""
    engine = create_engine(f"sqlite:///{tmp_path / 'mig.db'}")
    with engine.begin() as conn:
        for table in tables or AUDIT_TABLES:
            conn.execute(text(f'CREATE TABLE "{table}" (id VARCHAR PRIMARY KEY)'))
    return engine


def _columns(engine, table):
    return {col["name"] for col in inspect(engine).get_columns(table)}


class TestRunColumnMigrations:
    def test_adds_audit_columns_to_all_tables(self, tmp_path):
        engine = _make_engine(tmp_path)
        run_column_migrations(engine)
        for table in AUDIT_TABLES:
            cols = _columns(engine, table)
            assert cols >= {"created_by", "updated_by"}, f"{table} missing audit cols"

    def test_is_idempotent_second_run_clean(self, tmp_path):
        engine = _make_engine(tmp_path)
        run_column_migrations(engine)
        run_column_migrations(engine)  # must not raise, must not duplicate
        for table in AUDIT_TABLES:
            names = [c["name"] for c in inspect(engine).get_columns(table)]
            assert names.count("created_by") == 1
            assert names.count("updated_by") == 1

    def test_skips_missing_tables(self, tmp_path):
        engine = _make_engine(tmp_path, tables=["socios"])
        run_column_migrations(engine)  # membresias/pagos/aranceles absent → skip
        assert inspect(engine).has_table("socios")
        assert _columns(engine, "socios") >= {"created_by", "updated_by"}
        assert not inspect(engine).has_table("membresias")

    def test_columns_are_nullable(self, tmp_path):
        engine = _make_engine(tmp_path)
        run_column_migrations(engine)
        for table in AUDIT_TABLES:
            for col in inspect(engine).get_columns(table):
                if col["name"] in AUDIT_COLS:
                    assert col["nullable"], f"{table}.{col['name']} must be nullable"

    def test_no_op_when_columns_already_present(self, tmp_path):
        """A fresh create_all schema (columns present) is a clean no-op."""
        from backend.database import Base

        engine = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
        Base.metadata.create_all(bind=engine)
        run_column_migrations(engine)  # no error, no duplicate columns
        for table in AUDIT_TABLES:
            names = [c["name"] for c in inspect(engine).get_columns(table)]
            assert names.count("created_by") == 1
            assert names.count("updated_by") == 1
