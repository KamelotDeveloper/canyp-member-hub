"""Socio schemas."""

from datetime import date

from pydantic import BaseModel, field_validator

from backend.schemas.common import OrmConfig
from backend.services.telefonos import normalizar_telefono


class SocioBase(OrmConfig, BaseModel):
    nombre: str
    dni: str = ""
    telefono: str = ""
    email: str = ""
    direccion: str = ""
    fechaAlta: date
    activo: bool = True
    # Free lowercase string ("activo" | "vitalicio"), optional.
    categoria: str | None = None

    @field_validator("telefono")
    @classmethod
    def _normalizar_telefono(cls, v: str) -> str:
        return normalizar_telefono(v)


class SocioCreate(SocioBase):
    # id is server-generated when omitted (frontend doesn't send it)
    id: str | None = None
    # fechaAlta is server-defaulted to today when omitted (frontend doesn't send it)
    fechaAlta: date | None = None
    dni: str | None = None


class SocioUpdate(BaseModel):
    model_config = OrmConfig.model_config

    nombre: str | None = None
    dni: str | None = None
    telefono: str | None = None
    email: str | None = None
    direccion: str | None = None
    fechaAlta: date | None = None
    activo: bool | None = None
    categoria: str | None = None

    @field_validator("telefono")
    @classmethod
    def _normalizar_telefono(cls, v: str | None) -> str | None:
        return normalizar_telefono(v) if v is not None else None


class SocioResponse(SocioBase):
    id: str
    # La base persiste estos campos como NULL cuando no se enviaron (SocioCreate
    # los declara opcionales). Si la respuesta los declarara obligatorios, un
    # único socio con algún campo NULL rompería la serialización de TODA la
    # lista con ResponseValidationError 500.
    dni: str | None = None
    telefono: str | None = None
    email: str | None = None
    direccion: str | None = None
    # Audit columns (D7): null for rows imported/created before multi-user auth.
    created_by: str | None = None
    updated_by: str | None = None
