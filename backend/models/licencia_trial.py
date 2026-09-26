"""Modelo de trial local para la licencia de suscripción.

El trial es 100% local (SQLite): el webhook remoto jamás lo conoce. Una fila
por (client_id, app_id) — constraint único, idempotente ante re-solicitudes.
"""

from datetime import datetime, timedelta

from sqlalchemy import Boolean, DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base

TRIAL_DAYS = 7


class LicenciaTrial(Base):
    __tablename__ = "licencia_trials"
    __table_args__ = (
        UniqueConstraint("client_id", "app_id", name="uq_licencia_trial_pair"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    app_id: Mapped[str] = mapped_column(String(64), nullable=False, default="canyp")
    fecha_inicio: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    fecha_fin: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    def __repr__(self) -> str:
        return (
            f"<LicenciaTrial(client_id={self.client_id!r}, app_id={self.app_id!r}, "
            f"activo={self.activo})>"
        )


def fecha_fin_trial(fecha_inicio: datetime) -> datetime:
    """Fecha de expiración del trial (7 días desde su inicio)."""
    return fecha_inicio + timedelta(days=TRIAL_DAYS)