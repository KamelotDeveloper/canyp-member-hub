"""Historial de aranceles — preserve monto history on change."""

from datetime import date

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from backend.models.arancel import Arancel


def actualizar_monto_arancel(
    db: Session, arancel_id: str, nuevo_monto: float
) -> Arancel:
    """Update arancel monto, saving the old value to historico[].

    Business rule (AGENTS.md §4): freeze montoAplicado at payment time.
    """
    arancel = db.query(Arancel).filter(Arancel.id == arancel_id).first()
    if arancel is None:
        raise ValueError(f"Arancel {arancel_id} not found")

    # Save current monto to historico with its vigenteDesde
    arancel.historico.append(
        {"monto": arancel.monto, "vigenteDesde": str(arancel.vigenteDesde)}
    )
    flag_modified(arancel, "historico")

    # Update monto and reset vigenteDesde to today
    arancel.monto = nuevo_monto
    arancel.vigenteDesde = date.today()

    db.commit()
    db.refresh(arancel)
    return arancel
