"""Integration tests for /api/parcelas CRUD endpoints + manual vencimiento editing.

The second half of this file (from `TestVencimientoManual*` down) covers
spec CBM-06: the administrative valve that sets an ABSOLUTE `vencimiento` on an
área or a cuota social membership, individually or batched per parcel. It lives
here because both endpoints are exercised through the same unit fixture, and
because `pytest backend/tests/test_parcelas_api.py -q` is the focused command
that proves the whole work unit.
"""

from datetime import date

import pytest

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
from backend.models.pago import Pago, PagoItem
from backend.models.parcela import Parcela
from backend.models.socio import Socio


PARCELA_PAYLOAD = {
    "id": "p001",
    "nombre": "Cabaña del Lago",
    "tipo": "cabaña",
    "tamano": "40m2",
    "predio": "Almafuerte",
}


class TestParcelasCRUD:
    """Full CRUD lifecycle for parcelas."""

    def test_list_parcelas_empty(self, test_client):
        """GET /api/parcelas returns empty list when no parcelas exist."""
        resp = test_client.get("/api/parcelas")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_create_parcela(self, test_client):
        """POST /api/parcelas creates a parcela with 201."""
        resp = test_client.post("/api/parcelas", json=PARCELA_PAYLOAD)
        assert resp.status_code == 201
        body = resp.json()
        assert body["id"] == "p001"
        assert body["nombre"] == "Cabaña del Lago"
        assert body["tipo"] == "cabaña"
        assert body["predio"] == "Almafuerte"

    def test_get_parcela(self, test_client):
        """GET /api/parcelas/{id} returns the created parcela."""
        test_client.post("/api/parcelas", json=PARCELA_PAYLOAD)
        resp = test_client.get("/api/parcelas/p001")
        assert resp.status_code == 200
        assert resp.json()["id"] == "p001"
        assert resp.json()["nombre"] == "Cabaña del Lago"

    def test_get_parcela_nonexistent_returns_404(self, test_client):
        """GET /api/parcelas/{id} returns 404 for non-existent id."""
        resp = test_client.get("/api/parcelas/nonexistent")
        assert resp.status_code == 404

    def test_update_parcela(self, test_client):
        """PUT /api/parcelas/{id} updates the parcela."""
        test_client.post("/api/parcelas", json=PARCELA_PAYLOAD)
        resp = test_client.put(
            "/api/parcelas/p001",
            json={"nombre": "Cabaña del Sol", "tamano": "60m2"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["nombre"] == "Cabaña del Sol"
        assert body["tamano"] == "60m2"
        # Unchanged fields stay the same
        assert body["tipo"] == "cabaña"
        assert body["predio"] == "Almafuerte"

    def test_update_parcela_nonexistent_returns_404(self, test_client):
        """PUT /api/parcelas/{id} returns 404 for non-existent id."""
        resp = test_client.put(
            "/api/parcelas/nonexistent", json={"nombre": "Nope"}
        )
        assert resp.status_code == 404

    def test_delete_parcela(self, test_client):
        """DELETE /api/parcelas/{id} returns 204 and removes parcela."""
        test_client.post("/api/parcelas", json=PARCELA_PAYLOAD)
        resp = test_client.delete("/api/parcelas/p001")
        assert resp.status_code == 204
        # Verify gone
        resp = test_client.get("/api/parcelas/p001")
        assert resp.status_code == 404

    def test_delete_parcela_nonexistent_returns_404(self, test_client):
        """DELETE /api/parcelas/{id} returns 404 for non-existent id."""
        resp = test_client.delete("/api/parcelas/nonexistent")
        assert resp.status_code == 404

    def test_list_parcelas_filter_by_predio(self, test_client):
        """GET /api/parcelas?predio=Embalse filters by predio."""
        test_client.post("/api/parcelas", json=PARCELA_PAYLOAD)
        test_client.post(
            "/api/parcelas",
            json={
                **PARCELA_PAYLOAD,
                "id": "p002",
                "nombre": "Balsa Norte",
                "tipo": "balsa",
                "predio": "Embalse",
            },
        )
        resp = test_client.get("/api/parcelas", params={"predio": "Embalse"})
        assert resp.status_code == 200
        parcelas = resp.json()
        assert len(parcelas) == 1
        assert parcelas[0]["id"] == "p002"
        assert parcelas[0]["predio"] == "Embalse"

    def test_list_parcelas_returns_all_when_no_filter(self, test_client):
        """GET /api/parcelas returns all parcelas when no predio filter."""
        test_client.post("/api/parcelas", json=PARCELA_PAYLOAD)
        test_client.post(
            "/api/parcelas",
            json={
                **PARCELA_PAYLOAD,
                "id": "p002",
                "nombre": "Balsa Norte",
                "tipo": "balsa",
                "predio": "Embalse",
            },
        )
        resp = test_client.get("/api/parcelas")
        assert resp.status_code == 200
        assert len(resp.json()) == 2


class TestParcelaCascadeDelete:
    """Deleting a parcela must also remove its associated memberships."""

    def _setup_parcela_with_memberships(self, test_client):
        """Create a parcela, two socios, and two memberships linked to it."""
        test_client.post("/api/parcelas", json=PARCELA_PAYLOAD)
        test_client.post(
            "/api/socios",
            json={
                "id": "sDel1",
                "nombre": "Titular Uno",
                "dni": "10000001",
                "telefono": "",
                "email": "",
                "direccion": "",
                "activo": True,
            },
        )
        test_client.post(
            "/api/socios",
            json={
                "id": "sDel2",
                "nombre": "Integrante Dos",
                "dni": "10000002",
                "telefono": "",
                "email": "",
                "direccion": "",
                "activo": True,
            },
        )
        # Create memberships linked to the parcela
        test_client.post(
            "/api/membresias",
            json={
                "id": "mDel1",
                "socioId": "sDel1",
                "area": "Cabañeros",
                "predio": "Almafuerte",
                "estado": "activa",
                "vencimiento": "2026-12-31",
                "rol": "Titular",
                "parcelaId": "p001",
            },
        )
        test_client.post(
            "/api/membresias",
            json={
                "id": "mDel2",
                "socioId": "sDel2",
                "area": "Cabañeros",
                "predio": "Almafuerte",
                "estado": "activa",
                "vencimiento": "2026-12-31",
                "rol": "Integrante",
                "parcelaId": "p001",
            },
        )

    def test_delete_parcela_removes_memberships(self, test_client):
        """DELETE /api/parcelas/{id} also deletes all linked memberships."""
        self._setup_parcela_with_memberships(test_client)
        # Confirm memberships exist
        resp = test_client.get("/api/membresias", params={"predio": "Almafuerte"})
        assert resp.status_code == 200
        assert len(resp.json()) == 2

        # Delete the parcela
        resp = test_client.delete("/api/parcelas/p001")
        assert resp.status_code == 204

        # Parcela is gone
        resp = test_client.get("/api/parcelas/p001")
        assert resp.status_code == 404

        # Memberships linked to that parcela are also gone
        resp = test_client.get("/api/membresias", params={"predio": "Almafuerte"})
        assert resp.status_code == 200
        remaining = [m for m in resp.json() if m.get("parcelaId") == "p001"]
        assert remaining == []

    def test_delete_parcela_preserves_socios(self, test_client):
        """DELETE /api/parcelas/{id} removes memberships but NOT the socios themselves."""
        self._setup_parcela_with_memberships(test_client)
        resp = test_client.delete("/api/parcelas/p001")
        assert resp.status_code == 204

        # Socios still exist
        resp = test_client.get("/api/socios/sDel1")
        assert resp.status_code == 200
        resp = test_client.get("/api/socios/sDel2")
        assert resp.status_code == 200


# --------------------------------------------------------------------------
# CBM-06 — Edición manual de vencimiento (PR 6, tasks 6.1 + 6.2)
#
# The 10->10 cycle belongs to CHARGES (`services.renovacion.dia10`). These two
# endpoints are the opposite: an administrator correcting a date BY HAND. The
# three rules the tests below lock:
#   1. the admin's date is stored VERBATIM (day 10 or not, past or future);
#   2. a malformed date is a 422 that changes NOTHING (validated before write);
#   3. no `Pago` is ever created — this is a data correction, not a charge —
#      and the badge is recalculated, never stored (EST-02).
# --------------------------------------------------------------------------

# A legacy date already in the past: the whole reason this valve exists.
VENCIDO = date(2020, 1, 1)
# A day-10 in the future, i.e. what an admin would normally type.
AL_DIA = date(2030, 12, 10)
# Deliberately NOT a day 10: proves the date is not projected onto the cycle.
CUALQUIER_FECHA = date(2030, 3, 7)

ACTIVO = EstadoSocioVisual.ACTIVO.value
REVISAR = EstadoSocioVisual.ACTIVO_REVISAR.value
INACTIVO = EstadoSocioVisual.INACTIVO_REVISAR.value


def _socio(db, socio_id: str) -> str:
    db.add(
        Socio(
            id=socio_id,
            nombre=f"Socio {socio_id}",
            dni=f"30{socio_id.lstrip('s'):0>6}",
            fechaAlta=date(2024, 1, 1),
        )
    )
    db.commit()
    return socio_id


def _parcela(db, parcela_id: str, nombre: str) -> str:
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


def _area(db, mid: str, socio_id: str, parcela_id: str, *, rol=None, vencido=VENCIDO) -> str:
    """An área membership inside a unit (concepto AREA, carries the parcelaId)."""
    db.add(
        Membresia(
            id=mid,
            socioId=socio_id,
            area=Area.BALSEROS,
            predio=Predio.EMBALSE,
            estado=EstadoMembresia.ACTIVA,
            concepto=ConceptoMembresia.AREA,
            vencimiento=vencido,
            parcelaId=parcela_id,
            rol=rol or RolMembresia.INTEGRANTE,
        )
    )
    db.commit()
    return mid


def _cuota(db, socio_id: str, *, vencido=VENCIDO) -> str:
    """The socio's cuota social membership: no area, no predio, no parcela (CS-01)."""
    mid = f"mc{socio_id}"
    db.add(
        Membresia(
            id=mid,
            socioId=socio_id,
            area=None,
            predio=None,
            estado=EstadoMembresia.ACTIVA,
            concepto=ConceptoMembresia.CUOTA_SOCIAL,
            vencimiento=vencido,
            parcelaId=None,
            rol=None,
        )
    )
    db.commit()
    return mid


def _unidad(db, parcela_id="p1", miembros=("s1", "s2"), *, cuotas=VENCIDO, areas=VENCIDO):
    """A balsa with `miembros`, plus one cuota social row per member."""
    _parcela(db, parcela_id, f"Balsa {parcela_id}")
    for i, socio_id in enumerate(miembros):
        _socio(db, socio_id)
        _area(
            db,
            f"m{socio_id}",
            socio_id,
            parcela_id,
            rol=RolMembresia.TITULAR if i == 0 else RolMembresia.INTEGRANTE,
            vencido=areas,
        )
        _cuota(db, socio_id, vencido=cuotas)


def _por_concepto(db, concepto) -> dict[str, date]:
    """`{membresia_id: vencimiento}` for one concept, straight from the DB."""
    return {
        m.id: m.vencimiento
        for m in db.query(Membresia).filter(Membresia.concepto == concepto).all()
    }


def _estados(test_client) -> dict[str, str]:
    """`{socio_id: estado}` as the padrón serves it (EST-01)."""
    return {s["id"]: s["estado"] for s in test_client.get("/api/socios").json()}


def _pagos(db) -> tuple[int, int]:
    return db.query(Pago).count(), db.query(PagoItem).count()


class TestVencimientoManualMembresia:
    """PUT /api/membresias/{id}/vencimiento — the individual correction (CBM-06)."""

    def test_edita_el_vencimiento_de_un_area(self, test_client, test_db):
        """An área membership takes the admin's date verbatim."""
        _unidad(test_db, miembros=("s1",))
        assert _por_concepto(test_db, ConceptoMembresia.AREA) == {"ms1": VENCIDO}

        resp = test_client.put(
            "/api/membresias/ms1/vencimiento", json={"vencimiento": AL_DIA.isoformat()}
        )
        assert resp.status_code == 200
        assert resp.json()["vencimiento"] == AL_DIA.isoformat()
        test_db.expire_all()
        assert _por_concepto(test_db, ConceptoMembresia.AREA) == {"ms1": AL_DIA}

    def test_edita_el_vencimiento_de_una_cuota_social(self, test_client, test_db):
        """The same endpoint reaches a cuota social membership: the id decides.

        Also the isolation proof for the individual edit: correcting the cuota
        leaves the socio's own área row, and the persisted `estado` (a
        projection, not a flag the editor may touch), exactly as they were.
        """
        _unidad(test_db, miembros=("s1",))
        assert _por_concepto(test_db, ConceptoMembresia.CUOTA_SOCIAL) == {"mcs1": VENCIDO}

        resp = test_client.put(
            "/api/membresias/mcs1/vencimiento",
            json={"vencimiento": AL_DIA.isoformat()},
        )
        assert resp.status_code == 200
        test_db.expire_all()
        assert _por_concepto(test_db, ConceptoMembresia.CUOTA_SOCIAL) == {"mcs1": AL_DIA}
        assert _por_concepto(test_db, ConceptoMembresia.AREA) == {"ms1": VENCIDO}
        cuota = test_db.query(Membresia).filter(Membresia.id == "mcs1").one()
        assert cuota.estado == EstadoMembresia.ACTIVA

    def test_respeta_una_fecha_que_no_es_dia_10(self, test_client, test_db):
        """The date is stored AS TYPED: no `dia10` projection on the manual path.

        This is the documented interaction with the 10->10 cycle — projecting
        here would silently undo the correction, and the cycle is re-anchored
        by the next charge anyway (`services.renovacion.dia10`).
        """
        _unidad(test_db, miembros=("s1",))
        resp = test_client.put(
            "/api/membresias/ms1/vencimiento",
            json={"vencimiento": CUALQUIER_FECHA.isoformat()},
        )
        assert resp.status_code == 200
        test_db.expire_all()
        assert _por_concepto(test_db, ConceptoMembresia.AREA) == {"ms1": CUALQUIER_FECHA}

    def test_acepta_una_fecha_pasada(self, test_client, test_db):
        """No range constraint: legacy dates really are in the past (CBM-06).

        Refusing them would make the valve useless — the rows an admin most
        needs to correct are precisely the ones already overdue.
        """
        _unidad(test_db, miembros=("s1",))
        pasado = date(2019, 5, 3)
        resp = test_client.put(
            "/api/membresias/mcs1/vencimiento", json={"vencimiento": pasado.isoformat()}
        )
        assert resp.status_code == 200
        test_db.expire_all()
        assert _por_concepto(test_db, ConceptoMembresia.CUOTA_SOCIAL) == {"mcs1": pasado}

    def test_no_crea_ningun_pago(self, test_client, test_db):
        """A manual edit is NOT a charge: no `Pago`, no `PagoItem` (CBM-06)."""
        _unidad(test_db, miembros=("s1",))
        assert _pagos(test_db) == (0, 0)
        test_client.put(
            "/api/membresias/ms1/vencimiento", json={"vencimiento": AL_DIA.isoformat()}
        )
        test_client.put(
            "/api/membresias/mcs1/vencimiento", json={"vencimiento": AL_DIA.isoformat()}
        )
        test_db.expire_all()
        assert _pagos(test_db) == (0, 0)

    @pytest.mark.parametrize(
        "malformada",
        ["ayer", "10/12/2030", "2030-12-32", "2030-13-01", "2030-02-30", "hoy"],
    )
    def test_fecha_malformada_es_422_y_no_cambia_nada(self, test_client, test_db, malformada):
        """Unparseable or impossible calendar date -> 422, and NOTHING is written."""
        _unidad(test_db, miembros=("s1",))
        resp = test_client.put(
            "/api/membresias/ms1/vencimiento", json={"vencimiento": malformada}
        )
        assert resp.status_code == 422
        test_db.expire_all()
        assert _por_concepto(test_db, ConceptoMembresia.AREA) == {"ms1": VENCIDO}
        assert _por_concepto(test_db, ConceptoMembresia.CUOTA_SOCIAL) == {"mcs1": VENCIDO}

    @pytest.mark.parametrize("cuerpo", [{}, {"vencimiento": None}, {"vencimiento": ""}])
    def test_fecha_ausente_o_nula_es_422(self, test_client, test_db, cuerpo):
        """`vencimiento` is required on BOTH editors, unlike `MembresiaUpdate`.

        A missing or null date is a 422, never a silent "leave it alone" — the
        old batch endpoint took an optional field and no-oped on a null body.
        """
        _unidad(test_db, miembros=("s1",))
        assert test_client.put(
            "/api/membresias/ms1/vencimiento", json=cuerpo
        ).status_code == 422
        assert test_client.put(
            "/api/parcelas/p1/vencimiento", json=cuerpo
        ).status_code == 422
        test_db.expire_all()
        assert _por_concepto(test_db, ConceptoMembresia.AREA) == {"ms1": VENCIDO}

    def test_membresia_inexistente_es_404(self, test_client, test_db):
        """Unknown id -> 404, not a silent success."""
        _unidad(test_db, miembros=("s1",))
        resp = test_client.put(
            "/api/membresias/no-existe/vencimiento", json={"vencimiento": AL_DIA.isoformat()}
        )
        assert resp.status_code == 404
        test_db.expire_all()
        assert _por_concepto(test_db, ConceptoMembresia.AREA) == {"ms1": VENCIDO}

    def test_la_lectura_siguiente_refleja_la_edicion_del_area(self, test_client, test_db):
        """AC: the state reflects the edit on the next read (EST-02).

        Both read paths recalculate, and they are fed different `area` inputs by
        design (D5): the padrón uses the socio's OWN worst área, the unit panel
        the UNIT's worst área. So correcting s1's área row flips s1 to 🟢 in the
        padrón while the panel still shows ⚠️ for the whole unit until every
        área row is corrected — the manual valve does not bypass the unit-scoped
        rule, and no payment is recorded along the way.
        """
        _unidad(test_db, miembros=("s1", "s2"), cuotas=AL_DIA, areas=VENCIDO)
        assert _estados(test_client) == {"s1": REVISAR, "s2": REVISAR}

        test_client.put(
            "/api/membresias/ms1/vencimiento", json={"vencimiento": AL_DIA.isoformat()}
        )
        assert _estados(test_client) == {"s1": ACTIVO, "s2": REVISAR}
        panel = test_client.get("/api/membresias/parcelas").json()[0]["membresias"]
        assert {m["estadoSocio"] for m in panel} == {REVISAR}

        test_client.put(
            "/api/membresias/ms2/vencimiento", json={"vencimiento": AL_DIA.isoformat()}
        )
        assert _estados(test_client) == {"s1": ACTIVO, "s2": ACTIVO}
        panel = test_client.get("/api/membresias/parcelas").json()[0]["membresias"]
        assert {m["estadoSocio"] for m in panel} == {ACTIVO}

    def test_la_lectura_siguiente_refleja_la_edicion_de_la_cuota(self, test_client, test_db):
        """AC: correcting a 🔴 cuota social restores 🟢, again with no payment."""
        _unidad(test_db, miembros=("s1",), areas=AL_DIA, cuotas=VENCIDO)
        assert _estados(test_client) == {"s1": INACTIVO}

        test_client.put(
            "/api/membresias/mcs1/vencimiento", json={"vencimiento": AL_DIA.isoformat()}
        )
        assert _estados(test_client) == {"s1": ACTIVO}

    def test_vencer_la_cuota_a_mano_devuelve_el_socio_a_inactivo(self, test_client, test_db):
        """The valve is bidirectional: a date in the past re-arms 🔴 on its own."""
        _unidad(test_db, miembros=("s1",), areas=AL_DIA, cuotas=AL_DIA)
        assert _estados(test_client) == {"s1": ACTIVO}

        test_client.put(
            "/api/membresias/mcs1/vencimiento", json={"vencimiento": VENCIDO.isoformat()}
        )
        assert _estados(test_client) == {"s1": INACTIVO}


class TestVencimientoManualLote:
    """PUT /api/parcelas/{id}/vencimiento?concepto= — the per-parcel batch (CBM-06)."""

    def test_lote_de_area_deja_intacta_cada_cuota_social(self, test_client, test_db):
        """AC: a batch área edit changes every área row and NOT one cuota social."""
        _unidad(test_db, miembros=("s1", "s2"))
        resp = test_client.put(
            "/api/parcelas/p1/vencimiento",
            params={"concepto": "area"},
            json={"vencimiento": AL_DIA.isoformat()},
        )
        assert resp.status_code == 200
        test_db.expire_all()
        assert _por_concepto(test_db, ConceptoMembresia.AREA) == {
            "ms1": AL_DIA,
            "ms2": AL_DIA,
        }
        assert _por_concepto(test_db, ConceptoMembresia.CUOTA_SOCIAL) == {
            "mcs1": VENCIDO,
            "mcs2": VENCIDO,
        }

    def test_lote_sin_concepto_toca_solo_las_membresias_de_la_parcela(self, test_client, test_db):
        """Omitting `concepto` means "every membership of the parcel" — and a cuota
        social row carries no parcelaId (CS-01), so it is excluded structurally."""
        _unidad(test_db, miembros=("s1", "s2"))
        resp = test_client.put(
            "/api/parcelas/p1/vencimiento", json={"vencimiento": AL_DIA.isoformat()}
        )
        assert resp.status_code == 200
        assert resp.json()["concepto"] is None
        test_db.expire_all()
        assert _por_concepto(test_db, ConceptoMembresia.AREA) == {
            "ms1": AL_DIA,
            "ms2": AL_DIA,
        }
        assert _por_concepto(test_db, ConceptoMembresia.CUOTA_SOCIAL) == {
            "mcs1": VENCIDO,
            "mcs2": VENCIDO,
        }

    def test_lote_de_cuota_social_no_toca_las_areas(self, test_client, test_db):
        """The mirror of the AC: `concepto=cuota social` reaches the members' cuota
        rows THROUGH the unit and leaves every área row untouched."""
        _unidad(test_db, miembros=("s1", "s2"))
        resp = test_client.put(
            "/api/parcelas/p1/vencimiento",
            params={"concepto": "cuota social"},
            json={"vencimiento": AL_DIA.isoformat()},
        )
        assert resp.status_code == 200
        test_db.expire_all()
        assert _por_concepto(test_db, ConceptoMembresia.CUOTA_SOCIAL) == {
            "mcs1": AL_DIA,
            "mcs2": AL_DIA,
        }
        assert _por_concepto(test_db, ConceptoMembresia.AREA) == {
            "ms1": VENCIDO,
            "ms2": VENCIDO,
        }

    def test_el_lote_no_alcanza_a_otra_parcela(self, test_client, test_db):
        """A batch is scoped to its own unit, whichever concept it targets."""
        _unidad(test_db, parcela_id="p1", miembros=("s1", "s2"))
        _unidad(test_db, parcela_id="p2", miembros=("s3",))

        test_client.put(
            "/api/parcelas/p1/vencimiento", json={"vencimiento": AL_DIA.isoformat()}
        )
        test_db.expire_all()
        assert _por_concepto(test_db, ConceptoMembresia.AREA) == {
            "ms1": AL_DIA,
            "ms2": AL_DIA,
            "ms3": VENCIDO,
        }

        test_client.put(
            "/api/parcelas/p1/vencimiento",
            params={"concepto": "cuota social"},
            json={"vencimiento": CUALQUIER_FECHA.isoformat()},
        )
        test_db.expire_all()
        assert _por_concepto(test_db, ConceptoMembresia.CUOTA_SOCIAL) == {
            "mcs1": CUALQUIER_FECHA,
            "mcs2": CUALQUIER_FECHA,
            "mcs3": VENCIDO,
        }

    def test_el_lote_informa_cuantas_filas_actualizo(self, test_client, test_db):
        """`actualizadas` distinguishes an applied batch from a silent no-op."""
        _unidad(test_db, miembros=("s1", "s2"))
        cuerpo = {"vencimiento": AL_DIA.isoformat()}

        area = test_client.put(
            "/api/parcelas/p1/vencimiento", params={"concepto": "area"}, json=cuerpo
        )
        assert area.json()["actualizadas"] == 2
        assert area.json()["concepto"] == "area"

        cuota = test_client.put(
            "/api/parcelas/p1/vencimiento",
            params={"concepto": "cuota social"},
            json=cuerpo,
        )
        assert cuota.json()["actualizadas"] == 2
        assert cuota.json()["concepto"] == "cuota social"

    def test_lote_sobre_una_unidad_sin_miembros_es_200_con_cero(self, test_client, test_db):
        """An empty unit is a 200 with `actualizadas: 0`, never a 404 or a 500."""
        _parcela(test_db, "p9", "Balsa Vacía")
        resp = test_client.put(
            "/api/parcelas/p9/vencimiento", json={"vencimiento": AL_DIA.isoformat()}
        )
        assert resp.status_code == 200
        assert resp.json()["actualizadas"] == 0

    def test_lote_respeta_una_fecha_que_no_es_dia_10(self, test_client, test_db):
        """Same verbatim rule as the individual edit, applied to the whole unit."""
        _unidad(test_db, miembros=("s1",))
        resp = test_client.put(
            "/api/parcelas/p1/vencimiento", json={"vencimiento": CUALQUIER_FECHA.isoformat()}
        )
        assert resp.status_code == 200
        test_db.expire_all()
        assert _por_concepto(test_db, ConceptoMembresia.AREA) == {"ms1": CUALQUIER_FECHA}

    def test_no_crea_ningun_pago(self, test_client, test_db):
        """A batch correction is not a charge either (CBM-06 safety)."""
        _unidad(test_db, miembros=("s1", "s2"))
        cuerpo = {"vencimiento": AL_DIA.isoformat()}
        assert _pagos(test_db) == (0, 0)

        test_client.put("/api/parcelas/p1/vencimiento", json=cuerpo)
        test_client.put(
            "/api/parcelas/p1/vencimiento",
            params={"concepto": "cuota social"},
            json=cuerpo,
        )
        test_db.expire_all()
        assert _pagos(test_db) == (0, 0)

    @pytest.mark.parametrize("malformada", ["ayer", "2030-12-32", "2030-02-30", "2030-13-01"])
    def test_fecha_malformada_en_lote_es_422_y_no_cambia_nada(
        self, test_client, test_db, malformada
    ):
        """The batch validates before it writes, so a bad date moves nothing."""
        _unidad(test_db, miembros=("s1", "s2"))
        resp = test_client.put(
            "/api/parcelas/p1/vencimiento", json={"vencimiento": malformada}
        )
        assert resp.status_code == 422
        test_db.expire_all()
        assert _por_concepto(test_db, ConceptoMembresia.AREA) == {
            "ms1": VENCIDO,
            "ms2": VENCIDO,
        }
        assert _por_concepto(test_db, ConceptoMembresia.CUOTA_SOCIAL) == {
            "mcs1": VENCIDO,
            "mcs2": VENCIDO,
        }

    def test_concepto_desconocido_es_422(self, test_client, test_db):
        """An unknown concept is a validation error, never a silent all-rows batch."""
        _unidad(test_db, miembros=("s1",))
        resp = test_client.put(
            "/api/parcelas/p1/vencimiento",
            params={"concepto": "recargo"},
            json={"vencimiento": AL_DIA.isoformat()},
        )
        assert resp.status_code == 422
        test_db.expire_all()
        assert _por_concepto(test_db, ConceptoMembresia.AREA) == {"ms1": VENCIDO}

    def test_lote_registra_quien_edito(self, test_client, test_db, current_user_id):
        """Audit (D7): a batch correction stamps `updated_by` on every row it touches.

        The batch is the delicate edit (N memberships at once), so it must leave
        the same trace its authenticated individual sibling does.
        """
        _unidad(test_db, miembros=("s1", "s2"))
        resp = test_client.put(
            "/api/parcelas/p1/vencimiento",
            params={"concepto": "area"},
            json={"vencimiento": AL_DIA.isoformat()},
        )
        assert resp.status_code == 200
        test_db.expire_all()
        actualizadas = (
            test_db.query(Membresia)
            .filter(Membresia.concepto == ConceptoMembresia.AREA)
            .all()
        )
        assert {m.updated_by for m in actualizadas} == {current_user_id}
        # Cuota social rows were NOT part of the batch -> not stamped.
        cuotas = (
            test_db.query(Membresia)
            .filter(Membresia.concepto == ConceptoMembresia.CUOTA_SOCIAL)
            .all()
        )
        assert {m.updated_by for m in cuotas} == {None}

    def test_la_lectura_siguiente_refleja_el_lote(self, test_client, test_db):
        """AC: after a batch, the served state of every member is the new one."""
        _unidad(test_db, miembros=("s1", "s2"), cuotas=AL_DIA, areas=VENCIDO)
        assert _estados(test_client) == {"s1": REVISAR, "s2": REVISAR}

        resp = test_client.put(
            "/api/parcelas/p1/vencimiento", json={"vencimiento": AL_DIA.isoformat()}
        )
        assert resp.status_code == 200
        assert _estados(test_client) == {"s1": ACTIVO, "s2": ACTIVO}

    def test_un_lote_vencido_pone_en_inactivo_a_toda_la_unidad(self, test_client, test_db):
        """Correcting a cuota social by batch moves the state of every member."""
        _unidad(test_db, miembros=("s1", "s2"), cuotas=AL_DIA, areas=AL_DIA)
        assert _estados(test_client) == {"s1": ACTIVO, "s2": ACTIVO}

        test_client.put(
            "/api/parcelas/p1/vencimiento",
            params={"concepto": "cuota social"},
            json={"vencimiento": VENCIDO.isoformat()},
        )
        assert _estados(test_client) == {"s1": INACTIVO, "s2": INACTIVO}
