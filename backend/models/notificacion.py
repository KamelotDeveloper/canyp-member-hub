"""Notificacion model."""

from datetime import date

from sqlalchemy import Date, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base
from backend.models.enums import CanalNotificacion


class Notificacion(Base):
    __tablename__ = "notificaciones"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    socioId: Mapped[str] = mapped_column(String, ForeignKey("socios.id"), nullable=False)
    canal: Mapped[CanalNotificacion] = mapped_column(Enum(CanalNotificacion), nullable=False)
    fecha: Mapped[date] = mapped_column(Date, nullable=False)
    motivo: Mapped[str] = mapped_column(String, nullable=False)
    mensaje: Mapped[str] = mapped_column(String, nullable=False)
