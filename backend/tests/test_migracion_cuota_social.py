"""Legacy conversion migration (spec CBM-05, CBM-06, CS-01, CS-06).

The four properties that make this safe to hand to an operator:

* the plan is COMPLETE and read-only — a dry run writes nothing;
* the apply path creates one cuota social per socio and projects every
  ``vencimiento`` onto ``dia10`` (at-or-after), so a second run is a no-op;
* NOTHING in ``pagos`` / ``pago_items`` is created, altered or deleted;
* an apply takes a full backup FIRST and reports its path + SHA256.
"""

import hashlib
import sqlite3
from datetime import date

import pytest
from sqlalchemy import text

from backend.models.arancel import Arancel
from backend.models.enums import Area, ConceptoMembresia, EstadoMembresia, Predio
from backend.models.membresia import Membresia
from backend.models.pago import Pago, PagoItem
from backend.models.socio import Socio
from backend.services import backup as backup_service
from backend.services import migracion_cuota_social as migracion
from backend.services.cuota_social import cuota_de
from backend.services.renovacion import dia10

DIA10_EJEMPLO = date(2026, 10, 10)


@pytest.fixture()
def fake_backup(monkeypatch, tmp_path):
    """Stand in for ``services/backup.py`` with a REAL SQLite dump.

    The apply path must be proven to take a genuine pre-write snapshot, so this
    does not fake a file: it copies the live (in-memory) database through
    sqlite3's backup API at the moment ``create_backup`` is called. The dump is
    then opened and asserted on.
    """
    class FakeBackup:
        path = tmp_path / "canyp-backup.db"
        calls = 0

    fake = FakeBackup()

    def _create_backup(source_engine):
        fake.calls += 1
        destino = sqlite3.connect(str(fake.path))
        # raw_connection() checks a connection out of the StaticPool; it MUST be
        # returned to the pool (close(), not the driver's close) or the in-memory
        # database is destroyed for the rest of the test.
        cruda = source_engine.raw_connection()
        try:
            cruda.driver_connection.backup(destino)
        finally:
            cruda.close()
            destino.close()
        return {"tables": 0, "rows": {}, "path": str(fake.path)}

    monkeypatch.setattr(backup_service, "create_backup", _create_backup)
    return fake


def _socio(db, socio_id="s1"):
    s = Socio(id=socio_id, nombre=f"Socio {socio_id}", dni=f"30{socio_id:0>6}", fechaAlta=date(2026, 1, 1))
    db.add(s)
    db.commit()
    return s


def _legacy(db, mid, socio_id, *, area=Area.BALSEROS, predio=Predio.EMBALSE,
            vencimiento=date(2026, 7, 3), parcela_id=None):
    """A pre-change membership: AREA concept, a NON-day-10 date.

    ``parcela_id`` defaults to None so the row satisfies the FK without forcing
    a Parcela fixture into every test; the cuota projection never depends on it.
    """
    m = Membresia(
        id=mid,
        socioId=socio_id,
        area=area,
        predio=predio,
        estado=EstadoMembresia.ACTIVA,
        vencimiento=vencimiento,
        parcelaId=parcela_id,
    )
    db.add(m)
    db.commit()
    return m


def _pago(db, pago_id="p1", socio_id="s1", membresia_id="m1", monto=18500.0):
    """A real payment + item, so 'no writes to pagos' is asserted on real rows."""
    db.add(
        Arancel(id="a1", nombre="Amarre y Servicios", area=Area.BALSEROS,
                predio=Predio.EMBALSE, monto=monto, vigenteDesde=date(2026, 1, 1),
                historico=[])
    )
    pago = Pago(id=pago_id, numero=f"0001-{pago_id}", socioId=socio_id,
                fecha=date(2026, 6, 1), medio="efectivo", total=monto)
    db.add(pago)
    db.add(
        PagoItem(id=f"{pago_id}i1", pagoId=pago_id, arancelId="a1",
                 membresiaId=membresia_id, montoAplicado=monto,
                 arancelNombre="Amarre y Servicios")
    )
    db.commit()
    return pago


def _snap_pagos(db):
    return sorted(
        (p.id, p.fecha.isoformat(), p.total, p.medio)
        for p in db.query(Pago).all()
    ), sorted(
        (i.id, i.pagoId, i.membresiaId, i.montoAplicado) for i in db.query(PagoItem).all()
    )


def _vencimientos(db):
    return {m.id: m.vencimiento for m in db.query(Membresia).all()}


class TestGuardSchema:
    """The migration refuses to run before `migrate.py` has prepared the schema."""

    def test_missing_concepto_column_is_a_hard_error(self, test_db, tmp_path):
        # Drop the column the migration depends on, exactly as a pre-PR1 DB looks.
        test_db.execute(text("ALTER TABLE membresias DROP COLUMN concepto"))
        test_db.commit()

        with pytest.raises(migracion.MigracionCuotaSocialError) as exc:
            migracion.plan(test_db)
        assert "backend.migrate" in str(exc.value)


class TestPlanEsSoloLectura:
    """A dry run reports the complete plan and writes nothing."""

    def test_plan_lists_every_socio_without_a_cuota(self, test_db):
        _socio(test_db, "s1")
        _socio(test_db, "s2")
        _legacy(test_db, "m1", "s1")

        plan = migracion.plan(test_db)
        assert plan.socios == 2
        assert plan.socios_sin_cuota == 2
        assert plan.cuota_a_crear == ("s1", "s2")

    def test_plan_skips_socios_that_already_have_a_cuota(self, test_db):
        _socio(test_db, "s1")
        _legacy(test_db, "m1", "s1")
        test_db.add(
            Membresia(id="cu1", socioId="s1", estado=EstadoMembresia.ACTIVA,
                      vencimiento=DIA10_EJEMPLO, concepto=ConceptoMembresia.CUOTA_SOCIAL)
        )
        test_db.commit()

        plan = migracion.plan(test_db)
        assert plan.socios_sin_cuota == 0
        assert plan.cuota_a_crear == ()

    def test_plan_projects_every_off_cycle_date(self, test_db):
        _socio(test_db, "s1")
        _legacy(test_db, "m1", "s1", vencimiento=date(2026, 7, 3))
        _legacy(test_db, "m2", "s1", vencimiento=date(2026, 7, 20))
        _legacy(test_db, "m3", "s1", vencimiento=DIA10_EJEMPLO)  # already aligned

        plan = migracion.plan(test_db)
        cambios = {c.membresia_id: (c.anterior, c.nuevo) for c in plan.cambios}
        assert cambios["m1"] == (date(2026, 7, 3), date(2026, 7, 10))
        assert cambios["m2"] == (date(2026, 7, 20), date(2026, 8, 10))
        assert "m3" not in cambios
        assert plan.proyecciones == 2

    def test_plan_includes_the_projection_of_a_future_cuota_row(self, test_db):
        """A new cuota inherits a legacy date, so its projection must be visible."""
        _socio(test_db, "s1")
        _legacy(test_db, "m1", "s1", vencimiento=date(2026, 7, 3))

        plan = migracion.plan(test_db)
        nuevas = [
            c
            for c in plan.cambios
            if c.socio_id == "s1"
            and c.concepto == ConceptoMembresia.CUOTA_SOCIAL.value
        ]
        assert len(nuevas) == 1
        assert nuevas[0].nuevo == date(2026, 7, 10)

    def test_dry_run_writes_nothing(self, test_db):
        _socio(test_db, "s1")
        _legacy(test_db, "m1", "s1", vencimiento=date(2026, 7, 3))
        antes = _vencimientos(test_db)

        migracion.migrar(test_db, dry_run=True)

        assert _vencimientos(test_db) == antes
        assert test_db.query(Membresia).count() == 1  # no cuota row created

    def test_dry_run_never_touches_pagos(self, test_db):
        _socio(test_db, "s1")
        _legacy(test_db, "m1", "s1", vencimiento=date(2026, 7, 3))
        _pago(test_db)
        antes = _snap_pagos(test_db)

        migracion.migrar(test_db, dry_run=True)

        assert _snap_pagos(test_db) == antes


class TestApply:
    """The write path, on an already-prepared schema."""

    def test_creates_exactly_one_cuota_social_per_socio(self, test_db, fake_backup):
        _socio(test_db, "s1")
        _socio(test_db, "s2")
        _legacy(test_db, "m1", "s1")
        _legacy(test_db, "m2", "s2")

        plan = migracion.migrar(test_db, dry_run=False, engine=test_db.get_bind())

        assert plan.cuota_a_crear == ("s1", "s2")
        for socio_id in ("s1", "s2"):
            cuotas = [
                m
                for m in test_db.query(Membresia).filter(Membresia.socioId == socio_id)
                if m.concepto == ConceptoMembresia.CUOTA_SOCIAL
            ]
            assert len(cuotas) == 1
            assert cuotas[0].area is None and cuotas[0].predio is None

    def test_cuota_inherits_the_latest_area_vencimiento(self, test_db, fake_backup):
        _socio(test_db, "s1")
        _legacy(test_db, "m1", "s1", vencimiento=date(2026, 3, 15))
        _legacy(test_db, "m2", "s1", vencimiento=date(2026, 7, 3))

        migracion.migrar(test_db, dry_run=False, engine=test_db.get_bind())

        # Inherits the MOST RECENT area date (7/03), then projected to 7/10.
        assert cuota_de(test_db, "s1").vencimiento == date(2026, 7, 10)

    def test_socio_without_activity_anchors_on_the_current_window(self, test_db, fake_backup):
        from backend.services.cuota_social import ventana_actual

        _socio(test_db, "s1")
        migracion.migrar(test_db, dry_run=False, engine=test_db.get_bind())
        assert cuota_de(test_db, "s1").vencimiento == ventana_actual()

    def test_projects_every_vencimiento_onto_day_10(self, test_db, fake_backup):
        _socio(test_db, "s1")
        _legacy(test_db, "m1", "s1", vencimiento=date(2026, 7, 3))
        _legacy(test_db, "m2", "s1", vencimiento=date(2026, 7, 20))
        _legacy(test_db, "m3", "s1", vencimiento=DIA10_EJEMPLO)

        migracion.migrar(test_db, dry_run=False, engine=test_db.get_bind())

        vencimientos = _vencimientos(test_db)
        assert vencimientos["m1"] == date(2026, 7, 10)
        assert vencimientos["m2"] == date(2026, 8, 10)
        assert vencimientos["m3"] == DIA10_EJEMPLO
        assert all(v.day == 10 for v in vencimientos.values())

    def test_projection_is_at_or_after_never_backwards(self, test_db, fake_backup):
        _socio(test_db, "s1")
        _legacy(test_db, "m1", "s1", vencimiento=date(2026, 7, 10))  # day 10 stays
        _legacy(test_db, "m2", "s1", vencimiento=date(2026, 7, 11))  # day 11 -> next 10
        _legacy(test_db, "m3", "s1", vencimiento=date(2026, 7, 9))   # day 9 -> same month

        antes = _vencimientos(test_db)
        migracion.migrar(test_db, dry_run=False, engine=test_db.get_bind())
        despues = _vencimientos(test_db)

        assert despues["m1"] == antes["m1"]
        assert despues["m2"] == date(2026, 8, 10)
        assert despues["m3"] == date(2026, 7, 10)
        assert all(n >= a for a, n in zip(sorted(antes.values()), sorted(despues.values())))

    def test_conceptos_are_preserved_and_backfilled(self, test_db, fake_backup):
        _socio(test_db, "s1")
        _legacy(test_db, "m1", "s1")
        migracion.migrar(test_db, dry_run=False, engine=test_db.get_bind())

        por_id = {m.id: m for m in test_db.query(Membresia).all()}
        assert por_id["m1"].concepto == ConceptoMembresia.AREA
        assert por_id["m1"].area == Area.BALSEROS
        cuota = cuota_de(test_db, "s1")
        assert cuota.concepto == ConceptoMembresia.CUOTA_SOCIAL

    def test_stored_conceptos_are_enum_names_in_sqlite(self, test_db, fake_backup):
        """SQLite stores the NAME, not the value — asserted against raw SQL."""
        _socio(test_db, "s1")
        _legacy(test_db, "m1", "s1")
        migracion.migrar(test_db, dry_run=False, engine=test_db.get_bind())

        crudos = dict(
            test_db.execute(text("SELECT id, concepto FROM membresias")).all()
        )
        assert crudos["m1"] == "AREA"
        assert crudos[cuota_de(test_db, "s1").id] == "CUOTA_SOCIAL"

    def test_apply_never_touches_pagos(self, test_db, fake_backup):
        _socio(test_db, "s1")
        _legacy(test_db, "m1", "s1", vencimiento=date(2026, 7, 3))
        _pago(test_db)
        antes = _snap_pagos(test_db)

        migracion.migrar(test_db, dry_run=False, engine=test_db.get_bind())

        assert _snap_pagos(test_db) == antes
        # The payment still points at the same membership, which kept its id.
        assert test_db.query(Pago).count() == 1
        assert test_db.query(PagoItem).count() == 1


class TestIdempotencia:
    """A second run is a no-op — the whole point of at-or-after `dia10`."""

    def test_second_run_has_nothing_left_to_do(self, test_db, fake_backup):
        _socio(test_db, "s1")
        _socio(test_db, "s2")
        _legacy(test_db, "m1", "s1", vencimiento=date(2026, 7, 3))
        _legacy(test_db, "m2", "s2", vencimiento=date(2026, 7, 20))
        _pago(test_db)

        migracion.migrar(test_db, dry_run=False, engine=test_db.get_bind())
        despues_1 = _vencimientos(test_db)
        plan_2 = migracion.migrar(test_db, dry_run=False, engine=test_db.get_bind())

        assert plan_2.sin_cambios is True
        assert plan_2.cuota_a_crear == ()
        assert plan_2.cambios == ()
        assert _vencimientos(test_db) == despues_1

    def test_second_run_does_not_duplicate_cuotas(self, test_db, fake_backup):
        _socio(test_db, "s1")
        _legacy(test_db, "m1", "s1", vencimiento=date(2026, 7, 3))

        migracion.migrar(test_db, dry_run=False, engine=test_db.get_bind())
        migracion.migrar(test_db, dry_run=False, engine=test_db.get_bind())

        cuotas = [
            m
            for m in test_db.query(Membresia).all()
            if m.concepto == ConceptoMembresia.CUOTA_SOCIAL
        ]
        assert len(cuotas) == 1

    def test_third_run_is_still_a_noop_after_manual_legacy_data_arrives(self, test_db, fake_backup):
        """New legacy data is picked up, not skipped, and converges again."""
        _socio(test_db, "s1")
        _legacy(test_db, "m1", "s1", vencimiento=date(2026, 7, 3))
        migracion.migrar(test_db, dry_run=False, engine=test_db.get_bind())

        _legacy(test_db, "m-late", "s1", vencimiento=date(2026, 5, 17))
        plan = migracion.migrar(test_db, dry_run=False, engine=test_db.get_bind())

        assert [c.membresia_id for c in plan.cambios] == ["m-late"]
        assert _vencimientos(test_db)["m-late"] == date(2026, 6, 10)
        assert migracion.plan(test_db).sin_cambios is True


class TestBackupAntesDeEscribir:
    """The operator contract: no write happens without a fresh full dump."""

    def test_apply_takes_a_backup_before_writing(self, test_db, fake_backup):
        _socio(test_db, "s1")
        _legacy(test_db, "m1", "s1", vencimiento=date(2026, 7, 3))

        plan = migracion.migrar(test_db, dry_run=False, engine=test_db.get_bind())

        assert fake_backup.calls == 1
        assert plan.ejecucion is True
        assert plan.ruta_backup == str(fake_backup.path)
        assert plan.sha256_backup == hashlib.sha256(fake_backup.path.read_bytes()).hexdigest()

    def test_backup_contains_the_pre_migration_state(self, test_db, fake_backup):
        """The dump is taken BEFORE the writes, so it holds the legacy dates."""
        _socio(test_db, "s1")
        _legacy(test_db, "m1", "s1", vencimiento=date(2026, 7, 3))

        migracion.migrar(test_db, dry_run=False, engine=test_db.get_bind())

        import sqlite3 as s3

        copia = s3.connect(fake_backup.path)
        try:
            fila = copia.execute(
                "SELECT vencimiento FROM membresias WHERE id = 'm1'"
            ).fetchone()
        finally:
            copia.close()
        assert fila[0] == "2026-07-03"

    def test_dry_run_takes_no_backup(self, test_db, fake_backup):
        _socio(test_db, "s1")
        _legacy(test_db, "m1", "s1", vencimiento=date(2026, 7, 3))

        migracion.migrar(test_db, dry_run=True)

        assert fake_backup.calls == 0

    def test_apply_uses_create_backup_not_the_interval_gate(self, test_db, fake_backup, monkeypatch):
        """A fresh dump every time, even inside the 15-day window."""
        monkeypatch.setattr(backup_service, "should_backup", lambda *a, **k: False)
        _socio(test_db, "s1")
        _legacy(test_db, "m1", "s1", vencimiento=date(2026, 7, 3))

        migracion.migrar(test_db, dry_run=False, engine=test_db.get_bind())

        assert fake_backup.calls == 1

    def test_a_failed_backup_aborts_before_any_write(self, test_db, monkeypatch):
        _socio(test_db, "s1")
        _legacy(test_db, "m1", "s1", vencimiento=date(2026, 7, 3))
        antes = _vencimientos(test_db)

        def _boom(engine):
            raise OSError("disk full")

        monkeypatch.setattr(backup_service, "create_backup", _boom)
        with pytest.raises(OSError):
            migracion.migrar(test_db, dry_run=False, engine=test_db.get_bind())

        assert _vencimientos(test_db) == antes
        assert test_db.query(Membresia).count() == 1


class TestResumenOperador:
    """The printed report is the handoff artifact: complete counts, no ambiguity."""

    def test_dry_run_summary_reports_complete_counts(self, test_db):
        _socio(test_db, "s1")
        _legacy(test_db, "m1", "s1", vencimiento=date(2026, 7, 3))

        texto = migracion.plan(test_db).resumen()
        assert "socios sin cuota social .... 1" in texto
        assert "filas CUOTA_SOCIAL a crear . 1" in texto
        assert "2026-07-03 -> 2026-07-10" in texto
        assert "escribiría" in texto

    def test_apply_summary_reports_what_was_written(self, test_db, fake_backup):
        _socio(test_db, "s1")
        _legacy(test_db, "m1", "s1", vencimiento=date(2026, 7, 3))

        texto = migracion.migrar(
            test_db, dry_run=False, engine=test_db.get_bind()
        ).resumen()

        # Not zeros: the report is the pre-apply plan, i.e. the record of writes.
        assert "filas CUOTA_SOCIAL a crear . 1" in texto
        assert "2026-07-03 -> 2026-07-10" in texto
        assert "escribió" in texto
        assert fake_backup.path.name in texto

    def test_sample_is_truncated_but_the_count_is_not(self, test_db, monkeypatch):
        monkeypatch.setattr(migracion, "EJEMPLOS_MAXIMOS", 2)
        for i in range(5):
            _socio(test_db, f"s{i}")
            _legacy(test_db, f"m{i}", f"s{i}", vencimiento=date(2026, 7, 3))

        plan = migracion.plan(test_db)
        texto = plan.resumen()

        assert plan.proyecciones == 10  # 5 areas + 5 inherited quota dates
        assert "... y 3 más" in texto
