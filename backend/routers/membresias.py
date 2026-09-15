"""Membresia CRUD endpoints."""

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.enums import EstadoMembresia
from backend.models.membresia import Membresia
from backend.models.usuario import Usuario
from backend.schemas.import_bulk import (
    MAX_FILE_BYTES,
    MAX_PARSEABLE_ROWS,
    MAX_PREVIEW_ROWS,
    PreviewResult,
    RowData,
)
from backend.schemas.membresia import MembresiaCreate, MembresiaResponse, MembresiaUpdate
from backend.security import get_current_user
from backend.services.estado_visual import calcular_estado_visual
from backend.services.importer.exporter import build_template
from backend.services.importer.parser import ParseError
from backend.services.importer.pipeline import execute_rows, preview_file

router = APIRouter(prefix="/api/membresias", tags=["membresias"])


class ExecuteImportRequest(BaseModel):
    """Body for POST /import/execute — edited rows with skip flags."""

    rows: list[RowData]


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


def _validate_socio_id(db: Session, socio_id: str | None) -> None:
    """Server-side socioId FK validation.

    SQLite FKs are OFF against the live DB, so a bare insert with a bogus
    socioId would silently succeed. Reject it here instead.
    """
    if socio_id is None:
        return
    from backend.models.socio import Socio

    exists = db.query(Socio).filter(Socio.id == socio_id).first()
    if exists is None:
        raise HTTPException(status_code=422, detail=f"Socio {socio_id} not found")


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


@router.get("/import/template")
def import_template():
    """Return the membresias import template as an XLSX download.

    Registered before the ``/{membresia_id}`` dynamic route so ``import`` is
    not captured as a membresia id.
    """
    content = build_template("membresias")
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": 'attachment; filename="membresias_import_template.xlsx"'
        },
    )


@router.post("/import/preview", response_model=PreviewResult)
def import_preview(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Parse and validate an uploaded membresias file, returning a canonical preview.

    Enforces: max file size 10 MB (413), max 10,000 parseable rows (400), and
    returns at most 5,000 preview rows (client paginates). Each row must link to
    an existing socio (by DNI); missing socios fail with a per-row error.
    """
    content = file.file.read()
    if len(content) > MAX_FILE_BYTES:
        mb = MAX_FILE_BYTES // (1024 * 1024)
        raise HTTPException(
            status_code=413,
            detail=f"El archivo supera el límite de {mb} MB permitido.",
        )

    try:
        result = preview_file(file.filename or "", content, "membresias", db)
    except ParseError as exc:
        if str(MAX_PARSEABLE_ROWS) in str(exc):
            # Row-cap breach raised by the parser — surface a Spanish limit message.
            raise HTTPException(
                status_code=400,
                detail=(
                    "El archivo supera las "
                    f"{str(MAX_PARSEABLE_ROWS)} filas permitidas."
                ),
            )
        raise HTTPException(status_code=400, detail=str(exc))

    # Server-side preview cap: only the first MAX_PREVIEW_ROWS rows are returned.
    result.rows = result.rows[:MAX_PREVIEW_ROWS]
    return result


@router.post("/import/execute", status_code=201)
def import_execute(payload: ExecuteImportRequest, db: Session = Depends(get_db)):
    """Execute a batch of edited rows, applying per-row SAVEPOINTs.

    The whole batch imports in one transaction; a failing row is rolled back
    at its savepoint without aborting the remaining valid rows. Rejects payloads
    with more than 10,000 rows.
    """
    if len(payload.rows) > MAX_PARSEABLE_ROWS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"El lote supera las {MAX_PARSEABLE_ROWS:,} filas permitidas."
            ).replace(",", "."),
        )
    return execute_rows(payload.rows, "membresias", db)


@router.get("/{membresia_id}", response_model=MembresiaResponse)
def get_membresia(membresia_id: str, db: Session = Depends(get_db)):
    """Get a membresia by id."""
    m = db.query(Membresia).filter(Membresia.id == membresia_id).first()
    if m is None:
        raise HTTPException(status_code=404, detail=f"Membresia {membresia_id} not found")
    return m


@router.post("", response_model=MembresiaResponse, status_code=201)
def create_membresia(
    data: MembresiaCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Create a new membresia."""
    _validate_parcela_id(db, data.parcelaId)
    _validate_socio_id(db, data.socioId)
    membresia_id = data.id or f"m{uuid.uuid4().hex[:8]}"
    membresia = Membresia(
        id=membresia_id,
        created_by=current_user.id,
        **data.model_dump(exclude={"id"}),
    )
    db.add(membresia)
    db.commit()
    db.refresh(membresia)
    return membresia


@router.put("/{membresia_id}", response_model=MembresiaResponse)
def update_membresia(
    membresia_id: str,
    data: MembresiaUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Update a membresia."""
    m = db.query(Membresia).filter(Membresia.id == membresia_id).first()
    if m is None:
        raise HTTPException(status_code=404, detail=f"Membresia {membresia_id} not found")
    if data.socioId is not None:
        _validate_socio_id(db, data.socioId)
    if data.parcelaId is not None:
        _validate_parcela_id(db, data.parcelaId)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(m, key, value)
    m.updated_by = current_user.id
    db.commit()
    db.refresh(m)
    return m


@router.delete("/{membresia_id}", status_code=204)
def delete_membresia(membresia_id: str, db: Session = Depends(get_db)):
    """Delete a membresia.

    If the deleted membership was a unit Titular, the first remaining member
    of the same parcela (by Membresia.id ascending, a proxy for creation
    order — there is no created_at column) is promoted to Titular before the
    deletion. If the unit had no other members the Titular role is simply lost.
    """
    m = db.query(Membresia).filter(Membresia.id == membresia_id).first()
    if m is None:
        raise HTTPException(status_code=404, detail=f"Membresia {membresia_id} not found")
    if m.rol == "Titular" and m.parcelaId is not None:
        successor = (
            db.query(Membresia)
            .filter(
                Membresia.parcelaId == m.parcelaId,
                Membresia.id != m.id,
            )
            .order_by(Membresia.id.asc())
            .first()
        )
        if successor:
            successor.rol = "Titular"
    db.delete(m)
    db.commit()


@router.put("/{membresia_id}/estado", response_model=MembresiaResponse)
def set_estado_membresia(
    membresia_id: str,
    data: MembresiaUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Set membresia estado (suspendida/baja)."""
    m = db.query(Membresia).filter(Membresia.id == membresia_id).first()
    if m is None:
        raise HTTPException(status_code=404, detail=f"Membresia {membresia_id} not found")
    if data.estado is not None:
        m.estado = data.estado
    m.updated_by = current_user.id
    db.commit()
    db.refresh(m)
    return m
