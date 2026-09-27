"""Usage: python -m backend.services.migracion_split_aranceles --plan [--apply | --invertir | --auditar]

Data migration: split the merged arancel into "Amarre" + "Servicio" (D6/D7).

For an ALREADY-SEEDED database (production/qas). A fresh database never needs
it: ``backend/seed.py`` already emits the split state and this migration
converges to it, so running it on a seeded database reports "sin cambios: sí".

WHAT IT CHANGES
---------------
The old ``a1 "Amarre y Servicios" $18500`` (Balseros/Embalse) priced two things
in one row. The split:

1. RENAMES ``a1`` to ``"Amarre"`` — the row is never deleted, so every
   ``pago_items.arancelId`` keeps pointing at a real arancel.
2. INSERTS the SERVICIO row for that same place, with its own CONFIGURED
   amount. The amount is never inferred from 18500: what a utility costs is an
   admin decision, not a calculation (ReQ-105).
3. COPIES the ``historico`` entries onto the new row, so the price trail is not
   truncated by the split (ReQ-014c).

``monto`` is never touched, in either direction. ``pago_items.arancelNombre`` is
never rewritten either: old receipts keep saying "Amarre y Servicios" even
though the catalog no longer has that name (ReQ-016).

OPERATOR CONTRACT (SAFETY)
--------------------------
* ``--plan`` is the DEFAULT. It prints a reviewable plan and writes nothing.
* ``--apply`` writes, and only after ``services/backup.py`` has produced a full
  dump of the database. The backup path and its SHA256 are always reported.
* ``--invertir`` is the rollback: it deletes ONLY the inserted row (refusing, by
  name, when something references it) and restores the original name.
* Both directions are idempotent by construction: the inserted row has a
  DETERMINISTIC id, so a second ``--apply`` finds it and writes nothing.

This is a DATA migration of money, so it is deliberately outside the schema
migrators: ``backend/migrate.py`` and ``backend/migrations.py`` are column-level
runners with NO version table, and neither should re-run a data rewrite on every
startup. There is nothing to mark as "already applied" — convergence is decided
by the state itself, which is exactly why re-running is free.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from dataclasses import dataclass

from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.models.arancel import Arancel
from backend.models.enums import ConceptoCobro, ConceptoMembresia
from backend.models.membresia import Membresia
from backend.models.pago import PagoItem
from backend.services import backup as backup_service
from backend.services.resolucion import arancel_mismatch

# `created_by` is a plain nullable string with NO FK (models/arancel.py), so a
# mark id is the honest value here: no Usuario row backs this write.
MARCA_CREATED_BY = "migracion-split-aranceles"

# How many concrete ids the printed plan shows. The counts are always complete;
# only the sample is truncated, and the truncation is stated.
EJEMPLOS_MAXIMOS = 10

SIN_CAMBIOS_SI = "sin cambios: sí"
SIN_CAMBIOS_NO = "sin cambios: no"

# Membership concept -> the charge concept its assigned arancel must carry.
# Both enums share their values, so the mapping is by value, not by guess.
_CONCEPTO_DE_MEMBRESIA = {
    ConceptoMembresia.AREA: ConceptoCobro.AREA,
    ConceptoMembresia.CUOTA_SOCIAL: ConceptoCobro.CUOTA_SOCIAL,
}


class MigracionSplitArancelesError(RuntimeError):
    """The split cannot run safely (or did not complete) on this database.

    Three cases share this error on purpose: the origin row exists but is not
    the merged row, the post-apply verification found work left over, and the
    inverse refused to delete a referenced row. All mean "stop, do not report
    success".
    """


@dataclass(frozen=True)
class SplitConfig:
    """One merged arancel and the two rows it splits into.

    ``servicio_id`` is deterministic on purpose: it IS the idempotency key. A
    second ``--apply`` finds that exact id and skips the insert, so the split
    cannot run twice. The seed emits the same ids, which is why a freshly
    seeded database is already converged.
    """

    origen_id: str
    nombre_original: str
    nombre_area: str
    nombre_servicio: str
    servicio_id: str
    monto_servicio: float


SPLITS: tuple[SplitConfig, ...] = (
    SplitConfig(
        origen_id="a1",
        nombre_original="Amarre y Servicios",
        nombre_area="Amarre",
        nombre_servicio="Servicio",
        servicio_id="a_serv_balseros",
        # CONFIGURED, not derived. The club sets the real utility price in the
        # catalog; this is the value a fresh seed ships (ReQ-105).
        monto_servicio=5000.0,
    ),
)


@dataclass(frozen=True)
class _Plan:
    """The narrative plan plus the one fact the verification needs."""

    lineas: tuple[str, ...]
    pendiente: bool


def auditar_mismatches(db: Session) -> list[str]:
    """List memberships whose ``arancelId`` cannot price them (D8, ReQ-011).

    This is the BEFORE half of ReQ-011, and the reason the split is safe to run
    on a live database: a membership assigned to a row re-tagged to another
    concept is exactly what the charge-time ``avisos`` report at runtime, found
    here as a query, before a single row is written.

    The ``concepto`` each membership is checked against is its OWN: an AREA
    membership must name an AREA row, a CUOTA_SOCIAL one a CUOTA_SOCIAL row.
    Nothing is mutated — this is diagnosis, and the reasons come verbatim from
    :func:`arancel_mismatch` so the pre- and post-split wording match.
    """
    filas: list[str] = ["Auditoría de asignaciones (ReQ-011)"]
    total = 0
    for m in db.query(Membresia).order_by(Membresia.id).all():
        concepto = _CONCEPTO_DE_MEMBRESIA.get(m.concepto)
        if concepto is None or not m.arancelId:
            continue
        motivo = arancel_mismatch(db, m.arancelId, m.area, m.predio, concepto)
        if motivo is not None:
            total += 1
            if total <= EJEMPLOS_MAXIMOS:
                filas.append(f"  {m.id} ({m.socioId}): {motivo}")
    if total > EJEMPLOS_MAXIMOS:
        filas.append(f"  ... y {total - EJEMPLOS_MAXIMOS} más")
    filas.append(f"  asignaciones inconsistentes: {total}")
    return filas


def _servicio_de(db: Session, origen: Arancel, cfg: SplitConfig) -> Arancel | None:
    """The SERVICIO row of ``cfg``'s place, by id first then by tuple.

    The id is checked first because it is the id this migration inserts; the
    tuple lookup is what makes a database an admin already split BY HAND
    converge instead of getting a second service row for the same place.
    """
    por_id = db.get(Arancel, cfg.servicio_id)
    if por_id is not None:
        return por_id
    return (
        db.query(Arancel)
        .filter(
            Arancel.concepto == ConceptoCobro.SERVICIO,
            Arancel.area == origen.area,
            Arancel.predio == origen.predio,
        )
        .order_by(Arancel.id.asc())
        .first()
    )


def _pagas(db: Session, arancel_id: str) -> list[PagoItem]:
    return (
        db.query(PagoItem)
        .filter(PagoItem.arancelId == arancel_id)
        .order_by(PagoItem.id)
        .all()
    )


def _muestras(ids: list[str]) -> str:
    muestra = ids[:EJEMPLOS_MAXIMOS]
    texto = ", ".join(muestra) if muestra else "—"
    if len(ids) > EJEMPLOS_MAXIMOS:
        texto += f" ... y {len(ids) - EJEMPLOS_MAXIMOS} más"
    return texto


def _plan(db: Session) -> _Plan:
    """Compute the complete plan. Read-only: never writes, never commits."""
    lineas: list[str] = auditar_mismatches(db)
    pendiente = False

    for cfg in SPLITS:
        origen = db.get(Arancel, cfg.origen_id)
        if origen is None:
            lineas.append(
                f"{cfg.origen_id}: no existe en el catálogo — nada que dividir "
                f"(normal si la base ya fue sembrada con el seed nuevo)"
            )
            continue
        if origen.concepto is not ConceptoCobro.AREA:
            raise MigracionSplitArancelesError(
                f"{cfg.origen_id} está etiquetado como concepto="
                f"{origen.concepto.value}, no como area: no es la fila combinada "
                f"que esta migración divide. Revisá el catálogo antes de seguir."
            )

        if origen.nombre == cfg.nombre_area:
            lineas.append(
                f"origen {cfg.origen_id}: ya se llama {cfg.nombre_area!r} — renombre omitido"
            )
        else:
            pendiente = True
            lineas.append(
                f"origen {cfg.origen_id}: {origen.nombre!r} -> {cfg.nombre_area!r} "
                f"(monto {origen.monto:.2f} intacto)"
            )

        existente = _servicio_de(db, origen, cfg)
        if existente is not None:
            lineas.append(
                f"servicio {existente.id}: ya existe para "
                f"{origen.area.value}/{origen.predio.value} — alta omitida "
                f"(monto {existente.monto:.2f}, no se toca)"
            )
        else:
            pendiente = True
            lineas.append(
                f"+ servicio {cfg.servicio_id} {cfg.nombre_servicio!r} "
                f"{origen.area.value}/{origen.predio.value} concepto=servicio "
                f"categoria=— monto={cfg.monto_servicio:.2f} "
                f"(configurado, nunca inferido de {origen.monto:.2f})"
            )
            lineas.append(
                f"  historico: {len(origen.historico)} entrada(s) copiada(s) a la fila nueva"
            )

        items = _pagas(db, cfg.origen_id)
        lineas.append(
            f"  pago_items que siguen apuntando a {cfg.origen_id}: {len(items)} "
            f"({_muestras([i.id for i in items])}) — arancelNombre intacto (ReQ-016)"
        )

    lineas.append(SIN_CAMBIOS_NO if pendiente else SIN_CAMBIOS_SI)
    return _Plan(lineas=tuple(lineas), pendiente=pendiente)


def plan(db: Session) -> list[str]:
    """Public, read-only entry point used by the tests and the CLI dry run."""
    return list(_plan(db).lineas)


def _backup(engine) -> tuple[str, str]:
    """Full dump via `services/backup.py` + its SHA256, BEFORE any write.

    ``create_backup`` is called directly rather than ``run_backup_if_needed``:
    the 15-day interval would let a data migration run with a 14-day-old dump,
    and the operator contract is "fresh backup, every time".
    """
    resultado = backup_service.create_backup(engine)
    ruta = resultado["path"]
    with open(ruta, "rb") as fh:
        sha = hashlib.sha256(fh.read()).hexdigest()
    return ruta, sha


def _imprimir(lineas: list[str], cierre: str, backup: tuple[str, str] | None = None) -> None:
    for linea in lineas:
        print(linea)
    if backup:
        print(f"  backup ..................... {backup[0]}")
        print(f"  backup sha256 .............. {backup[1]}")
    print(cierre)


def _aplicar(db: Session) -> None:
    """The split, in a single transaction. Never touches ``monto``."""
    for cfg in SPLITS:
        origen = db.get(Arancel, cfg.origen_id)
        if origen is None:
            continue
        if origen.nombre != cfg.nombre_area:
            origen.nombre = cfg.nombre_area
        if _servicio_de(db, origen, cfg) is not None:
            continue
        db.add(
            Arancel(
                id=cfg.servicio_id,
                nombre=cfg.nombre_servicio,
                area=origen.area,
                predio=origen.predio,
                monto=cfg.monto_servicio,
                categoria=None,
                vigenteDesde=origen.vigenteDesde,
                # A fresh list, never the same object: the two rows must not
                # share a mutable `historico` inside the session.
                historico=[dict(h) for h in origen.historico],
                concepto=ConceptoCobro.SERVICIO,
                created_by=MARCA_CREATED_BY,
            )
        )
    db.commit()


def apply(db: Session, *, dry_run: bool = True, engine=None) -> None:
    """Split every configured arancel — or, by default, only say what it would do.

    ``dry_run=True`` writes NOTHING and prints the plan. ``dry_run=False`` takes
    a full backup first, then applies every split in ONE transaction and
    re-plans afterwards: a plan that still has work means the split did not land
    completely, and that raises instead of reporting success.

    Idempotent: the inserted row's id is deterministic, so a second run finds
    it, reports the skip and writes nothing.
    """
    if dry_run:
        _imprimir(plan(db), "Dry run complete. No changes were written.")
        return

    # Captured first: this is what the operator reviewed and what we applied.
    plan_aplicado = plan(db)
    backup = _backup(engine if engine is not None else db.get_bind())
    _aplicar(db)

    if _plan(db).pendiente:
        raise MigracionSplitArancelesError(
            "verificación post-aplicación falló: el plan sigue pendiente, "
            "revisá el estado de la base antes de operar."
        )

    _imprimir(
        plan_aplicado,
        "Split aplicado. Revertilo con --invertir (o restaurando el backup).",
        backup,
    )


def _referencias(db: Session, arancel_id: str) -> tuple[list[PagoItem], list[Membresia]]:
    """What blocks a delete: the FK-backed `pago_items` and the FK-less ids."""
    pagos = _pagas(db, arancel_id)
    membresias = (
        db.query(Membresia).filter(Membresia.arancelId == arancel_id).all()
    )
    return pagos, membresias


def _motivo_bloqueo(arancel_id: str, pagos: list[PagoItem], membresias: list[Membresia]) -> str:
    return (
        f"no se puede borrar {arancel_id}: lo referencian "
        f"{len(pagos)} pago_items ({_muestras([i.id for i in pagos])}) y "
        f"{len(membresias)} membresias ({_muestras([m.id for m in membresias])}). "
        f"Desasignalos primero."
    )


def _plan_invertir(db: Session) -> tuple[list[str], bool]:
    """What the inverse would undo. Read-only, and speaks about DELETING.

    It deliberately does not reuse :func:`_plan`: that one describes the SPLIT,
    so printing it on a revert run would claim it was about to rename a row and
    insert a service row — the exact opposite of what a rollback does. A money
    log that misdescribes its own writes is worse than no log.
    """
    lineas: list[str] = auditar_mismatches(db)
    pendiente = False

    for cfg in SPLITS:
        origen = db.get(Arancel, cfg.origen_id)
        if origen is None:
            lineas.append(f"origen {cfg.origen_id}: no existe — nada que revertir")
        elif origen.nombre == cfg.nombre_original:
            lineas.append(
                f"origen {cfg.origen_id}: ya se llama {cfg.nombre_original!r} — renombre omitido"
            )
        else:
            pendiente = True
            lineas.append(
                f"origen {cfg.origen_id}: {origen.nombre!r} -> {cfg.nombre_original!r} "
                f"(nombre restaurado, monto {origen.monto:.2f} intacto)"
            )

        servicio = db.get(Arancel, cfg.servicio_id)
        if servicio is None:
            lineas.append(f"- borrado {cfg.servicio_id}: no existe — nada que revertir")
            continue
        pagos, membresias = _referencias(db, cfg.servicio_id)
        if pagos or membresias:
            pendiente = True
            lineas.append(f"- borrado {cfg.servicio_id}: BLOQUEADO — {_motivo_bloqueo(cfg.servicio_id, pagos, membresias)}")
        else:
            pendiente = True
            lineas.append(
                f"- borrado {cfg.servicio_id} {servicio.nombre!r} "
                f"{servicio.area.value}/{servicio.predio.value} "
                f"(sin referencias; ni su monto ni el de {cfg.origen_id} se tocan)"
            )

    lineas.append(SIN_CAMBIOS_NO if pendiente else SIN_CAMBIOS_SI)
    return lineas, pendiente


def _invertir(db: Session) -> None:
    """Delete ONLY the inserted row and restore the original name."""
    for cfg in SPLITS:
        origen = db.get(Arancel, cfg.origen_id)
        if origen is not None and origen.nombre != cfg.nombre_original:
            origen.nombre = cfg.nombre_original

        servicio = db.get(Arancel, cfg.servicio_id)
        if servicio is None:
            continue
        # Same pre-check as D5: refuse BY NAME instead of blowing up the FK.
        # `Membresia.arancelId` has no FK, so it is counted too — a dangling id
        # there is invisible to the database and just as broken.
        pagos, membresias = _referencias(db, cfg.servicio_id)
        if pagos or membresias:
            db.rollback()
            raise MigracionSplitArancelesError(
                _motivo_bloqueo(cfg.servicio_id, pagos, membresias)
            )
        db.delete(servicio)
    db.commit()


def invertir(db: Session, *, dry_run: bool = True, engine=None) -> None:
    """Undo the split — or, by default, only say what it would undo.

    The inverse is idempotent by construction: the row it deletes is gone after
    the first run, so a second run has nothing to do and leaves the restored
    name alone.
    """
    if dry_run:
        lineas, _ = _plan_invertir(db)
        _imprimir(lineas, "Dry run complete. No changes were written.")
        return

    plan_aplicado, _ = _plan_invertir(db)
    backup = _backup(engine if engine is not None else db.get_bind())
    _invertir(db)
    _imprimir(plan_aplicado, "Split revertido.", backup)


def main(argv: list[str] | None = None) -> None:
    """CLI entry point (python -m backend.services.migracion_split_aranceles).

    ``--plan`` is the default: ``--apply`` or ``--invertir`` are required to
    write, and both take a backup first (module docstring, OPERATOR CONTRACT).
    """
    parser = argparse.ArgumentParser(
        prog="migracion_split_aranceles",
        description=(
            "Split the merged 'Amarre y Servicios' arancel into 'Amarre' + "
            "'Servicio'. Plan by default; --apply / --invertir write (and back up first)."
        ),
    )
    grupo = parser.add_mutually_exclusive_group()
    grupo.add_argument(
        "--plan", action="store_true", help="print the plan and write nothing (default)"
    )
    grupo.add_argument(
        "--apply", action="store_true", help="APPLY the split (takes a backup first)"
    )
    grupo.add_argument(
        "--invertir", action="store_true", help="REVERT the split (takes a backup first)"
    )
    grupo.add_argument(
        "--auditar", action="store_true", help="print only the ReQ-011 audit"
    )
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        if args.auditar:
            _imprimir(auditar_mismatches(db), "Auditoría completa. No changes were written.")
        elif args.apply:
            apply(db, dry_run=False)
        elif args.invertir:
            invertir(db, dry_run=False)
        else:
            _imprimir(plan(db), "Dry run complete. No changes were written.")
    except MigracionSplitArancelesError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
    except Exception as exc:  # pragma: no cover - defensive CLI boundary
        print(f"Migration failed: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()
    sys.exit(0)


if __name__ == "__main__":
    main()
