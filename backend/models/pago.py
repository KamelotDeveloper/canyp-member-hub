"""Pago and PagoItem models."""

from datetime import date

from sqlalchemy import Date, Enum, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base
from backend.models.enums import ConceptoCobro


class Pago(Base):
    __tablename__ = "pagos"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    numero: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    socioId: Mapped[str] = mapped_column(String, ForeignKey("socios.id"), nullable=False)
    fecha: Mapped[date] = mapped_column(Date, nullable=False)
    medio: Mapped[str] = mapped_column(String, nullable=False)
    total: Mapped[float] = mapped_column(Float, nullable=False)
    nota: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    # Audit columns (D7): plain nullable string ids, NO DB FK. Only created_by
    # is written (pagos has no update endpoint).
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True, default=None)
    updated_by: Mapped[str | None] = mapped_column(String(36), nullable=True, default=None)


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
    # One item = one charge concept. NOT NULL with an AREA default keeps both
    # existing FKs intact, so no SQLite rebuild is needed (D2/PAG-01).
    concepto: Mapped[ConceptoCobro] = mapped_column(
        Enum(ConceptoCobro), nullable=False, default=ConceptoCobro.AREA
    )
    # Resolved multiplier behind montoAplicado (1.0 = not multiplied, e.g. balsa
    # stays flat; n = cuota social × unit member count).
    factor: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
