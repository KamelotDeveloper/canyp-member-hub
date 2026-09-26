"""Socio CRUD + bulk import endpoints."""

import uuid
from datetime import date
from io import BytesIO

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.membresia import Membresia
from backend.models.notificacion import Notificacion
from backend.models.pago import Pago
from backend.models.socio import Socio
from backend.models.usuario import Usuario
from backend.schemas.import_bulk import (
    MAX_FILE_BYTES,
    MAX_PARSEABLE_ROWS,
    MAX_PREVIEW_ROWS,
    PreviewResult,
    RowData,
)
from backend.schemas.membresia import MembresiaResponse
from backend.schemas.socio import SocioCreate, SocioResponse, SocioUpdate
from backend.security import get_current_user
from backend.services.cuota_social import crear_cuota_social
from backend.services.estado_socio import estados_socio
from backend.services.importer.exporter import build_template
from backend.services.importer.parser import ParseError
from backend.services.importer.pipeline import execute_rows, preview_file
from backend.services.numeracion_socio import siguiente_numero_socio

router = APIRouter(prefix="/api/socios", tags=["socios"])

# Carnet foto: 5 MB cap, resized to at most 800px on the longest side, JPEG q85.
MAX_FOTO_BYTES = 5 * 1024 * 1024
MAX_FOTO_DIMENSION = 800
FOTO_JPEG_QUALITY = 85

# Serialized socio fields: every real column except the carnet `foto` bytes.
COLUMNAS_SOCIO = [c for c in Socio.__table__.columns if c.name != "foto"]


def _con_estado(socios: list[Socio], db: Session) -> list[dict]:
    """Attach the server-authoritative state to each socio row (EST-01).

    The state is never persisted, so it cannot be read off the ORM object: it is
    resolved for the whole listing in ONE grouped query and injected here. Only
    real columns are serialized (`foto` bytes never are), so the payload cannot
    drift from the model nor leak the carnet image.
    """
    estados = estados_socio(db, [s.id for s in socios])
    return [
        {
            **{c.name: getattr(socio, c.name) for c in COLUMNAS_SOCIO},
            "tieneFoto": socio.tieneFoto,
            "estado": estados[socio.id],
            "nominacion": estados[socio.id].value,
        }
        for socio in socios
    ]


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
    return _con_estado(q.order_by(Socio.nombre).all(), db)


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
    return _con_estado([socio], db)[0]


@router.post("/{socio_id}/foto")
def upload_socio_foto(
    socio_id: str,
    foto: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload (or replace) the carnet photo for a social member.

    Multipart field ``foto``; only image content types are accepted, the raw
    size cap is 5 MB, and the stored photo is resized to at most 800px on the
    longest side, saved as JPEG (quality 85) into ``socio.foto`` (bytea).
    """
    socio = db.query(Socio).filter(Socio.id == socio_id).first()
    if socio is None:
        raise HTTPException(status_code=404, detail=f"Socio {socio_id} not found")

    content = foto.file.read()
    if len(content) > MAX_FOTO_BYTES:
        raise HTTPException(
            status_code=413,
            detail="La foto supera el límite de 5 MB permitido.",
        )

    content_type = (foto.content_type or "").lower()
    if not content_type.startswith("image/"):
        raise HTTPException(
            status_code=415,
            detail="El archivo debe ser una imagen (image/*).",
        )

    try:
        img = Image.open(BytesIO(content))
        img.load()
    except (UnidentifiedImageError, OSError, ValueError):
        raise HTTPException(
            status_code=415,
            detail="El archivo no es una imagen válida.",
        )

    # Degrade to RGB (JPEG has no alpha/single-channel support) and resize.
    img = img.convert("RGB")
    longest_side = max(img.size)
    if longest_side > MAX_FOTO_DIMENSION:
        ratio = MAX_FOTO_DIMENSION / longest_side
        new_size = (
            max(1, round(img.width * ratio)),
            max(1, round(img.height * ratio)),
        )
        img = img.resize(new_size, Image.LANCZOS)

    buffer = BytesIO()
    img.save(buffer, format="JPEG", quality=FOTO_JPEG_QUALITY)
    socio.foto = buffer.getvalue()
    db.commit()
    return {"tieneFoto": True}


@router.get("/{socio_id}/foto")
def get_socio_foto(socio_id: str, db: Session = Depends(get_db)):
    """Serve the stored carnet photo as image/jpeg."""
    socio = db.query(Socio).filter(Socio.id == socio_id).first()
    if socio is None or socio.foto is None:
        raise HTTPException(
            status_code=404,
            detail=f"Socio {socio_id} not found or has no foto",
        )
    return Response(content=socio.foto, media_type="image/jpeg")


@router.delete("/{socio_id}/foto", status_code=204)
def delete_socio_foto(socio_id: str, db: Session = Depends(get_db)):
    """Remove the carnet photo (falls back to initials on the printed carnet)."""
    socio = db.query(Socio).filter(Socio.id == socio_id).first()
    if socio is None:
        raise HTTPException(status_code=404, detail=f"Socio {socio_id} not found")
    socio.foto = None
    db.commit()
    return Response(status_code=204)


@router.post("", response_model=SocioResponse, status_code=201)
def create_socio(
    data: SocioCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Create a new socio."""
    socio_id = data.id or f"s{uuid.uuid4().hex[:8]}"

    # Carnet: honor an explicit non-empty numeroSocio, otherwise auto-assign the
    # next sequential member number (atomic, advisory-locked on Postgres).
    numero_socio = None
    if data.numero_socio is None:
        numero_socio = siguiente_numero_socio(db)
    elif data.numero_socio.strip():
        numero_socio = data.numero_socio.strip()
    else:
        raise HTTPException(
            status_code=422,
            detail="numeroSocio no puede estar vacío.",
        )

    socio = Socio(
        id=socio_id,
        fechaAlta=data.fechaAlta or date.today(),
        numero_socio=numero_socio,
        created_by=current_user.id,
        **data.model_dump(exclude={"id", "fechaAlta", "numero_socio"}),
    )
    db.add(socio)
    # Every socio owes the cuota social (CS-02): it is created together with
    # the socio, inside the same transaction, so a rolled-back socio never
    # leaves an orphan cuota row behind.
    crear_cuota_social(db, socio)
    db.commit()
    db.refresh(socio)
    return _con_estado([socio], db)[0]


@router.put("/{socio_id}", response_model=SocioResponse)
def update_socio(
    socio_id: str,
    data: SocioUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Update a socio."""
    socio = db.query(Socio).filter(Socio.id == socio_id).first()
    if socio is None:
        raise HTTPException(status_code=404, detail=f"Socio {socio_id} not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(socio, key, value)
    socio.updated_by = current_user.id
    db.commit()
    db.refresh(socio)
    return _con_estado([socio], db)[0]


@router.delete("/{socio_id}", status_code=204)
def delete_socio(socio_id: str, db: Session = Depends(get_db)):
    """Delete a socio.

    Before deleting, for every unit where this socio is Titular, the first
    Integrante (by Membresia.id ascending as a proxy for creation order —
    there is no created_at column) is promoted to Titular.  If the unit has
    no other members the Titular role is simply lost when the membership is
    deleted.
    """
    socio = db.query(Socio).filter(Socio.id == socio_id).first()
    if socio is None:
        raise HTTPException(status_code=404, detail=f"Socio {socio_id} not found")

    # Contable: un socio con pagos registrados NO se borra — se da de baja.
    # El historial de comprobantes se conserva para poder atender reclamos.
    if db.query(Pago).filter(Pago.socioId == socio_id).first():
        raise HTTPException(
            status_code=409,
            detail=(
                "No se puede eliminar el socio porque tiene pagos registrados. "
                "Podés darlo de baja para conservar el historial."
            ),
        )

    # Promote Titular → first Integrante in every unit where this socio is Titular.
    titular_membresias = (
        db.query(Membresia)
        .filter(Membresia.socioId == socio_id, Membresia.rol == "Titular")
        .all()
    )
    for tm in titular_membresias:
        # Build the unit filter: same parcelaId (when set) or same area+predio.
        if tm.parcelaId:
            unit_filter = (
                (Membresia.parcelaId == tm.parcelaId)
                & (Membresia.socioId != socio_id)
            )
        else:
            unit_filter = (
                (Membresia.parcelaId.is_(None))
                & (Membresia.area == tm.area)
                & (Membresia.predio == tm.predio)
                & (Membresia.socioId != socio_id)
            )
        successor = (
            db.query(Membresia)
            .filter(unit_filter)
            .order_by(Membresia.id.asc())
            .first()
        )
        if successor:
            successor.rol = "Titular"

    # Cascade: delete dependents before socio.
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
