"""Usage: python -m backend.services.reparacion_cuota_social [--apply]

Focused data repair: give every loaded socio the ``CUOTA_SOCIAL`` membership
they should always have had, and nothing else.

``crear_cuota_social`` creates that row on socio creation, bulk import and
unit-member add, so a healthy database has one per socio. A database that
predates the change (or where a row was deleted by hand) can still hold socios
with no cuota row: the cobro de unidad counts them as impago (nothing says they
paid) and now repairs them at charge time, but the repair is only paid for by
people who get charged. This tool closes the gap for the whole carga at once.

This is NOT ``migracion_cuota_social``. That migration's apply runs TWO phases:
it backfills the missing cuotas AND projects EVERY ``membresia.vencimiento``
onto the 10->10 cycle. The projection is a separate, irreversible data change
that this repair deliberately does NOT want: it only creates the missing rows
and leaves every existing date (and every payment) exactly where it is.

OPERATOR CONTRACT (SAFETY)
--------------------------
* ``--dry-run`` is the DEFAULT. It prints a reviewable plan — how many socios
  lack a cuota and which — and writes nothing.
* ``--apply`` writes, and only after ``services/backup.py`` has produced a full
  dump of the database. The backup path and its SHA256 are always reported, so
  the handoff carries the evidence. When there is nothing to repair it is a
  no-op and takes no backup (there is no write to protect).
* Idempotent: the write goes through ``crear_cuota_social``, so a second run
  finds every row and reports zero changes.
* NOTHING here touches ``pagos`` or ``pago_items``, and no existing
  ``vencimiento`` is altered — only new cuota rows are inserted.

This module runs AFTER ``python -m backend.migrate`` (which adds and backfills
``membresias.concepto``); it refuses to run without that column rather than
silently degrading.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from dataclasses import dataclass, field, replace

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.models.socio import Socio
from backend.services import backup as backup_service
from backend.services.cuota_social import crear_cuota_social, cuota_de

# How many concrete socio ids the printed plan shows. The count is always
# complete; only the sample is truncated, and the truncation is stated.
EJEMPLOS_MAXIMOS = 20


class ReparacionCuotaSocialError(RuntimeError):
    """The repair cannot run safely (or did not complete) on this database.

    Two cases share this error on purpose: the schema is not ready (see the
    module docstring) and the post-apply verification still found socios without
    a cuota. Both mean "stop, do not report success".
    """


@dataclass(frozen=True)
class PlanReparacion:
    """Reviewable, complete summary of what the repair would do."""

    socios: int
    socios_sin_cuota: int
    cuota_a_crear: tuple[str, ...] = field(default_factory=tuple)
    ejecucion: bool = False
    ruta_backup: str | None = None
    sha256_backup: str | None = None

    @property
    def sin_cambios(self) -> bool:
        """True when a second run has nothing left to do (idempotency)."""
        return not self.cuota_a_crear

    def resumen(self) -> str:
        """The human-readable, reviewable plan printed by the CLI."""
        verb = "escribió" if self.ejecucion else "escribiría"
        lineas = [
            "Reparación de cuota social (socios sin fila)",
            f"  socios totales .............. {self.socios}",
            f"  socios sin cuota social .... {self.socios_sin_cuota}",
        ]
        if self.cuota_a_crear:
            muestra = self.cuota_a_crear[:EJEMPLOS_MAXIMOS]
            lineas.append(f"  {verb} cuota social para: {', '.join(muestra)}")
            if len(self.cuota_a_crear) > EJEMPLOS_MAXIMOS:
                lineas.append(
                    f"    ... y {len(self.cuota_a_crear) - EJEMPLOS_MAXIMOS} más"
                )
        else:
            lineas.append("  filas CUOTA_SOCIAL a crear . 0")
        if self.ruta_backup:
            lineas.append(f"  backup ..................... {self.ruta_backup}")
            lineas.append(f"  backup sha256 .............. {self.sha256_backup}")
        return "\n".join(lineas)


def _exigir_columna_concepto(db: Session) -> None:
    """Fail loudly when `migrate.py` has not run yet.

    `crear_cuota_social` writes `concepto` and `cuota_de` reads it; on a database
    that predates the column the ORM would raise an opaque `OperationalError`.
    """
    columnas = {c["name"] for c in inspect(db.get_bind()).get_columns("membresias")}
    if "concepto" not in columnas:
        raise ReparacionCuotaSocialError(
            "membresias.concepto no existe: corré 'python -m backend.migrate' "
            "primero (recrear area/predio -> agregar concepto -> backfill)."
        )


def _plan(db: Session) -> PlanReparacion:
    """Compute the complete plan. Read-only: never writes, never commits."""
    _exigir_columna_concepto(db)

    socios = db.scalars(select(Socio).order_by(Socio.id)).all()
    cuota_a_crear = [socio.id for socio in socios if cuota_de(db, socio.id) is None]

    return PlanReparacion(
        socios=len(socios),
        socios_sin_cuota=len(cuota_a_crear),
        cuota_a_crear=tuple(cuota_a_crear),
    )


def plan(db: Session) -> PlanReparacion:
    """Public, read-only entry point used by the tests and the CLI dry run."""
    return _plan(db)


def _aplicar(db: Session) -> None:
    """Insert the missing cuota rows in a single transaction.

    Goes through the runtime service (never a hand-built row), so the plan and
    the apply cannot drift and `id` generation / the flush live in one place.
    It deliberately does NOT project any date: only new rows are inserted.
    """
    for socio in db.scalars(select(Socio).order_by(Socio.id)).all():
        if cuota_de(db, socio.id) is None:
            crear_cuota_social(db, socio)
    db.commit()


def _backup(engine) -> tuple[str, str]:
    """Full dump via `services/backup.py` + its SHA256, BEFORE any write.

    ``create_backup`` is called directly rather than ``run_backup_if_needed``:
    the 15-day interval would let a destructive repair run with a 14-day-old
    dump, and the operator contract is "fresh backup, every time".
    """
    resultado = backup_service.create_backup(engine)
    ruta = resultado["path"]
    with open(ruta, "rb") as fh:
        sha = hashlib.sha256(fh.read()).hexdigest()
    return ruta, sha


def reparar(db: Session, *, dry_run: bool = True, engine=None) -> PlanReparacion:
    """Plan (and optionally apply) the repair.

    ``dry_run=True`` (the default) writes NOTHING: it returns the same plan the
    apply path would execute. ``dry_run=False`` takes a backup first (only when
    there is something to insert), applies the repair in one transaction and
    reports the backup evidence.

    The returned plan on apply is the one captured **before** the writes, so it
    is the record of what was executed. Re-planning afterwards would report
    zeros and throw away the only evidence the handoff carries.
    """
    if dry_run:
        return _plan(db)

    # Captured first: this is what the operator reviewed and what we applied.
    plan_aplicado = _plan(db)

    # Nothing to insert: a pure no-op needs no backup (no write to protect).
    if plan_aplicado.sin_cambios:
        return plan_aplicado

    if engine is None:
        engine = db.get_bind()
    ruta, sha = _backup(engine)
    _aplicar(db)

    # Idempotency guard: an empty re-plan proves every row landed.
    if not _plan(db).sin_cambios:
        raise ReparacionCuotaSocialError(
            "verificación post-aplicación falló: quedan socios sin cuota, "
            "revisá el estado de la base antes de operar."
        )

    return replace(
        plan_aplicado, ejecucion=True, ruta_backup=ruta, sha256_backup=sha
    )


def main(argv: list[str] | None = None) -> None:
    """CLI entry point (python -m backend.services.reparacion_cuota_social).

    Dry run by default. ``--apply`` is required to write, and it always takes a
    backup first (module docstring, "OPERATOR CONTRACT").
    """
    parser = argparse.ArgumentParser(
        prog="reparacion_cuota_social",
        description=(
            "Create the CUOTA_SOCIAL row of every socio that lacks one. "
            "Never touches vencimientos or pagos. Dry run by default; "
            "--apply writes (and backs up first)."
        ),
    )
    grupo = parser.add_mutually_exclusive_group()
    grupo.add_argument(
        "--dry-run",
        action="store_true",
        help="print the plan and write nothing (default)",
    )
    grupo.add_argument(
        "--apply",
        action="store_true",
        help="APPLY the repair to the live database (takes a backup first)",
    )
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        resultado = reparar(db, dry_run=not args.apply, engine=None)
    except ReparacionCuotaSocialError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
    except Exception as exc:  # pragma: no cover - defensive CLI boundary
        print(f"Repair failed: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()

    print(resultado.resumen())
    if resultado.ejecucion:
        print("Reparación aplicada. Restaurá desde el backup para revertir.")
    elif resultado.sin_cambios:
        print("No changes were written (nothing to repair).")
    else:
        print("Dry run complete. No changes were written.")
    sys.exit(0)


if __name__ == "__main__":
    main()
