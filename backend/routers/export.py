"""Generic data export endpoints.

``GET /api/export/{resource}?format=csv|xlsx`` returns a complete download of
the resource (all rows — never paginated) as CSV (UTF-8 BOM) or XLSX.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.services.importer.export_config import (
    get_export_headers,
    get_model,
)
from backend.services.importer.export_service import export_resource

router = APIRouter(prefix="/api/export", tags=["export"])

# The registry decides which resources are exportable.
EXPORTABLE_RESOURCES = frozenset(
    {
        "socios",
        "pagos",
        "parcelas",
        "membresias",
        "aranceles",
        "notificaciones",
    }
)


@router.get("/{resource}")
def export_data(
    resource: str,
    format: str = Query("csv", pattern="^(csv|xlsx)$"),
    db: Session = Depends(get_db),
):
    """Export all rows of a resource as CSV (default) or XLSX."""
    if resource not in EXPORTABLE_RESOURCES:
        raise HTTPException(
            status_code=404,
            detail=f"Recurso '{resource}' no tiene export configurado.",
        )
    try:
        get_model(resource)
        get_export_headers(resource)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None

    filename, content, media_type = export_resource(db, resource, format)
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )