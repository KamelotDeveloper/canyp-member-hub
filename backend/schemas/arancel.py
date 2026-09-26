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
    vigenteDesde: date | None = None
    historico: list[ArancelHistorial] | None = None


class ArancelResponse(ArancelBase):
    id: str
    # Read-only exposure of the catalog concept (CBM-01). The frontend needs it
    # to know which row prices the cuota social and which one prices a servicio
    # charge, and MUST NOT infer it from the row's name. Output-only on purpose:
    # `ArancelCreate`/`ArancelUpdate` are unchanged, so this adds no write path.
    concepto: ConceptoCobro | None = None
    # Audit columns (D7): null for rows created before multi-user auth.
    created_by: str | None = None
    updated_by: str | None = None
