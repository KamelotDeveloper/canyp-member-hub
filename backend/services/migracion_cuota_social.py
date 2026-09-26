"""Legacy conversion: cuota social rows + projection of every ``vencimiento``
onto the 10->10 cycle (spec CBM-05 / CS-02).

Two phases, in this order:

1. **Backfill** — one ``CUOTA_SOCIAL`` membership per socio that lacks one.
   ``vencimiento`` = the socio's most recent area ``vencimiento``, or the
   current 10->10 window when the socio has no area membership.
2. **Projection** — every ``membresias.vencimiento`` becomes
   ``dia10(vencimiento)``, i.e. the day-10 on or after it. A date already on the
   10th maps to itself, which is what makes a second run a no-op.

Both phases are guarded and idempotent. NOTHING here touches ``pagos`` or
``pago_items``: a payment is a receipt of a real charge, so a date projection
must never create, alter or delete one (CBM-05, CBM-06).

OPERATOR CONTRACT (SAFETY)
--------------------------
* ``--dry-run`` is the DEFAULT. It prints a reviewable plan and writes nothing.
* ``--apply`` writes, and only after ``services/backup.py`` has produced a full
  dump of the database. The backup path and its SHA256 are always reported, so
  the handoff carries the evidence.
* The projection is **not** reversible by re-running: a date like 03/07 becomes
  10/07 and re-running keeps 10/07. Restoring means restoring the backup.

This module runs AFTER ``python -m backend.migrate`` (which makes
``membresias.area``/``predio`` nullable and adds + backfills ``concepto``). It
refuses to run when that column is missing rather than silently degrading.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from dataclasses import dataclass, field, replace
from datetime import date

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.models.enums import ConceptoMembresia
from backend.models.membresia import Membresia
from backend.models.socio import Socio
from backend.services import backup as backup_service
from backend.services.cuota_social import (
    crear_cuota_social,
    cuota_de,
    ultimo_vencimiento_area,
    ventana_actual,
)
from backend.services.renovacion import dia10

# How many concrete date changes the printed plan shows. The counts are always
# complete; only the sample is truncated, and the truncation is stated.
EJEMPLOS_MAXIMOS = 20


class MigracionCuotaSocialError(RuntimeError):
    """The migration cannot run safely (or did not complete) on this database.

    Two cases share this error on purpose: the schema is not ready (see the
    module docstring) and the post-apply verification found work left over.
    Both mean "stop, do not report success".
    """


@dataclass(frozen=True)
class CambioVencimiento:
    """One membership whose ``vencimiento`` the projection would move."""

    membresia_id: str
    socio_id: str
    concepto: str
    anterior: date
    nuevo: date

    def __str__(self) -> str:
        return (
            f"  {self.membresia_id} (socio {self.socio_id}, {self.concepto}): "
            f"{self.anterior.isoformat()} -> {self.nuevo.isoformat()}"
        )


@dataclass(frozen=True)
class PlanMigracion:
    """Reviewable, complete summary of what the migration would do."""

    socios: int
    socios_sin_cuota: int
    membresias: int
    cambios: tuple[CambioVencimiento, ...] = field(default_factory=tuple)
    cuota_a_crear: tuple[str, ...] = field(default_factory=tuple)
    ejecucion: bool = False
    ruta_backup: str | None = None
    sha256_backup: str | None = None

    @property
    def proyecciones(self) -> int:
        """How many rows the projection would move onto a day-10."""
        return len(self.cambios)

    @property
    def sin_cambios(self) -> bool:
        """True when a second run has nothing left to do (idempotency)."""
        return not self.cuota_a_crear and not self.cambios

    def resumen(self) -> str:
        """The human-readable, reviewable plan printed by the CLI."""
        verb = "escribió" if self.ejecucion else "escribiría"
        proyectados = "proyectados" if self.ejecucion else "a proyectar"
        lineas = [
            "Plan de conversión a cuota social (10->10)",
            f"  socios totales .............. {self.socios}",
            f"  socios sin cuota social .... {self.socios_sin_cuota}",
            f"  filas CUOTA_SOCIAL a crear . {len(self.cuota_a_crear)}",
            f"  membresias totales ......... {self.membresias}",
            f"  vencimientos {proyectados} ... {self.proyecciones} "
            f"(dia10: hasta 9 días de adelanto, irreversible reejecutando)",
        ]
        if self.cuota_a_crear:
            muestra = self.cuota_a_crear[:EJEMPLOS_MAXIMOS]
            lineas.append(f"  {verb} cuota social para: {', '.join(muestra)}")
            if len(self.cuota_a_crear) > EJEMPLOS_MAXIMOS:
                lineas.append(
                    f"    ... y {len(self.cuota_a_crear) - EJEMPLOS_MAXIMOS} más"
                )
        if self.cambios:
            lineas.append("  cambios de vencimiento (muestra):")
            for cambio in self.cambios[:EJEMPLOS_MAXIMOS]:
                lineas.append(str(cambio))
            if len(self.cambios) > EJEMPLOS_MAXIMOS:
                lineas.append(
                    f"    ... y {len(self.cambios) - EJEMPLOS_MAXIMOS} más"
                )
        else:
            lineas.append("  cambios de vencimiento: ninguno")
        if self.ruta_backup:
            lineas.append(f"  backup ..................... {self.ruta_backup}")
            lineas.append(f"  backup sha256 .............. {self.sha256_backup}")
        return "\n".join(lineas)


def _exigir_columna_concepto(db: Session) -> None:
    """Fail loudly when `migrate.py` has not run yet.

    `crear_cuota_social` writes `concepto`; on a database that predates the
    column the ORM would raise an opaque `OperationalError` mid-write. The
    ordering (recreate -> add column -> backfill) is load-bearing, so it is
    checked up front.
    """
    columnas = {c["name"] for c in inspect(db.get_bind()).get_columns("membresias")}
    if "concepto" not in columnas:
        raise MigracionCuotaSocialError(
            "membresias.concepto no existe: corré 'python -m backend.migrate' "
            "primero (recrear area/predio -> agregar concepto -> backfill)."
        )


def _plan(db: Session) -> PlanMigracion:
    """Compute the complete plan. Read-only: never writes, never commits."""
    _exigir_columna_concepto(db)

    socios = db.scalars(select(Socio).order_by(Socio.id)).all()

    cuota_a_crear: list[str] = []
    pendientes: list[tuple[str, date]] = []
    for socio in socios:
        if cuota_de(db, socio.id) is not None:
            continue
        cuota_a_crear.append(socio.id)
        # Same default as the runtime service, so the plan matches the apply.
        pendientes.append(
            (socio.id, ultimo_vencimiento_area(db, socio.id) or ventana_actual())
        )

    membresias = db.scalars(
        select(Membresia).order_by(Membresia.id)
    ).all()

    cambios: list[CambioVencimiento] = []
    for m in membresias:
        nuevo = dia10(m.vencimiento)
        if nuevo != m.vencimiento:
            cambios.append(
                CambioVencimiento(
                    membresia_id=m.id,
                    socio_id=m.socioId,
                    concepto=m.concepto.value,
                    anterior=m.vencimiento,
                    nuevo=nuevo,
                )
            )
    # A brand-new cuota row inherits a legacy date and is projected too, so it
    # must appear in the plan even though it does not exist yet.
    for socio_id, heredado in pendientes:
        nuevo = dia10(heredado)
        if nuevo != heredado:
            cambios.append(
                CambioVencimiento(
                    membresia_id="(nueva cuota social)",
                    socio_id=socio_id,
                    concepto=ConceptoMembresia.CUOTA_SOCIAL.value,
                    anterior=heredado,
                    nuevo=nuevo,
                )
            )

    return PlanMigracion(
        socios=len(socios),
        socios_sin_cuota=len(cuota_a_crear),
        membresias=len(membresias),
        cambios=tuple(cambios),
        cuota_a_crear=tuple(cuota_a_crear),
    )


def plan(db: Session) -> PlanMigracion:
    """Public, read-only entry point used by the tests and the CLI dry run."""
    return _plan(db)


def _aplicar(db: Session) -> None:
    """Write both phases in a single transaction. Never touches pagos."""
    # Phase 1 — one cuota social row per socio lacking one. It goes through the
    # runtime service (not a hand-built row) so the plan and the apply cannot
    # drift apart, and so `id` generation and the flush live in one place.
    for socio in db.scalars(select(Socio).order_by(Socio.id)).all():
        if cuota_de(db, socio.id) is None:
            crear_cuota_social(db, socio)

    # Phase 2 — project every vencimiento onto the 10->10 cycle. `dia10` is
    # at-or-after, so a date already on the 10th is left alone: that is the
    # idempotency guarantee.
    for m in db.scalars(select(Membresia).order_by(Membresia.id)).all():
        nuevo = dia10(m.vencimiento)
        if nuevo != m.vencimiento:
            m.vencimiento = nuevo
    db.commit()


def _backup(engine) -> tuple[str, str]:
    """Full dump via `services/backup.py` + its SHA256, BEFORE any write.

    ``create_backup`` is called directly rather than ``run_backup_if_needed``:
    the 15-day interval would let a destructive migration run with a 14-day-old
    dump, and the operator contract is "fresh backup, every time".
    """
    resultado = backup_service.create_backup(engine)
    ruta = resultado["path"]
    with open(ruta, "rb") as fh:
        sha = hashlib.sha256(fh.read()).hexdigest()
    return ruta, sha


def migrar(db: Session, *, dry_run: bool = True, engine=None) -> PlanMigracion:
    """Plan (and optionally apply) the conversion.

    ``dry_run=True`` (the default) writes NOTHING: it returns the same plan the
    apply path would execute. ``dry_run=False`` takes a backup first, then
    applies both phases in one transaction and reports the backup evidence.

    The returned plan on apply is the one captured **before** the writes, so it
    is the record of what was executed. Re-planning afterwards would report
    zeros and throw away the only evidence the handoff carries.
    """
    if dry_run:
        return _plan(db)

    # Captured first: this is what the operator reviewed and what we applied.
    plan_aplicado = _plan(db)

    if engine is None:
        engine = db.get_bind()
    ruta, sha = _backup(engine)
    _aplicar(db)

    # Idempotency guard: an empty re-plan proves both phases landed completely.
    if not _plan(db).sin_cambios:
        raise MigracionCuotaSocialError(
            "verificación post-aplicación falló: el plan sigue pendiente, "
            "revisá el estado de la base antes de operar."
        )

    return replace(
        plan_aplicado, ejecucion=True, ruta_backup=ruta, sha256_backup=sha
    )


def main(argv: list[str] | None = None) -> None:
    """CLI entry point (python -m backend.services.migracion_cuota_social).

    Dry run by default. ``--apply`` is required to write, and it always takes a
    backup first (module docstring, "OPERATOR CONTRACT").
    """
    parser = argparse.ArgumentParser(
        prog="migracion_cuota_social",
        description=(
            "Idempotent cuota social backfill + 10->10 vencimiento projection. "
            "Dry run by default; --apply writes (and backs up first)."
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
        help="APPLY the plan to the live database (takes a backup first)",
    )
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        resultado = migrar(db, dry_run=not args.apply, engine=None)
    except MigracionCuotaSocialError as exc:
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
        print("Dry run complete. No changes were written (nothing to do).")
    else:
        print("Dry run complete. No changes were written.")
    sys.exit(0)


if __name__ == "__main__":
    main()
