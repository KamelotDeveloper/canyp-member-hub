"""Arancel CRUD endpoints."""

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from backend.database import get_db
from backend.models.arancel import Arancel
from backend.models.usuario import Usuario
from backend.schemas.arancel import ArancelCreate, ArancelResponse, ArancelUpdate
from backend.security import get_current_user
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
def create_arancel(
    data: ArancelCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Create a new arancel."""
    arancel_id = data.id or f"a{uuid.uuid4().hex[:8]}"
    arancel = Arancel(
        id=arancel_id,
        created_by=current_user.id,
        **data.model_dump(exclude={"id"}),
    )
    db.add(arancel)
    db.commit()
    db.refresh(arancel)
    return arancel


@router.put("/{arancel_id}", response_model=ArancelResponse)
def update_arancel(
    arancel_id: str,
    data: ArancelUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Fully update an arancel: nombre, area, predio, monto, categoria, vigenteDesde.

    Changing the monto pushes the old value to historico (same business rule as
    the /monto endpoint). Editing any other field alone does not.
    """
    arancel = db.query(Arancel).filter(Arancel.id == arancel_id).first()
    if arancel is None:
        raise HTTPException(status_code=404, detail=f"Arancel {arancel_id} not found")

    updates = data.model_dump(exclude_unset=True)
    monto = updates.pop("monto", None)

    # Apply non-monto fields directly.
    for field, value in updates.items():
        if field == "historico":
            continue
        setattr(arancel, field, value)

    if monto is not None and monto != arancel.monto:
        arancel.historico.append(
            {"monto": arancel.monto, "vigenteDesde": str(arancel.vigenteDesde)}
        )
        flag_modified(arancel, "historico")
        arancel.monto = monto
        arancel.vigenteDesde = date.today()

    arancel.updated_by = current_user.id
    db.commit()
    db.refresh(arancel)
    return arancel


@router.delete("/{arancel_id}", status_code=204)
def delete_arancel(arancel_id: str, db: Session = Depends(get_db)):
    """Delete an arancel."""
    arancel = db.query(Arancel).filter(Arancel.id == arancel_id).first()
    if arancel is None:
        raise HTTPException(status_code=404, detail=f"Arancel {arancel_id} not found")
    db.delete(arancel)
    db.commit()


@router.put("/{arancel_id}/monto", response_model=ArancelResponse)
def update_monto(
    arancel_id: str,
    data: ArancelUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
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
    arancel.updated_by = current_user.id
    db.commit()
    db.refresh(arancel)
    return arancel
