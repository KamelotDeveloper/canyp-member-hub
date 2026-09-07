"""Parcela CRUD endpoints."""

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.enums import Area, EstadoMembresia
from backend.models.membresia import Membresia
from backend.models.parcela import Parcela
from backend.models.socio import Socio
from backend.schemas.import_ import ImportPayload, ImportResponse
from backend.schemas.membresia import MembresiaUpdate
from backend.schemas.parcela import ParcelaCreate, ParcelaResponse, ParcelaUpdate

router = APIRouter(prefix="/api/parcelas", tags=["parcelas"])


@router.get("", response_model=list[ParcelaResponse])
def list_parcelas(
    predio: str | None = Query(None, description="Filter by predio"),
    db: Session = Depends(get_db),
):
    """List all parcelas with optional predio filter."""
    q = db.query(Parcela)
    if predio:
        q = q.filter(Parcela.predio == predio)
    return q.order_by(Parcela.nombre).all()


@router.post("", response_model=ParcelaResponse, status_code=201)
def create_parcela(data: ParcelaCreate, db: Session = Depends(get_db)):
    """Create a new parcela."""
    parcela = Parcela(**data.model_dump())
    db.add(parcela)
    db.commit()
    db.refresh(parcela)
    return parcela


@router.post("/import", response_model=ImportResponse)
def import_parcelas(data: ImportPayload, db: Session = Depends(get_db)):
    """Create parcelas + socios + membresias transactionally (RQ 8).

    Idempotent:
      - skip a Parcela whose (nombre, predio, tipo) already exists
      - socios matched by dni (never duplicated)
    On any validation error the whole batch rolls back (atomic).
    """
    created_parcelas: list[str] = []
    created_socios: list[str] = []
    created_membresias: list[str] = []

    for unidad in data.unidades:
        existing = (
            db.query(Parcela)
            .filter(
                Parcela.nombre == unidad.nombre,
                Parcela.predio == unidad.predio,
                Parcela.tipo == unidad.tipo,
            )
            .first()
        )
        if existing is not None:
            parcela = existing
        else:
            parcela = Parcela(
                id=f"p{uuid.uuid4().hex[:8]}",
                nombre=unidad.nombre,
                tipo=unidad.tipo,
                categoria=unidad.categoria,
                predio=unidad.predio,
            )
            db.add(parcela)
            created_parcelas.append(parcela.id)
            db.flush()

        for miembro in unidad.miembros:
            socio_schema = miembro.socio
            socio = (
                db.query(Socio).filter(Socio.dni == socio_schema.dni).first()
            )
            if socio is None:
                socio = Socio(
                    id=f"s{uuid.uuid4().hex[:8]}",
                    nombre=socio_schema.nombre,
                    dni=socio_schema.dni,
                    telefono=socio_schema.telefono or "",
                    email=socio_schema.email or "",
                    direccion="",
                    fechaAlta=date.today(),
                    activo=True,
                )
                db.add(socio)
                created_socios.append(socio.id)
                db.flush()

            # Idempotency: skip if this socio already has a membresia for the unit.
            existing_membresia = (
                db.query(Membresia)
                .filter(
                    Membresia.socioId == socio.id,
                    Membresia.parcelaId == parcela.id,
                )
                .first()
            )
            if existing_membresia is not None:
                continue

            # Map area from the parcela tipo.
            area = (
                Area.CABANEROS
                if unidad.tipo.value == "cabaña"
                else Area.BALSEROS
                if unidad.tipo.value == "balsa"
                else Area.GUARDERIA
            )
            membresia = Membresia(
                id=f"m{uuid.uuid4().hex[:8]}",
                socioId=socio.id,
                area=area,
                predio=unidad.predio,
                estado=EstadoMembresia.ACTIVA,
                vencimiento=miembro.vencimiento or date.today(),
                rol=miembro.rol,
                parcelaId=parcela.id,
                arancelId=unidad.arancelId,
            )
            db.add(membresia)
            created_membresias.append(membresia.id)

    db.commit()
    return ImportResponse(
        parcelas=created_parcelas,
        socios=created_socios,
        membresias=created_membresias,
    )


@router.post("/{parcela_id}/estado")
def set_batch_estado_parcela(parcela_id: str, data: MembresiaUpdate, db: Session = Depends(get_db)):
    """Set estado on all membresias of a parcela (batch, RQ 5)."""
    parcela = db.query(Parcela).filter(Parcela.id == parcela_id).first()
    if parcela is None:
        raise HTTPException(status_code=404, detail=f"Parcela {parcela_id} not found")
    if data.estado is not None:
        for m in db.query(Membresia).filter(Membresia.parcelaId == parcela_id).all():
            m.estado = data.estado
        db.commit()
    return {"parcelaId": parcela_id, "estado": data.estado}


@router.put("/{parcela_id}/vencimiento")
def set_batch_vencimiento_parcela(parcela_id: str, data: MembresiaUpdate, db: Session = Depends(get_db)):
    """Set vencimiento on all membresias of a parcela (batch, RQ 5)."""
    parcela = db.query(Parcela).filter(Parcela.id == parcela_id).first()
    if parcela is None:
        raise HTTPException(status_code=404, detail=f"Parcela {parcela_id} not found")
    if data.vencimiento is not None:
        for m in db.query(Membresia).filter(Membresia.parcelaId == parcela_id).all():
            m.vencimiento = data.vencimiento
        db.commit()
    return {"parcelaId": parcela_id, "vencimiento": data.vencimiento}


@router.get("/{parcela_id}", response_model=ParcelaResponse)
def get_parcela(parcela_id: str, db: Session = Depends(get_db)):
    """Get a parcela by id."""
    parcela = db.query(Parcela).filter(Parcela.id == parcela_id).first()
    if parcela is None:
        raise HTTPException(status_code=404, detail=f"Parcela {parcela_id} not found")
    return parcela


@router.put("/{parcela_id}", response_model=ParcelaResponse)
def update_parcela(parcela_id: str, data: ParcelaUpdate, db: Session = Depends(get_db)):
    """Update a parcela."""
    parcela = db.query(Parcela).filter(Parcela.id == parcela_id).first()
    if parcela is None:
        raise HTTPException(status_code=404, detail=f"Parcela {parcela_id} not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(parcela, key, value)
    db.commit()
    db.refresh(parcela)
    return parcela


@router.delete("/{parcela_id}", status_code=204)
def delete_parcela(parcela_id: str, db: Session = Depends(get_db)):
    """Delete a parcela and all its associated memberships."""
    parcela = db.query(Parcela).filter(Parcela.id == parcela_id).first()
    if parcela is None:
        raise HTTPException(status_code=404, detail=f"Parcela {parcela_id} not found")
    db.query(Membresia).filter(Membresia.parcelaId == parcela_id).delete()
    db.delete(parcela)
    db.commit()
