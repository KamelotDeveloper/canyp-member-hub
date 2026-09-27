"""Arancel CRUD endpoints."""

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from backend.database import get_db
from backend.models.arancel import Arancel
from backend.models.enums import Area, CategoriaParcela, ConceptoCobro, Predio
from backend.models.membresia import Membresia
from backend.models.pago import PagoItem
from backend.models.usuario import Usuario
from backend.schemas.arancel import ArancelCreate, ArancelResponse, ArancelUpdate
from backend.security import get_current_user
from backend.services.historial_aranceles import actualizar_monto_arancel

router = APIRouter(prefix="/api/aranceles", tags=["aranceles"])


def _checar_tupla(
    db: Session,
    area: Area,
    predio: Predio,
    categoria: CategoriaParcela | None,
    concepto: ConceptoCobro,
    *,
    excluir_id: str | None = None,
) -> None:
    """Rechaza con 409 una tupla `(area, predio, categoria, concepto)` repetida.

    No hay índice UNIQUE que la garantice: una `categoria` NULL nunca colisiona
    ni en SQLite ni en Postgres, así que el duplicado se cuela igual y la
    resolución queda ambigua. El guard vive acá (D1/D4, ReQ-006) y nombra la fila
    culpable para que el operador sepa cuál editar en vez de cuál borrar.
    """
    q = db.query(Arancel).filter(
        Arancel.area == area,
        Arancel.predio == predio,
        Arancel.concepto == concepto,
    )
    if categoria is None:
        q = q.filter(Arancel.categoria.is_(None))
    else:
        q = q.filter(Arancel.categoria == categoria)
    if excluir_id is not None:
        q = q.filter(Arancel.id != excluir_id)

    dup = q.first()
    if dup is None:
        return
    raise HTTPException(
        status_code=409,
        detail=(
            f"Ya existe un arancel con area={dup.area.value}, "
            f"predio={dup.predio.value}, "
            f"categoria={dup.categoria.value if dup.categoria else '—'}, "
            f"concepto={dup.concepto.value} (id={dup.id})"
        ),
    )


def _motivo_bloqueo(db: Session, arancel_id: str) -> str | None:
    """Por qué no se puede borrar un arancel, nombrando las filas que lo bloquean.

    `pago_items.arancelId` es un FK real de la base, pero `membresias.arancelId`
    es una referencia blanda sin FK: la base protege sólo la mitad del grafo.
    Por eso se cuentan las dos y se responden con 409 en vez de reventar como
    500 (D5, ReQ-007).
    """
    partes = []
    for modelo, etiqueta in ((PagoItem, "pago_items"), (Membresia, "membresias")):
        q = db.query(modelo.id).filter(modelo.arancelId == arancel_id)
        total = q.count()
        if not total:
            continue
        ids = [row[0] for row in q.limit(5).all()]
        muestra = ", ".join(ids) + (", ..." if total > len(ids) else "")
        partes.append(f"{total} {etiqueta} ({muestra})")
    if not partes:
        return None
    return f"No se puede eliminar el arancel {arancel_id}: " + "; ".join(partes)


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
    _checar_tupla(db, data.area, data.predio, data.categoria, data.concepto)
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
    """Fully update an arancel: nombre, area, predio, monto, categoria, concepto.

    Changing the monto pushes the old value to historico (same business rule as
    the /monto endpoint). Editing any other field alone does not.
    """
    arancel = db.query(Arancel).filter(Arancel.id == arancel_id).first()
    if arancel is None:
        raise HTTPException(status_code=404, detail=f"Arancel {arancel_id} not found")

    updates = data.model_dump(exclude_unset=True)
    monto = updates.pop("monto", None)

    # `concepto` is NOT NULL: an explicit null is a client bug, not a request to
    # clear the column (D4).
    if "concepto" in updates and updates["concepto"] is None:
        raise HTTPException(status_code=422, detail="concepto cannot be null")

    # Uniqueness is checked against the EFFECTIVE tuple — the update's own
    # area/predio/categoria merged over the stored row — and against every OTHER
    # row, so re-saving an arancel without touching its identity is a no-op and
    # not a self-collision (ReQ-006).
    concepto = updates.get("concepto", arancel.concepto)
    _checar_tupla(
        db,
        updates.get("area", arancel.area),
        updates.get("predio", arancel.predio),
        updates.get("categoria", arancel.categoria),
        concepto,
        excluir_id=arancel.id,
    )

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
    """Delete an arancel, refusing while something still points at it (D5)."""
    arancel = db.query(Arancel).filter(Arancel.id == arancel_id).first()
    if arancel is None:
        raise HTTPException(status_code=404, detail=f"Arancel {arancel_id} not found")

    motivo = _motivo_bloqueo(db, arancel_id)
    if motivo is not None:
        raise HTTPException(status_code=409, detail=motivo)

    try:
        db.delete(arancel)
        db.commit()
    except IntegrityError as e:
        # Red de seguridad: si mañana aparece otra FK, el catálogo responde 409
        # con un motivo legible en vez de un 500 (D5, ReQ-007).
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"No se puede eliminar el arancel {arancel_id}: hay filas que lo referencian",
        ) from e


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
