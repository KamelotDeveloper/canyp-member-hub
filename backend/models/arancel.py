"""Arancel model."""

from datetime import date

from sqlalchemy import Date, Enum, Float, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base
from backend.models.enums import Area, CategoriaParcela, Predio


class Arancel(Base):
    __tablename__ = "aranceles"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    nombre: Mapped[str] = mapped_column(String, nullable=False)
    area: Mapped[Area] = mapped_column(Enum(Area), nullable=False)
    predio: Mapped[Predio] = mapped_column(Enum(Predio), nullable=False)
    monto: Mapped[float] = mapped_column(Float, nullable=False)
    categoria: Mapped[CategoriaParcela | None] = mapped_column(
        Enum(CategoriaParcela), nullable=True
    )
    vigenteDesde: Mapped[date] = mapped_column(Date, nullable=False)
    historico: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
