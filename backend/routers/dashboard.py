"""Dashboard stats and alerts endpoints."""

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.enums import Area, EstadoMembresia
from backend.models.membresia import Membresia
from backend.services.estado_visual import calcular_estado_visual

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/stats")
def get_stats(db: Session = Depends(get_db)):
    """Counts by area, vencidas, por_vencer."""
    membresias = db.query(Membresia).all()

    counts_by_area: dict[str, int] = {a.value: 0 for a in Area}
    vencidas = 0
    por_vencer = 0
    activas = 0

    for m in membresias:
        counts_by_area[m.area.value] = counts_by_area.get(m.area.value, 0) + 1
        visual = calcular_estado_visual(m.estado.value, m.vencimiento)
        if visual == "vencida":
            vencidas += 1
        elif visual == "por_vencer":
            por_vencer += 1
        elif visual == "activa":
            activas += 1

    return {
        "totalMembresias": len(membresias),
        "countsByArea": counts_by_area,
        "vencidas": vencidas,
        "porVencer": por_vencer,
        "activas": activas,
    }


@router.get("/alertas")
def get_alertas(db: Session = Depends(get_db)):
    """Membresias vencidas + por vencer (sorted by urgency)."""
    membresias = db.query(Membresia).all()

    alertas = []
    for m in membresias:
        visual = calcular_estado_visual(m.estado.value, m.vencimiento)
        if visual in ("vencida", "por_vencer"):
            alertas.append(
                {
                    "id": m.id,
                    "socioId": m.socioId,
                    "area": m.area.value,
                    "predio": m.predio.value,
                    "estado": m.estado.value,
                    "vencimiento": str(m.vencimiento),
                    "estadoVisual": visual,
                }
            )

    # Sort: vencidas first, then by vencimiento ascending (most urgent first)
    priority = {"vencida": 0, "por_vencer": 1}
    alertas.sort(key=lambda a: (priority.get(a["estadoVisual"], 2), a["vencimiento"]))

    return alertas
