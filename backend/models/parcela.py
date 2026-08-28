"""Parcela model."""

from sqlalchemy import Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base
from backend.models.enums import CategoriaParcela, Predio, TipoParcela


class Parcela(Base):
    __tablename__ = "parcelas"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    nombre: Mapped[str] = mapped_column(String, nullable=False)
    tipo: Mapped[TipoParcela] = mapped_column(Enum(TipoParcela), nullable=False)
    tamano: Mapped[str | None] = mapped_column(String, nullable=True)
    predio: Mapped[Predio] = mapped_column(Enum(Predio), nullable=False)
    categoria: Mapped[CategoriaParcela | None] = mapped_column(
        Enum(CategoriaParcela), nullable=True
    )
