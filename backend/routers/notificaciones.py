"""Notificacion endpoints."""

import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.notificacion import Notificacion
from backend.schemas.notificacion import NotificacionCreate, NotificacionResponse

router = APIRouter(prefix="/api/notificaciones", tags=["notificaciones"])


@router.get("", response_model=list[NotificacionResponse])
def list_notificaciones(
    socio_id: str | None = Query(None, alias="socioId"),
    db: Session = Depends(get_db),
):
    """List all notificaciones with optional filter by socioId."""
    q = db.query(Notificacion)
    if socio_id:
        q = q.filter(Notificacion.socioId == socio_id)
    return q.order_by(Notificacion.fecha.desc()).all()


@router.post("", response_model=list[NotificacionResponse], status_code=201)
def create_notificaciones(
    data: NotificacionCreate | list[NotificacionCreate],
    db: Session = Depends(get_db),
):
    """Create notificaciones (bulk allowed)."""
    items = data if isinstance(data, list) else [data]
    created = []
    for item in items:
        notif = Notificacion(
            id=item.id or f"n{uuid.uuid4().hex[:8]}",
            socioId=item.socioId,
            canal=item.canal,
            fecha=item.fecha,
            motivo=item.motivo,
            mensaje=item.mensaje,
        )
        db.add(notif)
        created.append(notif)
    db.commit()
    for n in created:
        db.refresh(n)
    return created


@router.post("/whatsapp-link")
def generate_whatsapp_link(
    phone: str = Query(..., description="Phone number"),
    message: str = Query(..., description="Message text"),
):
    """Generate a wa.me link for WhatsApp messaging."""
    encoded_message = quote(message)
    phone_clean = phone.replace(" ", "").replace("-", "").replace("+", "")
    link = f"https://wa.me/{phone_clean}?text={encoded_message}"
    return {"link": link, "phone": phone_clean}
