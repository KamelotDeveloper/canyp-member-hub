"""Membresia CRUD endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.enums import EstadoMembresia
from backend.models.membresia import Membresia
from backend.schemas.membresia import MembresiaCreate, MembresiaResponse, MembresiaUpdate
from backend.services.estado_visual import calcular_estado_visual

router = APIRouter(prefix="/api/membresias", tags=["membresias"])


def _validate_parcela_id(db: Session, parcela_id: str | None) -> None:
    """Server-side parcelaId FK validation.

    SQLite FKs are OFF against the live DB, so a bare insert with a bogus
    parcelaId would silently succeed. Reject it here instead (RQ 11).
    """
    if parcela_id is None:
        return
    from backend.models.parcela import Parcela

    exists = db.query(Parcela).filter(Parcela.id == parcela_id).first()
    if exists is None:
        raise HTTPException(
            status_code=422, detail=f"Parcela {parcela_id} not found"
        )


@router.get("", response_model=list[MembresiaResponse])
def list_membresias(
    area: str | None = Query(None),
    predio: str | None = Query(None),
    estado: str | None = Query(None),
    socio_id: str | None = Query(None, alias="socioId"),
    db: Session = Depends(get_db),
):
    """List all membresias with optional filters."""
    q = db.query(Membresia)
    if area:
        q = q.filter(Membresia.area == area)
    if predio:
        q = q.filter(Membresia.predio == predio)
    if estado:
        q = q.filter(Membresia.estado == estado)
    if socio_id:
        q = q.filter(Membresia.socioId == socio_id)
    return q.order_by(Membresia.vencimiento.desc()).all()


@router.get("/parcelas", response_model=list)
def group_by_parcela(db: Session = Depends(get_db)):
    """List membresias grouped by parcela with computed estado_visual."""
    from backend.models.parcela import Parcela

    parcelas = db.query(Parcela).all()
    result = []
    for p in parcelas:
        membresias = (
            db.query(Membresia)
            .filter(Membresia.parcelaId == p.id)
            .order_by(Membresia.vencimiento.desc())
            .all()
        )
        result.append(
            {
                "parcela": {
                    "id": p.id,
                    "nombre": p.nombre,
                    "tipo": p.tipo.value,
                    "tamano": p.tamano,
                    "predio": p.predio.value,
                    "categoria": p.categoria.value if p.categoria else None,
                },
                "membresias": [
                    {
                        "id": m.id,
                        "socioId": m.socioId,
                        "area": m.area.value,
                        "predio": m.predio.value,
                        "estado": m.estado.value,
                        "vencimiento": str(m.vencimiento),
                        "rol": m.rol.value if m.rol else None,
                        "detalle": m.detalle,
                        "estadoVisual": calcular_estado_visual(
                            m.estado.value, m.vencimiento
                        ),
                    }
                    for m in membresias
                ],
            }
        )
    return result


@router.get("/{membresia_id}", response_model=MembresiaResponse)
def get_membresia(membresia_id: str, db: Session = Depends(get_db)):
    """Get a membresia by id."""
    m = db.query(Membresia).filter(Membresia.id == membresia_id).first()
    if m is None:
        raise HTTPException(status_code=404, detail=f"Membresia {membresia_id} not found")
    return m


@router.post("", response_model=MembresiaResponse, status_code=201)
def create_membresia(data: MembresiaCreate, db: Session = Depends(get_db)):
    """Create a new membresia."""
    _validate_parcela_id(db, data.parcelaId)
    membresia_id = data.id or f"m{uuid.uuid4().hex[:8]}"
    membresia = Membresia(id=membresia_id, **data.model_dump(exclude={"id"}))
    db.add(membresia)
    db.commit()
    db.refresh(membresia)
    return membresia


@router.put("/{membresia_id}", response_model=MembresiaResponse)
def update_membresia(
    membresia_id: str, data: MembresiaUpdate, db: Session = Depends(get_db)
):
    """Update a membresia."""
    m = db.query(Membresia).filter(Membresia.id == membresia_id).first()
    if m is None:
        raise HTTPException(status_code=404, detail=f"Membresia {membresia_id} not found")
    if data.parcelaId is not None:
        _validate_parcela_id(db, data.parcelaId)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(m, key, value)
    db.commit()
    db.refresh(m)
    return m


@router.delete("/{membresia_id}", status_code=204)
def delete_membresia(membresia_id: str, db: Session = Depends(get_db)):
    """Delete a membresia."""
    m = db.query(Membresia).filter(Membresia.id == membresia_id).first()
    if m is None:
        raise HTTPException(status_code=404, detail=f"Membresia {membresia_id} not found")
    db.delete(m)
    db.commit()


@router.put("/{membresia_id}/estado", response_model=MembresiaResponse)
def set_estado_membresia(
    membresia_id: str,
    data: MembresiaUpdate,
    db: Session = Depends(get_db),
):
    """Set membresia estado (suspendida/baja)."""
    m = db.query(Membresia).filter(Membresia.id == membresia_id).first()
    if m is None:
        raise HTTPException(status_code=404, detail=f"Membresia {membresia_id} not found")
    if data.estado is not None:
        m.estado = data.estado
    db.commit()
    db.refresh(m)
    return m
