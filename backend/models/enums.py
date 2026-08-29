"""Shared enumerations for CANYP domain models."""

import enum


class Predio(str, enum.Enum):
    EMBALSE = "Embalse"
    ALMAFUERTE = "Almafuerte"


class Area(str, enum.Enum):
    BALSEROS = "Balseros"
    CABANEROS = "Cabañeros"
    GUARDERIA = "Guardería"
    WINDSURF = "Windsurf"


class EstadoMembresia(str, enum.Enum):
    ACTIVA = "activa"
    SUSPENDIDA = "suspendida"
    VENCIDA = "vencida"
    BAJA = "baja"


class TipoParcela(str, enum.Enum):
    CABANA = "cabaña"
    BALSA = "balsa"
    GUARDERIA = "guardería"


class RolMembresia(str, enum.Enum):
    TITULAR = "Titular"
    INTEGRANTE = "Integrante"


class CategoriaParcela(str, enum.Enum):
    CHICA = "Chica"
    MEDIANA = "Mediana"
    ESPECIAL = "Especial"
    GRANDE = "Grande"


class CanalNotificacion(str, enum.Enum):
    EMAIL = "email"
    WHATSAPP = "whatsapp"


def predio_de_tipo(tipo: TipoParcela) -> Predio:
    """Predio correcto para un tipo de parcela (regla del dominio).

    Embalse aloja solo balsas; Almafuerte aloja cabañas y guardería.
    """
    if tipo == TipoParcela.BALSA:
        return Predio.EMBALSE
    return Predio.ALMAFUERTE
