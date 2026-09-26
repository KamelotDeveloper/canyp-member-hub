"""Catálogo puro de planes de suscripción para CANYP.

Fuente canónica de precios y duraciones del backend local. Los valores
DEBEN coincidir con el backend compartido (suscripcion-api/lib/mp-contract.mjs)
para que el webhook valide montos y planes. Sin dependencias externas.

Cada entrada: id, nombre, precio, dias, descuento (0 = sin descuento de plan).
`descripcion` se conserva para el frontend de escritorio que la consume.
"""

KNOWN_APPS = ("canyp",)

# Tabla fallback — los valores DEBEN coincidir con suscripcion-api
PLANES_FALLBACK = {
    "canyp": [
        {"id": "canyp_1_mes", "nombre": "Mensual", "descripcion": "Acceso completo por 1 mes", "precio": 120000, "dias": 30, "descuento": 0},
        {"id": "canyp_6_meses", "nombre": "Semestral", "descripcion": "Acceso completo por 6 meses", "precio": 617000, "dias": 180, "descuento": 0},
        {"id": "canyp_1_anio", "nombre": "Anual", "descripcion": "Acceso completo por 1 año", "precio": 1234000, "dias": 365, "descuento": 0},
    ],
}


def get_planes_for_app(app_id: str):
    """Devuelve el catálogo fallback para app_id, o None si es desconocida.

    Los callers deben responder 400 ante app_id desconocido (fail-loud,
    nunca default a otra app).
    """
    return PLANES_FALLBACK.get(app_id)