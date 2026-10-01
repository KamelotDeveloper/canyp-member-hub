"""Dashboard stats and alerts endpoints."""

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.enums import Area, EstadoMembresia, EstadoSocioVisual
from backend.models.membresia import Membresia
from backend.models.socio import Socio
from backend.services.estado_socio import estados_socio

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

# Bucket for memberships with no physical area — a cuota social row is not a
# place (spec CS-01), so `area` is NULL and the real Area enum values never
# describe it. The bucket is always present so the response shape is stable.
SIN_AREA = "Sin área"

# A membership is an alert when its own date already passed, or when its own
# `estado` says it is not being paid for. The 30-day "por vencer" warning no
# longer exists (EST-01/EST-04): there is no proximity warning, only a real debt.
#
# `VENCIDA` belongs here for the same reason it belongs in the badge
# (`services/estado_socio.Vigencia.vencida`): it is the operator's mark for
# "just expired", so a row carrying it OWES the same way a row whose date is
# past owes. It is a statement about the EXPIRY, not an administrative stop,
# which is why it is read on both concepts and routed by `concepto` (cuota -> 🔴,
# área -> ⚠️) instead of collapsing to a single bucket here.
#
# Leaving it out made this list disagree with the badge it exists to work from:
# the padrón served "Socio activo — revisar" for a row flagged `vencida` with a
# future `vencimiento`, and this endpoint — read by the "Atención inmediata"
# panel, by the "N a revisar" counter of every area card and by the
# Notificaciones screen — dropped it, so the operator was told to review a socio
# they had no way to find. Both readers now ask the same question.
ALERTA_ESTADOS = (
    EstadoMembresia.SUSPENDIDA,
    EstadoMembresia.BAJA,
    EstadoMembresia.VENCIDA,
)
# 🔴 before ⚠️: the debt that needs charging comes before the one to review.
PRIORIDAD = {
    EstadoSocioVisual.INACTIVO_REVISAR.value: 0,
    EstadoSocioVisual.ACTIVO_REVISAR.value: 1,
}


def _alerta(m, estado: EstadoSocioVisual) -> dict:
    return {
        "id": m.id,
        "socioId": m.socioId,
        # `area`/`predio` are nullable: a cuota social membership reports null,
        # never a placeholder area value.
        "area": m.area.value if m.area is not None else None,
        "predio": m.predio.value if m.predio is not None else None,
        "estado": m.estado.value,
        "vencimiento": str(m.vencimiento),
        # The state of the SOCIO, served (EST-01) — the alert row itself is the
        # membership, but what the operator has to act on is the person.
        "estadoSocio": estado.value,
        "nominacion": estado.value,
    }


@router.get("/stats")
def get_stats(db: Session = Depends(get_db)):
    """Counts by area + the 4 server-authoritative socio states."""
    membresias = db.query(Membresia).all()

    counts_by_area: dict[str, int] = {a.value: 0 for a in Area}
    counts_by_area[SIN_AREA] = 0
    for m in membresias:
        area_key = m.area.value if m.area is not None else SIN_AREA
        counts_by_area[area_key] = counts_by_area.get(area_key, 0) + 1

    # Always all 4 buckets, even at zero, so the dashboard never has to guess
    # a missing state. One grouped query, not one per socio.
    estados = {e.value: 0 for e in EstadoSocioVisual}
    for estado in estados_socio(db, [s for (s,) in db.query(Socio.id).all()]).values():
        estados[estado.value] += 1

    return {
        "totalMembresias": len(membresias),
        "countsByArea": counts_by_area,
        "estados": estados,
    }


@router.get("/alertas")
def get_alertas(db: Session = Depends(get_db)):
    """Overdue/suspended memberships with their socio's state (most urgent first)."""
    hoy = date.today()
    membresias = db.query(Membresia).all()
    socio_ids = {m.socioId for m in membresias}
    estados = estados_socio(db, sorted(socio_ids))

    alertas = [
        _alerta(m, estados.get(m.socioId, EstadoSocioVisual.SOLO_CUOTA_SOCIAL))
        for m in membresias
        if m.vencimiento < hoy or m.estado in ALERTA_ESTADOS
    ]
    # Sort: 🔴 first, then ⚠️, then by vencimiento ascending (most urgent first)
    alertas.sort(key=lambda a: (PRIORIDAD.get(a["estadoSocio"], 2), a["vencimiento"]))
    return alertas
