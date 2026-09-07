"""Tests for the idempotent additive schema migration (Unidades Compartidas).

IMPORTANT: these tests NEVER touch the live canyp.db. They exercise the
core `backend.migrate.migrate(db_path)` function against throwaway temp
SQLite files: a legacy DB (missing the new columns) and a fresh DB (columns
already present via create_all).
"""

import os
import sqlite3

import pytest

from backend.database import Base
from backend.migrate import migrate


# ---------------------------------------------------------------------------
# Helpers to build test database files
# ---------------------------------------------------------------------------


@pytest.fixture()
def legacy_db_path(tmp_path):
    """A pre-migration DB missing rol/categoria/nota columns, with legacy detalle rows.

    Creates minimal membresias/parcelas/aranceles/pagos tables exactly as they
    exist BEFORE this change (no rol/categoria/nota), plus a membresiás row whose
    `detalle` holds a legacy role value to exercise the backfill.
    """
    path = str(tmp_path / "legacy.db")
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE socios (
                id VARCHAR NOT NULL PRIMARY KEY,
                nombre VARCHAR NOT NULL,
                dni VARCHAR NOT NULL,
                telefono VARCHAR NOT NULL,
                email VARCHAR NOT NULL,
                direccion VARCHAR NOT NULL,
                "fechaAlta" DATE NOT NULL,
                activo BOOLEAN NOT NULL,
                UNIQUE (dni)
            );
            CREATE TABLE parcelas (
                id VARCHAR NOT NULL PRIMARY KEY,
                nombre VARCHAR NOT NULL,
                tipo VARCHAR(9) NOT NULL,
                tamano VARCHAR,
                predio VARCHAR(10) NOT NULL
            );
            CREATE TABLE membresias (
                id VARCHAR NOT NULL PRIMARY KEY,
                "socioId" VARCHAR NOT NULL REFERENCES socios (id),
                area VARCHAR(9) NOT NULL,
                predio VARCHAR(10) NOT NULL,
                estado VARCHAR(10) NOT NULL,
                vencimiento DATE NOT NULL,
                detalle VARCHAR,
                "parcelaId" VARCHAR REFERENCES parcelas (id)
            );
            CREATE TABLE aranceles (
                id VARCHAR NOT NULL PRIMARY KEY,
                nombre VARCHAR NOT NULL,
                area VARCHAR(9) NOT NULL,
                predio VARCHAR(10) NOT NULL,
                monto FLOAT NOT NULL,
                "vigenteDesde" DATE NOT NULL,
                historico JSON NOT NULL
            );
            INSERT INTO socios (id, nombre, dni, telefono, email, direccion, "fechaAlta", activo)
            VALUES ('s1', 'Ana', '30000001', '', '', '', '2025-01-01', 1),
                   ('s2', 'Luis', '30000002', '', '', '', '2025-01-01', 1);
            INSERT INTO parcelas (id, nombre, tipo, predio)
            VALUES ('p1', 'Cabaña A', 'CABANA', 'ALMAFUERTE');
            INSERT INTO membresias (id, "socioId", area, predio, estado, vencimiento, detalle, "parcelaId")
            VALUES ('m1', 's1', 'CABANEROS', 'ALMAFUERTE', 'ACTIVA', '2027-01-01', 'Titular', 'p1'),
                   ('m2', 's2', 'CABANEROS', 'ALMAFUERTE', 'ACTIVA', '2027-01-01', 'Integrante', 'p1'),
                   ('m3', 's2', 'WINDSURF', 'ALMAFUERTE', 'ACTIVA', '2027-01-01', 'nota libre', NULL);
            INSERT INTO aranceles (id, nombre, area, predio, monto, "vigenteDesde", historico)
            VALUES ('a1', 'Cabaña', 'CABANEROS', 'ALMAFUERTE', 100.0, '2026-01-01', '[]');
            CREATE TABLE pagos (
                id VARCHAR NOT NULL PRIMARY KEY,
                numero VARCHAR NOT NULL,
                "socioId" VARCHAR NOT NULL REFERENCES socios (id),
                fecha DATE NOT NULL,
                medio VARCHAR NOT NULL,
                total FLOAT NOT NULL
            );
            """
        )
        conn.commit()
    finally:
        conn.close()
    return path


def _columns(conn, table):
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def _run(db_path):
    """Execute migrate and return (actions, exit_code-ish)."""
    actions = migrate(db_path)
    return actions


# ---------------------------------------------------------------------------
# Migration scenarios
# ---------------------------------------------------------------------------

NEW_COLUMNS = {
    ("membresias", "rol"),
    ("parcelas", "categoria"),
    ("aranceles", "categoria"),
    ("pagos", "nota"),
    ("membresias", "arancelId"),
}


class TestMigration:
    def test_legacy_db_adds_all_new_columns(self, legacy_db_path):
        """Migrating a legacy DB adds rol, both categoria, pagos.nota, arancelId."""
        _run(legacy_db_path)
        conn = sqlite3.connect(legacy_db_path)
        try:
            for table, col in NEW_COLUMNS:
                assert col in _columns(conn, table), f"{table}.{col} missing"
            # Columns must be nullable (additive, backward-compatible).
            for row in conn.execute("PRAGMA table_info(membresias)"):
                if row[1] == "rol":
                    assert row[3] == 0  # notnull == 0
                if row[1] == "arancelId":
                    assert row[3] == 0  # notnull == 0
        finally:
            conn.close()

    def test_legacy_db_backfills_rol_from_detalle(self, legacy_db_path):
        """detalle values 'Titular'/'Integrante' flow into rol (as enum NAMES) and detalle clears."""
        _run(legacy_db_path)
        conn = sqlite3.connect(legacy_db_path)
        try:
            rows = {
                mid: (rol, detalle)
                for mid, rol, detalle in conn.execute(
                    "SELECT id, rol, detalle FROM membresias"
                )
            }
            # Backfilled for unit memberships — stored as the enum NAME.
            assert rows["m1"] == ("TITULAR", None)
            assert rows["m2"] == ("INTEGRANTE", None)
            # Non-role detalle (free text) is left untouched.
            assert rows["m3"] == (None, "nota libre")
        finally:
            conn.close()

    def test_backfill_hydrates_through_orm(self, legacy_db_path):
        """Backfilled rol values load back through SQLAlchemy as the enum members.

        Regression: the backfill previously wrote the enum .value ("Titular"),
        but the Enum column stores/reads NAMES, so hydration raised KeyError.
        """
        _run(legacy_db_path)

        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from backend.models.enums import RolMembresia
        from backend.models.membresia import Membresia

        engine = create_engine(f"sqlite:///{legacy_db_path}")
        session = sessionmaker(bind=engine)()
        try:
            by_id = {m.id: m for m in session.query(Membresia).all()}
            assert by_id["m1"].rol == RolMembresia.TITULAR
            assert by_id["m2"].rol == RolMembresia.INTEGRANTE
            assert by_id["m3"].rol is None
        finally:
            session.close()
            engine.dispose()

    def test_migration_is_idempotent_second_run_clean(self, legacy_db_path):
        """Running migrate twice is a no-op on the second run (no duplicates)."""
        first = _run(legacy_db_path)
        second = _run(legacy_db_path)

        conn = sqlite3.connect(legacy_db_path)
        try:
            for table, col in NEW_COLUMNS:
                cols = _columns(conn, table)
                assert cols.count(col) == 1, f"duplicate column {table}.{col}"

            # No rows double-backfilled / no errors.
            assert (conn.execute("SELECT COUNT(*) FROM membresias WHERE rol='TITULAR'").fetchone()[0]) == 1
            assert (conn.execute("SELECT COUNT(*) FROM membresias WHERE rol='INTEGRANTE'").fetchone()[0]) == 1
        finally:
            conn.close()

        # Second run performed no column additions / no table recreation.
        assert all("added" not in a for a in second), f"expected no-op, got: {second}"
        assert all("converted" not in a for a in second), f"expected no-op, got: {second}"

    def test_fresh_db_with_columns_runs_clean(self, tmp_path):
        """A fresh DB (columns already present via create_all) -> clean no-op."""
        path = str(tmp_path / "fresh.db")
        engine = None
        from sqlalchemy import create_engine

        engine = create_engine(f"sqlite:///{path}")
        Base.metadata.create_all(bind=engine)
        engine.dispose()

        actions = _run(path)

        conn = sqlite3.connect(path)
        try:
            for table, col in NEW_COLUMNS:
                assert col in _columns(conn, table)
            # socios.dni must remain nullable (never re-added as NOT NULL).
            dni_notnull = [
                row[3] for row in conn.execute("PRAGMA table_info(socios)") if row[1] == "dni"
            ]
            assert dni_notnull == [0], "socios.dni must stay nullable"
        finally:
            conn.close()
        # Columns that exist are no-ops; dni is already nullable.
        assert all(
            "already present" in a or "already nullable" in a for a in actions
        ), f"unexpected: {actions}"


# ---------------------------------------------------------------------------
# Model-level tests for new columns & enums
# ---------------------------------------------------------------------------


class TestNewEnums:
    def test_rol_membresia_values(self):
        """RolMembresia exposes Titular/Integrante string values."""
        from backend.models.enums import RolMembresia

        assert RolMembresia.TITULAR.value == "Titular"
        assert RolMembresia.INTEGRANTE.value == "Integrante"

    def test_categoria_parcela_values(self):
        """CategoriaParcela exposes Chica/Mediana/Especial/Grande."""
        from backend.models.enums import CategoriaParcela

        assert [c.value for c in CategoriaParcela] == [
            "Chica",
            "Mediana",
            "Especial",
            "Grande",
        ]

    def test_new_enums_exported(self):
        """New enums are re-exported from backend.models."""
        import backend.models as m

        assert hasattr(m, "RolMembresia")
        assert hasattr(m, "CategoriaParcela")


class TestNewModelColumns:
    def test_membresia_rol_nullable_defaults(self, test_db):
        """Membresia.rol is nullable and defaults to None."""
        from datetime import date

        from backend.models.enums import (
            Area,
            EstadoMembresia,
            Predio,
            RolMembresia,
        )
        from backend.models.membresia import Membresia
        from backend.models.socio import Socio

        socio = Socio(
            id="s1",
            nombre="Ana",
            dni="30000001",
            telefono="",
            email="",
            direccion="",
            fechaAlta=date(2025, 1, 1),
            activo=True,
        )
        test_db.add(socio)
        test_db.flush()

        m = Membresia(
            id="mx",
            socioId="s1",
            area=Area.WINDSURF,
            predio=Predio.EMBALSE,
            estado=EstadoMembresia.ACTIVA,
            vencimiento=date(2027, 1, 1),
        )
        test_db.add(m)
        test_db.commit()
        assert m.rol is None

        # Explicit role persists with the enum value.
        m2 = Membresia(
            id="my",
            socioId="s1",
            area=Area.CABANEROS,
            predio=Predio.EMBALSE,
            estado=EstadoMembresia.ACTIVA,
            vencimiento=date(2027, 1, 1),
            rol=RolMembresia.TITULAR,
        )
        test_db.add(m2)
        test_db.commit()
        assert m2.rol == RolMembresia.TITULAR

    def test_parcela_categoria_nullable_defaults(self, test_db):
        """Parcela.categoria is nullable, persists enum value."""
        from backend.models.enums import CategoriaParcela, Predio, TipoParcela
        from backend.models.parcela import Parcela

        p = Parcela(
            id="p1",
            nombre="Cabaña E",
            tipo=TipoParcela.CABANA,
            predio=Predio.ALMAFUERTE,
            categoria=CategoriaParcela.MEDIANA,
        )
        test_db.add(p)
        test_db.commit()
        assert p.categoria == CategoriaParcela.MEDIANA

        # Balsa with no categoria -> null
        p2 = Parcela(
            id="p2",
            nombre="Balsa N",
            tipo=TipoParcela.BALSA,
            predio=Predio.ALMAFUERTE,
        )
        test_db.add(p2)
        test_db.commit()
        assert p2.categoria is None

    def test_arancel_categoria_nullable(self, test_db):
        """Arancel.categoria is nullable, persists enum value."""
        from datetime import date

        from backend.models.arancel import Arancel
        from backend.models.enums import Area, CategoriaParcela, Predio

        a = Arancel(
            id="a1",
            nombre="Cabaña Chica",
            area=Area.CABANEROS,
            predio=Predio.ALMAFUERTE,
            monto=100.0,
            vigenteDesde=date(2026, 1, 1),
            categoria=CategoriaParcela.CHICA,
        )
        test_db.add(a)
        test_db.commit()
        assert a.categoria == CategoriaParcela.CHICA

        # Catch-all (null categoria) arancel stays null.
        a2 = Arancel(
            id="a2",
            nombre="Balsa",
            area=Area.BALSEROS,
            predio=Predio.ALMAFUERTE,
            monto=150.0,
            vigenteDesde=date(2026, 1, 1),
        )
        test_db.add(a2)
        test_db.commit()
        assert a2.categoria is None
