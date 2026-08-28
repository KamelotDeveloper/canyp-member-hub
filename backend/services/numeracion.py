"""Numeracion atomica de comprobantes de pago."""

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.models.pago import Pago


def siguiente_numero_comprobante(db: Session) -> str:
    """Generate the next sequential receipt number atomically.

    Format: "0001-XXXXXXXX" (prefix-8digit).
    Business rule (AGENTS.md §2): global sequential, not per-predio.
    """
    max_num: int | None = db.query(func.max(Pago.numero)).scalar()
    if max_num is None:
        next_num = 1
    else:
        # numero is stored as string like "0001-12345678"
        prefix = max_num.split("-")[0] if "-" in max_num else "0001"
        number_part = max_num.split("-")[1] if "-" in max_num else max_num
        next_num = int(number_part) + 1

    return f"{next_num:04d}-{next_num:08d}"
