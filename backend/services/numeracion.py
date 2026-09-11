"""Numeracion atomica de comprobantes de pago."""

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.models.pago import Pago

# App-wide advisory lock key for receipt numbering (arbitrary constant, "NUME").
_NUMERACION_LOCK_KEY = 0x4E554D45


def siguiente_numero_comprobante(db: Session) -> str:
    """Generate the next sequential receipt number atomically.

    Format: "0001-XXXXXXXX" (prefix-8digit).
    Business rule (AGENTS.md §2): global sequential, not per-predio.

    Concurrency (remoto/Supabase): a plain ``SELECT max(...) + 1`` pattern races
    when two admins save a payment at the same instant — both read the same last
    number and produce a duplicate. ``SELECT ... FOR UPDATE`` alone does NOT fix
    that under READ COMMITTED because the second transaction's snapshot cannot
    see the INSERT committed by the first one after its statement started.

    Fix: ``pg_advisory_xact_lock`` serializes the whole read+compute+insert
    section app-wide; the lock is released automatically at commit/rollback.
    SQLite skips the call (syntax is Postgres-only); local mode is effectively
    single-user and SQLite serializes writers with its database lock anyway.
    """
    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(:key)"), {"key": _NUMERACION_LOCK_KEY}
        )

    last = (
        db.query(Pago.numero)
        .order_by(Pago.numero.desc())
        .first()
    )

    if last is None:
        next_num = 1
    else:
        max_num = last[0]
        # numero is stored as a zero-padded sequential string like "0001-12345678"
        number_part = max_num.split("-")[1] if "-" in max_num else max_num
        next_num = int(number_part) + 1

    return f"{next_num:04d}-{next_num:08d}"
