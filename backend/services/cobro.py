"""Server-owned resolution of a charge into ONE ``PagoItem`` per concept (PR 5).

CBM-04, CS-03, CS-05, PAG-01 and design decisions D3/D4. The operator ticks the
concepts that apply; the SERVER decides how many items exist, what each one is
worth, what the receipt totals, and which memberships renew.

The four rules this service exists to enforce:

1. **One item per ticked concept** (CBM-04). A balsa with 4 members is ONE
   area line, not four — the area arancel is fixed per unit (CS-03). Two
   *different* units in the same charge (two cabanas of a different size) are
   still two lines, because they are two different catalog rows. So the
   identity of a line is ``(concepto, arancel)``, not ``(concepto)`` alone.
2. **The server owns every amount** (D3). ``Pago.total`` is the sum of the
   resolved items and a client-sent ``total`` is never authority. Two concepts
   are deliberate, documented exceptions on the ITEM's amount, both of which the
   operator types at charge time and neither of which ever writes to
   ``aranceles.monto``: the **recargo**, because ARA-01 defines its arancel as a
   carrier with no catalog amount at all, and the **servicio** (decision #646),
   whose arancel carries a real admin-editable price that the operator may
   adjust for one charge. Both are validated and then summed by the server like
   any other line. What the server never delegates is *which arancel* prices a
   line and *what the receipt adds up to*.
3. **The renewal set is an intersection** (D4): only the submitted
   ``membresiaIds`` whose own membership concept was ticked renew. A recargo or
   servicio line therefore cannot silently renew an area membership, and ticking
   the area does not renew an untouched cuota social.
4. **Windsurf is never double-charged** (CS-05). A Windsurf membership IS its
   cuota social, so it is classified as CUOTA_SOCIAL for charging purposes: it
   can never anchor an area line, and it renews when cuota social is ticked.

Amounts are frozen here at creation (AGENT.md rule 4): later arancel edits never
rewrite an existing ``PagoItem``.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from backend.models.arancel import Arancel
from backend.models.enums import (
    Area,
    ConceptoCobro,
    ConceptoMembresia,
    RolMembresia,
)
from backend.models.membresia import Membresia
from backend.models.parcela import Parcela
from backend.services.cuota_social import cuota_de
from backend.services.resolucion import (
    precio_cuota_social,
    precio_servicio,
    resolver_arancel_concepto,
    resolver_monto,
)


class CobroVacioError(ValueError):
    """The submitted charge resolves to nothing chargeable -> HTTP 422."""


@dataclass(frozen=True)
class ItemResuelto:
    """One line of the receipt, fully priced and frozen by the server."""

    concepto: ConceptoCobro
    arancelId: str
    membresiaId: str
    arancelNombre: str
    monto: float
    factor: float


@dataclass(frozen=True)
class CobroResuelto:
    """The whole charge: its lines, its total and the memberships that renew."""

    items: tuple[ItemResuelto, ...]
    total: float
    membresias_a_renovar: tuple[str, ...]


def concepto_socio_de(m: Membresia) -> ConceptoMembresia:
    """The membership concept a Windsurf membership counts as (CS-05).

    A Windsurf membership has no separate area arancel to pay — it *is* the
    cuota social. Classifying it as CUOTA_SOCIAL here is what keeps the charge
    from growing a second line for the same socio.
    """
    if m.area is Area.WINDSURF:
        return ConceptoMembresia.CUOTA_SOCIAL
    return m.concepto


def _categoria_de(db: Session, m: Membresia):
    """Categoria of the parcel a membership belongs to, or None."""
    if not m.parcelaId:
        return None
    parcela = db.get(Parcela, m.parcelaId)
    return parcela.categoria if parcela is not None else None


def _unidad(db: Session, submitted: list[Membresia]) -> set[str]:
    """Ids of the members of the unit being managed (CS-03 multiplier input).

    The managed unit is the parcel of the first area membership in the charge;
    when no area line is charged (a solo cuota social, CS-06) every submitted
    area membership counts. Windsurf memberships are excluded: they are cuota
    social, so charging them must not multiply the cuota by itself.
    """
    areas = [m for m in submitted if concepto_socio_de(m) is ConceptoMembresia.AREA]
    if not areas:
        return set()
    parcela_id = areas[0].parcelaId
    if parcela_id:
        return {m.id for m in areas if m.parcelaId == parcela_id}
    return {m.id for m in areas}


def _concepto_de(db: Session, item) -> ConceptoCobro:
    """The concept of a submitted item: the client's, else the arancel's own tag.

    A client that states no concept gets the catalog row's own tag, so pointing
    an item at the RECARGO carrier is enough to charge a recargo — the frontend
    does not have to know the concept vocabulary to avoid a wrong line.
    """
    if item.concepto is not None:
        return item.concepto
    arancel = db.get(Arancel, item.arancelId) if item.arancelId else None
    return arancel.concepto if arancel is not None else ConceptoCobro.AREA


def _anchor_area(
    db: Session, submitted: list[Membresia], item
) -> Membresia | None:
    """The membership an area line hangs on.

    ``PagoItem.membresiaId`` is NOT NULL, so every line needs a real anchor.
    An item that names one of the submitted memberships is anchored to THAT row,
    because a charge covering two units has two different areas and each line
    must be priced from its own parcel. Only a legacy item that names no
    submitted membership falls back to the unit's Titular — the same row the
    receipt has always named.
    """
    por_id = {m.id: m for m in submitted}
    propio = por_id.get(item.membresiaId)
    if propio is not None and concepto_socio_de(propio) is ConceptoMembresia.AREA:
        return propio
    areas = [m for m in submitted if concepto_socio_de(m) is ConceptoMembresia.AREA]
    for m in areas:
        if m.rol is RolMembresia.TITULAR:
            return m
    return areas[0] if areas else None


def _anchor_cuota(db: Session, socio_id: str, submitted: list[Membresia]) -> Membresia | None:
    """The cuota social line is anchored to the socio's own cuota row (DECISION B).

    A person pays for their own cuota social, not for a neighbour's: the factor
    expresses the unit size, the row the amount is frozen against is the
    titular's. A submitted cuota membership of the same socio is the fallback
    for a database that has not been backfilled yet.
    """
    cuota = cuota_de(db, socio_id)
    if cuota is not None:
        return cuota
    for m in submitted:
        if concepto_socio_de(m) is ConceptoMembresia.CUOTA_SOCIAL:
            return m
    return None


def _anchor_nea(db: Session, submitted: list[Membresia], item, socio_id: str) -> Membresia | None:
    """Fallback anchor for a concept that renews nothing: the member being charged.

    Used by the recargo, and by the servicio when the charge carries no unit at
    all. ``PagoItem.membresiaId`` is NOT NULL, so the line still points at a real
    membership. It is a bookkeeping anchor ONLY — D4 guarantees it renews
    nothing, which is exactly what ``_renovables`` below enforces.
    """
    if submitted:
        return submitted[0]
    propio = db.get(Membresia, item.membresiaId)
    if propio is not None:
        return propio
    return (
        db.query(Membresia)
        .filter(Membresia.socioId == socio_id)
        .order_by(Membresia.id.asc())
        .first()
    )


def _anchor_servicio(
    db: Session, submitted: list[Membresia], item, socio_id: str
) -> Membresia | None:
    """Anchor for the servicio line: the membership of the unit being charged.

    Utilities are billed PER UNIT, so the line hangs on the unit — the same
    anchor an area line would take — and its factor stays 1 whatever the head
    count. When the charge carries no unit at all (a socio with only a cuota
    social membership, CS-06) the line falls back to the member being charged,
    which keeps ``PagoItem.membresiaId`` satisfiable. Either way the anchor is
    bookkeeping: SERVICIO has no ``ConceptoMembresia`` counterpart, so it renews
    nothing.
    """
    return _anchor_area(db, submitted, item) or _anchor_nea(db, submitted, item, socio_id)


def _item_area(
    db: Session, concepto: ConceptoCobro, anchor: Membresia, item, cliente_arancel_id: str | None
) -> ItemResuelto | None:
    """Price an AREA line: catalog amount, factor 1.0, never multiplied.

    The unit's own explicit ``Membresia.arancelId`` beats the id the client
    named, because that assignment is the domain's and the client is not
    authority (D3). ``None`` means the area has no arancel in the catalog: the
    line is not chargeable and is dropped rather than invented.
    """
    arancel_id = anchor.arancelId or cliente_arancel_id
    arancel = resolver_monto(
        db,
        anchor.area,
        anchor.predio,
        _categoria_de(db, anchor),
        arancel_id=arancel_id,
        concepto=concepto,
    )
    if arancel is None:
        return None
    return ItemResuelto(
        concepto=concepto,
        arancelId=arancel.id,
        membresiaId=anchor.id,
        arancelNombre=arancel.nombre,
        monto=arancel.monto,
        factor=1.0,
    )


def _item_cuota(db: Session, anchor: Membresia, miembros: int) -> ItemResuelto | None:
    """Price the cuota social line: unit price x member count (CS-03).

    The multiplier lives on the item as ``factor``, so the receipt explains
    itself: "Cuota social x4". The amount is computed here, never taken from
    the client.
    """
    precio = precio_cuota_social(db)
    if precio is None:
        return None
    factor = float(max(1, miembros))
    return ItemResuelto(
        concepto=ConceptoCobro.CUOTA_SOCIAL,
        arancelId=precio.id,
        membresiaId=anchor.id,
        arancelNombre=precio.nombre,
        monto=precio.monto * factor,
        factor=factor,
    )


def _item_recargo(db: Session, item, anchor: Membresia) -> ItemResuelto:
    """Price the recargo line from the operator's figure (CBM-03, ARA-01).

    A RECARGO arancel is a carrier: its ``monto`` is 0 by design and the amount
    is typed per charge, so this is the ONE place a client figure is read. It
    is validated, and it is written to the item — never back to
    ``aranceles.monto``, which stays pristine.

    The carrier row is resolved BY CONCEPT, never from ``item.arancelId``: the
    client's id is not authority (D3) and it could otherwise point the recargo
    at an arbitrary catalog row — or at one that does not exist at all, which
    would fail later as a foreign key. The frozen name is the carrier's own.
    """
    monto = item.montoAplicado
    if monto is None or monto <= 0:
        raise CobroVacioError(
            "El recargo necesita un monto mayor a 0 para poder cobrarse"
        )
    carrier = resolver_arancel_concepto(db, ConceptoCobro.RECARGO)
    if carrier is None:
        raise CobroVacioError("El catálogo no tiene un arancel de recargo configurado")
    return ItemResuelto(
        concepto=ConceptoCobro.RECARGO,
        arancelId=carrier.id,
        membresiaId=anchor.id,
        arancelNombre=carrier.nombre,
        monto=float(monto),
        factor=1.0,
    )


def _item_servicio(db: Session, item, anchor: Membresia) -> ItemResuelto | None:
    """Price the per-unit servicio/luz line from the catalog (decision #646).

    The amount is the catalog row's ``monto`` — admin-editable, never derived
    from the area or the member count — which the operator may adjust for THIS
    charge by sending a different ``montoAplicado`` (a metered reading, a partial
    period). Like the recargo, the adjusted figure is validated, is written only
    to the item, and never overwrites ``aranceles.monto``.

    ``None`` means the catalog has no SERVICIO row at all: the line is not
    chargeable and is dropped rather than priced from thin air.
    """
    arancel = precio_servicio(db)
    if arancel is None:
        return None
    monto = arancel.monto if item.montoAplicado is None else item.montoAplicado
    if monto <= 0:
        raise CobroVacioError(
            "El servicio necesita un monto mayor a 0 para poder cobrarse"
        )
    return ItemResuelto(
        concepto=ConceptoCobro.SERVICIO,
        arancelId=arancel.id,
        membresiaId=anchor.id,
        arancelNombre=arancel.nombre,
        monto=float(monto),
        factor=1.0,
    )


def _renovables(
    submitted_ids: list[str], rows: dict[str, Membresia], ticks: set[ConceptoMembresia]
) -> list[str]:
    """D4: submitted memberships whose own concept was ticked, in submitted order.

    A recargo-only or servicio-only charge renews NOTHING here even though it
    carries a ``membresiaId``: that id is a bookkeeping anchor, never an
    instruction.
    """
    return [
        mid
        for mid in submitted_ids
        if mid in rows and concepto_socio_de(rows[mid]) in ticks
    ]


def resolver_cobro(
    db: Session,
    *,
    socio_id: str,
    items: list | None,
    membresia_ids: list[str] | None,
) -> CobroResuelto:
    """Resolve a submitted charge into items, a total and a renewal set.

    ``items`` are the client-sent ``PagoItemCreate`` rows (duck-typed: only
    ``arancelId``/``membresiaId``/``montoAplicado``/``concepto`` are read) and
    ``membresia_ids`` the memberships the operator wants renewed. An item states
    the concept it ticks; when it does not, the arancel's own ``concepto`` tag
    decides, which is how a recargo or a servicio line is charged without the
    client knowing the vocabulary. When no ``membresiaIds`` is submitted the
    items' own memberships are the submitted set, which keeps the historical
    items-only charge working while still passing through the same concept
    filter.

    Raises :class:`CobroVacioError` when the charge ends up with nothing to bill
    and nothing to renew — the 422 the spec requires for an empty charge
    (PAG-01). A single concept whose catalog row is missing is dropped, not
    fatal, so a partially-catalogued charge still registers what it can.
    """
    submitted_ids = list(dict.fromkeys(membresia_ids or []))
    resueltos = resolver_items(
        db, socio_id=socio_id, items=items or [], submitted_ids=submitted_ids
    )
    if not resueltos.items and not resueltos.membresias_a_renovar:
        raise CobroVacioError("El cobro no tiene conceptos ni membresías a cobrar")
    return resueltos


def resolver_items(
    db: Session, *, socio_id: str, items: list, submitted_ids: list[str]
) -> CobroResuelto:
    """Core resolution, split out so the empty-charge guard stays readable."""
    submitted: list[Membresia] = []
    if submitted_ids:
        filas = db.query(Membresia).filter(Membresia.id.in_(submitted_ids)).all()
        por_id = {m.id: m for m in filas}
        submitted = [por_id[mid] for mid in submitted_ids if mid in por_id]

    unidades = _unidad(db, submitted)
    vistos: set[tuple[ConceptoCobro, str]] = set()
    lineas: list[ItemResuelto] = []
    ticks: set[ConceptoMembresia] = set()

    if not items:
        # A charge with no items submits memberships and nothing else: nothing
        # was ticked, so the submitted list IS the instruction and D4's
        # intersection has nothing to intersect with. Renewing what was asked
        # for is the only reading that keeps this historical flow working.
        ticks = {concepto_socio_de(m) for m in submitted}
    for item in items:
        concepto = _concepto_de(db, item)

        if concepto is ConceptoCobro.CUOTA_SOCIAL:
            anchor = _anchor_cuota(db, socio_id, submitted)
            if anchor is None:
                raise CobroVacioError(
                    "El socio no tiene membresía de cuota social para cobrar"
                )
            linea = _item_cuota(db, anchor, len(unidades))
        elif concepto is ConceptoCobro.SERVICIO:
            anchor = _anchor_servicio(db, submitted, item, socio_id)
            if anchor is None:
                raise CobroVacioError("El cobro no tiene una membresía a la que imputarse")
            linea = _item_servicio(db, item, anchor)
        elif concepto is ConceptoCobro.AREA:
            anchor = _anchor_area(db, submitted, item)
            if anchor is None:
                continue
            linea = _item_area(db, concepto, anchor, item, item.arancelId)
        else:
            anchor = _anchor_nea(db, submitted, item, socio_id)
            if anchor is None:
                raise CobroVacioError("El cobro no tiene una membresía a la que imputarse")
            linea = _item_recargo(db, item, anchor)

        if linea is None:
            # Nothing was billed for this concept (its catalog row is missing), so
            # it must NOT renew anything: ticking a line the server could not
            # price would hand out a free renewal. The charge is still allowed to
            # go through with the concepts it could resolve.
            continue
        clave = (linea.concepto, linea.arancelId)
        if clave in vistos:
            continue
        vistos.add(clave)
        lineas.append(linea)

        # A concept renews only when its line was actually produced and kept.
        # ConceptoCobro is a superset of ConceptoMembresia (it also carries the
        # RECARGO carrier and the SERVICIO price), so a concepto with no
        # membership counterpart simply renews nothing.
        if concepto.name in ConceptoMembresia.__members__:
            ticks.add(ConceptoMembresia[concepto.name])

    return CobroResuelto(
        items=tuple(lineas),
        total=sum(linea.monto for linea in lineas),
        membresias_a_renovar=tuple(_renovables(submitted_ids, {m.id: m for m in submitted}, ticks)),
    )
