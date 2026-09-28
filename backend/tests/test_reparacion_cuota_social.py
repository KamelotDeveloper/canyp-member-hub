"""Focused cuota-social repair (socios without a cuota row).

The properties that make it safe to hand to an operator:

* the plan is COMPLETE and read-only — a dry run writes nothing;
* the apply path creates one cuota social per socio lacking one, is idempotent
  (a second run is a no-op) and takes a full backup FIRST, reporting path+SHA256;
* NOTHING in ``pagos`` / ``pago_items`` is created, altered or deleted, and no
  existing ``vencimiento`` is moved (contrast with ``migracion_cuota_social``,
  whose apply also projects every date onto the 10->10 cycle).
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
from backend.services import reparacion_cuota_social as reparacion
from backend.services.cuota_social import cuota_de

DIA10_EJEMPLO = date(2026, 10, 10)


@pytest.fixture()
def fake_backup(monkeypatch, tmp_path):
    """Stand in for ``services/backup.py`` with a REAL SQLite dump.

    The apply path must be proven to take a genuine pre-write snapshot, so this
    copies the live (in-memory) database through sqlite3's backup API at the
    moment ``create_backup`` is called. The dump is then opened and asserted on.
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
    s = Socio(
        id=socio_id,
        nombre=f"Socio {socio_id}",
        dni=f"30{socio_id:0>6}",
        fechaAlta=date(2026, 1, 1),
    )
    db.add(s)
    db.commit()
    return s


def _legacy(db, mid, socio_id, *, area=Area.BALSEROS, predio=Predio.EMBALSE,
            vencimiento=date(2026, 7, 3)):
    """A pre-change membership: AREA concept, a NON-day-10 date."""
    m = Membresia(
        id=mid,
        socioId=socio_id,
        area=area,
        predio=predio,
        estado=EstadoMembresia.ACTIVA,
        vencimiento=vencimiento,
        parcelaId=None,
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
        (p.id, p.fecha.isoformat(), p.total, p.medio) for p in db.query(Pago).all()
    ), sorted(
        (i.id, i.pagoId, i.membresiaId, i.montoAplicado) for i in db.query(PagoItem).all()
    )


def _vencimientos(db):
    return {m.id: m.vencimiento for m in db.query(Membresia).all()}


class TestGuardSchema:
    """The repair refuses to run before `migrate.py` has prepared the schema."""

    def test_missing_concepto_column_is_a_hard_error(self, test_db):
        test_db.execute(text("ALTER TABLE membresias DROP COLUMN concepto"))
        test_db.commit()

        with pytest.raises(reparacion.ReparacionCuotaSocialError) as exc:
            reparacion.plan(test_db)
        assert "backend.migrate" in str(exc.value)


class TestPlanEsSoloLectura:
    """A dry run reports the complete plan and writes nothing."""

    def test_plan_lists_every_socio_without_a_cuota(self, test_db):
        _socio(test_db, "s1")
        _socio(test_db, "s2")
        _legacy(test_db, "m1", "s1")

        plan = reparacion.plan(test_db)
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

        plan = reparacion.plan(test_db)
        assert plan.socios_sin_cuota == 0
        assert plan.cuota_a_crear == ()
        assert plan.sin_cambios is True

    def test_dry_run_writes_nothing(self, test_db):
        _socio(test_db, "s1")
        _legacy(test_db, "m1", "s1", vencimiento=date(2026, 7, 3))

        reparacion.reparar(test_db, dry_run=True)

        assert test_db.query(Membresia).count() == 1  # no cuota row created
        assert test_db.query(Membresia).filter(
            Membresia.concepto == ConceptoMembresia.CUOTA_SOCIAL
        ).count() == 0

    def test_dry_run_takes_no_backup(self, test_db, fake_backup):
        _socio(test_db, "s1")
        reparacion.reparar(test_db, dry_run=True)
        assert fake_backup.calls == 0


class TestApply:
    """The write path, on an already-prepared schema."""

    def test_creates_exactly_one_cuota_social_per_missing_socio(self, test_db, fake_backup):
        _socio(test_db, "s1")
        _socio(test_db, "s2")
        _legacy(test_db, "m1", "s1")
        _legacy(test_db, "m2", "s2")

        plan = reparacion.reparar(test_db, dry_run=False, engine=test_db.get_bind())

        assert plan.cuota_a_crear == ("s1", "s2")
        assert plan.ejecucion is True
        for socio_id in ("s1", "s2"):
            cuotas = [
                m
                for m in test_db.query(Membresia).filter(Membresia.socioId == socio_id)
                if m.concepto == ConceptoMembresia.CUOTA_SOCIAL
            ]
            assert len(cuotas) == 1
            assert cuotas[0].area is None and cuotas[0].predio is None

    def test_only_the_missing_rows_are_created(self, test_db, fake_backup):
        _socio(test_db, "s1")
        _socio(test_db, "s2")
        _legacy(test_db, "m1", "s1")
        test_db.add(
            Membresia(id="cu2", socioId="s2", estado=EstadoMembresia.ACTIVA,
                      vencimiento=DIA10_EJEMPLO, concepto=ConceptoMembresia.CUOTA_SOCIAL)
        )
        test_db.commit()

        plan = reparacion.reparar(test_db, dry_run=False, engine=test_db.get_bind())
        assert plan.cuota_a_crear == ("s1",)
        assert cuota_de(test_db, "s2").id == "cu2"

    def test_apply_never_touches_vencimientos_nor_pagos(self, test_db, fake_backup):
        _socio(test_db, "s1")
        _legacy(test_db, "m1", "s1", vencimiento=date(2026, 7, 3))
        _legacy(test_db, "m2", "s1", vencimiento=date(2026, 7, 20))
        _pago(test_db)
        venc_antes = _vencimientos(test_db)
        pagos_antes = _snap_pagos(test_db)

        reparacion.reparar(test_db, dry_run=False, engine=test_db.get_bind())

        # The existing dates are byte-for-byte the same: no projection happened.
        venc_despues = {k: v for k, v in _vencimientos(test_db).items() if k in venc_antes}
        assert venc_despues == venc_antes
        assert test_db.query(Pago).count() == 1
        assert test_db.query(PagoItem).count() == 1
        assert _snap_pagos(test_db) == pagos_antes


class TestIdempotencia:
    """A second run is a no-op."""

    def test_second_run_has_nothing_left_to_do(self, test_db, fake_backup):
        _socio(test_db, "s1")
        _socio(test_db, "s2")
        _legacy(test_db, "m1", "s1", vencimiento=date(2026, 7, 3))
        _legacy(test_db, "m2", "s2", vencimiento=date(2026, 7, 20))

        reparacion.reparar(test_db, dry_run=False, engine=test_db.get_bind())
        plan_2 = reparacion.reparar(test_db, dry_run=False, engine=test_db.get_bind())

        assert plan_2.sin_cambios is True
        assert plan_2.cuota_a_crear == ()
        assert plan_2.ejecucion is False
        assert fake_backup.calls == 1  # a no-op apply takes no second backup

    def test_second_run_does_not_duplicate_cuotas(self, test_db, fake_backup):
        _socio(test_db, "s1")
        _legacy(test_db, "m1", "s1", vencimiento=date(2026, 7, 3))

        reparacion.reparar(test_db, dry_run=False, engine=test_db.get_bind())
        reparacion.reparar(test_db, dry_run=False, engine=test_db.get_bind())

        cuotas = [
            m
            for m in test_db.query(Membresia).all()
            if m.concepto == ConceptoMembresia.CUOTA_SOCIAL
        ]
        assert len(cuotas) == 1


class TestBackupAntesDeEscribir:
    """The operator contract: no write happens without a fresh full dump."""

    def test_apply_takes_a_backup_before_writing(self, test_db, fake_backup):
        _socio(test_db, "s1")
        _legacy(test_db, "m1", "s1", vencimiento=date(2026, 7, 3))

        plan = reparacion.reparar(test_db, dry_run=False, engine=test_db.get_bind())

        assert fake_backup.calls == 1
        assert plan.ruta_backup == str(fake_backup.path)
        assert plan.sha256_backup == hashlib.sha256(fake_backup.path.read_bytes()).hexdigest()

    def test_backup_contains_the_pre_repair_state(self, test_db, fake_backup):
        _socio(test_db, "s1")
        _legacy(test_db, "m1", "s1", vencimiento=date(2026, 7, 3))

        reparacion.reparar(test_db, dry_run=False, engine=test_db.get_bind())

        copia = sqlite3.connect(fake_backup.path)
        try:
            fila = copia.execute(
                "SELECT COUNT(*) FROM membresias WHERE concepto = 'CUOTA_SOCIAL'"
            ).fetchone()
        finally:
            copia.close()
        assert fila[0] == 0

    def test_noop_apply_takes_no_backup(self, test_db, fake_backup):
        _socio(test_db, "s1")
        test_db.add(
            Membresia(id="cu1", socioId="s1", estado=EstadoMembresia.ACTIVA,
                      vencimiento=DIA10_EJEMPLO, concepto=ConceptoMembresia.CUOTA_SOCIAL)
        )
        test_db.commit()

        plan = reparacion.reparar(test_db, dry_run=False, engine=test_db.get_bind())

        assert plan.sin_cambios is True
        assert fake_backup.calls == 0


class TestResumenOperador:
    """The printed report is the handoff artifact: complete counts, no ambiguity."""

    def test_dry_run_summary_reports_count_and_which(self, test_db):
        _socio(test_db, "s1")
        _socio(test_db, "s2")
        _legacy(test_db, "m1", "s1")

        texto = reparacion.plan(test_db).resumen()
        assert "socios sin cuota social .... 2" in texto
        assert "s1" in texto and "s2" in texto
        assert "escribiría" in texto

    def test_sample_is_truncated_but_the_count_is_not(self, test_db, monkeypatch):
        monkeypatch.setattr(reparacion, "EJEMPLOS_MAXIMOS", 2)
        for i in range(5):
            _socio(test_db, f"s{i}")

        plan = reparacion.plan(test_db)
        texto = plan.resumen()

        assert plan.socios_sin_cuota == 5
        assert "... y 3 más" in texto
