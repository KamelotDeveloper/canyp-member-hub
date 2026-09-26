"""Tests for the idempotent additive schema migration (Unidades Compartidas).

IMPORTANT: these tests NEVER touch the live canyp.db. They exercise the
core `backend.migrate.migrate(db_path, dry_run=False)` function against
throwaway temp SQLite files: a legacy DB (missing the new columns) and a fresh
DB (columns already present via create_all).
"""

import hashlib
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


def _notnull(conn, table):
    """{column: notnull flag} for `table`."""
    return {row[1]: row[3] for row in conn.execute(f"PRAGMA table_info({table})")}


def _run(db_path, dry_run=False):
    """Execute migrate and return the action strings."""
    return migrate(db_path, dry_run=dry_run)


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

        from backend.migrations import run_column_migrations
        from backend.models.enums import RolMembresia
        from backend.models.membresia import Membresia

        engine = create_engine(f"sqlite:///{legacy_db_path}")
        # The audit-column runner adds created_by/updated_by (D7) to the legacy
        # DB — the same additive step the app lifespan runs on startup — so the
        # full ORM model (which now includes those columns) can hydrate.
        run_column_migrations(engine)
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


# ---------------------------------------------------------------------------
# Concept dimension: enums, nullable area/predio, additive columns
# ---------------------------------------------------------------------------


@pytest.fixture()
def concepto_legacy_db_path(tmp_path):
    """A legacy DB from BEFORE the concept dimension.

    Mirrors a real pre-migration file: `membresias.area`/`predio` are NOT NULL
    and typed `VARCHAR(n)`, `socios.dni` is NOT NULL, and `pago_items` exists
    with its original five columns. The `VARCHAR(n)` length qualifier is
    deliberate — a NOT NULL rewrite that only matches a bare type token silently
    no-ops on exactly these columns.
    """
    path = str(tmp_path / "concepto_legacy.db")
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
                activo BOOLEAN NOT NULL
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
            CREATE TABLE pagos (
                id VARCHAR NOT NULL PRIMARY KEY,
                numero VARCHAR NOT NULL,
                "socioId" VARCHAR NOT NULL REFERENCES socios (id),
                fecha DATE NOT NULL,
                medio VARCHAR NOT NULL,
                total FLOAT NOT NULL
            );
            CREATE TABLE pago_items (
                id VARCHAR NOT NULL PRIMARY KEY,
                "pagoId" VARCHAR NOT NULL REFERENCES pagos (id),
                "arancelId" VARCHAR NOT NULL REFERENCES aranceles (id),
                "membresiaId" VARCHAR NOT NULL REFERENCES membresias (id),
                "montoAplicado" FLOAT NOT NULL,
                "arancelNombre" VARCHAR NOT NULL
            );
            INSERT INTO socios (id, nombre, dni, telefono, email, direccion,
                                "fechaAlta", activo)
            VALUES ('s1', 'Ana', '30000001', '', '', '', '2025-01-01', 1),
                   ('s2', 'Luis', '30000002', '', '', '', '2025-01-01', 1);
            INSERT INTO parcelas (id, nombre, tipo, predio)
            VALUES ('p1', 'Balsa X', 'BALSA', 'EMBALSE');
            INSERT INTO membresias (id, "socioId", area, predio, estado,
                                    vencimiento, detalle, "parcelaId")
            VALUES ('m1', 's1', 'BALSEROS', 'EMBALSE', 'SUSPENDIDA',
                    '2027-07-03', 'Titular', 'p1'),
                   ('m2', 's2', 'WINDSURF', 'ALMAFUERTE', 'VENCIDA',
                    '2027-01-01', 'nota libre', NULL);
            INSERT INTO aranceles (id, nombre, area, predio, monto,
                                   "vigenteDesde", historico)
            VALUES ('a1', 'Balsa', 'BALSEROS', 'EMBALSE', 130000.0,
                    '2026-01-01', '[]');
            INSERT INTO pagos (id, numero, "socioId", fecha, medio, total)
            VALUES ('pg1', '0001', 's1', '2026-01-05', 'efectivo', 130000.0);
            INSERT INTO pago_items (id, "pagoId", "arancelId", "membresiaId",
                                    "montoAplicado", "arancelNombre")
            VALUES ('pi1', 'pg1', 'a1', 'm1', 130000.0, 'Balsa');
            """
        )
        conn.commit()
    finally:
        conn.close()
    return path


def _file_digest(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def _create_all_file(path):
    """create_all a throwaway SQLite file (a DB already at the new shape)."""
    from sqlalchemy import create_engine

    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(bind=engine)
    engine.dispose()
    return engine


class TestDryRun:
    def test_dry_run_writes_nothing(self, concepto_legacy_db_path):
        """--dry-run leaves the file byte-identical: no DDL, no DML."""
        before = _file_digest(concepto_legacy_db_path)
        actions = _run(concepto_legacy_db_path, dry_run=True)
        assert actions, "a dry run must report the plan it would apply"
        assert _file_digest(concepto_legacy_db_path) == before

    def test_dry_run_reports_the_pending_work(self, concepto_legacy_db_path):
        """The plan names every rebuild, column and backfill count."""
        actions = _run(concepto_legacy_db_path, dry_run=True)
        joined = "\n".join(actions)
        assert "membresias.area,predio: would convert NOT NULL -> nullable" in joined
        for label in (
            "membresias.concepto",
            "pago_items.concepto",
            "pago_items.factor",
            "aranceles.concepto",
            "parcelas.cuotaSocialIncluida",
        ):
            assert f"{label}: would be added" in joined, label
        assert "membresias.concepto: would backfill 2 row(s) to 'AREA'" in joined

    def test_dry_run_plan_matches_applied_run(self, concepto_legacy_db_path):
        """Every pending label the dry run previewed is one the apply reports."""
        previewed = {
            a.split(":")[0]
            for a in _run(concepto_legacy_db_path, dry_run=True)
            if ": would" in a
        }
        applied = {
            a.split(":")[0]
            for a in _run(concepto_legacy_db_path)
            if a.endswith("added") or "converted" in a
        }
        assert previewed == applied, (previewed, applied)


class TestConceptColumns:
    def test_area_and_predio_become_nullable(self, concepto_legacy_db_path):
        """membresias.area/predio are rebuilt to nullable (a cuota social row
        is not a physical location, CS-01)."""
        _run(concepto_legacy_db_path)
        conn = sqlite3.connect(concepto_legacy_db_path)
        try:
            notnull = _notnull(conn, "membresias")
            assert notnull["area"] == 0, notnull
            assert notnull["predio"] == 0, notnull
            # The rebuild must not have touched the other NOT NULL columns.
            assert notnull["socioId"] == 1
            assert notnull["estado"] == 1
            assert notnull["vencimiento"] == 1
        finally:
            conn.close()

    def test_concept_columns_are_added_as_nullable(self, concepto_legacy_db_path):
        """Every new column lands nullable; the NOT NULL contract is the ORM's.

        SQLite refuses `ADD COLUMN ... NOT NULL` without a default, and adding
        a default would silently rewrite the meaning of existing rows.
        """
        _run(concepto_legacy_db_path)
        conn = sqlite3.connect(concepto_legacy_db_path)
        try:
            for table, column in (
                ("membresias", "concepto"),
                ("pago_items", "concepto"),
                ("pago_items", "factor"),
                ("aranceles", "concepto"),
                ("parcelas", "cuotaSocialIncluida"),
            ):
                assert _notnull(conn, table)[column] == 0, f"{table}.{column}"
        finally:
            conn.close()

    def test_rebuild_precedes_add_column(self, concepto_legacy_db_path):
        """Regression: the rebuild copies rows POSITIONALLY.

        `_recreate_table_nullable` runs `INSERT INTO _new_membresias SELECT *
        FROM membresias`, and the staging table's schema is derived from the
        ORIGINAL CREATE statement. Adding `concepto` first would make the
        source one column wider than the staging table and the copy would abort
        with "table _new_membresias has N columns but M values were supplied".
        """
        actions = _run(concepto_legacy_db_path)
        rebuilt = next(
            i for i, a in enumerate(actions) if "membresias" in a and "converted" in a
        )
        added = next(
            i
            for i, a in enumerate(actions)
            if a.startswith("membresias.concepto:") and a.endswith("added")
        )
        assert rebuilt < added, actions

        # And the rebuild really did preserve every row.
        conn = sqlite3.connect(concepto_legacy_db_path)
        try:
            assert conn.execute("SELECT COUNT(*) FROM membresias").fetchone()[0] == 2
        finally:
            conn.close()


class TestConceptBackfill:
    def test_membresias_concepto_backfilled_to_enum_name(self, concepto_legacy_db_path):
        """Legacy rows become 'AREA' — the enum NAME, not the display value.

        SQLAlchemy stores Enum members by name, so writing 'area' here would
        fail hydration with LookupError.
        """
        _run(concepto_legacy_db_path)
        conn = sqlite3.connect(concepto_legacy_db_path)
        try:
            rows = dict(
                conn.execute("SELECT id, concepto FROM membresias").fetchall()
            )
            assert rows == {"m1": "AREA", "m2": "AREA"}
        finally:
            conn.close()

    def test_backfill_preserves_id_estado_and_area(self, concepto_legacy_db_path):
        """The backfill touches one column: id, estado, area and dates survive."""
        _run(concepto_legacy_db_path)
        conn = sqlite3.connect(concepto_legacy_db_path)
        try:
            rows = {
                r[0]: r
                for r in conn.execute(
                    "SELECT id, estado, area, predio, vencimiento, concepto "
                    "FROM membresias"
                )
            }
        finally:
            conn.close()
        assert rows["m1"] == (
            "m1", "SUSPENDIDA", "BALSEROS", "EMBALSE", "2027-07-03", "AREA",
        )
        assert rows["m2"][0] == "m2"
        assert rows["m2"][1] == "VENCIDA"
        # Nothing is deleted: socios, pagos and pago_items all survive (EST-03).
        conn = sqlite3.connect(concepto_legacy_db_path)
        try:
            assert conn.execute("SELECT COUNT(*) FROM socios").fetchone()[0] == 2
            assert conn.execute("SELECT COUNT(*) FROM pagos").fetchone()[0] == 1
            assert conn.execute("SELECT COUNT(*) FROM pago_items").fetchone()[0] == 1
        finally:
            conn.close()

    def test_pago_item_arancel_and_parcela_defaults_backfilled(
        self, concepto_legacy_db_path
    ):
        """Existing comprobantes keep working: items default to AREA ×1."""
        _run(concepto_legacy_db_path)
        conn = sqlite3.connect(concepto_legacy_db_path)
        try:
            assert conn.execute(
                "SELECT concepto, factor, montoAplicado FROM pago_items"
            ).fetchall() == [("AREA", 1.0, 130000.0)]
            assert conn.execute("SELECT concepto FROM aranceles").fetchall() == [
                ("AREA",)
            ]
            # Guardería opt-in defaults to OFF (CS-04).
            assert conn.execute(
                "SELECT cuotaSocialIncluida FROM parcelas"
            ).fetchall() == [(0,)]
        finally:
            conn.close()

    def test_second_run_changes_zero_rows(self, concepto_legacy_db_path):
        """A second run reports no work at all (idempotent by construction)."""
        _run(concepto_legacy_db_path)
        second = _run(concepto_legacy_db_path)
        for forbidden in ("added", "converted", "backfilled", "would"):
            assert all(forbidden not in a for a in second), second

    def test_backfilled_values_hydrate_through_the_orm(
        self, concepto_legacy_db_path
    ):
        """'AREA' hydrates back to ConceptoMembresia.AREA (MEM-01 backfill)."""
        _run(concepto_legacy_db_path)

        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from backend.migrations import run_column_migrations
        from backend.models.enums import ConceptoMembresia
        from backend.models.membresia import Membresia

        engine = create_engine(f"sqlite:///{concepto_legacy_db_path}")
        run_column_migrations(engine)
        session = sessionmaker(bind=engine)()
        try:
            loaded = {m.id: m for m in session.query(Membresia).all()}
            assert loaded["m1"].concepto == ConceptoMembresia.AREA
            assert loaded["m1"].estado.value == "suspendida"
            assert loaded["m1"].area is not None
        finally:
            session.close()
            engine.dispose()

    def test_fresh_db_from_create_all_is_a_clean_noop(self, tmp_path):
        """A DB already created by create_all needs no rebuild and no backfill."""
        path = str(tmp_path / "fresh_concepto.db")
        _create_all_file(path)
        actions = _run(path)
        assert all("converted" not in a for a in actions), actions
        assert all("backfilled" not in a for a in actions), actions
        conn = sqlite3.connect(path)
        try:
            assert _notnull(conn, "membresias")["area"] == 0
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Concept dimension: enums and model columns
# ---------------------------------------------------------------------------


class TestConceptEnums:
    def test_concepto_membresia_values(self):
        """ConceptoMembresia carries exactly the two MEM-01 concepts."""
        from backend.models.enums import ConceptoMembresia

        assert [c.name for c in ConceptoMembresia] == ["AREA", "CUOTA_SOCIAL"]

    def test_concepto_cobro_values(self):
        """ConceptoCobro: the 2 membership concepts + recargo + servicio (decision #646).

        The list is locked because `migrate.py` backfills `concepto='AREA'` by
        NAME: renaming or removing a member is a breaking change for every
        already-migrated database, and adding one is safe (plain VARCHAR, no
        CHECK constraint).
        """
        from backend.models.enums import ConceptoCobro

        assert [c.name for c in ConceptoCobro] == [
            "AREA",
            "CUOTA_SOCIAL",
            "RECARGO",
            "SERVICIO",
        ]

    def test_estado_socio_visual_nominaciones_are_exact(self):
        """UI-04 asserts these strings verbatim, em dash included."""
        from backend.models.enums import EstadoSocioVisual

        assert {e.name: e.value for e in EstadoSocioVisual} == {
            "ACTIVO": "Socio activo",
            "ACTIVO_REVISAR": "Socio activo \u2014 revisar",
            "INACTIVO_REVISAR": "Inactivo \u2014 revisar",
            "SOLO_CUOTA_SOCIAL": "Solo cuota social",
        }
        # Guard against a hyphen/en-dash swap sneaking into the em dash.
        assert "—" in EstadoSocioVisual.ACTIVO_REVISAR.value
        assert " - " not in EstadoSocioVisual.ACTIVO_REVISAR.value

    def test_concept_enums_exported(self):
        import backend.models as m

        assert hasattr(m, "ConceptoMembresia")
        assert hasattr(m, "ConceptoCobro")
        assert hasattr(m, "EstadoSocioVisual")


class TestConceptModelColumns:
    def test_membresia_concepto_defaults_to_area(self, test_db):
        """An area membership inserted without concepto lands as AREA."""
        from datetime import date

        from backend.models.enums import (
            Area,
            ConceptoMembresia,
            EstadoMembresia,
            Predio,
        )
        from backend.models.membresia import Membresia
        from backend.models.socio import Socio

        test_db.add(
            Socio(
                id="s1",
                nombre="Ana",
                dni="30000001",
                telefono="",
                email="",
                direccion="",
                fechaAlta=date(2025, 1, 1),
                activo=True,
            )
        )
        test_db.commit()

        m = Membresia(
            id="m1",
            socioId="s1",
            area=Area.BALSEROS,
            predio=Predio.EMBALSE,
            estado=EstadoMembresia.ACTIVA,
            vencimiento=date(2027, 1, 1),
        )
        test_db.add(m)
        test_db.commit()
        assert m.concepto == ConceptoMembresia.AREA

    def test_membresia_cuota_social_has_no_area_or_predio(self, test_db):
        """A cuota social membership carries no area/predio/parcelaId/rol (CS-01)."""
        from datetime import date

        from backend.models.enums import ConceptoMembresia, EstadoMembresia
        from backend.models.membresia import Membresia
        from backend.models.socio import Socio

        test_db.add(
            Socio(
                id="s9",
                nombre="Sin Actividad",
                dni="30000009",
                telefono="",
                email="",
                direccion="",
                fechaAlta=date(2025, 1, 1),
                activo=True,
            )
        )
        test_db.commit()

        cuota = Membresia(
            id="m9",
            socioId="s9",
            estado=EstadoMembresia.ACTIVA,
            vencimiento=date(2027, 1, 10),
            concepto=ConceptoMembresia.CUOTA_SOCIAL,
        )
        test_db.add(cuota)
        test_db.commit()
        test_db.refresh(cuota)
        assert cuota.area is None
        assert cuota.predio is None
        assert cuota.parcelaId is None
        assert cuota.rol is None
        assert cuota.concepto == ConceptoMembresia.CUOTA_SOCIAL

    def test_pago_item_concepto_and_factor_defaults(self, test_db):
        """Legacy-shaped items get concepto=AREA and factor=1.0 (D2)."""
        from datetime import date

        from backend.models.enums import (
            Area,
            ConceptoCobro,
            EstadoMembresia,
            Predio,
        )
        from backend.models.arancel import Arancel
        from backend.models.membresia import Membresia
        from backend.models.pago import Pago, PagoItem
        from backend.models.socio import Socio

        test_db.add(
            Socio(
                id="s1",
                nombre="Ana",
                dni="30000001",
                telefono="",
                email="",
                direccion="",
                fechaAlta=date(2025, 1, 1),
                activo=True,
            )
        )
        test_db.commit()
        test_db.add(
            Arancel(
                id="a1",
                nombre="Balsa",
                area=Area.BALSEROS,
                predio=Predio.EMBALSE,
                monto=130000.0,
                vigenteDesde=date(2026, 1, 1),
            )
        )
        test_db.commit()
        test_db.add(
            Membresia(
                id="m1",
                socioId="s1",
                area=Area.BALSEROS,
                predio=Predio.EMBALSE,
                estado=EstadoMembresia.ACTIVA,
                vencimiento=date(2027, 1, 10),
            )
        )
        test_db.commit()
        test_db.add(
            Pago(
                id="pg1",
                numero="0001",
                socioId="s1",
                fecha=date(2026, 1, 5),
                medio="efectivo",
                total=130000.0,
            )
        )
        test_db.commit()

        item = PagoItem(
            id="pi1",
            pagoId="pg1",
            arancelId="a1",
            membresiaId="m1",
            montoAplicado=130000.0,
            arancelNombre="Balsa",
        )
        test_db.add(item)
        test_db.commit()
        test_db.refresh(item)
        assert item.concepto == ConceptoCobro.AREA
        assert item.factor == 1.0

        # A multiplied cuota social line records its factor (PAG-01).
        item.factor = 4.0
        item.concepto = ConceptoCobro.CUOTA_SOCIAL
        test_db.commit()
        test_db.refresh(item)
        assert (item.concepto, item.factor) == (ConceptoCobro.CUOTA_SOCIAL, 4.0)

    def test_arancel_concepto_defaults_to_area(self, test_db):
        from datetime import date

        from backend.models.arancel import Arancel
        from backend.models.enums import Area, ConceptoCobro, Predio

        recargo = Arancel(
            id="a2",
            nombre="Recargo",
            area=Area.BALSEROS,
            predio=Predio.EMBALSE,
            monto=0.0,
            vigenteDesde=date(2026, 1, 1),
            concepto=ConceptoCobro.RECARGO,
        )
        test_db.add(recargo)
        test_db.commit()
        test_db.refresh(recargo)
        assert recargo.concepto == ConceptoCobro.RECARGO
        # A RECARGO carrier never defines a fixed amount (ARA-01).
        assert recargo.monto == 0.0

    def test_parcela_cuota_social_incluida_defaults_off(self, test_db):
        from backend.models.enums import Predio, TipoParcela
        from backend.models.parcela import Parcela

        p = Parcela(
            id="p1",
            nombre="Guardería Norte",
            tipo=TipoParcela.GUARDERIA,
            predio=Predio.ALMAFUERTE,
        )
        test_db.add(p)
        test_db.commit()
        test_db.refresh(p)
        assert p.cuotaSocialIncluida is False

        p.cuotaSocialIncluida = True
        test_db.commit()
        test_db.refresh(p)
        assert p.cuotaSocialIncluida is True
