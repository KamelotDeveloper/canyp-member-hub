"""Notificacion schemas."""

from datetime import date

from pydantic import BaseModel

from backend.models.enums import CanalNotificacion
from backend.schemas.common import OrmConfig


class NotificacionBase(OrmConfig, BaseModel):
    socioId: str
    canal: CanalNotificacion
    fecha: date
    motivo: str
    mensaje: str


class NotificacionCreate(NotificacionBase):
    id: str


class NotificacionUpdate(BaseModel):
    model_config = OrmConfig.model_config

    socioId: str | None = None
    canal: CanalNotificacion | None = None
    fecha: date | None = None
    motivo: str | None = None
    mensaje: str | None = None


class NotificacionResponse(NotificacionBase):
    id: str
