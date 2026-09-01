"""Header-to-field mapping for the bulk import engine.

Maps source headers (Spanish or English) to canonical model fields via the
per-resource registry. Both the source header and the registry keys are
normalized (trim -> lowercase -> spaces/dashes to underscores) before
matching. Unrecognized columns are ignored and reported as warnings.
"""

from __future__ import annotations

from typing import Any

from backend.services.importer.config import get_config


def normalize_header(header: str) -> str:
    """Normalize a header for matching.

    Trims whitespace, lowercases, and converts spaces/dashes/underscores to a
    single underscore. Accented characters are folded to their ASCII base.
    """
    s = str(header).strip().lower()
    s = s.replace("á", "a").replace("é", "e").replace("í", "i")
    s = s.replace("ó", "o").replace("ú", "u").replace("ü", "u")
    s = s.replace("ñ", "n")
    # spaces/dashes -> underscore, collapse repeats, strip edge underscores
    out = []
    for ch in s:
        if ch in (" ", "-", "_", "\t"):
            ch = "_"
        out.append(ch)
    joined = "".join(out)
    while "__" in joined:
        joined = joined.replace("__", "_")
    return joined.strip("_")


def _build_lookup(config: dict[str, Any]) -> dict[str, str]:
    """Map normalized source header -> canonical field used for matching.

    The registry keys are Spanish headers; canonical field values are also
    accepted (English headers). Builds a normalized lookup for both.
    """
    lookup: dict[str, str] = {}
    for src, field in config["headers"].items():
        lookup[normalize_header(src)] = field
        # English header (the canonical field name) is also valid.
        lookup[normalize_header(field)] = field
    return lookup


def map_headers(header_row: list[str], resource: str) -> tuple[dict[str, str], list[str]]:
    """Map the parsed header row to canonical fields.

    Returns ``(columns, ignored_columns)`` where ``columns`` maps the original
    header text -> canonical field, and ``ignored_columns`` lists source headers
    that did not match anything in the registry.
    """
    config = get_config(resource)
    lookup = _build_lookup(config)

    columns: dict[str, str] = {}
    ignored: list[str] = []
    for raw in header_row:
        key = normalize_header(raw)
        field = lookup.get(key)
        if field is None:
            ignored.append(raw)
        else:
            columns[raw] = field
    return columns, ignored


def column_to_field(column: str, resource: str) -> str | None:
    """Return the canonical field for a single source header, or None."""
    config = get_config(resource)
    lookup = _build_lookup(config)
    return lookup.get(normalize_header(column))
