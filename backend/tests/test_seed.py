"""Tests for the Almafuerte seed dataset (RQ 16 — tasks 5.1/5.2).

Validates backend/seed.py against a throwaway in-memory engine. NEVER the
live canyp.db. Covers: >=4 Almafuerte cabañas covering all 4 categorías,
2-3 Almafuerte balsas, Titular/Integrante roles, mixed vencimientos,
Guardería in both Chica+Grande, per-categoría aranceles, preservation of the
pre-existing seed data, and idempotency (run twice = same state).
"""

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import backend.models  # noqa: F401  (register models on Base.metadata)
from backend.database import Base
from backend.models.arancel import Arancel
from backend.models.enums import (
    Area,
    CategoriaParcela,
    Predio,
    RolMembresia,
    TipoParcela,
)
from backend.models.membresia import Membresia
from backend.models.parcela import Parcela
from backend.models.socio import Socio
from backend.seed import seed
from backend.services.estado_visual import calcular_estado_visual


@pytest.fixture()
def seed_engine():
    """In-memory isolated engine (same pattern as conftest.test_db)."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _fk(dbapi_conn, _rec):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    return engine


@pytest.fixture()
def seeded(seed_engine):
    """Run seed() once against the temp engine; yield a bound session."""
    seed(engine=seed_engine)
    Session = sessionmaker(bind=seed_engine)
    db = Session()
    try:
        yield db
    finally:
        db.close()


def _almafuerte_cabanas(db):
    return (
        db.query(Parcela)
        .filter(
            Parcela.tipo == TipoParcela.CABANA,
            Parcela.predio == Predio.ALMAFUERTE,
        )
        .all()
    )


def _almafuerte_balsas(db):
    return (
        db.query(Parcela)
        .filter(
            Parcela.tipo == TipoParcela.BALSA,
            Parcela.predio == Predio.ALMAFUERTE,
        )
        .all()
    )


def _members_of(db, parcela_id):
    return db.query(Membresia).filter(Membresia.parcelaId == parcela_id).all()


class TestAlmafuerteDataset:
    """RQ16: mock cabañas cover all categorías + balsas present."""

    def test_at_least_four_cabanas_covering_all_categorias(self, seeded):
        cabanas = _almafuerte_cabanas(seeded)
        assert len(cabanas) >= 4
        categorias = {p.categoria.value for p in cabanas if p.categoria}
        assert categorias == {"Chica", "Mediana", "Especial", "Grande"}

    def test_bal_two_three_balsas_categoria_null(self, seeded):
        balsas = _almafuerte_balsas(seeded)
        assert 2 <= len(balsas) <= 3
        assert all(b.categoria is None for b in balsas)

    def test_each_cabana_has_titular_plus_integrante(self, seeded):
        for p in _almafuerte_cabanas(seeded):
            members = _members_of(seeded, p.id)
            assert len(members) >= 2, f"{p.nombre} needs >= 2 socios"
            roles = [m.rol for m in members]
            assert roles.count(RolMembresia.TITULAR) == 1, (
                f"{p.nombre} needs exactly 1 Titular, got {roles}"
            )
            assert RolMembresia.INTEGRANTE in roles, (
                f"{p.nombre} needs at least 1 Integrante, got {roles}"
            )

    def test_each_balsa_has_titular_plus_integrante(self, seeded):
        for p in _almafuerte_balsas(seeded):
            members = _members_of(seeded, p.id)
            assert len(members) >= 2, f"{p.nombre} needs >= 2 socios"
            roles = [m.rol for m in members]
            assert roles.count(RolMembresia.TITULAR) == 1, (
                f"{p.nombre} needs exactly 1 Titular, got {roles}"
            )
            assert RolMembresia.INTEGRANTE in roles, (
                f"{p.nombre} needs at least 1 Integrante, got {roles}"
            )

    def test_mixed_vencimientos_across_units(self, seeded):
        cabanas = _almafuerte_cabanas(seeded)
        balsas = _almafuerte_balsas(seeded)
        unit_ids = [p.id for p in cabanas + balsas]
        memberships = (
            seeded.query(Membresia).filter(Membresia.parcelaId.in_(unit_ids)).all()
        )
        assert len(memberships) >= 10
        estados = {
            calcular_estado_visual(m.estado.value, m.vencimiento)
            for m in memberships
        }
        assert {"vencida", "por_vencer", "activa"} <= estados, (
            f"expected mixed vencimientos, got: {estados}"
        )

    def test_guarderia_appears_in_chica_and_grande(self, seeded):
        for cat in (CategoriaParcela.CHICA, CategoriaParcela.GRANDE):
            parcelas = (
                seeded.query(Parcela)
                .filter(
                    Parcela.tipo == TipoParcela.GUARDERIA,
                    Parcela.categoria == cat,
                )
                .all()
            )
            assert parcelas, f"Guardería {cat.value} parcela missing"
            assert any(
                seeded.query(Membresia)
                .filter(
                    Membresia.parcelaId == p.id,
                    Membresia.area == Area.GUARDERIA,
                )
                .count()
                >= 1
                for p in parcelas
            ), f"Guardería {cat.value} has no member"

    def test_aranceles_exist_for_size_categorias(self, seeded):
        rows = (
            seeded.query(Arancel.categoria)
            .filter(
                Arancel.area == Area.CABANEROS,
                Arancel.predio == Predio.ALMAFUERTE,
                Arancel.categoria.isnot(None),
            )
            .all()
        )
        covered = {c.value for c, in rows if c}
        assert {"Chica", "Mediana", "Especial", "Grande"} <= covered

    def test_guarderia_aranceles_exist_for_both_categorias(self, seeded):
        rows = (
            seeded.query(Arancel.categoria)
            .filter(
                Arancel.area == Area.GUARDERIA,
                Arancel.predio == Predio.ALMAFUERTE,
                Arancel.categoria.isnot(None),
            )
            .all()
        )
        covered = {c.value for c, in rows if c}
        assert {"Chica", "Grande"} <= covered


class TestExistingSeedPreserved:
    """The pre-existing seed data (Embalse, etc.) must survive the addition."""

    def test_embalse_parcelas_still_present(self, seeded):
        embalse = (
            seeded.query(Parcela).filter(Parcela.predio == Predio.EMBALSE).all()
        )
        assert len(embalse) >= 3
        nombres = {p.nombre for p in embalse}
        for expected in ("Cabaña A", "Cabaña B", "Balsa Principal"):
            assert expected in nombres

    def test_original_membresias_still_present(self, seeded):
        assert seeded.query(Membresia).count() >= 16
        for mid in ("m1", "m2", "m5", "m14"):
            assert seeded.query(Membresia).filter(Membresia.id == mid).count() == 1

    def test_original_aranceles_still_present(self, seeded):
        assert seeded.query(Arancel).count() >= 7
        for aid in ("a1", "a2", "a3", "a4", "a5", "a6", "a7"):
            assert seeded.query(Arancel).filter(Arancel.id == aid).count() == 1


def _snapshot(engine):
    """Full state dump — used to prove re-running seed changes nothing."""
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        parcelas = db.query(Parcela).all()
        membresias = db.query(Membresia).all()
        return {
            "socios": db.query(Socio).count(),
            "parcelas": sorted(
                (
                    p.id,
                    p.nombre,
                    p.tipo.value,
                    p.predio.value,
                    p.categoria.value if p.categoria else None,
                )
                for p in parcelas
            ),
            "membresias": sorted(
                (
                    m.id,
                    m.socioId,
                    m.area.value,
                    m.predio.value,
                    m.estado.value,
                    m.vencimiento.isoformat(),
                    m.parcelaId,
                    m.rol.value if m.rol else None,
                )
                for m in membresias
            ),
            "aranceles": sorted(
                (
                    a.id,
                    a.area.value,
                    a.predio.value,
                    a.categoria.value if a.categoria else None,
                    a.monto,
                )
                for a in db.query(Arancel).all()
            ),
        }
    finally:
        db.close()


class TestIdempotency:
    def test_seed_twice_produces_identical_state(self, seed_engine):
        seed(engine=seed_engine)
        first = _snapshot(seed_engine)
        seed(engine=seed_engine)  # second run must be a no-op
        second = _snapshot(seed_engine)
        assert first == second

    def test_seed_exact_dataset_shape(self, seeded):
        """Lock the expected Almafuerte counts (4 cabañas, 2 balsas)."""
        assert len(_almafuerte_cabanas(seeded)) == 4
        assert len(_almafuerte_balsas(seeded)) == 2

    def test_seed_populates_all_tables(self, seeded):
        assert seeded.query(Parcela).count() == 11
        assert seeded.query(Socio).count() == 12
        assert seeded.query(Membresia).count() == 25
        assert seeded.query(Arancel).count() == 13