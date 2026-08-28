"""Socio schemas."""

from datetime import date

from pydantic import BaseModel

from backend.schemas.common import OrmConfig


class SocioBase(OrmConfig, BaseModel):
    nombre: str
    dni: str
    telefono: str = ""
    email: str = ""
    direccion: str = ""
    fechaAlta: date
    activo: bool = True


class SocioCreate(SocioBase):
    # id is server-generated when omitted (frontend doesn't send it)
    id: str | None = None
    # fechaAlta is server-defaulted to today when omitted (frontend doesn't send it)
    fechaAlta: date | None = None


class SocioUpdate(BaseModel):
    model_config = OrmConfig.model_config

    nombre: str | None = None
    dni: str | None = None
    telefono: str | None = None
    email: str | None = None
    direccion: str | None = None
    fechaAlta: date | None = None
    activo: bool | None = None


class SocioResponse(SocioBase):
    id: str
