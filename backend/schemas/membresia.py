"""Membresia schemas."""

from datetime import date

from pydantic import BaseModel

from backend.models.enums import (
    Area,
    ConceptoMembresia,
    EstadoMembresia,
    Predio,
    RolMembresia,
)
from backend.schemas.common import OrmConfig


class MembresiaBase(OrmConfig, BaseModel):
    socioId: str
    # area/predio are optional: a cuota social membership is not a physical
    # location and carries neither (spec CS-01). Both columns are nullable in
    # the DB, so the response schema must accept null or serialising a cuota
    # social row would 500 the whole list.
    area: Area | None = None
    predio: Predio | None = None
    estado: EstadoMembresia
    vencimiento: date
    detalle: str | None = None
    rol: RolMembresia | None = None
    parcelaId: str | None = None
    arancelId: str | None = None


class MembresiaCreate(MembresiaBase):
    id: str | None = None


class MembresiaUpdate(BaseModel):
    model_config = OrmConfig.model_config

    socioId: str | None = None
    area: Area | None = None
    predio: Predio | None = None
    estado: EstadoMembresia | None = None
    vencimiento: date | None = None
    detalle: str | None = None
    rol: RolMembresia | None = None
    parcelaId: str | None = None
    arancelId: str | None = None


class MembresiaVencimientoUpdate(BaseModel):
    """Body of the manual `vencimiento` editor (spec CBM-06).

    Deliberately NOT `MembresiaUpdate`: `vencimiento` is REQUIRED and non-null
    here, so a missing, null or malformed date is rejected by the schema with a
    422 BEFORE any handler runs — that is what makes the edit atomic (nothing is
    read, nothing is written, no row is half-touched).
    """

    model_config = OrmConfig.model_config

    vencimiento: date


class MembresiaResponse(MembresiaBase):
    id: str
    # Read-only exposure of the membership concept (MEM-01). The frontend reads
    # it instead of re-deriving "no area ⇒ cuota social", and it keeps every
    # non-cobro surface (badges, tables) off a null-`area` code path. Output-only
    # on purpose: `MembresiaCreate`/`MembresiaUpdate` are unchanged.
    concepto: ConceptoMembresia | None = None
    # Audit columns (D7): null for rows created before multi-user auth.
    created_by: str | None = None
    updated_by: str | None = None
