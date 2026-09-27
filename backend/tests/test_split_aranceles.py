"""Split migration of the merged arancel (D6/D7, ReQ-011, ReQ-014, ReQ-015).

The five properties that make this safe to hand to an operator:

* the plan is COMPLETE and read-only — a dry run writes nothing, and the
  default of ``apply``/``invertir`` is that dry run;
* the apply is idempotent — the inserted row has a deterministic id, so a
  second run reports the skip and creates nothing;
* ``monto`` is NEVER touched, in either direction (ReQ-105);
* the historical ``PagoItem`` context survives: the receipts keep pointing at
  ``a1`` (now "Amarre") and their frozen ``arancelNombre`` is not rewritten
  (ReQ-016);
* the inverse is idempotent, refuses to delete a REFERENCED row by name, and
  re-applying after it converges back to the split state.
"""

import hashlib
import sqlite3
from datetime import date

import pytest

from backend.models.arancel import Arancel
from backend.models.enums import (
    Area,
    ConceptoCobro,
    ConceptoMembresia,
    EstadoMembresia,
    Predio,
)
from backend.models.membresia import Membresia
from backend.models.pago import Pago, PagoItem
from backend.models.socio import Socio
from backend.services import backup as backup_service
from backend.services import migracion_split_aranceles as migracion
from backend.services.resolucion import precio_servicio

ORIGEN = migracion.SPLITS[0].origen_id
SERVICIO_ID = migracion.SPLITS[0].servicio_id
MONTO_ORIGEN = 18500.0


@pytest.fixture()
def fake_backup(monkeypatch, tmp_path):
    """Stand in for ``services/backup.py`` with a REAL SQLite dump.

    The apply path must be proven to take a genuine pre-write snapshot, so this
    does not fake a file: it copies the live (in-memory) database through
    sqlite3's backup API at the moment ``create_backup`` is called.
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


def _base_legado(db, monto=MONTO_ORIGEN):
    """The pre-split world: merged ``a1`` + a socio + 2 receipts on it.

    The flushes are load-bearing: with ``PRAGMA foreign_keys=ON`` a single
    commit does not order the ``socios`` INSERT before the ``membresias`` one,
    so the FK fails. Same pattern as ``test_pagos_api._seed_unidad``.
    """
    db.add(Socio(id="s1", nombre="Socio 1", dni="30123456", fechaAlta=date(2026, 1, 1)))
    db.flush()
    db.add(
        Membresia(
            id="m1", socioId="s1", area=Area.BALSEROS, predio=Predio.EMBALSE,
            estado=EstadoMembresia.ACTIVA, vencimiento=date(2026, 10, 10),
            parcelaId=None,
        )
    )
    db.add(
        Arancel(
            id=ORIGEN, nombre="Amarre y Servicios", area=Area.BALSEROS,
            predio=Predio.EMBALSE, monto=monto, vigenteDesde=date(2026, 1, 1),
            historico=[{"monto": 15000.0, "vigenteDesde": "2025-01-01"}],
        )
    )
    db.flush()
    for i, pago_id in enumerate(("p1", "p2"), start=1):
        db.add(
            Pago(id=pago_id, numero=f"0001-{pago_id}", socioId="s1",
                 fecha=date(2026, 6, i), medio="efectivo", total=monto)
        )
        db.flush()
        db.add(
            PagoItem(id=f"pi{i}", pagoId=pago_id, arancelId=ORIGEN, membresiaId="m1",
                     montoAplicado=monto, arancelNombre="Amarre y Servicios")
        )
    db.commit()


def _arancel(db, arancel_id):
    return db.get(Arancel, arancel_id)


def _ids_arancel(db):
    return sorted(a.id for a in db.query(Arancel).all())


def _pago_items(db):
    return sorted(
        (i.id, i.arancelId, i.montoAplicado, i.arancelNombre)
        for i in db.query(PagoItem).all()
    )


def _texto(plan):
    return "\n".join(plan)


class TestPlanEsSoloLectura:
    """A dry run reports the complete plan and writes nothing."""

    def test_plan_nombra_el_origen_el_destino_y_el_monto_configurado(self, test_db):
        _base_legado(test_db)

        texto = _texto(migracion.plan(test_db))

        assert f"{ORIGEN}: 'Amarre y Servicios' -> 'Amarre'" in texto
        assert f"monto {MONTO_ORIGEN:.2f} intacto" in texto
        # The service amount is CONFIGURED, and the plan says so out loud.
        assert f"monto=5000.00 (configurado, nunca inferido de {MONTO_ORIGEN:.2f})" in texto

    def test_plan_reporta_historico_y_pago_items_del_origen(self, test_db):
        _base_legado(test_db)

        texto = _texto(migracion.plan(test_db))

        assert "historico: 1 entrada(s) copiada(s) a la fila nueva" in texto
        assert f"pago_items que siguen apuntando a {ORIGEN}: 2 (pi1, pi2)" in texto
        assert "sin cambios: no" in texto

    def test_dry_run_es_el_default_de_apply_y_no_escribe(self, test_db, capsys):
        _base_legado(test_db)
        antes = _ids_arancel(test_db)

        migracion.apply(test_db)  # NO dry_run kwarg: the default must be dry

        assert _ids_arancel(test_db) == antes
        assert _arancel(test_db, ORIGEN).nombre == "Amarre y Servicios"
        assert "Dry run complete. No changes were written." in capsys.readouterr().out

    def test_dry_run_de_invertir_tampoco_escribe(self, test_db, fake_backup, capsys):
        _base_legado(test_db)
        migracion.apply(test_db, dry_run=False, engine=test_db.get_bind())
        llamadas = fake_backup.calls
        capsys.readouterr()  # drain the apply's own log

        migracion.invertir(test_db)  # default dry

        assert _arancel(test_db, SERVICIO_ID) is not None
        assert fake_backup.calls == llamadas
        salida = capsys.readouterr().out
        assert "No changes were written" in salida
        # A revert log talks about DELETING, never about inserting a row.
        assert f"- borrado {SERVICIO_ID}" in salida
        assert f"+ servicio {SERVICIO_ID}" not in salida

    def test_la_auditoria_se_imprime_antes_de_todo_plan(self, test_db):
        _base_legado(test_db)
        plan = migracion.plan(test_db)
        # `plan` is the narrative the CLI prints: a list of str, audit first.
        assert isinstance(plan, list) and all(isinstance(l, str) for l in plan)
        assert plan[0].startswith("Auditoría de asignaciones")
        assert "asignaciones inconsistentes: 0" in _texto(plan)
        assert plan[-1] == migracion.SIN_CAMBIOS_NO

    def test_la_auditoria_nombra_las_asignaciones_inconsistentes(self, test_db):
        """ReQ-011 BEFORE: a membership on a re-tagged row is found by query."""
        _base_legado(test_db)
        # m1 points at a row re-tagged to SERVICIO: it can no longer price its
        # own AREA line.
        _arancel(test_db, ORIGEN).concepto = ConceptoCobro.SERVICIO
        db_m = test_db.get(Membresia, "m1")
        db_m.arancelId = ORIGEN
        test_db.commit()

        lineas = migracion.auditar_mismatches(test_db)

        assert "m1 (s1)" in lineas[-2]
        assert "concepto=servicio" in lineas[-2]
        assert lineas[-1] == "  asignaciones inconsistentes: 1"

    def test_una_fila_que_no_es_la_combinada_es_un_error_duro(self, test_db):
        """Guarding against a catalog the migration was not written for."""
        _base_legado(test_db)
        _arancel(test_db, ORIGEN).concepto = ConceptoCobro.SERVICIO
        test_db.commit()

        with pytest.raises(migracion.MigracionSplitArancelesError) as exc:
            migracion.plan(test_db)
        assert "no como area" in str(exc.value)


class TestApply:
    """The write path on a database that still holds the merged row."""

    def test_deja_amarre_y_servicio(self, test_db, fake_backup):
        _base_legado(test_db)

        migracion.apply(test_db, dry_run=False, engine=test_db.get_bind())

        assert _arancel(test_db, ORIGEN).nombre == "Amarre"
        servicio = _arancel(test_db, SERVICIO_ID)
        assert servicio is not None
        assert servicio.nombre == "Servicio"
        assert servicio.concepto is ConceptoCobro.SERVICIO
        assert (servicio.area, servicio.predio) == (Area.BALSEROS, Predio.EMBALSE)
        # categoria NULL is the catch-all branch every parcel size lands on.
        assert servicio.categoria is None
        assert servicio.created_by == migracion.MARCA_CREATED_BY

    def test_el_monto_del_origen_no_se_toca(self, test_db, fake_backup):
        _base_legado(test_db)
        antes = _arancel(test_db, ORIGEN).monto

        migracion.apply(test_db, dry_run=False, engine=test_db.get_bind())

        assert _arancel(test_db, ORIGEN).monto == antes == MONTO_ORIGEN
        # ReQ-105: the service amount is configured, never derived from 18500.
        assert _arancel(test_db, SERVICIO_ID).monto == 5000.0

    def test_duplica_el_historico_en_la_fila_nueva(self, test_db, fake_backup):
        """ReQ-014c: the price trail survives the split."""
        _base_legado(test_db)
        antes = list(_arancel(test_db, ORIGEN).historico)

        migracion.apply(test_db, dry_run=False, engine=test_db.get_bind())

        assert _arancel(test_db, SERVICIO_ID).historico == antes
        assert _arancel(test_db, ORIGEN).historico == antes

    def test_el_historico_no_se_comparte_como_objeto(self, test_db, fake_backup):
        """Two rows must not alias one mutable list inside the session."""
        _base_legado(test_db)
        migracion.apply(test_db, dry_run=False, engine=test_db.get_bind())

        _arancel(test_db, SERVICIO_ID).historico[0]["monto"] = 999.0

        assert _arancel(test_db, ORIGEN).historico[0]["monto"] == 15000.0

    def test_el_contexto_de_pago_no_se_pierde(self, test_db, fake_backup):
        """The receipts keep naming a REAL arancel, and keep their frozen name."""
        _base_legado(test_db)
        antes = _pago_items(test_db)

        migracion.apply(test_db, dry_run=False, engine=test_db.get_bind())

        assert _pago_items(test_db) == antes  # ni un byte del comprobante cambió
        for item in test_db.query(PagoItem).all():
            assert _arancel(test_db, item.arancelId) is not None  # no id fantasma
            assert item.arancelNombre == "Amarre y Servicios"  # ReQ-016

    def test_la_fila_nueva_ya_resuelve_el_servicio_del_lugar(self, test_db, fake_backup):
        """The split leaves the place resolvable, not just renamed."""
        _base_legado(test_db)
        migracion.apply(test_db, dry_run=False, engine=test_db.get_bind())
        test_db.expire_all()

        assert precio_servicio(test_db, Area.BALSEROS, Predio.EMBALSE).id == SERVICIO_ID

    def test_toma_backup_antes_de_escribir(self, test_db, fake_backup):
        _base_legado(test_db)

        migracion.apply(test_db, dry_run=False, engine=test_db.get_bind())

        assert fake_backup.calls == 1
        # The dump was taken PRE-migration, so it still holds the merged name.
        copia = sqlite3.connect(fake_backup.path)
        try:
            fila = copia.execute(
                "SELECT nombre FROM aranceles WHERE id = ?", (ORIGEN,)
            ).fetchone()
        finally:
            copia.close()
        assert fila[0] == "Amarre y Servicios"
        assert _arancel(test_db, ORIGEN).nombre == "Amarre"

    def test_un_backup_fallido_aborta_antes_de_cualquier_escritura(self, test_db, monkeypatch):
        _base_legado(test_db)
        antes = _arancel(test_db, ORIGEN).nombre

        def _boom(engine):
            raise OSError("disk full")

        monkeypatch.setattr(backup_service, "create_backup", _boom)
        with pytest.raises(OSError):
            migracion.apply(test_db, dry_run=False, engine=test_db.get_bind())

        assert _arancel(test_db, ORIGEN).nombre == antes
        assert _arancel(test_db, SERVICIO_ID) is None

    def test_verificacion_post_apply_falla_loudly_si_no_avanza(self, test_db, fake_backup, monkeypatch):
        """A re-plan with work left over must raise, never report success."""
        _base_legado(test_db)

        def _noop(db):
            """A split that silently does nothing: the re-plan must catch it."""
            return None

        monkeypatch.setattr(migracion, "_aplicar", _noop)
        with pytest.raises(migracion.MigracionSplitArancelesError) as exc:
            migracion.apply(test_db, dry_run=False, engine=test_db.get_bind())
        assert "post-aplicación" in str(exc.value)


class TestIdempotencia:
    """Re-running changes nothing — the whole point of a deterministic id."""

    def test_segundo_apply_no_duplica_ni_renombra_de_nuevo(self, test_db, fake_backup):
        _base_legado(test_db)
        migracion.apply(test_db, dry_run=False, engine=test_db.get_bind())
        tras_primero = _ids_arancel(test_db)

        migracion.apply(test_db, dry_run=False, engine=test_db.get_bind())
        plan_2 = migracion.plan(test_db)

        assert _ids_arancel(test_db) == tras_primero
        assert plan_2[-1] == migracion.SIN_CAMBIOS_SI
        assert "renombre omitido" in _texto(plan_2)

    def test_segundo_apply_no_toca_el_monto_configurado(self, test_db, fake_backup):
        """An admin edited the service price: a re-run must not reset it."""
        _base_legado(test_db)
        migracion.apply(test_db, dry_run=False, engine=test_db.get_bind())
        _arancel(test_db, SERVICIO_ID).monto = 7300.0
        test_db.commit()

        migracion.apply(test_db, dry_run=False, engine=test_db.get_bind())

        assert _arancel(test_db, SERVICIO_ID).monto == 7300.0

    def test_un_split_hecho_a_mano_no_genera_una_segunda_fila_de_servicio(self, test_db, fake_backup):
        """Convergence on the TUPLE, not only on the id (admin beat us to it)."""
        _base_legado(test_db)
        test_db.add(
            Arancel(id="a_serv_luz", nombre="Servicio (luz)", area=Area.BALSEROS,
                    predio=Predio.EMBALSE, monto=5000.0,
                    vigenteDesde=date(2026, 1, 1), historico=[],
                    concepto=ConceptoCobro.SERVICIO)
        )
        test_db.commit()

        migracion.apply(test_db, dry_run=False, engine=test_db.get_bind())

        servicios = [
            a for a in test_db.query(Arancel).all()
            if a.concepto is ConceptoCobro.SERVICIO
        ]
        assert [a.id for a in servicios] == ["a_serv_luz"]
        assert _arancel(test_db, ORIGEN).nombre == "Amarre"

    def test_una_base_sembrada_ya_esta_convergida(self, test_db, fake_backup):
        """The seed emits the post-split state, so a fresh DB needs no migration."""
        from backend.seed import seed

        seed(engine=test_db.get_bind())
        test_db.expire_all()

        assert migracion.plan(test_db)[-1] == migracion.SIN_CAMBIOS_SI
        assert _arancel(test_db, ORIGEN).nombre == "Amarre"


class TestInvertir:
    """The rollback, and the guards that keep it from destroying references."""

    def test_vuelve_a_una_sola_fila_con_el_nombre_original(self, test_db, fake_backup):
        _base_legado(test_db)
        migracion.apply(test_db, dry_run=False, engine=test_db.get_bind())
        monto = _arancel(test_db, ORIGEN).monto

        migracion.invertir(test_db, dry_run=False, engine=test_db.get_bind())

        assert _ids_arancel(test_db) == [ORIGEN]
        assert _arancel(test_db, ORIGEN).nombre == "Amarre y Servicios"
        assert _arancel(test_db, ORIGEN).monto == monto  # nunca se toca
        assert _pago_items(test_db) == [
            ("pi1", ORIGEN, MONTO_ORIGEN, "Amarre y Servicios"),
            ("pi2", ORIGEN, MONTO_ORIGEN, "Amarre y Servicios"),
        ]

    def test_segundo_invertir_no_rompe_nada(self, test_db, fake_backup):
        _base_legado(test_db)
        migracion.apply(test_db, dry_run=False, engine=test_db.get_bind())
        migracion.invertir(test_db, dry_run=False, engine=test_db.get_bind())
        tras_primero = _ids_arancel(test_db)

        migracion.invertir(test_db, dry_run=False, engine=test_db.get_bind())

        assert _ids_arancel(test_db) == tras_primero
        assert _arancel(test_db, ORIGEN).nombre == "Amarre y Servicios"

    def test_apply_tras_invertir_vuelve_al_estado_split_sin_duplicar(self, test_db, fake_backup):
        _base_legado(test_db)
        migracion.apply(test_db, dry_run=False, engine=test_db.get_bind())
        migracion.invertir(test_db, dry_run=False, engine=test_db.get_bind())

        migracion.apply(test_db, dry_run=False, engine=test_db.get_bind())

        assert _ids_arancel(test_db) == sorted([ORIGEN, SERVICIO_ID])
        assert _arancel(test_db, ORIGEN).nombre == "Amarre"
        assert _arancel(test_db, SERVICIO_ID).monto == 5000.0
        assert _arancel(test_db, ORIGEN).historico == [
            {"monto": 15000.0, "vigenteDesde": "2025-01-01"}
        ]

    def test_invertir_toma_backup_antes_de_escribir(self, test_db, fake_backup):
        _base_legado(test_db)
        migracion.apply(test_db, dry_run=False, engine=test_db.get_bind())
        migracion.invertir(test_db, dry_run=False, engine=test_db.get_bind())
        llamadas_despues_del_apply = fake_backup.calls

        migracion.invertir(test_db, dry_run=False, engine=test_db.get_bind())

        assert fake_backup.calls == llamadas_despues_del_apply + 1

    def test_se_niega_a_borrar_una_fila_referenciada_por_un_comprobante(self, test_db, fake_backup):
        """Same guard as D5: refuse by name, never break the FK."""
        _base_legado(test_db)
        migracion.apply(test_db, dry_run=False, engine=test_db.get_bind())
        test_db.query(PagoItem).filter(PagoItem.id == "pi1").update(
            {"arancelId": SERVICIO_ID}
        )
        test_db.commit()

        with pytest.raises(migracion.MigracionSplitArancelesError) as exc:
            migracion.invertir(test_db, dry_run=False, engine=test_db.get_bind())

        assert SERVICIO_ID in str(exc.value)
        assert "pi1" in str(exc.value)
        assert "pago_items" in str(exc.value)
        # Refused, not half-done: the row is still there and nothing was renamed.
        assert _arancel(test_db, SERVICIO_ID) is not None
        assert _arancel(test_db, ORIGEN).nombre == "Amarre"

    def test_tambien_nombra_las_membresias_sin_fk(self, test_db, fake_backup):
        """`Membresia.arancelId` has NO FK, so the DB would not protect it."""
        _base_legado(test_db)
        migracion.apply(test_db, dry_run=False, engine=test_db.get_bind())
        test_db.get(Membresia, "m1").arancelId = SERVICIO_ID
        test_db.commit()

        with pytest.raises(migracion.MigracionSplitArancelesError) as exc:
            migracion.invertir(test_db, dry_run=False, engine=test_db.get_bind())

        assert "membresias" in str(exc.value)
        assert "m1" in str(exc.value)
        assert _arancel(test_db, SERVICIO_ID) is not None


class TestResumenOperador:
    """The printed report is the handoff artifact: complete counts, no ambiguity."""

    def test_apply_reporta_el_backup_con_su_sha256(self, test_db, fake_backup, capsys):
        _base_legado(test_db)

        migracion.apply(test_db, dry_run=False, engine=test_db.get_bind())

        salida = capsys.readouterr().out
        assert "backup ....." in salida
        assert hashlib.sha256(fake_backup.path.read_bytes()).hexdigest() in salida
        assert "--invertir" in salida

    def test_la_muestra_se_trunca_pero_el_conteo_no(self, test_db, monkeypatch):
        monkeypatch.setattr(migracion, "EJEMPLOS_MAXIMOS", 1)
        _base_legado(test_db)
        test_db.add(
            PagoItem(id="pi3", pagoId="p1", arancelId=ORIGEN, membresiaId="m1",
                     montoAplicado=1.0, arancelNombre="Amarre y Servicios")
        )
        test_db.commit()

        texto = _texto(migracion.plan(test_db))

        assert "pago_items que siguen apuntando a a1: 3 (pi1" in texto
        assert "... y 2 más" in texto


class TestCli:
    """The CLI is the operator's only entry point, so every flag is exercised.

    These exist because the runtime harness caught a typo a unit test could
    not: ``main()`` called a function name that did not exist, and nothing in
    the suite ever ran ``main()``.
    """

    @pytest.fixture()
    def cli_db(self, test_db, monkeypatch, fake_backup):
        """Bind the module's own SessionLocal to the throwaway test session."""
        monkeypatch.setattr(migracion, "SessionLocal", lambda: test_db)
        return test_db

    def _main(self, argv):
        with pytest.raises(SystemExit) as exc:
            migracion.main(argv)
        return exc.value.code

    @pytest.mark.parametrize(
        "argv",
        [[], ["--plan"], ["--auditar"], ["--apply"], ["--invertir"]],
    )
    def test_todo_flag_sale_con_codigo_0(self, cli_db, argv):
        """Every documented flag resolves a real function and exits 0."""
        _base_legado(cli_db)

        assert self._main(argv) == 0

    def test_sin_flags_es_un_plan_que_no_escribe(self, cli_db, fake_backup, capsys):
        _base_legado(cli_db)

        assert self._main([]) == 0

        assert "sin cambios: no" in capsys.readouterr().out
        assert _arancel(cli_db, ORIGEN).nombre == "Amarre y Servicios"
        assert _arancel(cli_db, SERVICIO_ID) is None
        assert fake_backup.calls == 0

    def test_invertir_por_flag_revierte_el_split(self, cli_db, fake_backup):
        _base_legado(cli_db)
        self._main(["--apply"])

        assert self._main(["--invertir"]) == 0

        assert _ids_arancel(cli_db) == [ORIGEN]
        assert _arancel(cli_db, ORIGEN).nombre == "Amarre y Servicios"

    def test_auditar_solo_imprime(self, cli_db, fake_backup, capsys):
        _base_legado(cli_db)

        assert self._main(["--auditar"]) == 0

        assert "asignaciones inconsistentes: 0" in capsys.readouterr().out
        assert fake_backup.calls == 0
        assert _ids_arancel(cli_db) == [ORIGEN]

    def test_un_origen_imposible_sale_con_codigo_2(self, cli_db, fake_backup, capsys):
        """The operator error path: exit 2 + a named reason, never a traceback."""
        _base_legado(cli_db)
        _arancel(cli_db, ORIGEN).concepto = ConceptoCobro.RECARGO
        cli_db.commit()

        assert self._main(["--plan"]) == 2

        assert "no como area" in capsys.readouterr().err
