"""Bulk import schemas for the generic data-import engine.

Distinct from ``backend.schemas.import_`` (unit-share import for parcelas).
These are the canonical shapes shared by all resources wired into
``backend.services.importer.config.IMPORT_CONFIGS`` (currently only ``socios``).
"""

from datetime import date
from typing import Any

from pydantic import BaseModel, Field

from backend.schemas.common import OrmConfig


class ImportSocioRow(BaseModel):
    """Per-row socios payload produced by the import engine.

    Field conventions mirror ``backend.models.socio.Socio``: ``fechaAlta`` is
    optional in the parsed row and defaults to today at insert time; ``activo``
    defaults to True.
    """

    nombre: str
    dni: str
    telefono: str = ""
    email: str = ""
    direccion: str = ""
    fechaAlta: date | None = None
    activo: bool = True


class ColumnMapping(OrmConfig, BaseModel):
    """Detected header -> canonical field mapping."""

    resource: str
    columns: dict[str, str]
    ignored_columns: list[str] = Field(default_factory=list)


class FieldError(OrmConfig, BaseModel):
    """A single per-row, per-field validation error."""

    fila: int
    campo: str
    error: str


class RowData(OrmConfig, BaseModel):
    """A single normalized/preview row with an optional skip flag.

    ``data`` carries the canonical (camelCase) fields of the resource's row
    schema; the client may edit these between preview and execute.
    """

    skip: bool = False
    data: dict[str, Any]


class ImportStats(OrmConfig, BaseModel):
    """Aggregate statistics for a preview."""

    total: int
    validas: int
    con_errores: int
    a_saltar: int = 0


class PreviewResult(OrmConfig, BaseModel):
    """Canonical preview response: mapped columns, rows, warnings, stats."""

    resource: str
    columns: dict[str, str]
    ignored_columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]]
    stats: ImportStats
    errors: list[FieldError] = Field(default_factory=list)


class ExecuteRow(OrmConfig, BaseModel):
    """Per-row execute outcome."""

    fila: int
    outcome: str  # "importado" | "fallido" | "omitido"
    id: str | None = None
    errores: list[FieldError] = Field(default_factory=list)


class ExecuteResult(OrmConfig, BaseModel):
    """Canonical execute response."""

    importados: int
    fallidos: int
    omitidos: int
    rows: list[ExecuteRow]


# Common limit constants shared by preview/execute (enforced at endpoints later).
MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_PARSEABLE_ROWS = 10_000
MAX_PREVIEW_ROWS = 5_000
