"""Membresia schemas."""

from datetime import date

from pydantic import BaseModel

from backend.models.enums import Area, EstadoMembresia, Predio, RolMembresia
from backend.schemas.common import OrmConfig


class MembresiaBase(OrmConfig, BaseModel):
    socioId: str
    area: Area
    predio: Predio
    estado: EstadoMembresia
    vencimiento: date
    detalle: str | None = None
    rol: RolMembresia | None = None
    parcelaId: str | None = None


class MembresiaCreate(MembresiaBase):
    id: str


class MembresiaUpdate(BaseModel):
    model_config = OrmConfig.model_config

    socioId: str | None = None
    area: Area | None = None
    predio: Predio | None = None
    estado: EstadoMembresia | None = None
    vencimiento: date | None = None
    detalle: str | None = None
    rol: RolMembresia | None = None
    parcelaId: str | None = None


class MembresiaResponse(MembresiaBase):
    id: str
