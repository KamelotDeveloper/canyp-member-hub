"""Server-owned resolution of a charge into ONE ``PagoItem`` per concept (PR 5).

CBM-04, CS-03, CS-05, PAG-01 and design decisions D3/D4. The operator ticks the
concepts that apply; the SERVER decides how many items exist, what each one is
worth, what the receipt totals, and which memberships renew.

The six rules this service exists to enforce:

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
3. **The renewal set is an intersection** (D4), with ONE server-owned exception:
   only the submitted ``membresiaIds`` whose own membership concept was ticked
   renew. A recargo or servicio line therefore cannot silently renew an area
   membership, and ticking the area does not renew an untouched cuota social.
   The exception is the cuota social itself: because it is billed per UNPAID
   member (rule 6), exactly those members' cuota rows renew even when the client
   did not submit them — the unit dialog only submits area memberships, so the
   renewal set is derived server-side to keep charged == renewed. A member whose
   cuota is up to date is not billed and is not renewed.
4. **Windsurf is never double-charged** (CS-05). A Windsurf membership IS its
   cuota social, so it is classified as CUOTA_SOCIAL for charging purposes: it
   can never anchor an area line, and it renews when cuota social is ticked.
5. **A utility costs what its PLACE costs** (D2/D3). The SERVICIO line is priced
   from the anchor membership's own ``area``+``predio``, never from a global
   "the club's service price": two units in the same receipt pay two different
   amounts. ``montoAplicado`` still wins for that one receipt and never writes
   back to ``aranceles.monto`` (ReQ-010). When a submitted ``arancelId`` cannot
   price the line, the place's own row does and the reason is published in
   ``avisos`` (D8) — the line is charged, never dropped (decision #671).
6. **The cuota social is billed per UNPAID member, never per head** (CS-03 +
   the owner's rule). A unit of 4 where 1 member already paid is charged 3, not
   4: a member whose cuota is up to date is NOT charged again. "Unpaid" reuses
   the badge's own rule (:func:`backend.services.estado_socio.Vigencia`): no
   cuota row, a stopped cuota (suspendida/baja) or a vencimiento strictly before
   today. Everybody up to date -> no cuota line at all.

Amounts are frozen here at creation (AGENT.md rule 4): later arancel edits never
rewrite an existing ``PagoItem``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

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
from backend.services.estado_socio import InputsSocio, Vigencia, inputs_socio
from backend.services.resolucion import (
    arancel_mismatch,
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
    """The whole charge: its lines, its total, the memberships that renew and
    the notices the operator has to see.

    ``avisos`` is the observable half of D8/ReQ-011: it lists, in charge order,
    every requested ``arancelId`` this charge had to replace with the place's own
    row. Empty on a charge where every requested id matched.
    """

    items: tuple[ItemResuelto, ...]
    total: float
    membresias_a_renovar: tuple[str, ...]
    avisos: tuple[str, ...] = ()


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


def _miembros_unidad(db: Session, submitted: list[Membresia]) -> list[Membresia]:
    """The area memberships of the unit being managed (CS-03 multiplier input).

    The managed unit is the parcel of the first area membership in the charge.
    When no area membership travels (a solo cuota social, CS-06) the list is
    empty: the charge is per socio, not per unit. Windsurf memberships are
    excluded: they are cuota social, so charging them must not multiply the
    cuota by itself.
    """
    areas = [m for m in submitted if concepto_socio_de(m) is ConceptoMembresia.AREA]
    if not areas:
        return []
    parcela_id = areas[0].parcelaId
    if parcela_id:
        return [m for m in areas if m.parcelaId == parcela_id]
    return list(areas)


def _cuota_impaga(cuota: Vigencia | None, hoy: date) -> bool:
    """Whether a socio still OWES the cuota social, reusing the badge's rule.

    Mirrors the 🔴 branch of :func:`backend.services.estado_socio.calcular_estado_socio`
    plus one deliberate business rule the owner stated: a socio with NO cuota
    row owes it too, because nothing says it was ever created/paid. Three cases,
    no fourth: no row, a stopped cuota (``suspendida``/``baja``) or a
    ``vencimiento`` strictly before ``hoy`` (``== hoy`` is al día).
    """
    return cuota is None or cuota.parada or cuota.vencida(hoy)


def _socios_de_cuota(unidad: list[Membresia], socio_id: str) -> list[str]:
    """The socios a cuota social line bills: the unit's members, or the solo socio.

    A unit charge bills the unit (CS-03); a solo charge with no area membership
    (a cuota-social-only or Windsurf socio, CS-06) bills the charged socio once.
    Shared by the multiplier and the renewal set so both read the same people.
    """
    return [m.socioId for m in unidad] if unidad else [socio_id]


def _socios_impagos(
    inputs: dict[str, InputsSocio], socios: list[str], hoy: date
) -> list[str]:
    """The socios that still OWE the cuota, in order and de-duplicated.

    The single source of truth for "who is charged": the vigencia rule lives in
    :func:`_cuota_impaga`, so the multiplier and the renewal set can never
    disagree about who owes.
    """
    return [
        sid
        for sid in dict.fromkeys(socios)
        if _cuota_impaga(inputs.get(sid, InputsSocio(None, None)).cuota, hoy)
    ]


def _cuota_factor(
    db: Session, socio_id: str, unidad: list[Membresia], hoy: date
) -> int:
    """How many cuota social units this charge must bill (the multiplier).

    A unit charge bills ONE cuota per IMPAGO member of the unit: a member whose
    cuota is up to date is not charged again, so a unit of 4 with 1 paid bills 3
    (the owner's rule). A solo charge (no area membership — a cuota-social-only
    or Windsurf socio, CS-06) bills the charged socio once when they owe it.

    ``0`` means everybody involved is already paid: the caller emits no cuota
    line, so the operator cannot double-charge a settled member.
    """
    socios = _socios_de_cuota(unidad, socio_id)
    return len(_socios_impagos(inputs_socio(db, socios), socios, hoy))


def _cuotas_a_renovar(
    db: Session, socio_id: str, unidad: list[Membresia], hoy: date
) -> list[str]:
    """The cuota memberships of the SAME impago members the multiplier bills.

    The charge and the renewal are two halves of one rule: the cuota social is
    billed per impago member, so exactly those members' cuota rows must renew.
    Otherwise the money is collected and the ``vencimiento`` stays put, and the
    next charge bills the same member again — a double charge. A member whose
    cuota is up to date is not in the set, so their date is never touched.

    The set is derived server-side, never from the submitted ``membresiaIds``:
    the unit dialog submits only area memberships, so a client that forgets the
    cuotas cannot leave them charged but not renewed. A legacy impago socio with
    NO cuota row has nothing to renew; the missing row is a pre-existing data
    gap, not something this resolver invents.
    """
    socios = _socios_de_cuota(unidad, socio_id)
    return [
        cuota.id
        for sid in _socios_impagos(inputs_socio(db, socios), socios, hoy)
        if (cuota := cuota_de(db, sid)) is not None
    ]


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

    Utilities are billed PER UNIT and PER PLACE, so this anchor now carries the
    place the line is priced from, not just a membership to hang the
    ``PagoItem`` on: ``_item_servicio`` reads its ``area``+``predio`` to resolve
    the catalog row (D2/D3). It is the same anchor an area line would take and
    the factor stays 1 whatever the head count. When the charge carries no unit
    at all (a socio with only a cuota social membership, CS-06) the line falls
    back to the member being charged, which has no place to price from — so the
    line is dropped rather than priced from a global fallback (ReQ-009). Either
    way the anchor is bookkeeping: SERVICIO has no ``ConceptoMembresia``
    counterpart, so it renews nothing.
    """
    return _anchor_area(db, submitted, item) or _anchor_nea(db, submitted, item, socio_id)


def _item_area(
    db: Session,
    concepto: ConceptoCobro,
    anchor: Membresia,
    item,
    cliente_arancel_id: str | None,
    avisos: list[str],
) -> ItemResuelto | None:
    """Price an AREA line: catalog amount, factor 1.0, never multiplied.

    The unit's own explicit ``Membresia.arancelId`` beats the id the client
    named, because that assignment is the domain's and the client is not
    authority (D3). Whichever id was used, it only prices the line when it
    belongs to the anchor's place AND carries this concept: a re-tagged or
    out-of-place assignment is replaced by the place's real row and the reason
    is appended to ``avisos`` (D8, ReQ-011) — the line is charged at the right
    price, never dropped, because dropping it would hand out a free renewal
    (decision #671).

    ``None`` means the place has no arancel in the catalog at all: the line is
    not chargeable and is dropped rather than invented.
    """
    arancel_id = anchor.arancelId or cliente_arancel_id
    motivo = arancel_mismatch(db, arancel_id, anchor.area, anchor.predio, concepto)
    if motivo is not None:
        avisos.append(motivo)
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


def _item_cuota(db: Session, anchor: Membresia, factor: int) -> ItemResuelto | None:
    """Price the cuota social line: unit price x UNPAID member count (CS-03).

    ``factor`` is the number of members that actually owe the cuota
    (:func:`_cuota_factor`), so a unit where somebody already paid is billed for
    the rest, never for all. ``0`` (everybody up to date) yields no line: there
    is nothing to charge. The multiplier lives on the item as ``factor``, so the
    receipt explains itself: "Cuota social x3". The amount is computed here,
    never taken from the client.
    """
    if factor <= 0:
        return None
    precio = precio_cuota_social(db)
    if precio is None:
        return None
    return ItemResuelto(
        concepto=ConceptoCobro.CUOTA_SOCIAL,
        arancelId=precio.id,
        membresiaId=anchor.id,
        arancelNombre=precio.nombre,
        monto=precio.monto * factor,
        factor=float(factor),
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


def _item_servicio(
    db: Session, item, anchor: Membresia, avisos: list[str]
) -> ItemResuelto | None:
    """Price the per-unit servicio/luz line from the unit's OWN place (D2/D3).

    The catalog row is the one carrying the anchor membership's ``area``+
    ``predio``: two places of the same club bill different amounts, so there is
    no global service price to fall back on. ``montoAplicado`` is the operator's
    per-charge adjustment (a metered reading, a partial period) and it wins over
    ``monto`` for THIS receipt: it is frozen on the item and never overwrites
    ``aranceles.monto``, which stays the admin's to edit (ReQ-010).

    ``item.arancelId`` is honored when it IS a SERVICIO row of this same place —
    that is what lets two apartes of one place be ticked as two independent
    lines. When it is not, the place's own row wins and ``arancel_mismatch``
    explains the substitution in ``avisos`` (D8): charged, never dropped.

    ``None`` means this place has no service row, or the anchor has no place at
    all: the line is not chargeable and is dropped rather than priced from thin
    air (ReQ-003/009).
    """
    motivo = arancel_mismatch(
        db, item.arancelId, anchor.area, anchor.predio, ConceptoCobro.SERVICIO
    )
    if motivo is not None:
        avisos.append(motivo)
    arancel = precio_servicio(
        db,
        anchor.area,
        anchor.predio,
        _categoria_de(db, anchor),
        arancel_id=item.arancelId,
    )
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
    hoy: date | None = None,
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

    The returned ``avisos`` are the operator-visible half of D8: they name every
    submitted ``arancelId`` this charge had to replace with the place's own row.
    A charge that resolves exactly what was asked for returns an empty tuple.

    ``hoy`` is the reference date for "cuota al día" (rule 6): a cuota whose
    vencimiento is strictly before it is unpaid. It defaults to the real today,
    the same clock the socio badge reads, so the estimate the client shows and
    the amount the server charges agree.
    """
    submitted_ids = list(dict.fromkeys(membresia_ids or []))
    resueltos = resolver_items(
        db, socio_id=socio_id, items=items or [], submitted_ids=submitted_ids, hoy=hoy
    )
    if not resueltos.items and not resueltos.membresias_a_renovar:
        raise CobroVacioError("El cobro no tiene conceptos ni membresías a cobrar")
    return resueltos


def resolver_items(
    db: Session,
    *,
    socio_id: str,
    items: list,
    submitted_ids: list[str],
    hoy: date | None = None,
) -> CobroResuelto:
    """Core resolution, split out so the empty-charge guard stays readable.

    ``avisos`` is collected in item order and de-duplicated: the same bad
    ``arancelId`` submitted on two lines is ONE problem for the operator to fix,
    not two identical warnings.
    """
    submitted: list[Membresia] = []
    if submitted_ids:
        filas = db.query(Membresia).filter(Membresia.id.in_(submitted_ids)).all()
        por_id = {m.id: m for m in filas}
        submitted = [por_id[mid] for mid in submitted_ids if mid in por_id]

    hoy = hoy or date.today()
    unidades = _miembros_unidad(db, submitted)
    vistos: set[tuple[ConceptoCobro, str]] = set()
    avisos: list[str] = []
    lineas: list[ItemResuelto] = []
    ticks: set[ConceptoMembresia] = set()
    cuotas_extra: list[str] = []

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
            linea = _item_cuota(db, anchor, _cuota_factor(db, socio_id, unidades, hoy))
            if linea is not None:
                # The cuota is billed per impago member, so those SAME members'
                # cuota rows renew even when the client forgot to submit them:
                # charged == renewed, never a charge that grants no coverage.
                cuotas_extra.extend(_cuotas_a_renovar(db, socio_id, unidades, hoy))
        elif concepto is ConceptoCobro.SERVICIO:
            anchor = _anchor_servicio(db, submitted, item, socio_id)
            if anchor is None:
                raise CobroVacioError("El cobro no tiene una membresía a la que imputarse")
            linea = _item_servicio(db, item, anchor, avisos)
        elif concepto is ConceptoCobro.AREA:
            anchor = _anchor_area(db, submitted, item)
            if anchor is None:
                continue
            linea = _item_area(db, concepto, anchor, item, item.arancelId, avisos)
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
        membresias_a_renovar=tuple(
            dict.fromkeys(
                [
                    *_renovables(
                        submitted_ids, {m.id: m for m in submitted}, ticks
                    ),
                    *cuotas_extra,
                ]
            )
        ),
        avisos=tuple(dict.fromkeys(avisos)),
    )
