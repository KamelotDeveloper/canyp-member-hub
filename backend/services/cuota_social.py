"""Cuota social lifecycle — one ``Membresia`` row per socio (spec CS-01/CS-02).

Cuota social is **not** a separate entity and **not** a ``Socio`` boolean. It is
an ordinary membership whose ``concepto`` is ``CUOTA_SOCIAL``, so it reuses the
whole membership machinery: 10->10 renewal, state recalculation, receipts,
carnets and recargos all work on it unchanged.

The row carries no ``area``/``predio``/``parcelaId``/``rol`` because a cuota
social is not a physical place. That is exactly why PR 1 made those columns
nullable, and why task 2.3 had to guard every ``.value`` dereference on the
read paths.

Two Windsurf rules are honoured here by construction (CS-05): a Windsurf socio's
existing area membership IS their cuota social, so this service never creates a
second area row, and it never multiplies any area arancel — that is PR 5.

The service is TRANSACTION-AGNOSTIC: it adds + flushes but never commits, so
callers keep ownership of the transaction (a bulk import rolls its cuota rows
back inside the row's own SAVEPOINT; the legacy migration commits once).
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.models.enums import ConceptoMembresia, EstadoMembresia
from backend.models.membresia import Membresia
from backend.models.socio import Socio
from backend.services.renovacion import dia10


def ventana_actual(hoy: date | None = None) -> date:
    """Anchor of the current 10->10 window, i.e. ``dia10(today)``.

    A new cuota social membership is created inside the window that is running
    right now: on 25/09 it is 10/10, on 03/09 it is 10/09 (see
    :func:`backend.services.renovacion.dia10`).
    """
    return dia10(hoy or date.today())


def cuota_de(db: Session, socio_id: str) -> Membresia | None:
    """The socio's cuota social membership, or ``None`` when it has none.

    ``concepto`` is compared as an enum member, which SQLAlchemy renders as the
    stored NAME ``'CUOTA_SOCIAL'`` (never the display label), matching the
    backfill done by ``migrate.py``.
    """
    return (
        db.query(Membresia)
        .filter(
            Membresia.socioId == socio_id,
            Membresia.concepto == ConceptoMembresia.CUOTA_SOCIAL,
        )
        .order_by(Membresia.id.asc())
        .first()
    )


def ultimo_vencimiento_area(db: Session, socio_id: str) -> date | None:
    """Most recent ``vencimiento`` among the socio's area memberships.

    Keyed on ``area IS NOT NULL`` rather than ``concepto = 'AREA'`` on purpose:
    naming a physical area IS the definition of an area membership, and that
    predicate also works on a database whose ``concepto`` column exists but has
    not been backfilled yet. Returns ``None`` for a socio with no activity.
    """
    return (
        db.query(func.max(Membresia.vencimiento))
        .filter(Membresia.socioId == socio_id, Membresia.area.isnot(None))
        .scalar()
    )


def crear_cuota_social(
    db: Session,
    socio: Socio | str,
    *,
    vencimiento: date | None = None,
    hoy: date | None = None,
) -> tuple[Membresia, bool]:
    """Ensure `socio` owns exactly one ``CUOTA_SOCIAL`` membership (CS-02).

    Idempotent: when the cuota row already exists it is returned untouched and
    ``created`` is ``False`` — re-running never duplicates it.

    ``vencimiento`` defaults to the socio's most recent area ``vencimiento``
    and falls back to the current 10->10 window for a socio with no area
    membership (CS-02 backfill / CS-06 solo-cuota-social). Callers that wire
    this into a live create flow (socio creation, bulk import, unit member)
    rely on that default.

    The row is added and FLUSHED but never committed. The flush matters: the
    application session factory sets ``autoflush=False``
    (``backend/database.py``), so without it a second call in the same
    transaction would not see the pending row and would create a duplicate.
    """
    socio_id = socio if isinstance(socio, str) else socio.id

    existente = cuota_de(db, socio_id)
    if existente is not None:
        return existente, False

    if vencimiento is None:
        vencimiento = ultimo_vencimiento_area(db, socio_id) or ventana_actual(hoy)

    cuota = Membresia(
        id=f"m{uuid.uuid4().hex[:8]}",
        socioId=socio_id,
        # A cuota social is not a place, a unit or a role: all four stay NULL.
        area=None,
        predio=None,
        estado=EstadoMembresia.ACTIVA,
        concepto=ConceptoMembresia.CUOTA_SOCIAL,
        vencimiento=vencimiento,
        parcelaId=None,
        rol=None,
    )
    db.add(cuota)
    db.flush()
    return cuota, True
