"""Renovacion automatica de membresias (ciclo 10 -> 10)."""

from datetime import date

from dateutil.relativedelta import relativedelta
from sqlalchemy.orm import Session

from backend.models.enums import EstadoMembresia
from backend.models.membresia import Membresia


def dia10(f: date) -> date:
    """First day-10 ON OR AFTER ``f`` (at-or-after, CBM-01).

    A payment up to and including the 10th covers the window that starts that
    same day (``dia10(05/09) == dia10(10/09) == 10/09``), so the boundary is
    ``>=``, not ``>``. A payment after the 10th covers the CURRENT period and
    anchors on the next day-10 (``dia10(15/09) == 10/10``): lateness is
    penalised with a manual recargo (CBM-03), never with a shorter window.
    """
    d = date(f.year, f.month, 10)
    return d if f.day <= 10 else d + relativedelta(months=1)


def renovar_membresias(
    db: Session, membresia_ids: list[str], fecha_pago: date
) -> None:
    """Renew memberships on the 10->10 cycle: ``max(vencimiento, dia10(fecha_pago))``.

    Business rule (AGENT.md §3): monthly 10->10 window, set estado = activa.

    The ``max`` is the whole rule: it forbids shortening a membership already
    paid ahead and turns a second charge inside the same window into a no-op.
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
        m.vencimiento = max(m.vencimiento, dia10(fecha_pago))
        m.estado = EstadoMembresia.ACTIVA
    db.commit()
