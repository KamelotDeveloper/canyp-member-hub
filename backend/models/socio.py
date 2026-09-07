"""Socio model."""

from datetime import date

from sqlalchemy import Boolean, Date, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class Socio(Base):
    __tablename__ = "socios"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    nombre: Mapped[str] = mapped_column(String, nullable=False)
    dni: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    telefono: Mapped[str] = mapped_column(String, nullable=False, default="")
    email: Mapped[str] = mapped_column(String, nullable=False, default="")
    direccion: Mapped[str] = mapped_column(String, nullable=False, default="")
    fechaAlta: Mapped[date] = mapped_column(Date, nullable=False, default=date.today)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
