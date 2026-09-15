"""Pago CRUD endpoints."""

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.pago import Pago, PagoItem
from backend.models.usuario import Usuario
from backend.schemas.pago import PagoCreate, PagoResponse, PagoUpdate
from backend.security import get_current_user
from backend.services.numeracion import siguiente_numero_comprobante
from backend.services.renovacion import renovar_membresias

router = APIRouter(prefix="/api/pagos", tags=["pagos"])


def _pago_response(db: Session, pago: Pago) -> dict:
    """Build Pago response with items and membresiaIds."""
    items = db.query(PagoItem).filter(PagoItem.pagoId == pago.id).all()
    membresia_ids = list({item.membresiaId for item in items})
    return {
        "id": pago.id,
        "numero": pago.numero,
        "socioId": pago.socioId,
        "fecha": str(pago.fecha),
        "medio": pago.medio,
        "nota": pago.nota,
        "total": pago.total,
        "items": [
            {
                "arancelId": item.arancelId,
                "nombre": item.arancelNombre,
                "monto": item.montoAplicado,
            }
            for item in items
        ],
        "membresiaIds": membresia_ids,
        "createdBy": pago.created_by,
        "updatedBy": pago.updated_by,
    }


@router.get("", response_model=list)
def list_pagos(
    socio_id: str | None = Query(None, alias="socioId"),
    db: Session = Depends(get_db),
):
    """List all pagos with optional filter by socioId."""
    q = db.query(Pago)
    if socio_id:
        q = q.filter(Pago.socioId == socio_id)
    pagos = q.order_by(Pago.fecha.desc()).all()
    return [_pago_response(db, p) for p in pagos]


@router.get("/comprobante/{numero}", response_model=dict)
def get_pago_by_numero(numero: str, db: Session = Depends(get_db)):
    """Get a pago by receipt number."""
    pago = db.query(Pago).filter(Pago.numero == numero).first()
    if pago is None:
        raise HTTPException(status_code=404, detail=f"Pago {numero} not found")
    return _pago_response(db, pago)


@router.get("/{pago_id}", response_model=dict)
def get_pago(pago_id: str, db: Session = Depends(get_db)):
    """Get a pago by id."""
    pago = db.query(Pago).filter(Pago.id == pago_id).first()
    if pago is None:
        raise HTTPException(status_code=404, detail=f"Pago {pago_id} not found")
    return _pago_response(db, pago)


@router.post("", response_model=dict, status_code=201)
def create_pago(
    data: PagoCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Create a payment (uses services for numbering + renewal).

    The pago id is always server-generated (uuid4 hex, collision-safe across
    concurrent clients in remoto mode); any client-sent id is ignored.
    """
    pago_id = f"p{uuid.uuid4().hex}"
    numero = siguiente_numero_comprobante(db)

    pago = Pago(
        id=pago_id,
        numero=numero,
        socioId=data.socioId,
        fecha=data.fecha,
        medio=data.medio,
        total=data.total,
        nota=data.nota,
        created_by=current_user.id,
    )
    db.add(pago)
    db.flush()  # get pago.id available for PagoItem FK

    # Get the membresia IDs to renew (client-sent list, plus any from items)
    membresia_ids = list(data.membresiaIds or [])

    # Build PagoItems from the client's typed items
    for item in data.items or []:
        item_id = f"pi{uuid.uuid4().hex}"
        pago_item = PagoItem(
            id=item_id,
            pagoId=pago_id,
            arancelId=item.arancelId,
            membresiaId=item.membresiaId,
            montoAplicado=item.montoAplicado,
            arancelNombre=item.arancelNombre,
        )
        db.add(pago_item)
        if item.membresiaId not in membresia_ids:
            membresia_ids.append(item.membresiaId)

    db.commit()
    db.refresh(pago)

    # Renew memberships
    if membresia_ids:
        renovar_membresias(db, membresia_ids, pago.fecha)

    return _pago_response(db, pago)
