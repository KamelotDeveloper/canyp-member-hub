"""Tests for membresia arancelId (explicit arancel assignment) and resolver_monto override."""

from datetime import date

from backend.models.arancel import Arancel
from backend.models.enums import Area, CategoriaParcela, EstadoMembresia, Predio
from backend.models.membresia import Membresia
from backend.models.socio import Socio
from backend.services.resolucion import resolver_monto


def _seed_socio(test_db, socio_id="s1", dni="30111111"):
    socio = Socio(
        id=socio_id,
        nombre="Ana",
        dni=dni,
        fechaAlta=date(2024, 1, 1),
    )
    test_db.add(socio)
    test_db.commit()


def _seed_aranceles(test_db):
    """Catch-all + categoria-specific aranceles for Cabañeros/Almafuerte."""
    aranceles = [
        Arancel(
            id="a_catchall",
            nombre="Cuota Cabañeros Almafuerte",
            area=Area.CABANEROS,
            predio=Predio.ALMAFUERTE,
            monto=100.0,
            categoria=None,
            vigenteDesde=date(2025, 1, 1),
            historico=[],
        ),
        Arancel(
            id="a_chica",
            nombre="Cuota Cabañeros Chica",
            area=Area.CABANEROS,
            predio=Predio.ALMAFUERTE,
            monto=80.0,
            categoria=CategoriaParcela.CHICA,
            vigenteDesde=date(2025, 1, 1),
            historico=[],
        ),
        Arancel(
            id="a_grande",
            nombre="Cuota Cabañeros Grande",
            area=Area.CABANEROS,
            predio=Predio.ALMAFUERTE,
            monto=200.0,
            categoria=CategoriaParcela.GRANDE,
            vigenteDesde=date(2025, 1, 1),
            historico=[],
        ),
    ]
    test_db.add_all(aranceles)
    test_db.commit()


class TestMembresiaArancelCRUD:
    """arancelId persists in create/update/clear/get/response."""

    def test_create_membresia_with_arancel_id_persists(self, test_client, test_db):
        _seed_socio(test_db)
        resp = test_client.post(
            "/api/membresias",
            json={
                "id": "m9",
                "socioId": "s1",
                "area": "Cabañeros",
                "predio": "Almafuerte",
                "estado": "activa",
                "vencimiento": "2026-01-01",
                "arancelId": "a_chica",
            },
        )
        assert resp.status_code == 201
        assert resp.json()["arancelId"] == "a_chica"
        persisted = test_db.query(Membresia).filter(Membresia.id == "m9").first()
        assert persisted.arancelId == "a_chica"

    def test_create_membresia_without_arancel_id_defaults_null(self, test_client, test_db):
        _seed_socio(test_db, socio_id="s2", dni="30222222")
        resp = test_client.post(
            "/api/membresias",
            json={
                "id": "m10",
                "socioId": "s2",
                "area": "Guardería",
                "predio": "Almafuerte",
                "estado": "activa",
                "vencimiento": "2026-01-01",
            },
        )
        assert resp.status_code == 201
        assert resp.json()["arancelId"] is None

    def test_get_membresia_returns_arancel_id(self, test_client, test_db):
        _seed_socio(test_db)
        test_client.post(
            "/api/membresias",
            json={
                "id": "m9",
                "socioId": "s1",
                "area": "Cabañeros",
                "predio": "Almafuerte",
                "estado": "activa",
                "vencimiento": "2026-01-01",
                "arancelId": "a_chica",
            },
        )
        resp = test_client.get("/api/membresias/m9")
        assert resp.status_code == 200
        assert resp.json()["arancelId"] == "a_chica"

    def test_update_membresia_sets_arancel_id(self, test_client, test_db):
        _seed_socio(test_db)
        test_client.post(
            "/api/membresias",
            json={
                "id": "m9",
                "socioId": "s1",
                "area": "Cabañeros",
                "predio": "Almafuerte",
                "estado": "activa",
                "vencimiento": "2026-01-01",
            },
        )
        resp = test_client.put("/api/membresias/m9", json={"arancelId": "a_grande"})
        assert resp.status_code == 200
        assert resp.json()["arancelId"] == "a_grande"
        test_db.expire_all()
        assert (
            test_db.query(Membresia).filter(Membresia.id == "m9").first().arancelId
            == "a_grande"
        )

    def test_update_membresia_clears_arancel_id(self, test_client, test_db):
        _seed_socio(test_db)
        test_client.post(
            "/api/membresias",
            json={
                "id": "m9",
                "socioId": "s1",
                "area": "Cabañeros",
                "predio": "Almafuerte",
                "estado": "activa",
                "vencimiento": "2026-01-01",
                "arancelId": "a_chica",
            },
        )
        resp = test_client.put("/api/membresias/m9", json={"arancelId": None})
        assert resp.status_code == 200
        assert resp.json()["arancelId"] is None
        test_db.expire_all()
        assert (
            test_db.query(Membresia).filter(Membresia.id == "m9").first().arancelId
            is None
        )


class TestResolverMontoExplicitArancel:
    """resolver_monto(..., arancel_id) returns the explicit arancel when it exists."""

    def test_explicit_arancel_wins_over_heuristic(self, test_db):
        """a_chica is returned even though the heuristic would pick a_grande."""
        _seed_aranceles(test_db)
        arancel = resolver_monto(
            test_db,
            Area.CABANEROS,
            Predio.ALMAFUERTE,
            CategoriaParcela.GRANDE,
            arancel_id="a_chica",
        )
        assert arancel is not None
        assert arancel.id == "a_chica"
        assert arancel.monto == 80.0

    def test_missing_arancel_id_falls_back_to_heuristic(self, test_db):
        _seed_aranceles(test_db)
        arancel = resolver_monto(
            test_db, Area.CABANEROS, Predio.ALMAFUERTE, CategoriaParcela.CHICA
        )
        assert arancel is not None
        assert arancel.id == "a_chica"

    def test_stale_arancel_id_falls_back_to_heuristic(self, test_db):
        """An arancel_id that no longer exists → heuristic path."""
        _seed_aranceles(test_db)
        arancel = resolver_monto(
            test_db,
            Area.CABANEROS,
            Predio.ALMAFUERTE,
            CategoriaParcela.CHICA,
            arancel_id="a_eliminado",
        )
        assert arancel is not None
        assert arancel.id == "a_chica"

    def test_no_match_returns_none(self, test_db):
        """No arancel for the area+predio and no valid explicit id → None."""
        arancel = resolver_monto(
            test_db,
            Area.GUARDERIA,
            Predio.EMBALSE,
            CategoriaParcela.CHICA,
            arancel_id="no-existe",
        )
        assert arancel is None