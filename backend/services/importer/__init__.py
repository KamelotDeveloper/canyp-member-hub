"""Generic bulk data-import engine for CANYP.

Wired resources (in ``config.IMPORT_CONFIGS``) are re-used across the
preview / execute flow. Currently only ``socios`` is configured; the registry
is extensible for parcelas/balsas/aranceles once their DBs exist.

NOTE: the package is named ``importer`` (not ``import``) because ``import`` is
a Python reserved keyword and cannot appear in a dotted module path.
"""

from backend.services.importer.config import IMPORT_CONFIGS, get_config
from backend.services.importer.exporter import build_error_csv, build_log_json, build_template
from backend.services.importer.mapper import map_headers
from backend.services.importer.parser import parse_file
from backend.services.importer.pipeline import execute_rows, preview_file
from backend.services.importer.validator import validate_rows

__all__ = [
    "IMPORT_CONFIGS",
    "get_config",
    "parse_file",
    "map_headers",
    "validate_rows",
    "preview_file",
    "execute_rows",
    "build_template",
    "build_error_csv",
    "build_log_json",
]
