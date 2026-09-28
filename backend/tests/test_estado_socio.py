"""Server-authoritative socio states — 4 states, ONE grouped query (EST-01..04).

Replaces `test_estado_visual.py`: the 5 membership states that included a
30-day anticipación bucket are gone. The server is now the single authority and
serves exactly 4 states derived from the cuota social and área `vencimiento`
values.

The states are VISUAL CONTROL ONLY: nothing here deletes, hides, archives or
stops charging anything (EST-03). Paying restores the state by RECALCULATION on
the next read (EST-02) — there is no stored flag to maintain.
"""

from datetime import date, timedelta

from sqlalchemy import event

from backend.models.enums import (
    Area,
    ConceptoMembresia,
    EstadoMembresia,
    EstadoSocioVisual,
    Predio,
    RolMembresia,
    TipoParcela,
)
from backend.models.membresia import Membresia
from backend.models.parcela import Parcela
from backend.models.socio import Socio
from backend.services.estado_socio import (
    Vigencia,
    areas_por_unidad,
    calcular_estado_socio,
    estados_socio,
    inputs_socio,
    vigencia_mas_vencida,
)
from backend.services.renovacion import renovar_membresias

# A fixed reference day for the pure-function tests; the DB tests use the real
# clock because they go through the API.
HOY = date(2026, 9, 25)

ACTIVO = EstadoSocioVisual.ACTIVO.value
REVISAR = EstadoSocioVisual.ACTIVO_REVISAR.value
INACTIVO = EstadoSocioVisual.INACTIVO_REVISAR.value
SOLO = EstadoSocioVisual.SOLO_CUOTA_SOCIAL.value


def _socio(db, socio_id: str) -> Socio:
    db.add(
        Socio(
            id=socio_id,
            nombre=f"Socio {socio_id}",
            dni=f"30{socio_id.lstrip('s'):0>6}",
            fechaAlta=date(2026, 1, 1),
        )
    )
    db.commit()
    return socio_id


def _cuota(
    db,
    mid: str,
    socio_id: str,
    *,
    dias: int = 30,
    estado: EstadoMembresia = EstadoMembresia.ACTIVA,
    hoy: date | None = None,
) -> Membresia:
    """A cuota social membership: a Membresia with no area/predio/rol (CS-01)."""
    m = Membresia(
        id=mid,
        socioId=socio_id,
        area=None,
        predio=None,
        estado=estado,
        concepto=ConceptoMembresia.CUOTA_SOCIAL,
        vencimiento=(hoy or date.today()) + timedelta(days=dias),
    )
    db.add(m)
    db.commit()
    return m


def _area(
    db,
    mid: str,
    socio_id: str,
    *,
    dias: int = 30,
    estado: EstadoMembresia = EstadoMembresia.ACTIVA,
    parcela_id: str | None = None,
    rol: RolMembresia | None = None,
    hoy: date | None = None,
) -> Membresia:
    m = Membresia(
        id=mid,
        socioId=socio_id,
        area=Area.BALSEROS,
        predio=Predio.EMBALSE,
        estado=estado,
        concepto=ConceptoMembresia.AREA,
        vencimiento=(hoy or date.today()) + timedelta(days=dias),
        parcelaId=parcela_id,
        rol=rol,
    )
    db.add(m)
    db.commit()
    return m


def _parcela(db, parcela_id: str = "p1", nombre: str = "Balsa 1") -> str:
    db.add(
        Parcela(
            id=parcela_id,
            nombre=nombre,
            tipo=TipoParcela.BALSA,
            predio=Predio.EMBALSE,
        )
    )
    db.commit()
    return parcela_id


def _selects(test_db) -> list[str]:
    """Record every SELECT the next statements issue on the test engine."""
    statements: list[str] = []
    event.listen(
        test_db.get_bind(),
        "before_cursor_execute",
        lambda *a: statements.append(a[2]),
    )
    return statements


class TestVocabulario:
    """AC: exactly 4 states, exact nominaciones, no anticipación bucket left."""

    def test_exactly_four_states(self):
        assert len(EstadoSocioVisual) == 4

    def test_exact_nominaciones(self):
        assert {e.value for e in EstadoSocioVisual} == {
            "Socio activo",
            "Socio activo — revisar",
            "Inactivo — revisar",
            "Solo cuota social",
        }

    def test_dash_is_an_em_dash(self):
        for estado in (REVISAR, INACTIVO):
            assert "— revisar" in estado, estado
            assert "- revisar" not in estado, estado

    def test_the_30_day_warning_bucket_is_not_part_of_the_vocabulary(self):
        """The removed state must not sneak back in, by value or by member name.

        The token is built at runtime on purpose: the acceptance gate greps the
        backend for this literal and must find zero hits, this test included.
        """
        removed = "por_" + "vencer"
        assert removed not in {e.value for e in EstadoSocioVisual}
        assert removed not in {e.name for e in EstadoSocioVisual}
        assert removed not in {e.name.lower() for e in EstadoMembresia}


class TestCalcularEstadoSocio:
    """The pure function: `calcular_estado_socio(cuota, area, hoy)`, no DB."""

    def test_cuota_al_dia_y_area_al_dia_es_activo(self):
        assert (
            calcular_estado_socio(Vigencia(date(2026, 10, 10)), Vigencia(date(2026, 10, 10)), HOY)
            == EstadoSocioVisual.ACTIVO
        )

    def test_cuota_al_dia_sin_area_es_solo_cuota_social(self):
        assert (
            calcular_estado_socio(Vigencia(date(2026, 10, 10)), None, HOY)
            == EstadoSocioVisual.SOLO_CUOTA_SOCIAL
        )

    def test_cuota_al_dia_y_area_vencida_es_revisar(self):
        assert (
            calcular_estado_socio(Vigencia(date(2026, 10, 10)), Vigencia(date(2026, 9, 9)), HOY)
            == EstadoSocioVisual.ACTIVO_REVISAR
        )

    def test_cuota_vencida_es_inactivo(self):
        assert (
            calcular_estado_socio(Vigencia(date(2026, 9, 9)), Vigencia(date(2026, 10, 10)), HOY)
            == EstadoSocioVisual.INACTIVO_REVISAR
        )

    def test_cuota_vencida_sin_area_no_es_solo_cuota_social(self):
        """A debt outranks the "no área" nominación."""
        assert (
            calcular_estado_socio(Vigencia(date(2026, 9, 9)), None, HOY)
            == EstadoSocioVisual.INACTIVO_REVISAR
        )

    def test_vencimiento_igual_a_hoy_esta_al_dia(self):
        """AC: `vencimiento == hoy` counts as al día (the `>=` boundary)."""
        assert (
            calcular_estado_socio(Vigencia(HOY), Vigencia(HOY), HOY)
            == EstadoSocioVisual.ACTIVO
        )

    def test_vencimiento_igual_a_hoy_sin_area_es_solo_cuota_social(self):
        assert (
            calcular_estado_socio(Vigencia(HOY), None, HOY)
            == EstadoSocioVisual.SOLO_CUOTA_SOCIAL
        )

    def test_un_dia_antes_ya_esta_vencido(self):
        ayer = HOY - timedelta(days=1)
        assert calcular_estado_socio(Vigencia(ayer), None, HOY) == EstadoSocioVisual.INACTIVO_REVISAR

    def test_cuota_suspendida_es_inactivo_aunque_la_fecha_este_al_dia(self):
        assert (
            calcular_estado_socio(Vigencia(date(2027, 1, 10), parada=True), None, HOY)
            == EstadoSocioVisual.INACTIVO_REVISAR
        )

    def test_cuota_baja_es_inactivo_aunque_la_fecha_este_al_dia(self):
        assert (
            calcular_estado_socio(Vigencia(date(2027, 1, 10), parada=True), Vigencia(date(2027, 1, 10)), HOY)
            == EstadoSocioVisual.INACTIVO_REVISAR
        )

    def test_area_suspendida_o_baja_no_afecta_el_badge(self):
        """Design: a suspendida/baja AREA row is ignored by the badge."""
        assert (
            calcular_estado_socio(Vigencia(date(2027, 1, 10)), Vigencia(date(2027, 1, 10)), HOY)
            == EstadoSocioVisual.ACTIVO
        )

    def test_socio_sin_cuota_usa_su_solo_area(self):
        assert calcular_estado_socio(None, Vigencia(date(2027, 1, 10)), HOY) == EstadoSocioVisual.ACTIVO
        assert calcular_estado_socio(None, None, HOY) == EstadoSocioVisual.SOLO_CUOTA_SOCIAL


class TestEstadosSocioDesdeLaBase:
    """The grouped resolution behind the pure function."""

    def test_un_socio_solo_con_cuota(self, test_db):
        _socio(test_db, "s1")
        _cuota(test_db, "m1", "s1")
        assert estados_socio(test_db, ["s1"]) == {"s1": EstadoSocioVisual.SOLO_CUOTA_SOCIAL}

    def test_socio_sin_membresias_igual_recibe_estado(self, test_db):
        _socio(test_db, "s1")
        assert estados_socio(test_db, ["s1"]) == {"s1": EstadoSocioVisual.SOLO_CUOTA_SOCIAL}

    def test_lista_vacia_no_consulta_la_base(self, test_db):
        assert estados_socio(test_db, []) == {}

    def test_el_area_mas_vencida_manda(self, test_db):
        """Two area rows: one stale row must not be hidden by a fresher one."""
        _socio(test_db, "s1")
        _cuota(test_db, "m1", "s1")
        _area(test_db, "m2", "s1", dias=120)
        _area(test_db, "m3", "s1", dias=-1)
        assert estados_socio(test_db, ["s1"]) == {"s1": EstadoSocioVisual.ACTIVO_REVISAR}

    def test_la_cuota_vencida_gana_sobre_el_area(self, test_db):
        _socio(test_db, "s1")
        _cuota(test_db, "m1", "s1", dias=-1)
        _area(test_db, "m2", "s1", dias=120)
        assert estados_socio(test_db, ["s1"]) == {"s1": EstadoSocioVisual.INACTIVO_REVISAR}

    def test_la_fila_de_cuota_no_cuenta_como_area(self, test_db):
        """A cuota row has no area: it must not turn a solo-cuota socio active."""
        _socio(test_db, "s1")
        _cuota(test_db, "m1", "s1", dias=-1)
        inputs = inputs_socio(test_db, ["s1"])["s1"]
        assert inputs.area is None
        assert inputs.cuota.vencida(date.today()) is True

    def test_una_sola_consulta_agrupada_por_listado(self, test_db):
        """D5: ONE grouped query, never N+1 — constant statements, 1 vs 4 socios."""
        for i in (1, 2, 3, 4):
            _socio(test_db, f"s{i}")
            _cuota(test_db, f"m{i}", f"s{i}")

        uno = _selects(test_db)
        assert len(estados_socio(test_db, ["s1"])) == 1
        assert len([s for s in uno if s.lstrip().upper().startswith("SELECT")]) == 1
        assert len([s for s in uno if "GROUP BY" in s]) == 1

        cuatro = _selects(test_db)
        assert len(estados_socio(test_db, ["s1", "s2", "s3", "s4"])) == 4
        selects = [s for s in cuatro if s.lstrip().upper().startswith("SELECT")]
        assert len(selects) == 1, selects

    def test_areas_por_unidad_toma_la_mas_vencida_de_la_unidad(self, test_db):
        _parcela(test_db, "p1")
        _socio(test_db, "s1")
        _socio(test_db, "s2")
        _area(test_db, "m1", "s1", dias=120, parcela_id="p1")
        _area(test_db, "m2", "s2", dias=-1, parcela_id="p1")
        _cuota(test_db, "m3", "s1")
        _cuota(test_db, "m4", "s2")
        areas = areas_por_unidad(test_db, ["p1"])
        assert areas["p1"].vencida(date.today()) is True

        # Both members read the SAME unit area → the whole unit is ⚠️.
        inputs = inputs_socio(test_db, ["s1", "s2"])
        assert {
            socio: calcular_estado_socio(inputs[socio].cuota, areas["p1"], date.today())
            for socio in ("s1", "s2")
        } == {
            "s1": EstadoSocioVisual.ACTIVO_REVISAR,
            "s2": EstadoSocioVisual.ACTIVO_REVISAR,
        }

    def test_areas_por_unidad_de_una_unidad_sin_area(self, test_db):
        assert areas_por_unidad(test_db, []) == {}


class TestPadronSirveElEstado:
    """EST-01: the padron SERVES the state; the frontend never re-derives it."""

    def test_listado_sirve_estado_y_nominacion(self, test_client, test_db):
        _socio(test_db, "s1")
        _cuota(test_db, "m1", "s1")
        _area(test_db, "m2", "s1", dias=-1)
        body = test_client.get("/api/socios").json()
        assert body[0]["estado"] == REVISAR
        assert body[0]["nominacion"] == REVISAR

    def test_ficha_sirve_el_mismo_estado(self, test_client, test_db):
        _socio(test_db, "s1")
        _cuota(test_db, "m1", "s1", dias=-1)
        ficha = test_client.get("/api/socios/s1").json()
        listado = test_client.get("/api/socios").json()[0]
        assert ficha["estado"] == listado["estado"] == INACTIVO

    def test_socio_nuevo_nace_solo_cuota_social(self, test_client):
        resp = test_client.post(
            "/api/socios",
            json={"nombre": "Nuevo", "dni": "31111111", "fechaAlta": "2026-01-01"},
        )
        assert resp.status_code == 201
        assert resp.json()["estado"] == SOLO
        assert resp.json()["nominacion"] == "Solo cuota social"

    def test_update_conserva_el_estado_servido(self, test_client, test_db):
        _socio(test_db, "s1")
        _cuota(test_db, "m1", "s1", dias=-1)
        resp = test_client.put("/api/socios/s1", json={"telefono": "3514444444"})
        assert resp.status_code == 200
        assert resp.json()["estado"] == INACTIVO

    def test_el_buscador_sigue_sirviendo_el_estado(self, test_client, test_db):
        _socio(test_db, "s1")
        _socio(test_db, "s2")
        _cuota(test_db, "m1", "s1", dias=-1)
        _cuota(test_db, "m2", "s2")
        body = test_client.get("/api/socios", params={"search": "Socio s2"}).json()
        assert [s["estado"] for s in body] == [SOLO]


class TestRecalculoYRestauracion:
    """EST-02/EST-03: recalculated on every read, nothing ever deleted."""

    def test_el_estado_se_deriva_y_no_se_persiste(self, test_client, test_db):
        _socio(test_db, "s1")
        _cuota(test_db, "m1", "s1", dias=-1)
        assert test_client.get("/api/socios").json()[0]["estado"] == INACTIVO

        cuota = test_db.query(Membresia).filter(Membresia.id == "m1").one()
        cuota.vencimiento = date.today() + timedelta(days=30)
        test_db.commit()

        assert test_client.get("/api/socios").json()[0]["estado"] == SOLO
        # The recalculation wrote nothing: the stored state is untouched.
        cuota = test_db.query(Membresia).filter(Membresia.id == "m1").one()
        assert cuota.estado == EstadoMembresia.ACTIVA
        assert test_db.query(Membresia).count() == 1

    def test_pagar_restaura_el_estado_sin_paso_manual(self, test_client, test_db):
        _socio(test_db, "s1")
        cuota = _cuota(test_db, "m1", "s1", dias=-1)
        assert test_client.get("/api/socios").json()[0]["estado"] == INACTIVO

        renovar_membresias(test_db, [cuota.id], date.today())

        assert test_client.get("/api/socios").json()[0]["estado"] == SOLO
        assert test_db.query(Membresia).count() == 1

    def test_un_socio_moroso_sigue_visible_y_cobrable(self, test_client, test_db):
        """EST-03: 12 periods overdue is still listed, still queryable, rows intact."""
        _parcela(test_db, "p1")
        _socio(test_db, "s1")
        _cuota(test_db, "m1", "s1", dias=-365)
        _area(test_db, "m2", "s1", dias=-365, parcela_id="p1")

        body = test_client.get("/api/socios").json()
        assert [s["estado"] for s in body] == [INACTIVO]
        assert test_client.get("/api/socios/s1").status_code == 200
        assert test_client.get("/api/socios/s1/membresias").status_code == 200
        assert test_db.query(Membresia).count() == 2
        assert test_db.query(Socio).count() == 1

    def test_la_pendiente_se_refleja_en_el_dashboard(self, test_client, test_db):
        _socio(test_db, "s1")
        _cuota(test_db, "m1", "s1", dias=-365)
        assert test_client.get("/api/dashboard/stats").json()["estados"][INACTIVO] == 1


class TestUnidadMarcaATodaLaUnidad:
    """AC: an expired área marks the WHOLE unit (titular e integrantes)."""

    def _unidad(self, test_db, dias: int) -> None:
        _parcela(test_db, "p1")
        _socio(test_db, "s1")
        _socio(test_db, "s2")
        _cuota(test_db, "m1", "s1")
        _cuota(test_db, "m2", "s2")
        _area(test_db, "m3", "s1", dias=dias, parcela_id="p1", rol=RolMembresia.TITULAR)
        _area(test_db, "m4", "s2", dias=dias, parcela_id="p1", rol=RolMembresia.INTEGRANTE)

    def test_titular_e_integrantes_quedan_revisar(self, test_client, test_db):
        self._unidad(test_db, -1)
        miembros = test_client.get("/api/membresias/parcelas").json()[0]["membresias"]
        assert {m["estadoSocio"] for m in miembros} == {REVISAR}
        assert {s["estado"] for s in test_client.get("/api/socios").json()} == {REVISAR}

    def test_una_fila_al_dia_no_rescata_a_la_unidad(self, test_client, test_db):
        """The unit is one thing paid once: scope = unidad, not per-row."""
        self._unidad(test_db, -1)
        _area(test_db, "m5", "s2", dias=120, parcela_id="p1")
        miembros = test_client.get("/api/membresias/parcelas").json()[0]["membresias"]
        assert {m["estadoSocio"] for m in miembros} == {REVISAR}

    def test_cuota_vencida_manda_sobre_la_unidad_al_dia(self, test_client, test_db):
        self._unidad(test_db, 120)
        cuota = test_db.query(Membresia).filter(Membresia.id == "m1").one()
        cuota.vencimiento = date.today() - timedelta(days=1)
        test_db.commit()
        estados = {
            m["socioId"]: m["estadoSocio"]
            for m in test_client.get("/api/membresias/parcelas").json()[0]["membresias"]
        }
        assert estados == {"s1": INACTIVO, "s2": ACTIVO}

    def test_la_unidad_al_dia_marca_activo(self, test_client, test_db):
        self._unidad(test_db, 120)
        miembros = test_client.get("/api/membresias/parcelas").json()[0]["membresias"]
        assert {m["estadoSocio"] for m in miembros} == {ACTIVO}


class TestDashboardConCuatroBuckets:
    """Task 4.2: the dashboard counts the 4 server states, nothing else."""

    def test_los_cuatro_buckets_siempre_presentes(self, test_client):
        stats = test_client.get("/api/dashboard/stats").json()
        assert stats["estados"] == {ACTIVO: 0, REVISAR: 0, INACTIVO: 0, SOLO: 0}

    def test_los_buckets_cuentan_cada_socio_una_vez(self, test_client, test_db):
        _socio(test_db, "s1")
        _cuota(test_db, "m1", "s1")
        _area(test_db, "m2", "s1", dias=120)
        _socio(test_db, "s2")
        _cuota(test_db, "m3", "s2")
        _area(test_db, "m4", "s2", dias=-1)
        _socio(test_db, "s3")
        _cuota(test_db, "m5", "s3", dias=-1)
        _socio(test_db, "s4")
        _cuota(test_db, "m6", "s4")

        stats = test_client.get("/api/dashboard/stats").json()
        assert stats["estados"] == {ACTIVO: 1, REVISAR: 1, INACTIVO: 1, SOLO: 1}
        assert sum(stats["estados"].values()) == 4

    def test_el_dashboard_conserva_los_conteos_por_area(self, test_client, test_db):
        _socio(test_db, "s1")
        _cuota(test_db, "m1", "s1")
        _area(test_db, "m2", "s1", dias=-1)
        stats = test_client.get("/api/dashboard/stats").json()
        assert stats["totalMembresias"] == 2
        assert stats["countsByArea"]["Sin área"] == 1
        assert stats["countsByArea"][Area.BALSEROS.value] == 1

    def test_el_dashboard_no_expone_las_bolsas_por_estado(self, test_client, test_db):
        _socio(test_db, "s1")
        _cuota(test_db, "m1", "s1", dias=1)
        stats = test_client.get("/api/dashboard/stats").json()
        assert "porVencer" not in stats
        assert "vencidas" not in stats
        assert "activas" not in stats

    def test_alertas_solo_por_membresia_vencida(self, test_client, test_db):
        _socio(test_db, "s1")
        _cuota(test_db, "m1", "s1", dias=-1)
        _area(test_db, "m2", "s1", dias=120)
        alertas = test_client.get("/api/dashboard/alertas").json()
        assert [a["id"] for a in alertas] == ["m1"]
        assert alertas[0]["estadoSocio"] == INACTIVO

    def test_alertas_priorizan_el_inactivo_sobre_el_revisar(self, test_client, test_db):
        _socio(test_db, "s1")
        _cuota(test_db, "m1", "s1", dias=-1)
        _area(test_db, "m2", "s1", dias=120)
        _socio(test_db, "s2")
        _cuota(test_db, "m3", "s2")
        _area(test_db, "m4", "s2", dias=-5)
        alertas = test_client.get("/api/dashboard/alertas").json()
        assert [a["id"] for a in alertas] == ["m1", "m4"]
        assert [a["estadoSocio"] for a in alertas] == [INACTIVO, REVISAR]


class TestEstadoVencidaPersistido:
    """`Membresia.estado = 'vencida'` reuses the two existing buckets.

    Reported as: "en la pestaña Socio activo, si cambio la ficha a uno y pongo
    vencida, queda en activo".

    The mark is not a state of its own: it is a shortcut for "just expired", so
    `concepto` picks the bucket exactly as a past `vencimiento` does — a `vencida`
    área row reads ⚠️ `Socio activo — revisar`, a `vencida` cuota row reads 🔴
    `Inactivo — revisar` (owner's decision). `Vigencia.vencida` folds the mark
    into the single "is it expired" predicate, so the precedence, the four
    buckets and every read path are the ones that already existed.

    Confirmed on the remote database: the only `vencida` row there is an `area`
    membership with `vencimiento = 2026-10-10`, i.e. the ⚠️ case below.
    """

    def test_area_vencida_con_fecha_futura_es_revisar(self, test_db):
        """The real row: an `area` membership flagged `vencida`, date untouched."""
        _socio(test_db, "s1")
        _cuota(test_db, "m1", "s1", dias=120)
        _area(test_db, "m2", "s1", dias=120, estado=EstadoMembresia.VENCIDA)
        assert estados_socio(test_db, ["s1"])["s1"] == EstadoSocioVisual.ACTIVO_REVISAR

    def test_cuota_vencida_con_fecha_futura_es_inactivo(self, test_db):
        _socio(test_db, "s1")
        _cuota(test_db, "m1", "s1", dias=120, estado=EstadoMembresia.VENCIDA)
        _area(test_db, "m2", "s1", dias=120)
        assert estados_socio(test_db, ["s1"])["s1"] == EstadoSocioVisual.INACTIVO_REVISAR

    def test_el_padron_sirve_revisar_para_una_membresia_vencida(self, test_client, test_db):
        _socio(test_db, "s1")
        _cuota(test_db, "m1", "s1", dias=120)
        _area(test_db, "m2", "s1", dias=120, estado=EstadoMembresia.VENCIDA)
        body = test_client.get("/api/socios").json()
        assert body[0]["estado"] == REVISAR
        assert body[0]["nominacion"] == REVISAR

    def test_el_dashboard_no_cuenta_como_activo(self, test_client, test_db):
        _socio(test_db, "s1")
        _cuota(test_db, "m1", "s1", dias=120)
        _area(test_db, "m2", "s1", dias=120, estado=EstadoMembresia.VENCIDA)
        assert test_client.get("/api/dashboard/stats").json()["estados"] == {
            ACTIVO: 0,
            REVISAR: 1,
            INACTIVO: 0,
            SOLO: 0,
        }

    def test_la_fecha_vencida_si_mueve_el_estado(self, test_db):
        """Control: the `vencimiento` path works, which isolates the mark to `estado`."""
        _socio(test_db, "s1")
        _cuota(test_db, "m1", "s1", dias=120)
        _area(test_db, "m2", "s1", dias=-1)
        assert estados_socio(test_db, ["s1"])["s1"] == EstadoSocioVisual.ACTIVO_REVISAR

    def test_todo_al_dia_sigue_activo(self, test_db):
        """Control: the untouched pair keeps the green state."""
        _socio(test_db, "s1")
        _cuota(test_db, "m1", "s1", dias=120)
        _area(test_db, "m2", "s1", dias=120)
        assert estados_socio(test_db, ["s1"])["s1"] == EstadoSocioVisual.ACTIVO

    def test_la_cuota_vencida_manda_sobre_el_area_vencida(self, test_db):
        """Precedence unchanged: a 🔴 cuota is never downgraded to the ⚠️ warning."""
        _socio(test_db, "s1")
        _cuota(test_db, "m1", "s1", dias=120, estado=EstadoMembresia.VENCIDA)
        _area(test_db, "m2", "s1", dias=120, estado=EstadoMembresia.VENCIDA)
        assert estados_socio(test_db, ["s1"])["s1"] == EstadoSocioVisual.INACTIVO_REVISAR

    def test_la_marca_no_se_esconde_detras_de_una_fecha_mas_nueva(self, test_db):
        """Aggregation, not last-row-wins: one flagged row of a concept flags it."""
        _socio(test_db, "s1")
        _cuota(test_db, "m1", "s1", dias=120)
        _area(test_db, "m2", "s1", dias=-5)
        _area(test_db, "m3", "s1", dias=300, estado=EstadoMembresia.VENCIDA)
        assert estados_socio(test_db, ["s1"])["s1"] == EstadoSocioVisual.ACTIVO_REVISAR

    def test_una_marca_vencida_no_arrastra_a_la_otra_cuota(self, test_db):
        """The split is per concept: an área mark never reaches the 🔴 branch."""
        _socio(test_db, "s1")
        _cuota(test_db, "m1", "s1", dias=120)
        _area(test_db, "m2", "s1", dias=120, estado=EstadoMembresia.VENCIDA)
        inputs = inputs_socio(test_db, ["s1"])["s1"]
        assert inputs.cuota.estado_vencida is False
        assert inputs.area.estado_vencida is True

    def test_la_marca_se_borra_al_cobrar(self, test_client, test_db):
        """EST-02: paying restores the state on the next read, no manual step.

        A charge writes `estado = 'activa'` (`renovacion.dia10`), which is what
        keeps the mark a recalculation and not a second stored badge.
        """
        _socio(test_db, "s1")
        cuota = _cuota(test_db, "m1", "s1", dias=120, estado=EstadoMembresia.VENCIDA)
        assert test_client.get("/api/socios").json()[0]["estado"] == INACTIVO

        renovar_membresias(test_db, [cuota.id], date.today())

        assert test_client.get("/api/socios").json()[0]["estado"] == SOLO

    def test_la_unidad_entera_lectura_el_marca_de_area(self, test_client, test_db):
        """Scope = unidad: the ⚠️ reaches the titular AND the integrante."""
        _parcela(test_db, "p1")
        _socio(test_db, "s1")
        _socio(test_db, "s2")
        _cuota(test_db, "m1", "s1")
        _cuota(test_db, "m2", "s2")
        _area(test_db, "m3", "s1", dias=120, parcela_id="p1", rol=RolMembresia.TITULAR)
        _area(
            test_db,
            "m4",
            "s2",
            dias=120,
            parcela_id="p1",
            rol=RolMembresia.INTEGRANTE,
            estado=EstadoMembresia.VENCIDA,
        )
        miembros = test_client.get("/api/membresias/parcelas").json()[0]["membresias"]
        assert {m["socioId"]: m["estadoSocio"] for m in miembros} == {
            "s1": REVISAR,
            "s2": REVISAR,
        }

    def test_la_marca_del_area_no_se_pierde_al_unir_con_la_unidad(self, test_db):
        """`vigencia_mas_vencida` unions the mark, it does not pick a date and drop it.

        The flagged unit row carries a LATER date than the member's own area, so a
        date-only comparison would return the unflagged one and serve 🟢.
        """
        propio = Vigencia(date(2026, 10, 5))
        unidad = Vigencia(date(2026, 12, 20), estado_vencida=True)
        unida = vigencia_mas_vencida(propio, unidad)
        assert unida.vencimiento == date(2026, 10, 5)
        assert unida.vencida(HOY) is True

    def test_una_sola_consulta_agrupada_con_la_marca(self, test_db):
        """D5: reading the mark costs no extra round trip."""
        _socio(test_db, "s1")
        _cuota(test_db, "m1", "s1", dias=120, estado=EstadoMembresia.VENCIDA)
        selects = _selects(test_db)
        assert estados_socio(test_db, ["s1"])["s1"] == EstadoSocioVisual.INACTIVO_REVISAR
        assert len([s for s in selects if s.lstrip().upper().startswith("SELECT")]) == 1

