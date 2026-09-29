"""Tests for the catalog data migration (carrier recargo, servicio cabañeros, predio guardería).

What these lock down, in the order that matters for money data:

* the plan is COMPLETE and READ-ONLY — a dry run writes nothing;
* the RECARGO carrier lands with ``monto = 0`` and the placeholder place, which
  is the whole point of a carrier (the operator types the amount per charge);
* the CABANEROS service row is BLOCKED without a configured amount and is NEVER
  invented from the seed's demo figure;
* the Guardería correction moves ``predio`` ONLY: ``monto``, ``area`` and
  ``historico`` are provably untouched;
* a second run is a no-op (idempotency), and a wrong row is refused, not edited;
* NOTHING in socios/membresias/pagos/pago_items/notificaciones moves.
"""

import hashlib
import sqlite3
from datetime import date

import pytest

from backend.models.arancel import Arancel
from backend.models.enums import (
    Area,
    ConceptoCobro,
    EstadoMembresia,
    Predio,
    TipoParcela,
)
from backend.models.pago import Pago
from backend.services import migracion_catalogo_recargo_cabaneros as migracion


@pytest.fixture(autouse=True)
def fake_backup(monkeypatch, tmp_path):
    """Stand in for ``services/backup.py`` with a REAL SQLite dump.

    The fixture DB is ``:memory:``, and ``create_backup``'s SQLite fast path
    copies a FILE — it cannot dump an in-memory database. This does not fake
    the file either: it copies the live in-memory database through sqlite3's
    backup API at the moment ``create_backup`` is called, so the apply path is
    still proven to take a genuine pre-write snapshot. Autouse, because EVERY
    apply in this module is supposed to back up first.
    """
    class FakeBackup:
        path = tmp_path / "canyp-backup.db"
        calls = 0

    fake = FakeBackup()

    def _create_backup(source_engine):
        fake.calls += 1
        destino = sqlite3.connect(str(fake.path))
        # raw_connection() checks a connection out of the StaticPool; it MUST
        # be returned to the pool (close(), not the driver's close) or the
        # in-memory database is destroyed for the rest of the test.
        cruda = source_engine.raw_connection()
        try:
            cruda.driver_connection.backup(destino)
        finally:
            cruda.close()
            destino.close()
        return {"tables": 0, "rows": {}, "path": str(fake.path)}

    monkeypatch.setattr(migracion.backup_service, "create_backup", _create_backup)
    return fake


def _arancel(db, **kwargs):
    base = dict(
        nombre="X",
        area=Area.BALSEROS,
        predio=Predio.EMBALSE,
        monto=1000.0,
        categoria=None,
        vigenteDesde=date(2026, 1, 1),
        historico=[],
        concepto=ConceptoCobro.AREA,
    )
    base.update(kwargs)
    fila = Arancel(**base)
    db.add(fila)
    db.commit()
    return fila


def _guarderia(db, **kwargs):
    """La fila que el dueño describió: area Guardería, predio Embalse, 20000."""
    return _arancel(
        db,
        id=kwargs.pop("id", "a_guard"),
        nombre="Cuota Guardería",
        area=Area.GUARDERIA,
        predio=kwargs.pop("predio", Predio.EMBALSE),
        monto=kwargs.pop("monto", 20000.0),
        concepto=ConceptoCobro.AREA,
        **kwargs,
    )


class TestPlanEsReadOnly:
    def test_dry_run_no_escribe_nada(self, test_db):
        _guarderia(test_db)
        antes = migracion.snapshot(test_db)
        migracion.aplicar(test_db, dry_run=True)
        assert migracion.snapshot(test_db) == antes

    def test_plan_es_completo_y_dice_que_no_toca(self, test_db):
        _guarderia(test_db)
        plan = migracion.plan(test_db)
        assert len(plan.cambios) == 3
        texto = plan.resumen()
        assert "NO toca" in texto
        assert "socios" in texto and "pagos" in texto


class TestCarrierRecargo:
    def test_se_inserta_con_monto_cero(self, test_db):
        migracion.aplicar(test_db, dry_run=False, engine=None)
        carrier = migracion._carrier_recargo(test_db)
        assert carrier is not None
        assert carrier.concepto is ConceptoCobro.RECARGO
        assert float(carrier.monto) == 0.0
        assert carrier.categoria is None
        assert carrier.area is migracion.LUGAR_NEUTRAL_AREA
        assert carrier.predio is migracion.LUGAR_NEUTRAL_PREDIO

    def test_el_gate_del_cobro_lo_encuentra_por_concepto(self, test_db):
        """El carrier se resuelve por `concepto`, nunca por area+predio."""
        from backend.services.resolucion import resolver_arancel_concepto

        migracion.aplicar(test_db, dry_run=False)
        assert resolver_arancel_concepto(test_db, ConceptoCobro.RECARGO) is not None

    def test_un_carrier_con_importe_no_se_reescribe(self, test_db):
        """Una fila recargo con monto > 0 no es un carrier: se reporta, no se toca."""
        _arancel(db=test_db, id="a_r", nombre="Recargo", concepto=ConceptoCobro.RECARGO, monto=500.0)
        migracion.aplicar(test_db, dry_run=False)
        assert float(test_db.get(Arancel, "a_r").monto) == 500.0
        assert test_db.query(Arancel).filter(Arancel.concepto == ConceptoCobro.RECARGO).count() == 1

    def test_un_carrier_creado_a_mano_hace_converger(self, test_db):
        """Si el admin ya lo creó, la migración no agrega un segundo carrier."""
        _arancel(db=test_db, id="a_manual", nombre="Recargo", concepto=ConceptoCobro.RECARGO, monto=0.0)
        migracion.aplicar(test_db, dry_run=False)
        assert test_db.query(Arancel).filter(Arancel.concepto == ConceptoCobro.RECARGO).count() == 1
        assert test_db.get(Arancel, migracion.RECARGO_CARRIER_ID) is None


class TestServicioCabaneros:
    def test_sin_monto_queda_bloqueado(self, test_db):
        plan = migracion.plan(test_db, monto_cabaneros=None)
        bloqueado = next(c for c in plan.cambios if "cabañeros" in c.linea.lower())
        assert bloqueado.bloqueado is not None
        assert "no hay importe de referencia" in bloqueado.bloqueado

    def test_bloqueado_no_inserta_nada(self, test_db):
        migracion.aplicar(test_db, dry_run=False, monto_cabaneros=None)
        assert test_db.query(Arancel).filter(Arancel.area == Area.CABANEROS).count() == 0

    def test_nunca_hereda_el_monto_demo_del_seed(self, test_db):
        """Regresión del riesgo real: 4000.0 (seed) no es el precio de nadie."""
        migracion.aplicar(test_db, dry_run=False, monto_cabaneros=None)
        fila = migracion._servicio_cabaneros(test_db)
        assert fila is None

    def test_con_monto_configurado_se_inserta(self, test_db):
        migracion.aplicar(test_db, dry_run=False, monto_cabaneros=4200.0)
        fila = migracion._servicio_cabaneros(test_db)
        assert fila is not None
        assert float(fila.monto) == 4200.0
        assert fila.concepto is ConceptoCobro.SERVICIO
        assert fila.area is Area.CABANEROS
        assert fila.predio is Predio.ALMAFUERTE
        assert fila.categoria is None

    def test_reescribe_el_precio_de_una_fila_existente(self, test_db):
        """`--monto-cabaneros` es la vía de decisión del dueño, en ambos sentidos.

        Antes este caso se reportaba y no se escribía. Parkear un importe de
        ejemplo en 15000 era justamente el riesgo: si alguien cobraba antes de
        editarlo, se cobraba 15000. Bajar a 0 tiene que ser posible desde acá.
        """
        _arancel(db=test_db, id="a_serv_cabaneros", nombre="Servicio",
                 area=Area.CABANEROS, predio=Predio.ALMAFUERTE,
                 monto=777.0, concepto=ConceptoCobro.SERVICIO)
        migracion.aplicar(test_db, dry_run=False, monto_cabaneros=4200.0)
        assert float(test_db.get(Arancel, "a_serv_cabaneros").monto) == 4200.0

    def test_baja_el_importe_a_cero_para_aparcar_el_placeholder(self, test_db):
        """El caso del dueño: 15000 es demasiado riesgoso hasta que defina el precio."""
        fila = _arancel(db=test_db, id="a_serv_cabaneros", nombre="Servicio",
                        area=Area.CABANEROS, predio=Predio.ALMAFUERTE,
                        monto=15000.0, concepto=ConceptoCobro.SERVICIO)
        migracion.aplicar(test_db, dry_run=False, monto_cabaneros=0.0)
        test_db.refresh(fila)
        assert float(fila.monto) == 0.0
        # Solo el importe se mueve: el resto de la fila es la que resuelve.
        assert fila.area is Area.CABANEROS
        assert fila.predio is Predio.ALMAFUERTE
        assert fila.concepto is ConceptoCobro.SERVICIO
        assert fila.categoria is None

    def test_el_importe_anterior_queda_en_el_historico(self, test_db):
        """Misma regla que la app: bajar un precio no borra el anterior.

        Escribir `monto` a pelo perdería los 15000 del historial en silencio.
        """
        fila = _arancel(db=test_db, id="a_serv_cabaneros", nombre="Servicio",
                        area=Area.CABANEROS, predio=Predio.ALMAFUERTE,
                        monto=15000.0, concepto=ConceptoCobro.SERVICIO)
        vigente_antes = fila.vigenteDesde
        migracion.aplicar(test_db, dry_run=False, monto_cabaneros=0.0)
        test_db.refresh(fila)
        assert float(fila.monto) == 0.0
        assert len(fila.historico) == 1
        assert float(fila.historico[0]["monto"]) == 15000.0
        assert fila.historico[0]["vigenteDesde"] == str(vigente_antes)
        assert fila.vigenteDesde == date.today()

    def test_es_idempotente_al_bajar_a_cero(self, test_db):
        """Correrlo dos veces no vuelve a tocar la fila ni duplica el historico."""
        _arancel(db=test_db, id="a_serv_cabaneros", nombre="Servicio",
                 area=Area.CABANEROS, predio=Predio.ALMAFUERTE,
                 monto=15000.0, concepto=ConceptoCobro.SERVICIO)
        migracion.aplicar(test_db, dry_run=False, monto_cabaneros=0.0)
        segundo = migracion.aplicar(test_db, dry_run=False, monto_cabaneros=0.0)
        assert segundo.sin_cambios
        fila = test_db.get(Arancel, "a_serv_cabaneros")
        assert float(fila.monto) == 0.0
        assert len(fila.historico) == 1  # no un 15000 duplicado

    def test_sin_flag_no_mueve_un_importe_existente(self, test_db):
        """Sin `--monto-cabaneros` no hay decisión del dueño: no se toca nada."""
        _arancel(db=test_db, id="a_serv_cabaneros", nombre="Servicio",
                 area=Area.CABANEROS, predio=Predio.ALMAFUERTE,
                 monto=15000.0, concepto=ConceptoCobro.SERVICIO)
        migracion.aplicar(test_db, dry_run=False, monto_cabaneros=None)
        assert float(test_db.get(Arancel, "a_serv_cabaneros").monto) == 15000.0

    def test_el_plan_admite_que_mueve_el_importe(self, test_db):
        """El reporte no puede decir 'NO toca: montos' mientras mueve uno."""
        _arancel(db=test_db, id="a_serv_cabaneros", nombre="Servicio",
                 area=Area.CABANEROS, predio=Predio.ALMAFUERTE,
                 monto=15000.0, concepto=ConceptoCobro.SERVICIO)
        texto = migracion.plan(test_db, monto_cabaneros=0.0).resumen()
        assert "NO toca: montos" not in texto
        assert "importe" in texto.lower()

    def test_una_linea_de_servicio_en_cero_sigue_resolviendose(self, test_db):
        """El riesgo real de dejar el importe en 0: que la línea desaparezca.

        El resolver busca por concepto y lugar, nunca por importe, así que una
        fila en 0 se sigue ofreciendo. Lo que se rechaza es COBRAR sin
        `montoAplicado`, y eso lo hace el cobro, no el catálogo.
        """
        from backend.services.resolucion import resolver_arancel_concepto

        _arancel(db=test_db, id="a_serv_cabaneros", nombre="Servicio",
                 area=Area.CABANEROS, predio=Predio.ALMAFUERTE,
                 monto=15000.0, concepto=ConceptoCobro.SERVICIO)
        migracion.aplicar(test_db, dry_run=False, monto_cabaneros=0.0)

        fila = resolver_arancel_concepto(test_db, ConceptoCobro.SERVICIO)
        assert fila is not None, "una línea en 0 no puede desaparecer del cobro"
        assert fila.id == "a_serv_cabaneros"
        assert float(fila.monto) == 0.0


class TestPredioGuarderia:
    def test_mueve_solo_el_predio(self, test_db):
        fila = _guarderia(test_db)
        migracion.aplicar(test_db, dry_run=False)
        test_db.refresh(fila)
        assert fila.predio is Predio.ALMAFUERTE
        assert float(fila.monto) == 20000.0
        assert fila.area is Area.GUARDERIA
        assert fila.historico == []

    def test_no_toca_montos_de_otras_filas(self, test_db):
        otra = _arancel(db=test_db, id="a_w", area=Area.WINDSURF, predio=Predio.ALMAFUERTE, monto=10000.0)
        _guarderia(test_db)
        migracion.aplicar(test_db, dry_run=False)
        assert float(test_db.get(Arancel, "a_w").monto) == 10000.0

    def test_una_fila_que_no_es_la_del_dueno_no_se_toca(self, test_db):
        """El monto esperado es la guarda: si no coincide, no es nuestra fila."""
        fila = _guarderia(test_db, monto=12345.0)
        with pytest.raises(migracion.MigracionCatalogoError):
            migracion.aplicar(test_db, dry_run=False)
        test_db.rollback()
        test_db.refresh(fila)
        assert fila.predio is Predio.EMBALSE
        assert float(fila.monto) == 12345.0

    def test_ya_corregida_no_hace_nada(self, test_db):
        _guarderia(test_db, predio=Predio.ALMAFUERTE)
        # The carrier is still missing, so the plan is NOT empty; what matters
        # is that the Guardería correction itself is a no-op.
        linea = next(c for c in migracion.plan(test_db).cambios if "guardería" in c.linea)
        assert linea.linea.startswith("=")
        assert not linea.escribe


class TestIdempotencia:
    def test_correr_dos_veces_no_crea_nada_nuevo(self, test_db):
        _guarderia(test_db)
        migracion.aplicar(test_db, dry_run=False, monto_cabaneros=4200.0)
        despues = migracion.snapshot(test_db)
        segunda = migracion.aplicar(test_db, dry_run=False, monto_cabaneros=4200.0)
        assert migracion.snapshot(test_db) == despues
        assert segunda.sin_cambios

    def test_la_segunda_pasada_no_toma_backup(self, test_db, fake_backup):
        _guarderia(test_db)
        migracion.aplicar(test_db, dry_run=False)
        segunda = migracion.aplicar(test_db, dry_run=False)
        assert segunda.sin_cambios
        assert fake_backup.calls == 1  # solo la primera pasada

    def test_apply_toma_backup_antes_de_escribir(self, test_db, fake_backup):
        _guarderia(test_db)
        plan = migracion.aplicar(test_db, dry_run=False)
        assert fake_backup.calls == 1
        assert plan.ruta_backup == str(fake_backup.path)
        assert plan.sha256_backup == hashlib.sha256(fake_backup.path.read_bytes()).hexdigest()

    def test_el_backup_contiene_el_estado_pre_migracion(self, test_db, fake_backup):
        """La evidencia del handoff tiene que probar el estado ANTERIOR."""
        _guarderia(test_db)
        migracion.aplicar(test_db, dry_run=False)
        copia = sqlite3.connect(str(fake_backup.path))
        try:
            filas = copia.execute('SELECT id, predio FROM "aranceles"').fetchall()
        finally:
            copia.close()
        # SQLite stores the Enum by NAME, so the dump reads EMBALSE, not Embalse.
        assert ("a_guard", "EMBALSE") in filas
        assert not any(f[0] == migracion.RECARGO_CARRIER_ID for f in filas)


class TestIntegridad:
    def test_no_toca_nada_fuera_del_catalogo(self, test_db):
        from backend.models.membresia import Membresia
        from backend.models.parcela import Parcela
        from backend.models.socio import Socio

        _guarderia(test_db)
        test_db.add(Socio(id="s1", nombre="Socio", dni="30111222", fechaAlta=date(2026, 1, 1)))
        test_db.add(
            Parcela(id="pa1", nombre="Balsa", tipo=TipoParcela.BALSA, predio=Predio.EMBALSE)
        )
        test_db.commit()
        # Committed apart, like the other migration suites do: the membersía
        # carries two FKs and this fixture does not need the flush ordering.
        test_db.add(
            Membresia(
                id="m1",
                socioId="s1",
                area=Area.BALSEROS,
                predio=Predio.EMBALSE,
                estado=EstadoMembresia.ACTIVA,
                vencimiento=date(2026, 10, 10),
                parcelaId="pa1",
            )
        )
        test_db.commit()

        antes = migracion.snapshot(test_db)["intactas"]
        migracion.aplicar(test_db, dry_run=False, monto_cabaneros=4200.0)
        assert migracion.snapshot(test_db)["intactas"] == antes

    def test_el_snapshot_cubre_las_tablas_de_la_carga(self, test_db):
        claves = migracion.snapshot(test_db)["intactas"]
        assert set(claves) == {"socios", "membresias", "pagos", "pago_items", "notificaciones"}
        assert all(isinstance(v, int) for v in claves.values())
        assert test_db.query(Pago).count() == 0


class TestNoEsMigracionDeEsquema:
    def test_no_toca_el_esquema(self, test_db):
        """Es DATOS: ninguna tabla/columna nueva debe aparecer."""
        from sqlalchemy import inspect

        antes = set(inspect(test_db.get_bind()).get_table_names())
        migracion.aplicar(test_db, dry_run=False, monto_cabaneros=4200.0)
        assert set(inspect(test_db.get_bind()).get_table_names()) == antes
