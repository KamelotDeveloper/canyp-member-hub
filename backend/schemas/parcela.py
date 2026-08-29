"""Parcela schemas."""

from pydantic import BaseModel, model_validator

from backend.models.enums import (
    CategoriaParcela,
    Predio,
    TipoParcela,
    predio_de_tipo,
)
from backend.schemas.common import OrmConfig


class ParcelaBase(OrmConfig, BaseModel):
    nombre: str
    tipo: TipoParcela
    tamano: str | None = None
    predio: Predio
    categoria: CategoriaParcela | None = None


class ParcelaCreate(ParcelaBase):
    id: str

    @model_validator(mode="after")
    def _predio_coherente(self):
        esperado = predio_de_tipo(self.tipo)
        if self.predio != esperado:
            raise ValueError(
                f"{self.tipo.value} belongs to {esperado.value}, not {self.predio.value}"
            )
        return self


class ParcelaUpdate(BaseModel):
    model_config = OrmConfig.model_config

    nombre: str | None = None
    tipo: TipoParcela | None = None
    tamano: str | None = None
    predio: Predio | None = None
    categoria: CategoriaParcela | None = None


class ParcelaResponse(ParcelaBase):
    id: str
