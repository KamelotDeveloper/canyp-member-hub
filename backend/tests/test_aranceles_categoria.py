"""Tests for arancel categoria dimension and resolver_monto fallback (RQ 13)."""

from datetime import date

from backend.models.arancel import Arancel
from backend.models.enums import Area, CategoriaParcela, Predio
from backend.services.resolucion import resolver_monto


def _mkdir_aranceles(db):
    """Seed the category-specific + catch-all aranceles from spec scenario."""
    aranceles = [
        Arancel(
            id="a_cab_chica",
            nombre="Cuota Cabañeros Chica",
            area=Area.CABANEROS,
            predio=Predio.ALMAFUERTE,
            monto=100.0,
            categoria=CategoriaParcela.CHICA,
            vigenteDesde=date(2025, 1, 1),
            historico=[],
        ),
        Arancel(
            id="a_cab_grande",
            nombre="Cuota Cabañeros Grande",
            area=Area.CABANEROS,
            predio=Predio.ALMAFUERTE,
            monto=200.0,
            categoria=CategoriaParcela.GRANDE,
            vigenteDesde=date(2025, 1, 1),
            historico=[],
        ),
        Arancel(
            id="a_bal_catchall",
            nombre="Cuota Balseros Almafuerte",
            area=Area.BALSEROS,
            predio=Predio.ALMAFUERTE,
            monto=150.0,
            categoria=None,
            vigenteDesde=date(2025, 1, 1),
            historico=[],
        ),
    ]
    db.add_all(aranceles)
    db.commit()


class TestResolverMontoCategoria:
    """resolver_monto(): exact categoria match, then catch-all, then None."""

    def test_exact_categoria_wins(self, test_db):
        """A categoria-specific arancel returns its own montos (spec)."""
        _mkdir_aranceles(test_db)
        monto_chico = resolver_monto(
            test_db, Area.CABANEROS, Predio.ALMAFUERTE, CategoriaParcela.CHICA
        )
        monto_grande = resolver_monto(
            test_db, Area.CABANEROS, Predio.ALMAFUERTE, CategoriaParcela.GRANDE
        )
        assert monto_chico is not None
        assert monto_chico.monto == 100.0
        assert monto_grande.monto == 200.0

    def test_null_categoria_falls_back_to_catchall(self, test_db):
        """Balsa (null categoria) matches the null-catch-all arancel (spec)."""
        _mkdir_aranceles(test_db)
        arancel = resolver_monto(
            test_db, Area.BALSEROS, Predio.ALMAFUERTE, None
        )
        assert arancel is not None
        assert arancel.monto == 150.0

    def test_unknown_categoria_falls_back_to_catchall(self, test_db):
        """A categoria with no specific row falls back to category IS NULL."""
        # Cabañeros only has CHICA/GRANDE rows; MEDIANA should fall to... none.
        _mkdir_aranceles(test_db)
        arancel = resolver_monto(
            test_db, Area.CABANEROS, Predio.ALMAFUERTE, CategoriaParcela.MEDIANA
        )
        # No specific row AND no catch-all for Cabañeros/Almafuerte → None
        assert arancel is None

    def test_catchall_shadows_unknown_categoria(self, test_db):
        """When a catch-all exists, unknown categoria resolves to it."""
        catchall = Arancel(
            id="a_cab_catchall",
            nombre="Cuota Cabañeros Almafuerte",
            area=Area.CABANEROS,
            predio=Predio.ALMAFUERTE,
            monto=90.0,
            categoria=None,
            vigenteDesde=date(2025, 1, 1),
            historico=[],
        )
        test_db.add(catchall)
        test_db.commit()
        arancel = resolver_monto(
            test_db, Area.CABANEROS, Predio.ALMAFUERTE, CategoriaParcela.MEDIANA
        )
        assert arancel is not None
        assert arancel.monto == 90.0

    def test_no_match_returns_none(self, test_db):
        """No arancel at all → None."""
        _mkdir_aranceles(test_db)
        arancel = resolver_monto(
            test_db, Area.GUARDERIA, Predio.EMBALSE, CategoriaParcela.CHICA
        )
        assert arancel is None


class TestArancelCreateCategoria:
    """POST /api/aranceles accepts optional categoria (RQ 13)."""

    def test_create_arancel_with_categoria(self, test_client):
        resp = test_client.post(
            "/api/aranceles",
            json={
                "id": "a_cat",
                "nombre": "Cuota Cabañeros Especial",
                "area": "Cabañeros",
                "predio": "Almafuerte",
                "monto": 13000.0,
                "categoria": "Especial",
                "vigenteDesde": "2025-06-01",
                "historico": [],
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["categoria"] == "Especial"

    def test_create_arancel_without_categoria_defaults_null(self, test_client):
        resp = test_client.post(
            "/api/aranceles",
            json={
                "id": "a_nocat",
                "nombre": "Cuota Balseros",
                "area": "Balseros",
                "predio": "Almafuerte",
                "monto": 9999.0,
                "vigenteDesde": "2025-06-01",
                "historico": [],
            },
        )
        assert resp.status_code == 201
        assert resp.json()["categoria"] is None

    def test_created_categoria_is_persisted(self, test_client, test_db):
        test_client.post(
            "/api/aranceles",
            json={
                "id": "a_persist",
                "nombre": "Cuota Guardería Chica",
                "area": "Guardería",
                "predio": "Embalse",
                "monto": 7000.0,
                "categoria": "Chica",
                "vigenteDesde": "2025-06-01",
                "historico": [],
            },
        )
        a = test_db.query(Arancel).filter(Arancel.id == "a_persist").first()
        assert a is not None
        assert a.categoria == CategoriaParcela.CHICA
