"""Per-resource import configuration registry.

``IMPORT_CONFIGS`` maps a resource key (e.g. ``"socios"``) to its column
mapping, validation schema, and field normalizers. It is the single extension
point: adding a new resource (parcelas/balsas/aranceles) means adding one
entry here — the engine, endpoints, and frontend reuse it unchanged.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Callable

from sqlalchemy.orm import Session

from backend.models.arancel import Arancel
from backend.models.membresia import Membresia
from backend.models.socio import Socio
from backend.schemas.import_bulk import (
    FieldError,
    ImportMembresiaResolveRow,
    ImportSocioRow,
)
from backend.services.telefonos import normalizar_telefono

# Type alias for a normalizer: raw cell value -> canonical Python value.
Normalizer = Callable[[Any], Any]


def norm_str(value: Any) -> str:
    """Normalize a string cell: trim surrounding whitespace."""
    if value is None:
        return ""
    return str(value).strip()


def norm_str_optional(value: Any) -> str | None:
    """Normalize an optional string cell: returns None when empty.

    Used for fields like ``dni`` where multiple NULLs are valid in a UNIQUE
    column (SQLite treats NULLs as distinct), but multiple empty strings
    would violate the constraint.
    """
    if value is None:
        return None
    trimmed = str(value).strip()
    return trimmed or None


def norm_int(value: Any) -> int | None:
    """Normalize an integer cell (accepts numeric strings, optional)."""
    if value is None or str(value).strip() == "":
        return None
    return int(float(str(value).replace(",", "").strip()))


def norm_decimal(value: Any) -> float | None:
    """Normalize a decimal number written with a comma as the separator.

    Accepts both ``12.50`` and ``12,50`` (Latin-1/UTF-8 comma maps to dot).
    Raises ``ValueError`` when the value cannot be normalized.
    """
    if value is None or str(value).strip() == "":
        return None
    raw = str(value).strip().replace(",", ".")
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"'{value}' is not a valid number") from exc


def norm_email(value: Any) -> str:
    """Normalize an email cell: trim and lowercase."""
    return norm_str(value).lower()


def norm_bool(value: Any) -> bool:
    """Normalize a boolean cell.

    Accepts explicit truthy/falsy tokens plus Spanish labels
    (``sí``/``no``) as well as ``si``/``no``/``true``/``false``/``1``/``0``.
    Bare empty cells default to True (matching the model default).
    """
    if value is None:
        return True
    raw = str(value).strip().lower()
    if raw in ("", "true", "1", "si", "sí", "yes", "y"):
        return True
    if raw in ("false", "0", "no", "n", "not"):
        return False
    return True


def norm_date(value: Any) -> str:
    """Normalize a date cell into ``YYYY-MM-DD`` or ``""`` when empty.

    Spec requires tolerant dd/mm/yyyy parsing via ``python-dateutil``.
    Accepts a range of common formats (dd/mm/yyyy, dd-mm-yyyy, YYYY-MM-DD, ...).
    Raises ``ValueError`` with a readable message when the date is invalid.
    """
    from dateutil import parser as dateutil_parser

    if value is None or str(value).strip() == "":
        return ""
    raw = str(value).strip()
    # dateutil is very tolerant; dayfirst=True favours dd/mm/yyyy as specified.
    try:
        parsed = dateutil_parser.parse(raw, dayfirst=True).date()
    except (ValueError, OverflowError, TypeError) as exc:
        raise ValueError(f"'{raw}' is not a valid date") from exc
    return parsed.isoformat()


# Full normalizer set shared/extensible by future resources.
NORMALIZERS: dict[str, Normalizer] = {
    "str": norm_str,
    "int": norm_int,
    "decimal": norm_decimal,
    "email": norm_email,
    "bool": norm_bool,
    "date": norm_date,
}


def _defaults_for_socios() -> dict[str, Any]:
    """Computed default values applied to a socios row when fields are empty."""
    return {"fechaAlta": date.today().isoformat(), "activo": True}


def _resolve_membresia_row(data: dict[str, Any], db: Session, fila: int) -> list[FieldError]:
    """Resolve cross-references for a membresias row.

    Checks the linked socio (by DNI) exists in the padron and, when the row
    carries an ``arancel`` nombre, resolves it to ``arancelId`` within the
    row's area+predio (exact match). Returns a list of per-field errors (``[]``
    when the row is consistent).
    """
    socio = db.query(Socio).filter(Socio.dni == data["dni"]).first()
    if socio is None:
        return [
            FieldError(
                fila=fila,
                campo="dni",
                error=f"Socio con DNI '{data['dni']}' no existe",
            )
        ]

    arancel_nombre = data.get("arancel")
    if arancel_nombre:
        arancel = (
            db.query(Arancel)
            .filter(
                Arancel.nombre == arancel_nombre,
                Arancel.area == data["area"],
                Arancel.predio == data["predio"],
            )
            .first()
        )
        if arancel is None:
            return [
                FieldError(
                    fila=fila,
                    campo="arancel",
                    error=(
                        f"Arancel '{arancel_nombre}' no encontrado para "
                        f"{data['area']}/{data['predio']}"
                    ),
                )
            ]
        data["arancelId"] = arancel.id
    return []


def _build_membresia(data: dict[str, Any], db: Session) -> Membresia:
    """Instantiate a ``Membresia`` row from canonical import data.

    The row was already validated at preview (socio exists, arancel resolved),
    so this mirrors the ``resolve`` hook's socio lookup but raises on a missing
    socio so the row's SAVEPOINT rolls back and reports the failure at execute
    time.
    """
    socio = db.query(Socio).filter(Socio.dni == data["dni"]).first()
    if socio is None:
        raise ValueError(f"Socio con DNI '{data['dni']}' no existe")
    return Membresia(
        id=f"m{uuid.uuid4().hex[:8]}",
        socioId=socio.id,
        area=data["area"],
        predio=data["predio"],
        estado=data["estado"],
        vencimiento=date.fromisoformat(data["vencimiento"]),
        arancelId=data.get("arancelId"),
        detalle=data.get("detalle") or None,
    )


_IMPORT_MEMBRESIAS: dict[str, Any] = {
    "model": ImportMembresiaResolveRow,
    "model_cls": Membresia,
    # Spanish -> English canonical header mapping (canonical keys in values).
    "headers": {
        "DNI": "dni",
        "Área": "area",
        "Predio": "predio",
        "Vencimiento": "vencimiento",
        "Estado": "estado",
        "Arancel": "arancel",
        "Detalle": "detalle",
    },
    "required": ["dni", "area", "predio", "vencimiento"],
    # Membresias have no natural unique key: a socio may hold several.
    # No dedupe_key.
    "normalizers": {
        "dni": norm_str,
        "area": norm_str,
        "predio": norm_str,
        "vencimiento": norm_date,
        "estado": norm_str,
        "arancel": norm_str_optional,
        "detalle": norm_str_optional,
    },
    "defaults": lambda: {"estado": "activa"},
    # Canonical ordering of headers for the XLSX template.
    "template_headers": [
        "dni",
        "area",
        "predio",
        "vencimiento",
        "estado",
        "arancel",
        "detalle",
    ],
    # Cross-row/DB validation hook run during preview (and available to
    # execute via the ``build`` hook).
    "resolve": _resolve_membresia_row,
    # Execute-side instance builder (overrides the default Socio builder).
    "build": _build_membresia,
}


_IMPORT_SOCIOS: dict[str, Any] = {
    "model": ImportSocioRow,
    "model_cls": Socio,
    # Spanish -> English canonical header mapping (canonical keys in values).
    "headers": {
        "Nombre y Apellido": "nombre",
        "Dni": "dni",
        "Teléfono": "telefono",
        "Email": "email",
        "Dirección": "direccion",
        "Fecha de Alta": "fechaAlta",
    },
    "required": ["nombre", "telefono"],
    "dedupe_key": "dni",
    # Field -> normalizer by canonical field name.
    "normalizers": {
        "nombre": norm_str,
        "dni": norm_str_optional,
        "telefono": normalizar_telefono,
        "email": norm_email,
        "direccion": norm_str,
        "fechaAlta": norm_date,
        "activo": norm_bool,
    },
    "defaults": _defaults_for_socios,
    # Canonical ordering of headers for the XLSX template.
    "template_headers": ["nombre", "dni", "telefono", "email", "direccion", "fechaAlta"],
}


IMPORT_CONFIGS: dict[str, dict[str, Any]] = {
    "socios": _IMPORT_SOCIOS,
    "membresias": _IMPORT_MEMBRESIAS,
    # parcelas / balsas / aranceles: stubbed — raise KeyError until wired.
}


def get_config(resource: str) -> dict[str, Any]:
    """Return the config for a resource or raise a readable error."""
    try:
        return IMPORT_CONFIGS[resource]
    except KeyError:
        raise KeyError(
            f"Import resource '{resource}' is not configured. "
            "Add it to IMPORT_CONFIGS before use."
        ) from None
