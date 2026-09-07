"""Export service — serialize resource rows into CSV or XLSX downloads.

Mirror of the import pipeline: reads a config-registry entry for a resource,
queries ALL rows (never paginated), resolves FK ids to readable names, and
renders the requested format.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime
from enum import Enum
from typing import Any

from sqlalchemy.orm import Session

from backend.models.parcela import Parcela
from backend.models.socio import Socio
from backend.services.importer.export_config import (
    RESOLVERS,
    get_export_headers,
    get_model,
)

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CSV_MEDIA_TYPE = "text/csv; charset=utf-8"


def _cell_value(value: Any) -> Any:
    """Serialize a model attribute into an export-friendly cell value."""
    if value is None:
        return ""
    if isinstance(value, Enum):
        # Store enum NAMES (TITULAR/CHICA); expose values (Titular/Chica).
        return value.value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, bool):
        return "Sí" if value else "No"
    return value


def _build_lookups(db: Session, resource: str) -> dict[str, dict[str, str]]:
    """Build label lookup maps for FK-id columns (socioId -> socio nombre)."""
    lookups: dict[str, dict[str, str]] = {}
    for field, (table, _label) in RESOLVERS.get(resource, {}).items():
        if table == "socios":
            rows = db.query(Socio.id, Socio.nombre).all()
            lookups[field] = {socio_id: nombre for socio_id, nombre in rows}
        elif table == "parcelas":
            rows = db.query(Parcela.id, Parcela.nombre).all()
            lookups[field] = {parcela_id: nombre for parcela_id, nombre in rows}
    return lookups


def _rows_for_resource(db: Session, resource: str) -> list[dict[str, Any]]:
    """Return all rows of the resource as flat dicts (never paginated)."""
    model = get_model(resource)
    headers = get_export_headers(resource)
    lookups = _build_lookups(db, resource)

    # Stable ordering by primary key where present, otherwise natural order.
    pk = getattr(model, "id", None)
    query = db.query(model)
    if pk is not None:
        query = query.order_by(pk)
    records = query.all()

    rows: list[dict[str, Any]] = []
    for record in records:
        row: dict[str, Any] = {}
        for _label, field in headers:
            raw = getattr(record, field, None)
            if field in lookups:
                raw = lookups[field].get(raw, "")
            row[field] = _cell_value(raw)
        rows.append(row)
    return rows


def export_to_csv(db: Session, resource: str) -> str:
    """Render ALL rows of a resource as a UTF-8-BOM CSV string."""
    headers = get_export_headers(resource)
    rows = _rows_for_resource(db, resource)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([label for label, _ in headers])
    for row in rows:
        writer.writerow([row[field] for _label, field in headers])
    # BOM so Excel opens accents correctly.
    return "\ufeff" + buffer.getvalue()


def export_to_xlsx(db: Session, resource: str) -> bytes:
    """Render ALL rows of a resource as an XLSX workbook (bytes)."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    headers = get_export_headers(resource)
    rows = _rows_for_resource(db, resource)

    wb = Workbook()
    ws = wb.active
    ws.title = "Export"
    ws.append([label for label, _ in headers])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for row in rows:
        ws.append([row[field] for _label, field in headers])

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def export_resource(db: Session, resource: str, fmt: str) -> tuple[str, bytes, str]:
    """Return ``(filename, content, media_type)`` for a resource export."""
    today = date.today().isoformat()
    if fmt == "csv":
        content = export_to_csv(db, resource).encode("utf-8")
        return f"{resource}_{today}.csv", content, CSV_MEDIA_TYPE
    if fmt == "xlsx":
        content = export_to_xlsx(db, resource)
        return f"{resource}_{today}.xlsx", content, XLSX_MEDIA_TYPE
    raise ValueError(f"Unsupported export format: {fmt}")