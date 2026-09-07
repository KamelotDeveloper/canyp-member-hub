"""Resolution of arancel monto for a membership's parcela (RQ 13).

Design #421 D3: a categoria-specific arancel wins; otherwise fall back to the
categoria IS NULL (catch-all) row for the same area+predio; otherwise None.
"""

from sqlalchemy.orm import Session

from backend.models.arancel import Arancel
from backend.models.enums import Area, CategoriaParcela, Predio


def resolver_monto(
    db: Session,
    area: Area,
    predio: Predio,
    categoria: CategoriaParcela | None,
    arancel_id: str | None = None,
) -> Arancel | None:
    """Resolve the applicable Arancel for area+predio+categoria.

    Priority:
      0. explicit arancel_id (when given and the Arancel still exists)
      1. exact categoria match (when categoria is not None)
      2. catch-all row where categoria IS NULL for the same area+predio
      3. None
    """
    if arancel_id is not None:
        directo = db.query(Arancel).filter(Arancel.id == arancel_id).first()
        if directo is not None:
            return directo

    if categoria is not None:
        exact = (
            db.query(Arancel)
            .filter(
                Arancel.area == area,
                Arancel.predio == predio,
                Arancel.categoria == categoria,
            )
            .first()
        )
        if exact is not None:
            return exact

    return (
        db.query(Arancel)
        .filter(
            Arancel.area == area,
            Arancel.predio == predio,
            Arancel.categoria.is_(None),
        )
        .first()
    )
