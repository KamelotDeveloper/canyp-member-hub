"""Resolution of the catalog arancel that prices a charge (RQ 13, PR 5 D3).

Design #421 D3: a categoria-specific arancel wins; otherwise fall back to the
categoria IS NULL (catch-all) row for the same area+predio; otherwise None.

PR 5 adds the CONCEPT dimension (PAG-01): every lookup is now scoped by
``Arancel.concepto``, so a concept can never be priced by another concept's
row. That matters because the non-place rows (RECARGO, CUOTA_SOCIAL, SERVICIO)
store placeholder area/predio values — they are found BY CONCEPT ONLY,
never by area+predio, and never by an explicit id handed in by a client that
named a row of the wrong concept.
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

    Priority:
      0. explicit arancel_id (when given, the Arancel still exists AND it is
         tagged with the requested concept)
      1. exact categoria match (when categoria is not None)
      2. catch-all row where categoria IS NULL for the same area+predio
      3. None

    ``concepto`` defaults to AREA, which is every pre-PR-5 call site's intent.
    """
    if arancel_id is not None:
        directo = (
            db.query(Arancel)
            .filter(Arancel.id == arancel_id, Arancel.concepto == concepto)
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


def precio_servicio(db: Session) -> Arancel | None:
    """Catalog price of the per-unit servicio/luz charge (decision #646).

    Unlike the RECARGO carrier — which exists only to carry an operator-typed
    amount — a SERVICIO arancel is a REAL catalog price that an admin edits, and
    it is resolved by concept exactly like the cuota social unit price. Utilities
    are billed per unit, so ``monto`` is the price of ONE unit and the charge
    does NOT multiply it by the member count (that is the cuota social's job).

    Returns ``None`` when the catalog has no SERVICIO row: the charge then drops
    the line rather than inventing an amount. A database that was migrated but
    never re-seeded has no such row, so this is a reachable state, not a
    defensive branch.
    """
    return resolver_arancel_concepto(db, ConceptoCobro.SERVICIO)
