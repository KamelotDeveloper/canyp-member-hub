"""Tests for parcela categoria + import + batch endpoints (RQ 5, 8, 12)."""

from datetime import date

from backend.models.enums import (
    Area,
    CategoriaParcela,
    EstadoMembresia,
    Predio,
    RolMembresia,
    TipoParcela,
)
from backend.models.membresia import Membresia
from backend.models.parcela import Parcela
from backend.models.socio import Socio

BASE_PARCELA = {
    "id": "p001",
    "nombre": "Cabaña del Lago",
    "tipo": "cabaña",
    "predio": "Embalse",
}


class TestParcelaCategoria:
    """categoria persists in create/update/response (RQ 11)."""

    def test_create_parcela_with_categoria(self, test_client):
        resp = test_client.post(
            "/api/parcelas",
            json={**BASE_PARCELA, "categoria": "Mediana"},
        )
        assert resp.status_code == 201
        assert resp.json()["categoria"] == "Mediana"

    def test_create_parcela_without_categoria_defaults_null(self, test_client):
        resp = test_client.post("/api/parcelas", json=BASE_PARCELA)
        assert resp.status_code == 201
        assert resp.json()["categoria"] is None

    def test_update_parcela_categoria(self, test_client):
        test_client.post("/api/parcelas", json=BASE_PARCELA)
        resp = test_client.put("/api/parcelas/p001", json={"categoria": "Grande"})
        assert resp.status_code == 200
        assert resp.json()["categoria"] == "Grande"

    def test_created_categoria_is_persisted(self, test_client, test_db):
        test_client.post(
            "/api/parcelas", json={**BASE_PARCELA, "categoria": "Especial"}
        )
        p = test_db.query(Parcela).filter(Parcela.id == "p001").first()
        assert p is not None
        assert p.categoria == CategoriaParcela.ESPECIAL


IMPORT_PAYLOAD = {
    "unidades": [
        {
            "nombre": "Cabaña A",
            "tipo": "cabaña",
            "categoria": "Chica",
            "predio": "Almafuerte",
            "miembros": [
                {
                    "socio": {"nombre": "Ana", "dni": "11111111"},
                    "rol": "Titular",
                    "vencimiento": "2026-12-01",
                },
                {
                    "socio": {"nombre": "Luis", "dni": "22222222"},
                    "rol": "Integrante",
                    "vencimiento": "2026-12-01",
                },
            ],
        },
        {
            "nombre": "Cabaña B",
            "tipo": "cabaña",
            "categoria": "Grande",
            "predio": "Almafuerte",
            "miembros": [
                {
                    "socio": {"nombre": "María", "dni": "33333333"},
                    "rol": "Titular",
                    "vencimiento": "2026-12-01",
                }
            ],
        },
        {
            "nombre": "Balsa Norte",
            "tipo": "balsa",
            "predio": "Almafuerte",
            "miembros": [
                {
                    "socio": {"nombre": "Pedro", "dni": "44444444"},
                    "rol": "Titular",
                    "vencimiento": "2026-12-01",
                }
            ],
        },
    ]
}


class TestImportUnidades:
    """POST /api/parcelas/import — spec Import 3 units scenario."""

    def test_import_creates_parcelas_and_membresias(self, test_client, test_db):
        resp = test_client.post("/api/parcelas/import", json=IMPORT_PAYLOAD)
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["parcelas"]) == 3
        assert len(body["membresias"]) == 4  # 2+1+1

        parcelas = test_db.query(Parcela).all()
        assert len(parcelas) == 3
        cabana_a = (
            test_db.query(Parcela).filter(Parcela.nombre == "Cabaña A").first()
        )
        assert cabana_a.categoria == CategoriaParcela.CHICA
        assert cabana_a.tipo == TipoParcela.CABANA
        assert cabana_a.predio == Predio.ALMAFUERTE

        membresias = test_db.query(Membresia).all()
        assert len(membresias) == 4

    def test_import_is_idempotent(self, test_client, test_db):
        """Re-calling with same payload creates 0 additional records."""
        test_client.post("/api/parcelas/import", json=IMPORT_PAYLOAD)
        resp2 = test_client.post("/api/parcelas/import", json=IMPORT_PAYLOAD)
        assert resp2.status_code == 200
        body = resp2.json()
        # Second call creates nothing new — response lists newly-created ids only
        assert body["parcelas"] == []
        assert body["socios"] == []
        assert body["membresias"] == []

        # No duplicates in DB
        assert test_db.query(Parcela).count() == 3
        assert test_db.query(Membresia).count() == 4
        assert test_db.query(Socio).count() == 4

    def test_import_sets_rol_on_membresias(self, test_client, test_db):
        test_client.post("/api/parcelas/import", json=IMPORT_PAYLOAD)
        ana = test_db.query(Socio).filter(Socio.dni == "11111111").first()
        m_ana = (
            test_db.query(Membresia).filter(Membresia.socioId == ana.id).first()
        )
        assert m_ana.rol == RolMembresia.TITULAR
        luis = test_db.query(Socio).filter(Socio.dni == "22222222").first()
        m_luis = (
            test_db.query(Membresia).filter(Membresia.socioId == luis.id).first()
        )
        assert m_luis.rol == RolMembresia.INTEGRANTE

    def test_import_validation_error_rolls_back(self, test_client, test_db):
        """An invalid row (bad rol) returns 422 and nothing is persisted."""
        bad_payload = {
            "unidades": [
                {
                    "nombre": "Cabaña Z",
                    "tipo": "cabaña",
                    "predio": "Almafuerte",
                    "miembros": [
                        {
                            "socio": {"nombre": "Zoe", "dni": "55555555"},
                            "rol": "NoExiste",
                            "vencimiento": "2026-12-01",
                        }
                    ],
                }
            ]
        }
        resp = test_client.post("/api/parcelas/import", json=bad_payload)
        assert resp.status_code == 422
        assert test_db.query(Parcela).count() == 0
        assert test_db.query(Membresia).count() == 0
        assert test_db.query(Socio).count() == 0


class TestBatchEndpoints:
    """POST /{id}/estado and PUT /{id}/vencimiento affect all membresias."""

    def _seed_multimember_unit(self, test_db):
        socio1 = Socio(
            id="s1", nombre="Ana", dni="60111111", fechaAlta=date(2024, 1, 1)
        )
        socio2 = Socio(
            id="s2", nombre="Luis", dni="60222222", fechaAlta=date(2024, 1, 1)
        )
        test_db.add_all([socio1, socio2])
        test_db.flush()
        parcela = Parcela(
            id="p1",
            nombre="Cabaña Multi",
            tipo="cabaña",
            predio=Predio.ALMAFUERTE,
            categoria=CategoriaParcela.MEDIANA,
        )
        test_db.add(parcela)
        test_db.flush()
        m1 = Membresia(
            id="m1",
            socioId="s1",
            area=Area.CABANEROS,
            predio=Predio.ALMAFUERTE,
            estado=EstadoMembresia.ACTIVA,
            vencimiento=date(2027, 1, 1),
            parcelaId="p1",
        )
        m2 = Membresia(
            id="m2",
            socioId="s2",
            area=Area.CABANEROS,
            predio=Predio.ALMAFUERTE,
            estado=EstadoMembresia.ACTIVA,
            vencimiento=date(2027, 1, 1),
            parcelaId="p1",
        )
        test_db.add_all([m1, m2])
        test_db.commit()

    def test_batch_estado_updates_all(self, test_client, test_db):
        self._seed_multimember_unit(test_db)
        resp = test_client.post("/api/parcelas/p1/estado", json={"estado": "suspendida"})
        assert resp.status_code == 200
        test_db.expire_all()
        estados = {
            m.estado.value
            for m in test_db.query(Membresia).filter(Membresia.parcelaId == "p1").all()
        }
        assert estados == {"suspendida"}

    def test_batch_vencimiento_updates_all(self, test_client, test_db):
        self._seed_multimember_unit(test_db)
        resp = test_client.put(
            "/api/parcelas/p1/vencimiento", json={"vencimiento": "2028-06-01"}
        )
        assert resp.status_code == 200
        test_db.expire_all()
        vencimientos = {
            m.vencimiento.isoformat()
            for m in test_db.query(Membresia).filter(Membresia.parcelaId == "p1").all()
        }
        assert vencimientos == {"2028-06-01"}

    def test_batch_estado_nonexistent_parcela_404(self, test_client):
        resp = test_client.post("/api/parcelas/nope/estado", json={"estado": "baja"})
        assert resp.status_code == 404

    def test_batch_vencimiento_nonexistent_parcela_404(self, test_client):
        resp = test_client.put(
            "/api/parcelas/nope/vencimiento", json={"vencimiento": "2028-06-01"}
        )
        assert resp.status_code == 404
