"""Import 'unidades compartidas' schemas (RQ 8)."""

from datetime import date

from pydantic import BaseModel

from backend.models.enums import CategoriaParcela, Predio, RolMembresia, TipoParcela
from backend.schemas.common import OrmConfig


class ImportSocio(BaseModel):
    nombre: str
    dni: str
    telefono: str | None = None
    email: str | None = None


class ImportMembresia(BaseModel):
    socio: ImportSocio
    rol: RolMembresia
    vencimiento: date | None = None


class ImportParcela(BaseModel):
    nombre: str
    tipo: TipoParcela
    categoria: CategoriaParcela | None = None
    predio: Predio
    miembros: list[ImportMembresia] = []


class ImportPayload(BaseModel):
    unidades: list[ImportParcela]


class ImportResponse(OrmConfig, BaseModel):
    parcelas: list[str]
    socios: list[str]
    membresias: list[str]
