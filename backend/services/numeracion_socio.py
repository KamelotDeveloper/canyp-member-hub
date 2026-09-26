"""Numeración secuencial del número de socio (carnet)."""

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.models.socio import Socio

# App-wide advisory lock key for member numbering (arbitrary constant, "SOCI").
_SOCIO_LOCK_KEY = 0x534F4349


def siguiente_numero_socio(db: Session) -> str:
    """Generate the next sequential member number atomically.

    Format: zero-padded 5 digits ("00001", "00002", ...).

    Concurrency (remoto/Supabase): mirrors the receipt numbering in
    ``backend/services/numeracion.py`` — ``pg_advisory_xact_lock`` serializes
    the whole read+compute+insert section app-wide; the lock is released
    automatically at commit/rollback. SQLite skips the call (local mode is
    effectively single-user and serializes writers with its database lock).
    """
    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(:key)"), {"key": _SOCIO_LOCK_KEY}
        )

    highest = 0
    for (numero,) in db.query(Socio.numero_socio).filter(
        Socio.numero_socio.is_not(None)
    ):
        try:
            highest = max(highest, int(str(numero).strip()))
        except ValueError:
            continue

    return f"{highest + 1:05d}"