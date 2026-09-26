"""Socio model."""

from datetime import date

from sqlalchemy import Boolean, Date, LargeBinary, String
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
    # Categoria: free lowercase string ("activo" | "vitalicio"), optional.
    categoria: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    # Audit columns (D7): plain nullable string ids, NO DB FK.
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True, default=None)
    updated_by: Mapped[str | None] = mapped_column(String(36), nullable=True, default=None)
    # Carnet: sequential member number (zero-padded, unique) + photo (bytea).
    numero_socio: Mapped[str | None] = mapped_column(
        String, nullable=True, unique=True, default=None
    )
    foto: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True, default=None)

    @property
    def tieneFoto(self) -> bool:
        """Whether a carnet photo is stored (light field for SocioResponse)."""
        return self.foto is not None
