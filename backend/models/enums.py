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


class ConceptoMembresia(str, enum.Enum):
    """Charge concept a membership belongs to.

    Stored by NAME in the database (SQLAlchemy `Enum` convention), so the
    migration backfills `'AREA'` / `'CUOTA_SOCIAL'` and never the display value.
    """

    AREA = "area"
    CUOTA_SOCIAL = "cuota social"


class ConceptoCobro(str, enum.Enum):
    """Charge concept carried by a `PagoItem` and tagged on an `Arancel`.

    Additive: the SQLite columns are plain VARCHAR (no CHECK constraint), so a
    new member is a non-breaking change for already-migrated databases.

    The four chargeable concepts and where each amount comes from:

    | concept | amount | renews |
    |---|---|---|
    | `AREA` | catalog row for area+predio+categoria, per unit | the unit's AREA rows |
    | `CUOTA_SOCIAL` | catalog unit price x member count | the CUOTA_SOCIAL rows |
    | `RECARGO` | operator-entered per charge, never in the catalog | nothing |
    | `SERVICIO` | catalog row per unit, adjustable at charge time | nothing |

    `RECARGO` and `SERVICIO` have no `ConceptoMembresia` counterpart: they are
    lines on a receipt, not memberships, so ticking one renews nothing.
    """

    AREA = "area"
    CUOTA_SOCIAL = "cuota social"
    RECARGO = "recargo"
    SERVICIO = "servicio"


class EstadoSocioVisual(str, enum.Enum):
    """The 4 server-authoritative socio states (EST-01).

    The value IS the exact UI nominación (UI-04), including the em dash in
    `ACTIVO_REVISAR`. Do not paraphrase these strings.
    """

    ACTIVO = "Socio activo"
    ACTIVO_REVISAR = "Socio activo — revisar"
    INACTIVO_REVISAR = "Inactivo — revisar"
    SOLO_CUOTA_SOCIAL = "Solo cuota social"


def predio_de_tipo(tipo: TipoParcela) -> Predio:
    """Predio correcto para un tipo de parcela (regla del dominio).

    Embalse aloja solo balsas; Almafuerte aloja cabañas y guardería.
    """
    if tipo == TipoParcela.BALSA:
        return Predio.EMBALSE
    return Predio.ALMAFUERTE
