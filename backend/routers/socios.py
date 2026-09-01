"""Socio CRUD + bulk import endpoints."""

import uuid
from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.membresia import Membresia
from backend.models.notificacion import Notificacion
from backend.models.socio import Socio
from backend.schemas.import_bulk import (
    MAX_FILE_BYTES,
    MAX_PARSEABLE_ROWS,
    MAX_PREVIEW_ROWS,
    PreviewResult,
    RowData,
)
from backend.schemas.membresia import MembresiaResponse
from backend.schemas.socio import SocioCreate, SocioResponse, SocioUpdate
from backend.services.importer.exporter import build_template
from backend.services.importer.parser import ParseError
from backend.services.importer.pipeline import execute_rows, preview_file

router = APIRouter(prefix="/api/socios", tags=["socios"])


class ExecuteImportRequest(BaseModel):
    """Body for POST /import/execute — edited rows with skip flags."""

    rows: list[RowData]


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


@router.get("/import/template")
def import_template():
    """Return the socios import template as an XLSX download.

    Registered before the ``/{socio_id}`` dynamic route so ``template`` is not
    captured as a socio id.
    """
    content = build_template("socios")
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": 'attachment; filename="socios_import_template.xlsx"'
        },
    )


@router.post("/import/preview", response_model=PreviewResult)
def import_preview(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Parse and validate an uploaded socios file, returning a canonical preview.

    Enforces: max file size 10 MB (413), max 10,000 parseable rows (400), and
    returns at most 5,000 preview rows (client paginates).
    """
    content = file.file.read()
    if len(content) > MAX_FILE_BYTES:
        mb = MAX_FILE_BYTES // (1024 * 1024)
        raise HTTPException(
            status_code=413,
            detail=f"El archivo supera el límite de {mb} MB permitido.",
        )

    try:
        result = preview_file(file.filename or "", content, "socios", db)
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
    return execute_rows(payload.rows, "socios", db)


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
