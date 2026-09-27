"""Resolution of the catalog arancel that prices a charge (RQ 13, PR 5 D3).

Design #421 D3: a categoria-specific arancel wins; otherwise fall back to the
categoria IS NULL (catch-all) row for the same area+predio; otherwise None.

PR 5 added the CONCEPT dimension (PAG-01): every lookup is scoped by
``Arancel.concepto``, so a concept can never be priced by another concept's row.
``cobro-aranceles-flexibles`` completes that split with the PLACE, and the two
rules coexist in one catalog because ``concepto`` is the tag that decides which
one applies:

- **AREA and SERVICIO are PLACES.** A balsa and a cabaña of the same club pay
  different amounts, so both resolve from the unit's own area+predio. The old
  ``precio_servicio(db)`` had no place at all, which is why every service in the
  club cost the same global price (ReQ-009).
- **CUOTA_SOCIAL and RECARGO are CONCEPTS, not places.** Their rows only exist
  to satisfy the NOT NULL area/predio columns, so they keep a placeholder place
  and are found by concept only, through :func:`resolver_arancel_concepto`
  (ReQ-101).

Determinism is explicit: every branch orders by ``Arancel.id`` so a duplicated
tuple always resolves the same way (D1), and :func:`arancel_mismatch` explains
the case where a requested ``arancelId`` had to be replaced by the place's own
row (D8).
"""

from sqlalchemy.orm import Session

from backend.models.arancel import Arancel
from backend.models.enums import (
    Area,
    CategoriaParcela,
    ConceptoCobro,
    Predio,
)


def resolver_monto(
    db: Session,
    area: Area,
    predio: Predio,
    categoria: CategoriaParcela | None,
    arancel_id: str | None = None,
    concepto: ConceptoCobro = ConceptoCobro.AREA,
) -> Arancel | None:
    """Resolve the applicable Arancel for area+predio+categoria+concepto.

    **The dual rule (D1).** A place-priced concept — ``AREA`` and ``SERVICIO`` —
    is resolved BY PLACE: the row must carry this ``area``+``predio`` (plus
    ``categoria`` when the parcel has one), because two places of the same club
    carry different prices. ``CUOTA_SOCIAL`` and ``RECARGO`` are not places at
    all, so they never come through here: they go through
    :func:`resolver_arancel_concepto`.

    Priority:
      0. explicit arancel_id, when the row still exists AND carries the requested
         concept AND belongs to this same area+predio. A row of another place
         never prices this unit, not even when the id was handed in by a client
         or by the membership's own ``arancelId``.
      1. exact categoria match (when categoria is not None)
      2. catch-all row where categoria IS NULL for the same area+predio
      3. None

    Every branch orders by ``Arancel.id`` ascending: given a duplicated tuple the
    lowest id wins deterministically instead of whatever the query planner
    happens to return first (ReQ-008). A UNIQUE index cannot guarantee that —
    a NULL ``categoria`` never collides, in SQLite nor in Postgres — so the 409
    of D4 is what keeps the duplicate out of the catalog and this ORDER BY is
    what keeps resolution sane if one ever shows up anyway.

    ``concepto`` defaults to AREA, which is every pre-PR-5 call site's intent.
    A rejected ``arancel_id`` is not silent: :func:`arancel_mismatch` reports it.
    """
    if arancel_id is not None:
        directo = (
            db.query(Arancel)
            .filter(
                Arancel.id == arancel_id,
                Arancel.concepto == concepto,
                Arancel.area == area,
                Arancel.predio == predio,
            )
            .order_by(Arancel.id.asc())
            .first()
        )
        if directo is not None:
            return directo

    if categoria is not None:
        exact = (
            db.query(Arancel)
            .filter(
                Arancel.area == area,
                Arancel.predio == predio,
                Arancel.categoria == categoria,
                Arancel.concepto == concepto,
            )
            .order_by(Arancel.id.asc())
            .first()
        )
        if exact is not None:
            return exact

    return (
        db.query(Arancel)
        .filter(
            Arancel.area == area,
            Arancel.predio == predio,
            Arancel.categoria.is_(None),
            Arancel.concepto == concepto,
        )
        .order_by(Arancel.id.asc())
        .first()
    )


def resolver_arancel_concepto(
    db: Session,
    concepto: ConceptoCobro,
    categoria: CategoriaParcela | None = None,
) -> Arancel | None:
    """Resolve the ONE catalog row that prices ``concepto``, ignoring area/predio.

    A concept that is not a physical place (the cuota social unit price, the
    RECARGO carrier) still has to satisfy the NOT NULL ``area``/``predio``
    columns, so its row carries placeholder values. Filtering by area+predio
    would therefore be meaningless — and actively wrong, since a placeholder can
    collide with a real area. The concept tag IS the key; ``categoria`` stays
    available for a concept that ever gets size-based pricing.

    Ordered by id so the resolution is deterministic when a catalog carries more
    than one row for the same concept: the first wins, never an arbitrary one.
    """
    q = db.query(Arancel).filter(Arancel.concepto == concepto)
    if categoria is not None:
        q = q.filter(Arancel.categoria == categoria)
    else:
        q = q.filter(Arancel.categoria.is_(None))
    return q.order_by(Arancel.id.asc()).first()


def precio_cuota_social(db: Session) -> Arancel | None:
    """Unit price of the cuota social (CS-03).

    The row is a plain concept-tagged arancel: ``monto`` is the price of ONE
    member, and the charge multiplies it by the unit's member count. Returning
    the ``Arancel`` (not a float) keeps the frozen name + amount on the same
    object the ``PagoItem`` needs.
    """
    return resolver_arancel_concepto(db, ConceptoCobro.CUOTA_SOCIAL)


def precio_servicio(
    db: Session,
    area: Area | None,
    predio: Predio | None,
    categoria: CategoriaParcela | None = None,
    arancel_id: str | None = None,
) -> Arancel | None:
    """Catalog price of the per-unit servicio/luz charge for ONE place (D2).

    Unlike the RECARGO carrier — which exists only to carry an operator-typed
    amount — a SERVICIO arancel is a REAL catalog price an admin edits per place,
    so it is resolved by place exactly like an AREA row: a balsa's service and a
    cabaña's service are different rows with different amounts. Utilities are
    billed per unit, so ``monto`` is the price of ONE unit and the charge does
    NOT multiply it by the member count (that is the cuota social's job).

    ``arancel_id`` is honored when it IS a SERVICIO row of this same place: that
    is what lets two apartes of one place be ticked as two independent lines
    (D3). When it is not, this place's own row wins and
    :func:`arancel_mismatch` says why (D8).

    ``None`` means "no service to charge", and it is an explicit answer, not a
    fallback: with no place there is nothing to resolve a per-place price from
    (a Windsurf socio IS its cuota social, ReQ-009), and with no row for the place
    the charge drops the line rather than inventing an amount (ReQ-003). A
    database that was migrated but never re-seeded lands here too, so it is a
    reachable state, not a defensive branch.
    """
    if area is None or predio is None:
        return None
    return resolver_monto(
        db,
        area,
        predio,
        categoria,
        arancel_id=arancel_id,
        concepto=ConceptoCobro.SERVICIO,
    )


def _lugar(area: Area | None, predio: Predio | None) -> str:
    """``area``/``predio`` as one label; ``(sin lugar)`` when either is missing."""
    if area is None or predio is None:
        return "(sin lugar)"
    return f"{area.value}/{predio.value}"


def arancel_mismatch(
    db: Session,
    arancel_id: str | None,
    area: Area | None,
    predio: Predio | None,
    concepto: ConceptoCobro,
) -> str | None:
    """Why the requested ``arancel_id`` cannot price this line (D8, ReQ-011).

    Returns the reason as a message, or ``None`` when the id asked for IS a row
    that can price the line: it exists, it carries ``concepto`` and it belongs to
    the same place. Pure diagnosis — it never picks a price, never mutates and
    never drops a line. :func:`resolver_monto` is what re-resolves; this is what
    makes that correction observable instead of silent.

    When a row DID price the line, the place's own price was charged (decision
    #671) rather than dropping it, because dropping hands out a free renewal.

    The wording is deliberately diagnostic, not a receipt: it never claims an
    amount was charged, because the re-resolve has not happened yet and may end in
    the line being dropped (ReQ-003 — the place has no such row at all). The
    amounts are on the same answer the avisos ride on, so the operator reads the
    difference between what was asked and what was charged there, and reads here
    only WHICH catalog assignment is wrong and has to be fixed.
    """
    if arancel_id is None:
        return None

    lugar = _lugar(area, predio)
    fila = db.get(Arancel, arancel_id)
    if fila is None:
        return (
            f"El arancel {arancel_id} ya no existe en el catálogo: "
            f"la línea se resuelve con la fila de {lugar} para el concepto "
            f"{concepto.value}, si existe; sin ella la línea no se cobra"
        )
    if fila.concepto != concepto:
        return (
            f"El arancel {arancel_id} está etiquetado como concepto="
            f"{fila.concepto.value} y no como {concepto.value}: "
            f"la línea se resuelve con la fila de {lugar} para el concepto "
            f"{concepto.value}, si existe; sin ella la línea no se cobra"
        )
    if area is None or predio is None:
        return (
            f"El arancel {arancel_id} no se puede imputar a un cobro sin lugar: "
            f"la membresía ancla no tiene área ni predio"
        )
    if fila.area != area or fila.predio != predio:
        return (
            f"El arancel {arancel_id} pertenece a "
            f"{fila.area.value}/{fila.predio.value} y no a {lugar}: "
            f"la línea se resuelve con la fila de {lugar} para el concepto "
            f"{concepto.value}, si existe; sin ella la línea no se cobra"
        )
    return None
