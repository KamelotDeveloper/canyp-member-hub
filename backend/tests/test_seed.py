"""Tests for the seed dataset (RQ 16 — tasks 5.1/5.2).

Validates backend/seed.py against a throwaway in-memory engine. NEVER the
live canyp.db. Covers: >=4 Almafuerte cabañas covering all 4 categorías,
2-3 Embalse balsas, Titular/Integrante roles, mixed vencimientos,
Guardería in both Chica+Grande, per-categoría aranceles, domain predio mapping
(Embalse = balsas only; Almafuerte = cabañas/guardería/windsurf), and
idempotency (run twice = same state).
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import backend.models  # noqa: F401  (register models on Base.metadata)
from backend.database import Base, get_db
from backend.main import app
from backend.models.arancel import Arancel
from backend.models.enums import (
    Area,
    CategoriaParcela,
    ConceptoCobro,
    ConceptoMembresia,
    EstadoSocioVisual,
    Predio,
    RolMembresia,
    TipoParcela,
)
from backend.models.membresia import Membresia
from backend.models.parcela import Parcela
from backend.models.socio import Socio
from backend.models.usuario import Usuario
from backend.security import create_access_token, hash_password
from backend.seed import seed
from backend.services.estado_socio import estados_socio


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


@pytest.fixture()
def seeded_client(seed_engine, seeded):
    """Authenticated TestClient bound to the SEEDED engine.

    Needed because the read paths under test are authenticated and must run
    against the seeded padron (not the throwaway ``test_db``).
    """
    usuario = Usuario(username="seeduser", password_hash=hash_password("testpass123"))
    seeded.add(usuario)
    seeded.commit()

    Session = sessionmaker(bind=seed_engine)
    token = create_access_token(usuario.id, usuario.username)

    def _override():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {token}"})
    try:
        yield client
    finally:
        app.dependency_overrides.clear()


def _almafuerte_cabanas(db):
    return (
        db.query(Parcela)
        .filter(
            Parcela.tipo == TipoParcela.CABANA,
            Parcela.predio == Predio.ALMAFUERTE,
        )
        .all()
    )


def _embalse_balsas(db):
    return (
        db.query(Parcela)
        .filter(
            Parcela.tipo == TipoParcela.BALSA,
            Parcela.predio == Predio.EMBALSE,
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
        balsas = _embalse_balsas(seeded)
        assert 2 <= len(balsas) <= 3
        assert all(b.categoria is None for b in balsas)

    def test_each_shared_cabana_has_titular_plus_integrante(self, seeded):
        shared = [p for p in _almafuerte_cabanas(seeded) if p.categoria is not None]
        assert len(shared) >= 4, "need >= 4 shared cabañas (categoría assigned)"
        for p in shared:
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
        for p in _embalse_balsas(seeded):
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
        balsas = _embalse_balsas(seeded)
        unit_ids = [p.id for p in cabanas + balsas]
        members = [
            m.socioId
            for m in seeded.query(Membresia)
            .filter(Membresia.parcelaId.in_(unit_ids))
            .all()
        ]
        assert len(members) >= 10
        estados = {
            e.value for e in estados_socio(seeded, sorted(set(members))).values()
        }
        # The padron must show a realistic mix under the 4-state model: some
        # are current, some need reviewing and some owe cuota social.
        assert {
            EstadoSocioVisual.ACTIVO,
            EstadoSocioVisual.ACTIVO_REVISAR,
            EstadoSocioVisual.INACTIVO_REVISAR,
        } <= estados, f"expected a mixed padron, got: {estados}"

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

    def test_embalse_parcelas_are_balsas_only(self, seeded):
        embalse = (
            seeded.query(Parcela).filter(Parcela.predio == Predio.EMBALSE).all()
        )
        nombres = {p.nombre for p in embalse}
        assert nombres == {"Balsa Principal", "Balsa Norte", "Balsa Sur"}
        assert all(p.tipo == TipoParcela.BALSA for p in embalse)
        assert all(p.categoria is None for p in embalse)

    def test_original_membresias_still_present(self, seeded):
        assert seeded.query(Membresia).count() >= 16
        for mid in ("m1", "m2", "m5", "m14"):
            assert seeded.query(Membresia).filter(Membresia.id == mid).count() == 1

    def test_original_aranceles_still_present(self, seeded):
        assert seeded.query(Arancel).count() == 11
        for aid in ("a1", "a7"):
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
                    # Null-safe: a cuota social row has no area/predio (CS-01).
                    m.area.value if m.area else None,
                    m.predio.value if m.predio else None,
                    m.estado.value,
                    m.vencimiento.isoformat(),
                    m.parcelaId,
                    m.rol.value if m.rol else None,
                    m.concepto.value,
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
                    a.concepto.value,
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
        """Lock the expected unit counts (6 cabañas Almafuerte, 3 balsas Embalse)."""
        assert len(_almafuerte_cabanas(seeded)) == 6
        assert len(_embalse_balsas(seeded)) == 3

    def test_seed_populates_all_tables(self, seeded):
        assert seeded.query(Parcela).count() == 11
        assert seeded.query(Socio).count() == 12
        # 27 area memberships + 12 cuota social rows (one per socio).
        assert seeded.query(Membresia).count() == 39
        # 7 area/price rows + the RECARGO carrier + the cuota social unit price
        # + the SERVICIO price.
        assert seeded.query(Arancel).count() == 11


class TestCuotaSocialEnElSeed:
    """Task 3.3: the seeded padron already lives on the cuota social model."""

    def _cuotas(self, seeded):
        return (
            seeded.query(Membresia)
            .filter(Membresia.concepto == ConceptoMembresia.CUOTA_SOCIAL)
            .all()
        )

    def test_exactly_one_cuota_social_per_socio(self, seeded):
        cuotas = self._cuotas(seeded)
        assert len(cuotas) == 12
        assert sorted(c.socioId for c in cuotas) == sorted(
            s.id for s in seeded.query(Socio).all()
        )

    def test_cuota_rows_carry_no_area_predio_nor_rol(self, seeded):
        for cuota in self._cuotas(seeded):
            assert cuota.area is None
            assert cuota.predio is None
            assert cuota.parcelaId is None
            assert cuota.rol is None

    def test_every_seeded_vencimiento_is_a_day_10(self, seeded):
        """The padron must already be on the 10->10 cycle, in both concepts."""
        for m in seeded.query(Membresia).all():
            assert m.vencimiento.day == 10, m.id

    def test_area_memberships_are_kept_as_AREA_concept(self, seeded):
        areas = [
            m
            for m in seeded.query(Membresia).all()
            if m.concepto == ConceptoMembresia.AREA
        ]
        assert len(areas) == 27
        assert all(m.area is not None and m.predio is not None for m in areas)

    def test_recargo_carrier_arancel_exists_with_zero_monto(self, seeded):
        """ARA-01: the RECARGO row is a carrier; the amount is operator-entered."""
        recargo = seeded.query(Arancel).filter(Arancel.concepto == ConceptoCobro.RECARGO).all()
        assert len(recargo) == 1
        assert recargo[0].monto == 0.0

    def test_cuota_social_unit_price_exists(self, seeded):
        """CS-03 needs ONE catalog price per member to multiply by unit size."""
        precios = (
            seeded.query(Arancel)
            .filter(Arancel.concepto == ConceptoCobro.CUOTA_SOCIAL)
            .all()
        )
        assert len(precios) == 1
        assert precios[0].monto > 0

    def test_servicio_price_exists_in_the_catalog(self, seeded):
        """Decision #646: unlike the recargo carrier, SERVICIO carries a price."""
        precios = (
            seeded.query(Arancel)
            .filter(Arancel.concepto == ConceptoCobro.SERVICIO)
            .all()
        )
        assert len(precios) == 1
        assert precios[0].monto > 0

    def test_dashboard_reads_a_padron_with_cuota_rows(self, seeded_client):
        """The seeded dataset must not 500 any read path (task 2.3 gate)."""
        assert seeded_client.get("/api/dashboard/stats").status_code == 200
        assert seeded_client.get("/api/dashboard/alertas").status_code == 200
        assert seeded_client.get("/api/membresias").status_code == 200

    def test_padron_appears_under_sin_area(self, seeded_client):
        """The 12 cuota rows are exactly the null-area population."""
        stats = seeded_client.get("/api/dashboard/stats").json()
        assert stats["countsByArea"]["Sin área"] == 12
        assert stats["totalMembresias"] == 39