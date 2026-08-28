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
