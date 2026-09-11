"""Renovacion automatica de membresias."""

from datetime import date

from dateutil.relativedelta import relativedelta
from sqlalchemy.orm import Session

from backend.models.enums import EstadoMembresia
from backend.models.membresia import Membresia


def renovar_membresias(
    db: Session, membresia_ids: list[str], fecha_pago: date
) -> None:
    """Renew memberships for 12 months from max(vencimiento, fecha_pago).

    Business rule (AGENTS.md §3): set estado = activa.

    ``FOR UPDATE`` serializes read-modify-write of each membership row so two
    admins charging the same membership concurrently (remoto/Supabase) renew
    from a consistent base date. SQLite accepts the clause as a no-op.
    """
    for mid in membresia_ids:
        m = (
            db.query(Membresia)
            .filter(Membresia.id == mid)
            .with_for_update()
            .first()
        )
        if m is None:
            continue
        base = max(m.vencimiento, fecha_pago)
        m.vencimiento = base + relativedelta(months=12)
        m.estado = EstadoMembresia.ACTIVA
    db.commit()
