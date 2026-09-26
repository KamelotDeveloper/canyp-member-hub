"""Manual `vencimiento` editing — the administrative safety valve (spec CBM-06).

The 10->10 cycle is produced by CHARGES (`renovacion.dia10`). This module is
the other, deliberate path: an administrator setting an ABSOLUTE date to correct
a legacy or veiled mistake. Both concepts are covered — área and cuota social —
individually and batched per parcel.

Three rules shape the whole module:

* **Verbatim.** The admin's date is stored EXACTLY as given, day 10 or not.
  Projecting it onto the 10->10 cycle would silently undo the correction, and
  projecting a date that is not the 10th is what makes this an override. A
  non-day-10 date here is a deliberate, reviewable override; the next charge
  still re-anchors to the cycle through `renovacion.dia10`.
* **No range constraint.** A date in the past is accepted. Legacy rows DO sit
  in the past, and "fixing" one to the future would fabricate coverage nobody
  paid for. Past = vencida, and that is a true statement about the socio.
* **Never a charge.** Nothing here creates, alters or deletes a `Pago` or
  `PagoItem` (CBM-06 safety, EST-03). These are data corrections, so the state
  they produce is pure recalculation on the next read (`estado_socio`), with no
  hook and no stored flag to maintain.

The service is TRANSACTION-AGNOSTIC: it writes + flushes but never commits, so
the router keeps ownership of the transaction (same contract as
`services/cuota_social.py`).
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from backend.models.enums import ConceptoMembresia
from backend.models.membresia import Membresia


def membresias_de_unidad(
    db: Session, parcela_id: str, concepto: ConceptoMembresia | None = None
) -> list[Membresia]:
    """Resolve exactly which rows a per-parcel batch edit may touch.

    `concepto=None` means "every membership of the parcel" and resolves to the
    rows carrying `parcelaId`, which is the whole unit: a cuota social row never
    carries a `parcelaId` (CS-01), so the two concepts are structurally
    isolated and one batch can never move the other.

    `concepto=AREA` is the same set narrowed to the área concept.

    `concepto=CUOTA_SOCIAL` is the only branch that leaves the parcel: a cuota
    social membership belongs to no unit, so it is reached THROUGH the unit's
    members — the socios holding a row in this parcel — and not through
    `parcelaId`. Every socio of the parcel has exactly one cuota social
    membership (CS-02), so this updates one row per member. A member with no
    cuota row yet simply contributes nothing; creating one is
    `services.cuota_social.crear_cuota_social`'s job, not a side effect of
    editing a date.

    Ordered by `id` so a batch is deterministic.
    """
    if concepto is ConceptoMembresia.CUOTA_SOCIAL:
        socios = [
            row[0]
            for row in db.query(Membresia.socioId)
            .filter(Membresia.parcelaId == parcela_id)
            .distinct()
            .all()
        ]
        if not socios:
            return []
        return (
            db.query(Membresia)
            .filter(
                Membresia.socioId.in_(socios),
                Membresia.concepto == ConceptoMembresia.CUOTA_SOCIAL,
            )
            .order_by(Membresia.id.asc())
            .all()
        )

    q = db.query(Membresia).filter(Membresia.parcelaId == parcela_id)
    if concepto is not None:
        q = q.filter(Membresia.concepto == concepto)
    return q.order_by(Membresia.id.asc()).all()


def editar_vencimiento(
    db: Session, membresias: list[Membresia], vencimiento: date
) -> list[Membresia]:
    """Write `vencimiento` verbatim on every row and return them.

    The date is stored as given (no `dia10` projection): this is the manual
    correction path, and the 10->10 cycle belongs to `services.renovacion`.
    """
    for m in membresias:
        m.vencimiento = vencimiento
    if membresias:
        db.flush()
    return membresias
