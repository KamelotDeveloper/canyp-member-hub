"""Membresia model."""

from datetime import date

from sqlalchemy import Date, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base
from backend.models.enums import Area, EstadoMembresia, Predio, RolMembresia


class Membresia(Base):
    __tablename__ = "membresias"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    socioId: Mapped[str] = mapped_column(String, ForeignKey("socios.id"), nullable=False)
    area: Mapped[Area] = mapped_column(Enum(Area), nullable=False)
    predio: Mapped[Predio] = mapped_column(Enum(Predio), nullable=False)
    estado: Mapped[EstadoMembresia] = mapped_column(Enum(EstadoMembresia), nullable=False)
    vencimiento: Mapped[date] = mapped_column(Date, nullable=False)
    detalle: Mapped[str | None] = mapped_column(String, nullable=True)
    rol: Mapped[RolMembresia | None] = mapped_column(
        Enum(RolMembresia), nullable=True
    )
    parcelaId: Mapped[str | None] = mapped_column(
        String, ForeignKey("parcelas.id"), nullable=True
    )
    arancelId: Mapped[str | None] = mapped_column(String, nullable=True)
