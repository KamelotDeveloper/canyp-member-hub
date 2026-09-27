"""Arancel schemas."""

from datetime import date

from pydantic import BaseModel

from backend.models.enums import Area, CategoriaParcela, ConceptoCobro, Predio
from backend.schemas.common import OrmConfig


class ArancelHistorial(BaseModel):
    monto: float
    vigenteDesde: date


class ArancelBase(OrmConfig, BaseModel):
    nombre: str
    area: Area
    predio: Predio
    monto: float
    categoria: CategoriaParcela | None = None
    # Charge concept this row prices. Defaults to AREA, exactly like the column,
    # so an admin who omits it gets the safe one instead of a 422 (D4).
    concepto: ConceptoCobro = ConceptoCobro.AREA
    vigenteDesde: date
    historico: list[ArancelHistorial] = []


class ArancelCreate(ArancelBase):
    id: str | None = None


class ArancelUpdate(BaseModel):
    model_config = OrmConfig.model_config

    nombre: str | None = None
    area: Area | None = None
    predio: Predio | None = None
    monto: float | None = None
    categoria: CategoriaParcela | None = None
    # Writable on purpose (D4): create and update share the same validation
    # semantics, so an admin can retag a row without a second code path. An
    # explicit `null` is refused by the router with 422 — the column is NOT NULL.
    concepto: ConceptoCobro | None = None
    vigenteDesde: date | None = None
    historico: list[ArancelHistorial] | None = None


class ArancelResponse(ArancelBase):
    id: str
    # Audit columns (D7): null for rows created before multi-user auth.
    created_by: str | None = None
    updated_by: str | None = None
