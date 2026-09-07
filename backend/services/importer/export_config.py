"""Per-resource export configuration registry.

``EXPORT_CONFIGS`` maps a resource key (e.g. ``"socios"``) to its exportable
column list. It is the mirror of ``IMPORT_CONFIGS``: adding a new resource means
adding one entry here — the export service, endpoints, and frontend reuse it
unchanged.
"""

from __future__ import annotations

from backend.models.arancel import Arancel
from backend.models.membresia import Membresia
from backend.models.notificacion import Notificacion
from backend.models.pago import Pago
from backend.models.parcela import Parcela
from backend.models.socio import Socio

# A column entry: (Spanish header label, model attribute name).
# When ``resolve`` is present for a field, the service replaces the raw FK id
# with the human-readable value from a lookup map (e.g. socioId -> socio nombre).
ExportColumn = tuple[str, str]

_HEADERS: dict[str, list[ExportColumn]] = {
    "socios": [
        ("Nombre y Apellido", "nombre"),
        ("DNI", "dni"),
        ("Teléfono", "telefono"),
        ("Email", "email"),
        ("Dirección", "direccion"),
        ("Fecha de Alta", "fechaAlta"),
        ("Activo", "activo"),
    ],
    "pagos": [
        ("Número", "numero"),
        ("Socio", "socioId"),
        ("Fecha", "fecha"),
        ("Medio", "medio"),
        ("Total", "total"),
        ("Nota", "nota"),
    ],
    "parcelas": [
        ("Nombre", "nombre"),
        ("Tipo", "tipo"),
        ("Tamaño", "tamano"),
        ("Predio", "predio"),
        ("Categoría", "categoria"),
    ],
    "membresias": [
        ("Socio", "socioId"),
        ("Área", "area"),
        ("Predio", "predio"),
        ("Estado", "estado"),
        ("Vencimiento", "vencimiento"),
        ("Detalle", "detalle"),
        ("Rol", "rol"),
        ("Parcela", "parcelaId"),
    ],
    "aranceles": [
        ("Nombre", "nombre"),
        ("Área", "area"),
        ("Predio", "predio"),
        ("Monto", "monto"),
        ("Categoría", "categoria"),
        ("Vigente Desde", "vigenteDesde"),
    ],
    "notificaciones": [
        ("Socio", "socioId"),
        ("Canal", "canal"),
        ("Fecha", "fecha"),
        ("Motivo", "motivo"),
        ("Mensaje", "mensaje"),
    ],
}

# Fields whose raw FK id should be replaced by a readable name via lookup maps.
# Keys are model attribute names; values are the lookup table name + label.
RESOLVERS: dict[str, dict[str, tuple[str, str]]] = {
    "pagos": {"socioId": ("socios", "Socio")},
    "membresias": {
        "socioId": ("socios", "Socio"),
        "parcelaId": ("parcelas", "Parcela"),
    },
    "notificaciones": {"socioId": ("socios", "Socio")},
}


def get_export_headers(resource: str) -> list[ExportColumn]:
    """Return the exportable columns for a resource or raise a readable error."""
    try:
        return _HEADERS[resource]
    except KeyError:
        raise KeyError(
            f"Export resource '{resource}' is not configured. "
            "Add it to EXPORT_CONFIGS before use."
        ) from None


MODEL_BY_RESOURCE: dict[str, type] = {
    "socios": Socio,
    "pagos": Pago,
    "parcelas": Parcela,
    "membresias": Membresia,
    "aranceles": Arancel,
    "notificaciones": Notificacion,
}


def get_model(resource: str) -> type:
    """Return the SQLAlchemy model for a resource."""
    try:
        return MODEL_BY_RESOURCE[resource]
    except KeyError:
        raise KeyError(
            f"Export resource '{resource}' has no model. "
            "Add it to MODEL_BY_RESOURCE before use."
        ) from None