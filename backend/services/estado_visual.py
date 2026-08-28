"""Estado visual de membresia — pure function, no DB."""

from datetime import date, timedelta


def calcular_estado_visual(estado: str, vencimiento: date) -> str:
    """Compute the display status of a membership.

    Business rules (AGENTS.md §1):
    - baja/suspendida are persisted states that override date logic.
    - vencimiento < today → vencida
    - vencimiento <= 30 days → por_vencer
    - vencimiento > 30 days → activa
    """
    if estado in ("baja", "suspendida"):
        return estado

    today = date.today()
    if vencimiento < today:
        return "vencida"
    if vencimiento <= today + timedelta(days=30):
        return "por_vencer"
    return "activa"
