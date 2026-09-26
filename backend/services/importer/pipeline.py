"""Orchestration for the bulk import engine.

``preview_file`` runs parse -> decode -> map -> normalize -> validate and
returns a canonical :class:`PreviewResult`. ``execute_rows`` inserts verified
rows inside a single transaction using per-row SAVEPOINTs (``db.begin_nested()``)
so one failing row does not abort the rest of the batch. No upsert — duplicate
dnis are rejected rather than updated.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.schemas.import_bulk import (
    ExecuteResult,
    ExecuteRow,
    FieldError,
    ImportStats,
    PreviewResult,
)
from backend.services.importer.config import get_config
from backend.services.importer.mapper import map_headers
from backend.services.importer.parser import parse_file
from backend.services.importer.validator import validate_rows


def _rows_to_dicts(rows: list[list[str]], header: list[str]) -> list[dict[str, str]]:
    """Convert parsed row lists into dicts keyed by original header text."""
    result: list[dict[str, str]] = []
    for row in rows:
        d: dict[str, str] = {}
        for i, cell in enumerate(row):
            key = header[i] if i < len(header) else f"_col{i}"
            d[key] = cell
        result.append(d)
    return result


def preview_file(
    filename: str,
    raw: bytes,
    resource: str,
    db: Session,
) -> PreviewResult:
    """Parse and validate an uploaded file into a canonical preview result."""
    parsed = parse_file(filename, raw)
    header = parsed[0]
    body = parsed[1:]

    config = get_config(resource)
    columns, ignored = map_headers(header, resource)

    row_dicts = _rows_to_dicts(body, header)
    valid_rows, errors = validate_rows(row_dicts, columns, resource, db=db)

    total = len(body)
    con_errores = len(errors)
    stats = ImportStats(total=total, validas=len(valid_rows), con_errores=con_errores)

    return PreviewResult(
        resource=resource,
        columns=columns,
        ignored_columns=ignored,
        rows=valid_rows,
        stats=stats,
        errors=errors,
    )


def _build_instance(data: dict[str, Any], config: dict[str, Any]):
    """Instantiate the resource SQLAlchemy model from canonical row data.

    ``data`` carries ISO date strings (mode="json"); the SQLAlchemy Date column
    requires a real ``datetime.date`` object, so convert ``fechaAlta`` back.
    """
    from datetime import date

    model_cls = config["model_cls"]
    fecha_alta = _parse_iso_date(data.get("fechaAlta")) or date.today()
    return model_cls(
        id=f"s{uuid.uuid4().hex[:8]}",
        fechaAlta=fecha_alta,
        **{k: v for k, v in data.items() if k != "fechaAlta"},
    )


def _parse_iso_date(value: Any) -> date | None:
    """Parse an ISO ``YYYY-MM-DD`` string into a ``date`` (or None)."""
    from datetime import date, datetime

    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _prepare_model_data(row: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Re-validate a raw edited row against the resource schema.

    The client may edit cells between preview and execute, so the server
    re-runs the resource Pydantic schema on each row. Returns the validated
    canonical data, or raises the pydantic ``ValidationError``.
    """
    model_cls = config["model"]
    return model_cls(**row).model_dump(mode="json")


def _dedupe_context(
    config: dict[str, Any], db: Session
) -> tuple[str | None, set[str]]:
    """Return the current dedupe key and the set of DB values already present."""
    dedupe_key = config.get("dedupe_key")
    existing: set[str] = set()
    model_cls = config.get("model_cls")
    if db is not None and dedupe_key and model_cls is not None:
        col = getattr(model_cls, dedupe_key, None)
        if col is not None:
            existing = {str(v) for (v,) in db.query(col).all() if v is not None}
    return dedupe_key, existing


def _validation_errors(exc: ValidationError, fila: int) -> list[FieldError]:
    """Convert pydantic errors into per-field errors for the given row."""
    errores: list[FieldError] = []
    for err in exc.errors():
        loc = err.get("loc", ())
        campo = str(loc[0]) if loc else "row"
        errores.append(FieldError(fila=fila, campo=campo, error=err.get("msg", "invalid")))
    return errores


def execute_rows(
    rows: list[dict[str, Any]],
    resource: str,
    db: Session,
) -> ExecuteResult:
    """Execute a batch of edited rows.

    ``rows`` is a list of ``{skip: bool, data: {canonical fields}}`` dicts
    (mirroring :class:`RowData`). Each non-skipped row is re-validated and
    inserted inside its own SAVEPOINT; the whole batch is committed once.

    A resource config may declare an ``after_insert(instance, db)`` hook for
    per-row follow-up rows. It runs inside that row's SAVEPOINT, so dependents
    roll back with the row instead of surviving as orphans.
    """
    config = get_config(resource)
    dedupe_key, existing = _dedupe_context(config, db)
    seen: set[str] = set()

    result_rows: list[ExecuteRow] = []
    importados = 0
    fallidos = 0
    omitidos = 0

    for idx, item in enumerate(rows):
        fila = idx + 2
        if isinstance(item, dict):
            skip = bool(item.get("skip", False))
            data = dict(item.get("data") or {})
        else:
            skip = bool(getattr(item, "skip", False))
            data = dict(getattr(item, "data", {}) or {})

        if skip:
            omitidos += 1
            result_rows.append(ExecuteRow(fila=fila, outcome="omitido", errores=[]))
            continue

        # Dedupe check (re-evaluated at execute time too).
        if dedupe_key:
            value = data.get(dedupe_key)
            if isinstance(value, str) and value.strip():
                norm_value = value.strip()
                if norm_value in seen or norm_value in existing:
                    fallidos += 1
                    result_rows.append(
                        ExecuteRow(
                            fila=fila,
                            outcome="fallido",
                            errores=[
                                FieldError(
                                    fila=fila,
                                    campo=dedupe_key,
                                    error=f"Duplicate {dedupe_key} '{norm_value}'",
                                )
                            ],
                        )
                    )
                    continue
                seen.add(norm_value)

        # Re-validate against the resource schema.
        try:
            model_data = _prepare_model_data(data, config)
        except ValidationError as exc:
            fallidos += 1
            result_rows.append(
                ExecuteRow(fila=fila, outcome="fallido", errores=_validation_errors(exc, fila))
            )
            continue

        # Insert inside a SAVEPOINT; roll back only this row on failure.
        try:
            with db.begin_nested():
                builder = config.get("build")
                instance = (
                    builder(model_data, db)
                    if builder
                    else _build_instance(model_data, config)
                )
                db.add(instance)
                db.flush()
                new_id = instance.id
                # Per-row follow-up work (e.g. the cuota social membership every
                # socio owes). It runs INSIDE the SAVEPOINT, so a row that fails
                # afterwards rolls back its dependents too, not just itself.
                after_insert = config.get("after_insert")
                if after_insert:
                    after_insert(instance, db)
            importados += 1
            result_rows.append(ExecuteRow(fila=fila, outcome="importado", id=new_id))
        except (SQLAlchemyError, ValueError) as exc:
            fallidos += 1
            message = (
                "Value violates a uniqueness constraint"
                if getattr(exc, "orig", None) is not None
                else str(exc)
            )
            result_rows.append(
                ExecuteRow(
                    fila=fila,
                    outcome="fallido",
                    errores=[
                        FieldError(fila=fila, campo=dedupe_key or "row", error=message)
                    ],
                )
            )

    db.commit()

    return ExecuteResult(
        importados=importados,
        fallidos=fallidos,
        omitidos=omitidos,
        rows=result_rows,
    )
