"""Pago and PagoItem models."""

from datetime import date

from sqlalchemy import Date, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class Pago(Base):
    __tablename__ = "pagos"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    numero: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    socioId: Mapped[str] = mapped_column(String, ForeignKey("socios.id"), nullable=False)
    fecha: Mapped[date] = mapped_column(Date, nullable=False)
    medio: Mapped[str] = mapped_column(String, nullable=False)
    total: Mapped[float] = mapped_column(Float, nullable=False)
    nota: Mapped[str | None] = mapped_column(String, nullable=True, default=None)


class PagoItem(Base):
    __tablename__ = "pago_items"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    pagoId: Mapped[str] = mapped_column(String, ForeignKey("pagos.id"), nullable=False)
    arancelId: Mapped[str] = mapped_column(String, ForeignKey("aranceles.id"), nullable=False)
    membresiaId: Mapped[str] = mapped_column(
        String, ForeignKey("membresias.id"), nullable=False
    )
    montoAplicado: Mapped[float] = mapped_column(Float, nullable=False)
    arancelNombre: Mapped[str] = mapped_column(String, nullable=False)
