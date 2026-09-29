"""Flags de desarrollo, apagadas por defecto y con doble condición.

Existe un camino que simula un pago sin cobrar (endpoints ``/mock-pago`` y
``/mock-confirm`` de suscripciones). Ese camino no puede quedar disponible en
producción: quien lo alcanzara activaría licencias sin que entre dinero.

Por eso la habilitación exige DOS condiciones simultáneas:

1. ``CANYP_ALLOW_MOCK_PAYMENTS=1`` en el entorno del proceso.
2. ``CANYP_CLIENT_BUILD`` distinto de ``1``.

La segunda condición es la que hace que no se pueda activar por accidente: si
la variable se colara en un launcher de un build distribuido, el propio build
de cliente rechaza el modo simulado. Los builds de cliente son los que salen
de la máquina del operador; los de desarrollo nunca llevan el flag.
"""

from __future__ import annotations

import os

FLAG_MOCK_PAGOS = "CANYP_ALLOW_MOCK_PAYMENTS"
FLAG_CLIENT_BUILD = "CANYP_CLIENT_BUILD"


def es_build_cliente() -> bool:
    """True si el proceso es un sidecar empaquetado para el cliente final."""
    return os.environ.get(FLAG_CLIENT_BUILD) == "1"


def mock_pagos_habilitados() -> bool:
    """True solo en desarrollo explícito, nunca en un build de cliente."""
    if os.environ.get(FLAG_MOCK_PAGOS) != "1":
        return False
    return not es_build_cliente()


def motivo_mock_pagos_deshabilitado() -> str:
    """Explicación legible del por qué, para el mensaje de error."""
    if os.environ.get(FLAG_MOCK_PAGOS) != "1":
        return (
            f"El cobro simulado esta deshabilitado. Habilitalo solo en desarrollo, "
            f"con {FLAG_MOCK_PAGOS}=1."
        )
    return (
        "El cobro simulado no existe en builds de cliente: activaria licencias "
        "sin cobrar. Si necesita testing, use un build de desarrollo."
    )


__all__ = [
    "FLAG_CLIENT_BUILD",
    "FLAG_MOCK_PAGOS",
    "es_build_cliente",
    "mock_pagos_habilitados",
    "motivo_mock_pagos_deshabilitado",
]
