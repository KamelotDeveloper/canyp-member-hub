"""Membresia model."""

from datetime import date

from sqlalchemy import Date, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base
from backend.models.enums import (
    Area,
    ConceptoMembresia,
    EstadoMembresia,
    Predio,
    RolMembresia,
)


class Membresia(Base):
    __tablename__ = "membresias"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    socioId: Mapped[str] = mapped_column(String, ForeignKey("socios.id"), nullable=False)
    # area/predio are NULLABLE: a cuota social membership is not a physical
    # location, so it carries no area/predio (CS-01). Existing area rows keep
    # their values; migrate.py makes the columns nullable in place.
    area: Mapped[Area | None] = mapped_column(Enum(Area), nullable=True)
    predio: Mapped[Predio | None] = mapped_column(Enum(Predio), nullable=True)
    estado: Mapped[EstadoMembresia] = mapped_column(Enum(EstadoMembresia), nullable=False)
    # Concept dimension. Declared NOT NULL with an AREA default: every legacy
    # row is backfilled to 'AREA' by migrate.py (D7), so the NOT NULL contract
    # holds without a table rebuild.
    concepto: Mapped[ConceptoMembresia] = mapped_column(
        Enum(ConceptoMembresia), nullable=False, default=ConceptoMembresia.AREA
    )
    vencimiento: Mapped[date] = mapped_column(Date, nullable=False)
    detalle: Mapped[str | None] = mapped_column(String, nullable=True)
    rol: Mapped[RolMembresia | None] = mapped_column(
        Enum(RolMembresia), nullable=True
    )
    parcelaId: Mapped[str | None] = mapped_column(
        String, ForeignKey("parcelas.id"), nullable=True
    )
    arancelId: Mapped[str | None] = mapped_column(String, nullable=True)
    # Audit columns (D7): plain nullable string ids, NO DB FK.
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True, default=None)
    updated_by: Mapped[str | None] = mapped_column(String(36), nullable=True, default=None)
