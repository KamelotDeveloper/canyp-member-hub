"""Import 'unidades compartidas' schemas (RQ 8)."""

from datetime import date

from pydantic import BaseModel, model_validator

from backend.models.enums import (
    CategoriaParcela,
    Predio,
    RolMembresia,
    TipoParcela,
    predio_de_tipo,
)
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

    @model_validator(mode="after")
    def _predio_coherente(self):
        esperado = predio_de_tipo(self.tipo)
        if self.predio != esperado:
            raise ValueError(
                f"{self.tipo.value} belongs to {esperado.value}, not {self.predio.value}"
            )
        return self


class ImportPayload(BaseModel):
    unidades: list[ImportParcela]


class ImportResponse(OrmConfig, BaseModel):
    parcelas: list[str]
    socios: list[str]
    membresias: list[str]
