"""Per-resource row validation for the bulk import engine.

Applies field normalizers, enforces required fields, runs the resource's
Pydantic schema, and enforces ``dni`` uniqueness both within the upload
(in-file set) and against the database.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from backend.schemas.import_bulk import FieldError
from backend.services.importer.config import get_config


def _build_row_data(row: dict[str, str], columns: dict[str, str]) -> dict[str, Any]:
    """Map raw cells to canonical fields using the detected column mapping.

    ``row`` maps original header text -> raw cell value; ``columns`` maps
    source header -> canonical field. Only mapped columns are carried over;
    ignored columns are dropped here (already reported at mapping time).
    """
    data: dict[str, Any] = {}
    for raw_header, field in columns.items():
        val = row.get(raw_header, "")
        data[field] = val
    return data


def _apply_normalizers(
    data: dict[str, Any],
    config: dict[str, Any],
    errors: list[FieldError],
    fila: int,
) -> dict[str, Any]:
    """Apply per-field normalizers; collect field errors on failure."""
    normalized: dict[str, Any] = {}
    norm = config.get("normalizers", {})
    for field, value in data.items():
        fn = norm.get(field)
        if fn is None:
            normalized[field] = value
            continue
        try:
            normalized[field] = fn(value)
        except ValueError as exc:
            errors.append(FieldError(fila=fila, campo=field, error=str(exc)))
    return normalized


def _apply_defaults(data: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Fill empty optional fields from the resource defaults."""
    out = dict(data)
    defaults = config.get("defaults")
    if callable(defaults):
        defaults = defaults()
    for key, value in (defaults or {}).items():
        if not data.get(key):
            out[key] = value
    return out


def _validate_required(
    data: dict[str, Any],
    config: dict[str, Any],
    errors: list[FieldError],
    fila: int,
) -> None:
    """Flag missing required fields."""
    for field in config.get("required", []):
        value = data.get(field)
        if value is None or str(value).strip() == "":
            errors.append(FieldError(fila=fila, campo=field, error=f"'{field}' is required"))


def _model_errors_from_validation(exc: ValidationError) -> list[FieldError]:
    """Convert pydantic validation errors into per-field errors (fila filled later)."""
    out: list[FieldError] = []
    for err in exc.errors():
        loc = err.get("loc", ())
        campo = str(loc[0]) if loc else "row"
        out.append(FieldError(fila=0, campo=campo, error=err.get("msg", "invalid value")))
    return out


def _validate_row(
    data: dict[str, Any],
    config: dict[str, Any],
    fila: int,
) -> tuple[dict[str, Any] | None, list[FieldError]]:
    """Validate a single normalized row against the resource schema.

    Returns ``(valid_data_or_None, errors)``.
    """
    errors: list[FieldError] = []
    # Defaults are applied to empty optional fields (required enforced below).
    data = _apply_defaults(data, config)

    # Required-field check produces friendly messages before pydantic runs.
    _validate_required(data, config, errors, fila)

    model_cls = config["model"]
    if errors:
        return None, errors

    try:
        validated = model_cls(**data)
    except ValidationError as exc:
        for err in _model_errors_from_validation(exc):
            err.fila = fila
            errors.append(err)
        return None, errors

    return validated.model_dump(mode="json"), errors


def validate_rows(
    rows: list[dict[str, str]],
    columns: dict[str, str],
    resource: str,
    db: Session | None = None,
) -> tuple[list[dict[str, Any]], list[FieldError]]:
    """Validate all normalized rows.

    ``rows`` are dicts keyed by original header text -> raw cell value
    (deferred mapping is performed here via ``_build_row_data``).

    Returns ``(valid_rows, errors)`` where ``valid_rows`` are the canonical
    validated row dicts (in original order) and ``errors`` collects every
    per-row/field error with the source row number.
    """
    config = get_config(resource)
    dedupe_key = config.get("dedupe_key")
    seen: set[str] = set()

    # Preload dnis already present in the DB for dedupe.
    db_dnis: set[str] = set()
    if db is not None and dedupe_key:
        model_cls = config.get("model_cls")
        if model_cls is not None:
            col = getattr(model_cls, dedupe_key, None)
            if col is not None:
                db_dnis = {str(v) for (v,) in db.query(col).all() if v is not None}

    valid_rows: list[dict[str, Any]] = []
    errors: list[FieldError] = []

    for idx, raw_row in enumerate(rows):
        fila = idx + 2  # +1 header row => source spreadsheet row number
        data = _build_row_data(raw_row, columns)

        row_errors: list[FieldError] = []
        data = _apply_normalizers(data, config, row_errors, fila)

        validated_data: dict[str, Any] | None = None
        if not row_errors:
            validated_data, row_errors = _validate_row(data, config, fila)

        # Dedupe on the canonical key value.
        if dedupe_key:
            value = data.get(dedupe_key)
            if isinstance(value, str) and value.strip():
                norm_value = value.strip()
                if norm_value in seen or norm_value in db_dnis:
                    row_errors.append(
                        FieldError(
                            fila=fila,
                            campo=dedupe_key,
                            error=f"Duplicate {dedupe_key} '{norm_value}'",
                        )
                    )
                else:
                    seen.add(norm_value)

        # Resource resolve hook: cross-row/DB lookups (e.g. socio exists,
        # arancel nombre -> arancelId). Needs a live DB session.
        resolve = config.get("resolve")
        if resolve and db is not None and validated_data is not None:
            row_errors.extend(resolve(validated_data, db, fila))

        if row_errors:
            errors.extend(row_errors)
        else:
            if validated_data is not None:
                valid_rows.append(validated_data)

    return valid_rows, errors
