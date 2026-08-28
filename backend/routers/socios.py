"""Socio CRUD endpoints."""

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.membresia import Membresia
from backend.models.notificacion import Notificacion
from backend.models.socio import Socio
from backend.schemas.membresia import MembresiaResponse
from backend.schemas.socio import SocioCreate, SocioResponse, SocioUpdate

router = APIRouter(prefix="/api/socios", tags=["socios"])


@router.get("", response_model=list[SocioResponse])
def list_socios(
    search: str | None = Query(None, description="Search by nombre or dni"),
    db: Session = Depends(get_db),
):
    """List all socios with optional search by nombre/dni."""
    q = db.query(Socio)
    if search:
        pattern = f"%{search}%"
        q = q.filter(Socio.nombre.ilike(pattern) | Socio.dni.ilike(pattern))
    return q.order_by(Socio.nombre).all()


@router.get("/{socio_id}", response_model=SocioResponse)
def get_socio(socio_id: str, db: Session = Depends(get_db)):
    """Get a socio by id."""
    socio = db.query(Socio).filter(Socio.id == socio_id).first()
    if socio is None:
        raise HTTPException(status_code=404, detail=f"Socio {socio_id} not found")
    return socio


@router.post("", response_model=SocioResponse, status_code=201)
def create_socio(data: SocioCreate, db: Session = Depends(get_db)):
    """Create a new socio."""
    socio_id = data.id or f"s{uuid.uuid4().hex[:8]}"
    socio = Socio(
        id=socio_id,
        fechaAlta=data.fechaAlta or date.today(),
        **data.model_dump(exclude={"id", "fechaAlta"}),
    )
    db.add(socio)
    db.commit()
    db.refresh(socio)
    return socio


@router.put("/{socio_id}", response_model=SocioResponse)
def update_socio(socio_id: str, data: SocioUpdate, db: Session = Depends(get_db)):
    """Update a socio."""
    socio = db.query(Socio).filter(Socio.id == socio_id).first()
    if socio is None:
        raise HTTPException(status_code=404, detail=f"Socio {socio_id} not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(socio, key, value)
    db.commit()
    db.refresh(socio)
    return socio


@router.delete("/{socio_id}", status_code=204)
def delete_socio(socio_id: str, db: Session = Depends(get_db)):
    """Delete a socio."""
    socio = db.query(Socio).filter(Socio.id == socio_id).first()
    if socio is None:
        raise HTTPException(status_code=404, detail=f"Socio {socio_id} not found")
    # Cascade: delete dependents before socio
    db.query(Membresia).filter(Membresia.socioId == socio_id).delete()
    db.query(Notificacion).filter(Notificacion.socioId == socio_id).delete()
    db.delete(socio)
    db.commit()


@router.get("/{socio_id}/membresias", response_model=list[MembresiaResponse])
def list_socio_membresias(socio_id: str, db: Session = Depends(get_db)):
    """List membresias for a specific socio."""
    socio = db.query(Socio).filter(Socio.id == socio_id).first()
    if socio is None:
        raise HTTPException(status_code=404, detail=f"Socio {socio_id} not found")
    from backend.models.membresia import Membresia

    membresias = (
        db.query(Membresia)
        .filter(Membresia.socioId == socio_id)
        .order_by(Membresia.vencimiento.desc())
        .all()
    )
    return membresias
