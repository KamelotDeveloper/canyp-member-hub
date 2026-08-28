"""Parcela schemas."""

from pydantic import BaseModel

from backend.models.enums import CategoriaParcela, Predio, TipoParcela
from backend.schemas.common import OrmConfig


class ParcelaBase(OrmConfig, BaseModel):
    nombre: str
    tipo: TipoParcela
    tamano: str | None = None
    predio: Predio
    categoria: CategoriaParcela | None = None


class ParcelaCreate(ParcelaBase):
    id: str


class ParcelaUpdate(BaseModel):
    model_config = OrmConfig.model_config

    nombre: str | None = None
    tipo: TipoParcela | None = None
    tamano: str | None = None
    predio: Predio | None = None
    categoria: CategoriaParcela | None = None


class ParcelaResponse(ParcelaBase):
    id: str
