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
from backend.services.cobro import CobroVacioError, resolver_cobro
from backend.services.numeracion import siguiente_numero_comprobante
from backend.services.renovacion import renovar_membresias

router = APIRouter(prefix="/api/pagos", tags=["pagos"])


def _pago_response(db: Session, pago: Pago) -> dict:
    """Build Pago response with items and membresiaIds.

    Each item now carries its ``concepto`` and the resolved ``factor`` behind the
    frozen amount (PAG-01), so a receipt explains *why* an amount is what it is
    ("Cuota social x4") without re-deriving anything.
    """
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
                "concepto": item.concepto.value if item.concepto else None,
                "factor": item.factor,
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
    concurrent clients in remoto mode); any client-sent id is ignored. PR 5 goes
    further: the item set, every amount, the total AND the renewal set are
    resolved by ``services.cobro``. The client sends which concepts apply; the
    server owns the arithmetic (D3, D4).
    """
    submitted_ids = list(data.membresiaIds or []) or [
        item.membresiaId for item in (data.items or [])
    ]
    try:
        cobro = resolver_cobro(
            db,
            socio_id=data.socioId,
            items=data.items or [],
            membresia_ids=submitted_ids,
        )
    except CobroVacioError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    pago_id = f"p{uuid.uuid4().hex}"
    numero = siguiente_numero_comprobante(db)

    pago = Pago(
        id=pago_id,
        numero=numero,
        socioId=data.socioId,
        fecha=data.fecha,
        medio=data.medio,
        total=cobro.total,
        nota=data.nota,
        created_by=current_user.id,
    )
    db.add(pago)
    db.flush()  # get pago.id available for PagoItem FK

    for resuelto in cobro.items:
        db.add(
            PagoItem(
                id=f"pi{uuid.uuid4().hex}",
                pagoId=pago_id,
                arancelId=resuelto.arancelId,
                membresiaId=resuelto.membresiaId,
                montoAplicado=resuelto.monto,
                arancelNombre=resuelto.arancelNombre,
                concepto=resuelto.concepto,
                factor=resuelto.factor,
            )
        )

    db.commit()
    db.refresh(pago)

    # Renew only the memberships whose own concept was part of the charge.
    if cobro.membresias_a_renovar:
        renovar_membresias(db, list(cobro.membresias_a_renovar), pago.fecha)

    return _pago_response(db, pago)
