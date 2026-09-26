"""Tests for the carnet migration: columns, numero_socio backfill, unique index.

Exercises ``backend.migrations`` against throwaway SQLite engines with a
legacy ``socios`` table lacking the carnet columns. Never touches the live DB.
"""

from sqlalchemy import create_engine, inspect, text

from backend.migrations import EXTRA_COLUMNS, _pad_expr, run_column_migrations

_LEGACY_SOCIOS_SQL = (
    'CREATE TABLE socios (id VARCHAR PRIMARY KEY, nombre VARCHAR, '
    '"fechaAlta" DATE)'
)


def _make_engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as conn:
        conn.execute(text(_LEGACY_SOCIOS_SQL))
    return engine


def _columns(engine, table):
    return {col["name"] for col in inspect(engine).get_columns(table)}


def _numbers(engine):
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, numero_socio FROM socios ORDER BY id")
        ).fetchall()
    return {row[0]: row[1] for row in rows}


class TestMigracionCarnetRegistry:
    """The migration registry advertises the new columns (VERIFY checklist)."""

    def test_extra_columns_include_carnet_columns(self):
        assert "numero_socio" in EXTRA_COLUMNS["socios"]
        assert "foto" in EXTRA_COLUMNS["socios"]


class TestMigracionCarnetPadExpr:
    """The zero-pad expression must produce exactly 5 chars on BOTH dialects.

    Regression guard: PostgreSQL's ``SUBSTR(s, -5)`` does NOT truncate from the
    end the way SQLite's does (it returns the whole remaining string), so the
    postgres expression must use ``LPAD`` instead. SQLite keeps the SUBSTR form.
    The SQLite expression is executed against a real SQLite engine; the Postgres
    expression is asserted structurally (LPAD, no SUBSTR) — running it needs a
    live Postgres, which the live-environment verification covers.
    """

    def test_sqlite_substr_pads_to_five(self, tmp_path):
        engine = _make_engine(tmp_path)
        with engine.begin() as conn:
            # Exactly the divergence that bit the live Supabase backfill:
            # '0000054' (7 chars) must become '00054' (5 chars).
            for src in ("54", "0000054", "00000246", "001"):
                got = conn.execute(
                    text(f"SELECT {_pad_expr('sqlite').replace(':val', ':v')}"),
                    {"v": src},
                ).scalar()
                assert len(got) == 5, f"{src!r} -> {got!r}"

    def test_postgres_pad_expr_uses_lpad(self):
        # The expression must exist and target LPAD, not SUBSTR semantics.
        expr = _pad_expr("postgresql")
        assert "LPAD" in expr and "SUBSTR" not in expr


class TestMigracionCarnetColumns:
    def test_run_column_migrations_adds_carnet_columns(self, tmp_path):
        engine = _make_engine(tmp_path)
        run_column_migrations(engine)
        cols = _columns(engine, "socios")
        assert {"numero_socio", "foto"} <= cols

    def test_is_idempotent(self, tmp_path):
        engine = _make_engine(tmp_path)
        run_column_migrations(engine)
        run_column_migrations(engine)
        names = [c["name"] for c in inspect(engine).get_columns("socios")]
        assert names.count("numero_socio") == 1
        assert names.count("foto") == 1

    def test_creates_unique_index_on_numero_socio(self, tmp_path):
        engine = _make_engine(tmp_path)
        run_column_migrations(engine)
        indexes = {i["name"]: i for i in inspect(engine).get_indexes("socios")}
        assert "ix_socios_numero_socio" in indexes
        assert indexes["ix_socios_numero_socio"]["unique"] == 1


class TestMigracionCarnetBackfill:
    """Existing socios without numero_socio get sequential numbers."""

    def _seed(self, engine, rows):
        with engine.begin() as conn:
            for sid, fecha in rows:
                conn.execute(
                    text(
                        'INSERT INTO socios (id, nombre, "fechaAlta") '
                        "VALUES (:id, 'X', :fecha)"
                    ),
                    {"id": sid, "fecha": fecha},
                )

    def test_backfills_ordered_by_fechaalta_then_id(self, tmp_path):
        engine = _make_engine(tmp_path)
        self._seed(engine, [("sA", "2024-03-01"), ("sB", "2024-01-01"), ("sC", "2024-02-01")])
        run_column_migrations(engine)
        assert _numbers(engine) == {
            "sB": "00001",
            "sC": "00002",
            "sA": "00003",
        }

    def test_tie_breaks_by_id(self, tmp_path):
        engine = _make_engine(tmp_path)
        self._seed(engine, [("sB", "2024-01-01"), ("sA", "2024-01-01")])
        run_column_migrations(engine)
        assert _numbers(engine) == {"sA": "00001", "sB": "00002"}

    def test_continues_after_existing_numbers(self, tmp_path):
        # Legacy table that ALREADY has numero_socio (explicit numbers on rows).
        engine = create_engine(f"sqlite:///{tmp_path / 'legacy2.db'}")
        with engine.begin() as conn:
            conn.execute(
                text(
                    'CREATE TABLE socios (id VARCHAR PRIMARY KEY, nombre VARCHAR, '
                    '"fechaAlta" DATE, numero_socio VARCHAR)'
                )
            )
            conn.execute(
                text(
                    'INSERT INTO socios (id, nombre, "fechaAlta", numero_socio) '
                    "VALUES ('sExplicit', 'X', '2023-01-01', '00042')"
                )
            )
            conn.execute(
                text(
                    'INSERT INTO socios (id, nombre, "fechaAlta") '
                    "VALUES ('sA', 'X', '2024-01-01'), ('sB', 'X', '2024-02-01')"
                )
            )
        run_column_migrations(engine)
        assert _numbers(engine) == {
            "sExplicit": "00042",
            "sA": "00043",
            "sB": "00044",
        }

    def test_does_not_touch_already_numbered_rows(self, tmp_path):
        engine = _make_engine(tmp_path)
        self._seed(engine, [("sA", "2024-01-01")])
        run_column_migrations(engine)
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE socios SET numero_socio = '00007' WHERE id = 'sA'")
            )
        self._seed(engine, [("sB", "2024-02-01")])
        run_column_migrations(engine)
        assert _numbers(engine) == {"sA": "00007", "sB": "00008"}