"""Arancel CRUD endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.arancel import Arancel
from backend.schemas.arancel import ArancelCreate, ArancelResponse, ArancelUpdate
from backend.services.historial_aranceles import actualizar_monto_arancel

router = APIRouter(prefix="/api/aranceles", tags=["aranceles"])


@router.get("", response_model=list[ArancelResponse])
def list_aranceles(
    area: str | None = Query(None),
    predio: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """List all aranceles with optional filters."""
    q = db.query(Arancel)
    if area:
        q = q.filter(Arancel.area == area)
    if predio:
        q = q.filter(Arancel.predio == predio)
    return q.order_by(Arancel.nombre).all()


@router.get("/{arancel_id}", response_model=ArancelResponse)
def get_arancel(arancel_id: str, db: Session = Depends(get_db)):
    """Get an arancel by id."""
    a = db.query(Arancel).filter(Arancel.id == arancel_id).first()
    if a is None:
        raise HTTPException(status_code=404, detail=f"Arancel {arancel_id} not found")
    return a


@router.post("", response_model=ArancelResponse, status_code=201)
def create_arancel(data: ArancelCreate, db: Session = Depends(get_db)):
    """Create a new arancel."""
    arancel_id = data.id or f"a{uuid.uuid4().hex[:8]}"
    arancel = Arancel(id=arancel_id, **data.model_dump(exclude={"id"}))
    db.add(arancel)
    db.commit()
    db.refresh(arancel)
    return arancel


@router.put("/{arancel_id}/monto", response_model=ArancelResponse)
def update_monto(
    arancel_id: str,
    data: ArancelUpdate,
    db: Session = Depends(get_db),
):
    """Update arancel monto (saves to historico)."""
    if data.monto is None:
        raise HTTPException(
            status_code=422, detail="monto field is required"
        )
    try:
        arancel = actualizar_monto_arancel(db, arancel_id, data.monto)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return arancel
