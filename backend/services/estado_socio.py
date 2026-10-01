"""Estados de socio — the 4 server-authoritative states (spec EST-01..EST-04).

Replaces the old 5-state `servicios/estado_visual.py`. Two things changed, and
they are the whole point of this module:

* **The 30-day warning window is gone.** There is no anticipación bucket
  anymore. A membership is al día until its `vencimiento` is in the past, and
  the boundary is `>=`: `vencimiento == hoy` is al día (same rule as
  `renovacion.dia10`).
* **The state belongs to the socio, not to a single membership.** It is derived
  from the cuota social membership plus the área memberships, so it is a pure
  function of stored data (`calcular_estado_socio`) and NOT a persisted flag.
  Nothing is written to recompute it, and paying restores the state on the very
  next read (EST-02).
* **`Membresia.estado = 'vencida'` is a shortcut for "just expired".** It adds
  no state: the very same buckets are reached by `concepto` instead of by date,
  so a `vencida` área row reads ⚠️ like an área whose `vencimiento` is past and a
  `vencida` cuota row reads 🔴 like a cuota that owes. It is read and never
  written here, and a charge clears it (`renovacion` writes `activa`), so the
  state stays a recalculation and not a stored badge.

These states are VISUAL CONTROL ONLY (EST-03): reading them never deletes,
hides, archives or stops charging anything. A 🔴 socio is still listed,
exportable and chargeable, and a 🟢 one is never "locked" — the next read
recomputes from the dates.

The `⚠️` state is scoped to the UNIT (titular e integrantes), so the same
function serves every read path with a different `area` input: the padrón passes
the socio's own worst área, the unit panel passes the unit's worst área
(`areas_por_unidad`). Same function, same 4 states, no duplicated rule.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from typing import NamedTuple

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from backend.models.enums import ConceptoMembresia, EstadoMembresia, EstadoSocioVisual
from backend.models.membresia import Membresia

# The ONLY persisted flag the badge honours for an administrative stop: a cuota
# social membership in `suspendida`/`baja` maps to 🔴 even when its date is still
# in the future. A `suspendida`/`baja` on an ÁREA row is IGNORED by the badge
# (design table) and stays in `Membresia.estado` untouched.
#
# `EstadoMembresia.VENCIDA` is deliberately NOT here: it is a statement about the
# EXPIRY, not an administrative stop, so it is honoured on both concepts and
# routed by `concepto` through the ordinary buckets instead (see `Vigencia`).
CUOTA_PARADA = (EstadoMembresia.SUSPENDIDA, EstadoMembresia.BAJA)


@dataclass(frozen=True)
class Vigencia:
    """The stored `vencimiento` a state derives from, plus its stop flag."""

    vencimiento: date
    # True only for a cuota social row whose persisted estado is suspendida/baja.
    parada: bool = False
    # True when any row behind this value carries the operator's `estado =
    # 'vencida'` mark. Aggregated like `parada`, so one flagged row can never
    # hide behind a fresher one of the same concept.
    estado_vencida: bool = False

    def vencida(self, hoy: date) -> bool:
        """Expired when strictly before today: `vencimiento == hoy` is al día.

        The operator's `vencida` mark enters through THIS predicate instead of a
        parallel branch, so "expired" keeps a single definition for every caller
        that reuses it (the badge and `cobro._cuota_impaga`): a flagged row is
        expired from the moment it is flagged, and the date and the mark can
        never disagree about which side of the bucket a row falls on.
        """
        return self.estado_vencida or self.vencimiento < hoy


class InputsSocio(NamedTuple):
    """The two facts `calcular_estado_socio` needs, already resolved."""

    cuota: Vigencia | None
    area: Vigencia | None


def calcular_estado_socio(
    cuota: Vigencia | None, area: Vigencia | None, hoy: date
) -> EstadoSocioVisual:
    """The 4 socio states, from data only. Pure: no DB, no clock, no I/O.

    | input | state |
    |---|---|
    | cuota vencida (or `suspendida`/`baja`/`vencida`) | 🔴 Inactivo — revisar |
    | cuota al día, sin área | Solo cuota social |
    | cuota al día, área vencida | ⚠️ Socio activo — revisar |
    | cuota al día, área al día (o sin cuota) | 🟢 Socio activo |

    "Vencida" is ONE concept with two inputs — a `vencimiento` in the past or the
    operator's `estado = 'vencida'` mark, both folded by `Vigencia.vencida` — so
    the mark reuses these buckets instead of adding a fifth state. Which concept
    carries it selects the row above: only the cuota social deactivates (🔴), an
    área that expired only warns (⚠️), exactly as if its date were past.

    Order matters: a debt outranks the "no área" nominación, and a 🔴 socio is
    never downgraded to a warning just because the área is also late.
    """
    if cuota is not None and (cuota.parada or cuota.vencida(hoy)):
        return EstadoSocioVisual.INACTIVO_REVISAR
    if area is None:
        return EstadoSocioVisual.SOLO_CUOTA_SOCIAL
    if area.vencida(hoy):
        return EstadoSocioVisual.ACTIVO_REVISAR
    return EstadoSocioVisual.ACTIVO


def inputs_socio(db: Session, socio_ids: list[str]) -> dict[str, InputsSocio]:
    """Resolve `(cuota, worst área)` for every socio in ONE grouped query (D5).

    Never N+1: one `GROUP BY socioId` returns the earliest `vencimiento` per
    concept, so a single stale row can never hide behind a fresher one and an
    entire padron costs the same one round trip as one socio. Every requested
    id is present in the result, even with no membership rows at all.

    An "área membership" is `area IS NOT NULL` (a cuota social is not a place,
    CS-01) rather than `concepto = 'AREA'`, so a row written before the
    `concepto` backfill still counts. The cuota side keys on the concept, which
    is the only way to tell a cuota row from an área one.

    The `vencida` mark is aggregated per concept with the same `max(...)` as
    `cuota_parada` — any flagged row of that concept flags the value — so it
    adds two columns to the SAME grouped query and never a round trip. A socio
    with several área rows (their own plus the ones of other units) therefore
    cannot hide a flagged one behind a fresher row, and the per-concept split is
    what routes the mark to 🔴 (cuota) or ⚠️ (área) with no extra rule.
    """
    wanted = list(dict.fromkeys(socio_ids))
    if not wanted:
        return {}

    es_cuota = Membresia.concepto == ConceptoMembresia.CUOTA_SOCIAL
    es_area = Membresia.area.isnot(None)
    marcada = Membresia.estado == EstadoMembresia.VENCIDA
    rows = (
        db.query(
            Membresia.socioId,
            func.min(case((es_cuota, Membresia.vencimiento))).label("cuota_venc"),
            func.max(case((es_cuota & Membresia.estado.in_(CUOTA_PARADA), 1), else_=0)).label(
                "cuota_parada"
            ),
            func.max(case((es_cuota & marcada, 1), else_=0)).label("cuota_vencida"),
            func.min(case((es_area, Membresia.vencimiento))).label("area_venc"),
            func.max(case((es_area & marcada, 1), else_=0)).label("area_vencida"),
        )
        .filter(Membresia.socioId.in_(wanted))
        .group_by(Membresia.socioId)
        .all()
    )

    result: dict[str, InputsSocio] = {
        socio_id: InputsSocio(None, None) for socio_id in wanted
    }
    for row in rows:
        cuota = (
            Vigencia(
                row.cuota_venc,
                parada=bool(row.cuota_parada),
                estado_vencida=bool(row.cuota_vencida),
            )
            if row.cuota_venc is not None
            else None
        )
        area = (
            Vigencia(row.area_venc, estado_vencida=bool(row.area_vencida))
            if row.area_venc is not None
            else None
        )
        result[row.socioId] = InputsSocio(cuota, area)
    return result


def estados_socio(
    db: Session, socio_ids: list[str], *, hoy: date | None = None
) -> dict[str, EstadoSocioVisual]:
    """`{socio_id: state}` for a whole listing, in ONE grouped query (D5)."""
    hoy = hoy or date.today()
    return {
        socio_id: calcular_estado_socio(inputs.cuota, inputs.area, hoy)
        for socio_id, inputs in inputs_socio(db, socio_ids).items()
    }


def areas_por_unidad(db: Session, parcela_ids: list[str]) -> dict[str, Vigencia]:
    """Worst área membership per unit, ONE grouped query.

    Scope = unidad (design D5): a balsa or a cabaña is one thing paid once, so
    its state is the earliest `vencimiento` among its members' área rows. A
    titular with a stale row and an integrantes with a fresh one are still the
    SAME unit: passing this value as the `area` input is what makes every member
    read ⚠️ together instead of splitting the unit.

    A member's own área rows (e.g. another unit they belong to) are NOT
    included — the caller combines both when it needs the full picture.

    The `vencida` mark is read here too, in the same grouped query: the unit is
    the thing that is paid once, so a row an operator flagged as expired belongs
    to the whole unit and not to one member. Leaving it out is what would let
    the unit panel serve ⚠️ while the padrón — which combines this value with
    the socio's own área — served 🟢 for the same socio.
    """
    wanted = list(dict.fromkeys(parcela_ids))
    if not wanted:
        return {}
    rows = (
        db.query(
            Membresia.parcelaId.label("parcelaId"),
            func.min(Membresia.vencimiento).label("venc"),
            func.max(
                case((Membresia.estado == EstadoMembresia.VENCIDA, 1), else_=0)
            ).label("vencida"),
        )
        .filter(Membresia.parcelaId.in_(wanted), Membresia.area.isnot(None))
        .group_by(Membresia.parcelaId)
        .all()
    )
    return {
        row.parcelaId: Vigencia(row.venc, estado_vencida=bool(row.vencida))
        for row in rows
    }


def vigencia_mas_vencida(*vigencias: Vigencia | None) -> Vigencia | None:
    """The earliest of several `Vigencia` values (`None` when all are `None`).

    Combines a socio's own área with their unit's área so the unit panel and
    the padrón can never disagree about a socio who belongs to a stale unit.

    "Most expired" is the earliest date PLUS the `vencida` mark, not the earliest
    date alone: the unit's flagged row can carry a LATER date than the member's
    own, and picking by date would drop the mark and serve 🟢 for a unit that is
    flagged as expired. The mark is therefore unioned, never overwritten.
    """
    presentes = [v for v in vigencias if v is not None]
    if not presentes:
        return None
    peor = min(presentes, key=lambda v: v.vencimiento)
    if any(v.estado_vencida for v in presentes):
        return replace(peor, estado_vencida=True)
    return peor
