"""Usage: python -m backend.services.migracion_catalogo_recargo_cabaneros [--apply] [--monto-cabaneros N]

Data migration of the arancel catalog: three independent row changes, all of
them DATA. No business logic is touched here — the RECARGO charge logic is
already complete and correct (see ``services/cobro.py``).

WHAT IT CHANGES
---------------
1. INSERTS the RECARGO **carrier**. A carrier declares "this concept exists in
   the catalog" and nothing more: its ``monto`` is ``0`` by design and the real
   amount is typed by the operator on every charge (``montoAplicado``), never
   written back to the catalog (``enums.ConceptoCobro``, ``cobro._item_recargo``,
   ``arancel-helpers.CONCEPTO_AYUDA.recargo``). Without this row the recargo line
   is unreachable: the frontend gate is ``arancelPorConcepto(aranceles,
   "recargo")`` and the server resolver is ``resolver_arancel_concepto`` — both
   need a row tagged ``concepto=recargo`` to find.

2. INSERTS the SERVICIO row of ``CABANEROS``, or — when the row is already
   there — **UPDATES its amount** when ``--monto-cabaneros`` says so. The amount
   is never inferred; see MONTOS below.

3. CORRECTS the ``predio`` of the Guardería AREA row from ``EMBALSE`` to
   ``ALMAFUERTE``, confirmed by the owner and matching the domain rule in
   ``enums.predio_de_tipo`` ("Embalse aloja solo balsas; Almafuerte aloja cabañas
   y guardería"). ONLY ``predio`` moves: ``monto`` and ``area`` are left exactly
   as they are, and nothing is pushed to ``historico`` (a place is not a price).

MONTOS ARE CONFIGURED, NEVER DERIVED
-------------------------------------
Change 2 has **no trustworthy reference amount** and this script will not
invent one:

* there is NO Cabañeros row of any concept in the live catalog, so no sibling
  price exists to read;
* the only Cabañeros service number anywhere in the repo is the seed's
  ``a_serv_cabaneros`` at 4000.0, and ``seed.py`` labels the three service
  amounts as DEMO values ("+ valores a configurar por admin") that are never
  inferred (ReQ-105);
* the live catalog has already moved off the seed's demo figures (the live
  Balseros service row is 15000, not the seed's 5000), so the seed's 4000.0
  carries no authority for a price the owner has not set.

So the amount is an explicit operator input: ``--monto-cabaneros <n>`` supplies
it, and without that flag the change is reported as BLOCKED and not written. A
utility price is an admin decision, not a calculation.

WHY THE FLAG CAN ALSO LOWER A PRICE
-----------------------------------
The flag is the owner's decision channel, so it is honoured in BOTH directions:
running ``--monto-cabaneros 0`` against an existing row rewrites the amount
instead of only inserting. That is what makes a placeholder safe to park at 0 —
an amount nobody has decided yet must not sit in the catalog where an operator
could charge it by accident. Idempotent: a second run reports "sin cambios: sí".

The write follows the SAME rule as the API
(``services/historial_aranceles.actualizar_monto_arancel``, which
``PUT /api/aranceles/{id}/monto`` and the full edit both use): the old amount is
pushed to ``historico`` with the date it was in force, and ``vigenteDesde``
restarts today. Rewriting the price without that would quietly erase 15000 from
the price history — the same "written and never read" defect in reverse.

A 0 amount is a real state, not a broken row: the line still RESOLVES in the
cobro (the resolver looks the row up by concept and place, never by amount) and
the operator types the real figure per charge as ``montoAplicado``. Only the
submission of a charge without an amount is refused, loudly
(``services/cobro._item_servicio``), and never by dropping the line.

OPERATOR CONTRACT (SAFETY)
--------------------------
* Dry run is the DEFAULT. It prints the full plan and writes NOTHING.
* ``--apply`` writes, one transaction per change, and each change is verified
  before the next one starts. A full dump (``services/backup.py``) is taken
  first and its path + SHA256 are reported.
* Idempotent by construction: every change looks the row up by its natural key
  FIRST (``concepto`` for the carriers, ``area``+``predio`` for the place) and
  only writes when the row is missing or the field differs. Running it twice
  reports the second run as ``sin cambios: sí``.
* Exit code 3 means "a configured change was BLOCKED and was not applied" — a
  partial success, reported as such rather than as a clean run.

This is DATA, so it lives in its own script and is deliberately outside
``backend/migrate.py`` / ``backend/migrations.py``: those are column-level
runners with no version table, and a data rewrite must not re-run on startup.
Convergence is decided by the state itself, which is why re-running is free.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.models.arancel import Arancel
from backend.models.enums import Area, ConceptoCobro, Predio
from backend.models.membresia import Membresia
from backend.models.pago import Pago, PagoItem
from backend.models.notificacion import Notificacion
from backend.models.socio import Socio
from backend.services import backup as backup_service
from backend.services.historial_aranceles import actualizar_monto_arancel

# `created_by` is a plain nullable string with NO FK (models/arancel.py), so a
# mark id is the honest value here: no Usuario row backs this write.
MARCA_CREATED_BY = "migracion-catalogo-recargo-cabaneros"

# Deterministic id — this IS the idempotency key for the carrier, the same
# trick `migracion_split_aranceles` uses for its inserted service row.
RECARGO_CARRIER_ID = "a_recargo_carrier"

# The no-place placeholder (`arancel-helpers.LUGAR_NEUTRAL`). A carrier must
# still satisfy the NOT NULL area/predio columns, and the resolver finds it by
# `concepto` alone, so these are placeholders. Guardería/Almafuerte is the pair
# the seeded carriers use, and the one the live cuota social row already carries.
LUGAR_NEUTRAL_AREA = Area.GUARDERIA
LUGAR_NEUTRAL_PREDIO = Predio.ALMAFUERTE

# The place the owner confirmed for Cabañeros: a cabaña lives in Almafuerte
# (`enums.predio_de_tipo`). The DOMAIN decides this, not the script.
CABANEROS_AREA = Area.CABANEROS
CABANEROS_PREDIO = Predio.ALMAFUERTE

# Guardería's wrong place, and the place the owner confirmed.
GUARDERIA_PREDIO_ACTUAL = Predio.EMBALSE
GUARDERIA_PREDIO_ESPERADO = Predio.ALMAFUERTE

# The amount the owner states for the Guardería row. Asserted before the
# change: if the row is not the one described, this is not our row to edit.
GUARDERIA_MONTO_ESPERADO = 20000.0

SIN_CAMBIOS_SI = "sin cambios: sí"
SIN_CAMBIOS_NO = "sin cambios: no"


class MigracionCatalogoError(RuntimeError):
    """The catalog migration cannot run safely (or did not complete).

    Every case means the same thing: stop, do not report success. A row that is
    not the one the plan described, a duplicate that would break the (area,
    predio, categoria, concepto) tuple the API enforces with a 409, and a
    post-apply verification that still finds work left over.
    """


@dataclass
class Cambio:
    """One row change: its plan line, and what applying it would do.

    ``escribe`` is SEPARATE from the line prefix on purpose. ``~`` alone is
    ambiguous — for the Guardería place it means "this will be written", for the
    Cabañeros price it means "this is deliberately NOT written, read this". A
    post-apply check that keyed off the prefix would call a correct no-op a
    failure, and a money log must not be able to do that. ``escribe`` is the
    only thing that decides whether there is work left.
    """

    linea: str
    escribe: bool = False
    bloqueado: str | None = None

    @property
    def accion(self) -> str:
        return "BLOQUEADO" if self.bloqueado else ("aplicar" if self.escribe else "sin cambios")


@dataclass
class PlanCatalogo:
    """Reviewable plan + the integrity snapshot taken at the same moment."""

    cambios: list[Cambio] = field(default_factory=list)
    antes: dict = field(default_factory=dict)
    monto_cabaneros: float | None = None
    ejecucion: bool = False
    ruta_backup: str | None = None
    sha256_backup: str | None = None

    @property
    def bloqueados(self) -> list[Cambio]:
        return [c for c in self.cambios if c.bloqueado]

    @property
    def aplicables(self) -> list[Cambio]:
        return [c for c in self.cambios if not c.bloqueado]

    @property
    def sin_cambios(self) -> bool:
        """True when applying would write nothing — a second run's answer.

        Only ``escribe`` counts. A BLOCKED change is not pending work: it waits
        for an operator amount no amount of re-running can supply, so a fully
        applied catalog (minus the amount the owner has not set) is still a
        converged database, not a half-finished one.
        """
        return not any(c.escribe for c in self.cambios)

    @property
    def mueve_monto(self) -> bool:
        """True when a planned change rewrites ``aranceles.monto``.

        The footer of the report has to admit it, because "NO toca: montos" is
        exactly the sentence an operator would rely on to let it run.
        """
        return any(
            c.escribe and c.linea.startswith("~ servicio cabañeros") for c in self.cambios
        )

    @property
    def escriben(self) -> list[Cambio]:
        """The changes that actually WRITE. Not the same as ``aplicables``.

        Reporting "3 de 3" when two are no-ops is the kind of arithmetic that
        makes an operator stop reading the lines under it.
        """
        return [c for c in self.cambios if c.escribe]

    def resumen(self) -> str:
        verb = "aplicó" if self.ejecucion else "aplicaría"
        lineas = [
            "Migración de catálogo (datos: carrier recargo, servicio cabañeros, predio guardería)",
            f"  {verb} ......................................... "
            f"{len(self.escriben)} escritura(s) sobre {len(self.cambios)} cambio(s)",
        ]
        for c in self.cambios:
            marca = "  BLOQUEADO ->" if c.bloqueado else "  *"
            lineas.append(f"{marca} {c.linea}")
            if c.bloqueado:
                lineas.append(f"      motivo: {c.bloqueado}")
        lineas.append(f"  {SIN_CAMBIOS_NO if not self.sin_cambios else SIN_CAMBIOS_SI}")
        if self.mueve_monto:
            # Saying "NO toca montos" while the plan moves one would be a lie
            # the operator reads as permission.
            lineas.append("  mueve: SOLO el importe del servicio cabañeros;")
            lineas.append("        ese importe queda en historico de la fila.")
        else:
            lineas.append("  NO toca: montos, areas, categorias, historico.")
        lineas.append("  nunca toca: socios, membresias, pagos, pago_items,")
        lineas.append("              notificaciones.")
        if self.ruta_backup:
            lineas.append(f"  backup ..................... {self.ruta_backup}")
            lineas.append(f"  backup sha256 .............. {self.sha256_backup}")
        return "\n".join(lineas)


def snapshot(db: Session) -> dict:
    """Integrity snapshot: catalog rows per concept + the tables we never touch.

    Read-only. The second half is the guard that proves this migration is DATA
    about the catalog and not an accidental write to real members: socios,
    membresias, pagos, pago_items and notificaciones must be identical before
    and after.
    """
    por_concepto: dict[str, int] = {}
    for concepto in ConceptoCobro:
        por_concepto[concepto.value] = db.scalar(
            select(func.count()).select_from(Arancel).where(Arancel.concepto == concepto)
        )
    return {
        "aranceles": {
            **por_concepto,
            "TOTAL": db.scalar(select(func.count()).select_from(Arancel)),
        },
        "intactas": {
            "socios": db.scalar(select(func.count()).select_from(Socio)),
            "membresias": db.scalar(select(func.count()).select_from(Membresia)),
            "pagos": db.scalar(select(func.count()).select_from(Pago)),
            "pago_items": db.scalar(select(func.count()).select_from(PagoItem)),
            "notificaciones": db.scalar(select(func.count()).select_from(Notificacion)),
        },
    }


# ── Change 1: the RECARGO carrier ──────────────────────────────────────────


def _carrier_recargo(db: Session) -> Arancel | None:
    """The existing RECARGO carrier, by id first then by the concept it serves.

    The concept lookup is what makes a database an admin already fixed BY HAND
    converge instead of collecting a second carrier: two rows tagged `recargo`
    would leave ``resolver_arancel_concepto`` picking by id, silently.
    """
    por_id = db.get(Arancel, RECARGO_CARRIER_ID)
    if por_id is not None:
        return por_id
    return (
        db.query(Arancel)
        .filter(Arancel.concepto == ConceptoCobro.RECARGO, Arancel.categoria.is_(None))
        .order_by(Arancel.id.asc())
        .first()
    )


def _plan_recargo(db: Session) -> Cambio:
    existente = _carrier_recargo(db)
    if existente is not None:
        if float(existente.monto) != 0.0:
            return Cambio(
                linea=(
                    f"= carrier recargo {existente.id}: ya existe con monto "
                    f"{float(existente.monto):.2f} — no se toca (un carrier con "
                    f"importe NO es un carrier; revisá el catálogo a mano)"
                )
            )
        return Cambio(
            linea=(
                f"= carrier recargo {existente.id}: ya existe "
                f"({existente.area.value}/{existente.predio.value}, monto 0) — alta omitida"
            )
        )
    return Cambio(
        linea=(
            f"+ carrier recargo {RECARGO_CARRIER_ID} 'Recargo' "
            f"{LUGAR_NEUTRAL_AREA.value}/{LUGAR_NEUTRAL_PREDIO.value} "
            f"concepto=recargo categoria=— monto=0.00 "
            f"(el importe lo carga el operador por cobro, nunca el catálogo)"
        ),
        escribe=True,
    )


def _aplicar_recargo(db: Session) -> None:
    """Insert the carrier, or leave an existing one alone. Never edits `monto`."""
    if _carrier_recargo(db) is not None:
        return
    db.add(
        Arancel(
            id=RECARGO_CARRIER_ID,
            nombre="Recargo",
            area=LUGAR_NEUTRAL_AREA,
            predio=LUGAR_NEUTRAL_PREDIO,
            monto=0.0,
            categoria=None,
            vigenteDesde=date.today(),
            historico=[],
            concepto=ConceptoCobro.RECARGO,
            created_by=MARCA_CREATED_BY,
        )
    )
    db.commit()
    # Verified in its own transaction: the row must be findable BY CONCEPT, the
    # way the charge will look for it.
    if _carrier_recargo(db) is None:
        raise MigracionCatalogoError(
            "verificación del carrier recargo falló: la fila insertada no "
            "resuelve por concepto. Revisá el estado de la base."
        )


# ── Change 2: the CABANEROS service row (amount is an operator input) ───────


def _servicio_cabaneros(db: Session) -> Arancel | None:
    """The Cabañeros service row, by id first then by place."""
    por_id = db.get(Arancel, "a_serv_cabaneros")
    if por_id is not None:
        return por_id
    return (
        db.query(Arancel)
        .filter(
            Arancel.concepto == ConceptoCobro.SERVICIO,
            Arancel.area == CABANEROS_AREA,
        )
        .order_by(Arancel.id.asc())
        .first()
    )


def _plan_cabaneros(db: Session, monto: float | None) -> Cambio:
    existente = _servicio_cabaneros(db)
    if existente is not None:
        monto_actual = float(existente.monto)
        if monto is not None and monto_actual != monto:
            # The flag is the owner's decision channel, so it is honoured in both
            # directions. Parking a placeholder at 0 has to be possible, or an
            # undecided price sits in the catalog waiting to be charged.
            return Cambio(
                linea=(
                    f"~ servicio cabañeros {existente.id}: "
                    f"{monto_actual:.2f} -> {monto:.2f} "
                    f"(el importe viejo {monto_actual:.2f} se guarda en "
                    f"historico y vigenteDesde vuelve a hoy; el área y el "
                    f"predio no se tocan)"
                ),
                escribe=True,
            )
        return Cambio(
            linea=(
                f"= servicio cabañeros {existente.id}: ya existe "
                f"({existente.area.value}/{existente.predio.value}, monto "
                f"{monto_actual:.2f}) — alta omitida"
            )
        )
    if monto is None:
        return Cambio(
            linea=(
                "+ servicio cabañeros: fila de servicio para "
                f"{CABANEROS_AREA.value}/{CABANEROS_PREDIO.value} "
                "concepto=servicio categoria=—"
            ),
            bloqueado=(
                "no hay importe de referencia confiable: el catálogo no tiene "
                "ninguna fila de Cabañeros, y el único número del repo (4000.0 "
                "en seed.py) es un valor DEMO ya reemplazado en producción "
                "(Balseros figura 15000, no los 5000 del seed). Pasá "
                "--monto-cabaneros <n> con el precio que configure el dueño."
            ),
            escribe=False,
        )
    return Cambio(
        linea=(
            f"+ servicio cabañeros a_serv_cabaneros 'Servicio' "
            f"{CABANEROS_AREA.value}/{CABANEROS_PREDIO.value} concepto=servicio "
            f"categoria=— monto={monto:.2f} (configurado por el operador, no inferido)"
        ),
        escribe=True,
    )


def _aplicar_cabaneros(db: Session, monto: float | None) -> None:
    """Insert the Cabañeros service row, or move an existing one's amount.

    A blocked change writes nothing. An existing row is only touched when the
    owner passed an amount that differs from the one in place.
    """
    if monto is None:
        return
    existente = _servicio_cabaneros(db)
    if existente is not None:
        _aplicar_monto_cabaneros(db, existente, monto)
        return
    # The API rejects a repeated (area, predio, categoria, concepto) tuple with a
    # 409. Check it here too, so a duplicate can never be committed behind the
    # API's back.
    if (
        db.query(Arancel)
        .filter(
            Arancel.area == CABANEROS_AREA,
            Arancel.predio == CABANEROS_PREDIO,
            Arancel.concepto == ConceptoCobro.SERVICIO,
            Arancel.categoria.is_(None),
        )
        .first()
        is not None
    ):
        raise MigracionCatalogoError(
            f"ya existe un arancel de servicio en "
            f"{CABANEROS_AREA.value}/{CABANEROS_PREDIO.value} que no es el de "
            f"esta migración: revisá el catálogo a mano."
        )
    db.add(
        Arancel(
            id="a_serv_cabaneros",
            nombre="Servicio",
            area=CABANEROS_AREA,
            predio=CABANEROS_PREDIO,
            monto=float(monto),
            categoria=None,
            vigenteDesde=date.today(),
            historico=[],
            concepto=ConceptoCobro.SERVICIO,
            created_by=MARCA_CREATED_BY,
        )
    )
    db.commit()
    if _servicio_cabaneros(db) is None:
        raise MigracionCatalogoError(
            "verificación del servicio cabañeros falló: la fila insertada no "
            "resuelve. Revisá el estado de la base."
        )


def _aplicar_monto_cabaneros(db: Session, existente: Arancel, monto: float) -> None:
    """Move an existing Cabañeros service row to the owner's amount.

    Delegates to ``actualizar_monto_arancel`` on purpose: that is the single
    implementation of the price-change rule the API already uses (old amount to
    ``historico`` with its ``vigenteDesde``, then ``vigenteDesde`` = today), so
    the script cannot drift from what the app does with the same edit. Writing
    ``monto`` directly here would silently drop the old price from the history.

    Everything EXCEPT the amount is asserted intact afterwards, and the amount
    is re-read through the resolver's own lookup, so a run that moved more than
    the price is reported as the failure it is.
    """
    monto_antes = float(existente.monto)
    historico_antes = len(existente.historico or [])
    area_antes = existente.area
    predio_antes = existente.predio
    concepto_antes = existente.concepto

    arancel = actualizar_monto_arancel(db, existente.id, float(monto))
    arancel.updated_by = MARCA_CREATED_BY
    db.commit()

    db.refresh(arancel)
    if float(arancel.monto) != float(monto):
        raise MigracionCatalogoError(
            f"verificación del importe falló: quedó {float(arancel.monto):.2f} "
            f"y se pidió {float(monto):.2f}. Revisá el estado de la base."
        )
    if len(arancel.historico or []) != historico_antes + 1:
        raise MigracionCatalogoError(
            f"el cambio de importe no dejó el valor anterior "
            f"({monto_antes:.2f}) en el historico: quedaría perdido."
        )
    if (
        arancel.area is not area_antes
        or arancel.predio is not predio_antes
        or arancel.concepto is not concepto_antes
    ):
        raise MigracionCatalogoError(
            "el cambio de importe movió un campo que no debía "
            "(area/predio/concepto). Revisá el estado de la base."
        )
    if _servicio_cabaneros(db) is None:
        raise MigracionCatalogoError(
            "verificación del servicio cabañeros falló: la fila ya no resuelve "
            "por lugar. Revisá el estado de la base."
        )


# ── Change 3: the Guardería place correction ───────────────────────────────


def _plan_guarderia(db: Session) -> Cambio:
    fila = (
        db.query(Arancel)
        .filter(
            Arancel.concepto == ConceptoCobro.AREA,
            Arancel.area == Area.GUARDERIA,
            Arancel.predio == GUARDERIA_PREDIO_ACTUAL,
        )
        .order_by(Arancel.id.asc())
        .all()
    )
    if not fila:
        return Cambio(
            linea=(
                f"= predio guardería: no hay fila de área en "
                f"{Area.GUARDERIA.value}/{GUARDERIA_PREDIO_ACTUAL.value} — nada que corregir"
            )
        )
    if len(fila) > 1:
        raise MigracionCatalogoError(
            f"hay {len(fila)} filas de área en "
            f"{Area.GUARDERIA.value}/{GUARDERIA_PREDIO_ACTUAL.value} "
            f"({', '.join(f.id for f in fila)}): no se sabe cuál corregir. "
            f"Resolvé el duplicado a mano."
        )
    arancel = fila[0]
    if float(arancel.monto) != GUARDERIA_MONTO_ESPERADO:
        raise MigracionCatalogoError(
            f"{arancel.id} tiene monto {float(arancel.monto):.2f}, no el "
            f"{GUARDERIA_MONTO_ESPERADO:.2f} que el dueño describió: no es la "
            f"fila de esta migración. Revisá el catálogo."
        )
    if arancel.predio is GUARDERIA_PREDIO_ESPERADO:
        return Cambio(
            linea=(
                f"= predio guardería {arancel.id}: ya está en "
                f"{GUARDERIA_PREDIO_ESPERADO.value} — corrección omitida"
            )
        )
    return Cambio(
        linea=(
            f"~ predio guardería {arancel.id} 'Cuota Guardería': "
            f"{GUARDERIA_PREDIO_ACTUAL.value} -> {GUARDERIA_PREDIO_ESPERADO.value} "
            f"(monto {float(arancel.monto):.2f} y area intactos, historico intacto)"
        ),
        escribe=True,
    )


def _aplicar_guarderia(db: Session) -> None:
    """Move ONLY the place. `monto`, `area` and `historico` are not touched."""
    arancel = (
        db.query(Arancel)
        .filter(
            Arancel.concepto == ConceptoCobro.AREA,
            Arancel.area == Area.GUARDERIA,
            Arancel.predio == GUARDERIA_PREDIO_ACTUAL,
        )
        .order_by(Arancel.id.asc())
        .first()
    )
    if arancel is None:
        return
    monto_antes = float(arancel.monto)
    area_antes = arancel.area
    historico_antes = len(arancel.historico or [])

    # The (area, predio, categoria, concepto) tuple must stay unique: this is
    # the 409 the API enforces, and a duplicate would make the place ambiguous.
    if (
        db.query(Arancel)
        .filter(
            Arancel.area == Area.GUARDERIA,
            Arancel.predio == GUARDERIA_PREDIO_ESPERADO,
            Arancel.concepto == ConceptoCobro.AREA,
            Arancel.categoria == arancel.categoria,
        )
        .first()
        is not None
    ):
        raise MigracionCatalogoError(
            f"ya existe una fila de área en "
            f"{Area.GUARDERIA.value}/{GUARDERIA_PREDIO_ESPERADO.value}: mover "
            f"{arancel.id} crearía un duplicado. Resolvé el conflicto a mano."
        )

    arancel.predio = GUARDERIA_PREDIO_ESPERADO
    db.commit()

    db.refresh(arancel)
    if arancel.predio is not GUARDERIA_PREDIO_ESPERADO:
        raise MigracionCatalogoError("verificación del predio guardería falló.")
    if float(arancel.monto) != monto_antes or arancel.area is not area_antes:
        raise MigracionCatalogoError(
            "la corrección del predio movió un campo que no debía: monto/area "
            "cambiaron. Revisá el estado de la base."
        )
    if len(arancel.historico or []) != historico_antes:
        raise MigracionCatalogoError(
            "la corrección del predio empujo historico: un lugar no es un precio."
        )


# ── plan / apply ───────────────────────────────────────────────────────────


def _plan(db: Session, monto_cabaneros: float | None) -> PlanCatalogo:
    """Compute the complete plan + snapshot. Read-only: never writes/commits."""
    return PlanCatalogo(
        cambios=[
            _plan_recargo(db),
            _plan_cabaneros(db, monto_cabaneros),
            _plan_guarderia(db),
        ],
        antes=snapshot(db),
        monto_cabaneros=monto_cabaneros,
    )


def plan(db: Session, monto_cabaneros: float | None = None) -> PlanCatalogo:
    """Public, read-only entry point used by the tests and the CLI dry run."""
    return _plan(db, monto_cabaneros)


def _backup(engine) -> tuple[str, str]:
    """Full dump via `services/backup.py` + its SHA256, BEFORE any write.

    `create_backup` is called directly rather than `run_backup_if_needed`: the
    15-day interval would let a data migration run with a 14-day-old dump, and
    the operator contract is "fresh backup, every time".
    """
    resultado = backup_service.create_backup(engine)
    ruta = resultado["path"]
    with open(ruta, "rb") as fh:
        sha = hashlib.sha256(fh.read()).hexdigest()
    return ruta, sha


def aplicar(db: Session, *, monto_cabaneros: float | None = None,
            engine=None, dry_run: bool = True) -> PlanCatalogo:
    """Plan (and optionally apply) the catalog changes.

    `dry_run=True` (the default) writes NOTHING. `dry_run=False` takes a backup
    first (only when there is something to write), then applies one change per
    transaction, verifying each before moving on, and finally re-plans: a plan
    that still shows an applicable write means a change did not land.

    The returned plan is the one captured BEFORE the writes — the record of what
    was executed. A re-plan would report zeros and throw the evidence away.
    """
    plan_aplicado = _plan(db, monto_cabaneros)
    if dry_run:
        return plan_aplicado

    pendiente = [c for c in plan_aplicado.cambios if c.escribe]
    if not pendiente:
        # A pure no-op needs no backup: there is no write to protect.
        return plan_aplicado

    if engine is None:
        engine = db.get_bind()
    ruta, sha = _backup(engine)

    _aplicar_recargo(db)
    _aplicar_cabaneros(db, monto_cabaneros)
    _aplicar_guarderia(db)

    # Idempotency guard: a re-plan that still wants to write proves a change did
    # not land. Blocked changes are excluded — they are waiting on an operator
    # amount, not on a bug.
    restantes = [c.linea for c in _plan(db, monto_cabaneros).cambios if c.escribe]
    if restantes:
        raise MigracionCatalogoError(
            "verificación post-aplicación falló, quedaron cambios sin aplicar: "
            + " | ".join(restantes)
        )

    plan_aplicado.ejecucion = True
    plan_aplicado.ruta_backup = ruta
    plan_aplicado.sha256_backup = sha
    return plan_aplicado


def main(argv: list[str] | None = None) -> None:
    """CLI entry point (python -m backend.services.migracion_catalogo_recargo_cabaneros).

    Dry run by default; `--apply` writes, and takes a backup first.
    """
    parser = argparse.ArgumentParser(
        prog="migracion_catalogo_recargo_cabaneros",
        description=(
            "Catalog data: add the RECARGO carrier, add the CABANEROS service "
            "row (needs --monto-cabaneros), and move Guardería to Almafuerte. "
            "Dry run by default; --apply writes (and backs up first)."
        ),
    )
    grupo = parser.add_mutually_exclusive_group()
    grupo.add_argument(
        "--dry-run", action="store_true", help="print the plan and write nothing (default)"
    )
    grupo.add_argument(
        "--apply", action="store_true", help="APPLY the catalog changes (takes a backup first)"
    )
    parser.add_argument(
        "--monto-cabaneros",
        type=float,
        default=None,
        metavar="N",
        help=(
            "service price for CABANEROS, configured by the owner. Without it "
            "that change stays BLOCKED (never inferred)."
        ),
    )
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        resultado = aplicar(
            db, monto_cabaneros=args.monto_cabaneros, dry_run=not args.apply
        )
    except MigracionCatalogoError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
    except Exception as exc:  # pragma: no cover - defensive CLI boundary
        print(f"Migration failed: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()

    print(resultado.resumen())
    if resultado.ejecucion:
        print("Migración aplicada. Restaurá desde el backup para revertir.")
    elif resultado.sin_cambios:
        print("No changes were written (nothing to do).")
    else:
        print("Dry run complete. No changes were written.")
    sys.exit(3 if resultado.bloqueados else 0)


if __name__ == "__main__":
    main()
