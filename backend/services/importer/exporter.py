"""Export helpers for the bulk import engine.

Generates an XLSX column template with the resource's canonical English
headers, an errors CSV (``fila,campo,error``), and a detailed execute log JSON.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from backend.services.importer.config import get_config


def build_template(resource: str) -> bytes:
    """Generate an XLSX template (BytesIO) with canonical English headers."""
    from openpyxl import Workbook

    config = get_config(resource)
    headers = config.get("template_headers", list(config["headers"].values()))

    wb = Workbook()
    ws = wb.active
    ws.title = "Import"
    ws.append(headers)

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def build_error_csv(errors: list[Any]) -> str:
    """Render errors as a CSV string with columns ``fila,campo,error``."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["fila", "campo", "error"])
    for err in errors:
        writer.writerow(
            [
                getattr(err, "fila", 0),
                getattr(err, "campo", ""),
                getattr(err, "error", ""),
            ]
        )
    return buffer.getvalue()


def build_log_json(result: Any) -> str:
    """Render an execute result as the detailed download log (JSON)."""
    payload: dict[str, Any] = {
        "importados": getattr(result, "importados", 0),
        "fallidos": getattr(result, "fallidos", 0),
        "omitidos": getattr(result, "omitidos", 0),
        "rows": [
            {
                "fila": getattr(row, "fila", 0),
                "outcome": getattr(row, "outcome", ""),
                "id": getattr(row, "id", None),
                "errores": [
                    {
                        "fila": getattr(err, "fila", 0),
                        "campo": getattr(err, "campo", ""),
                        "error": getattr(err, "error", ""),
                    }
                    for err in getattr(row, "errores", [])
                ],
            }
            for row in getattr(result, "rows", [])
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
