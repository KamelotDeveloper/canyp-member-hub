"""Tests for membresia rol (Titular/Integrante) and grouping categoria+rol (RQ 9, 11)."""

from datetime import date

from backend.models.arancel import Arancel
from backend.models.enums import Area, CategoriaParcela, EstadoMembresia, Predio, RolMembresia
from backend.models.membresia import Membresia
from backend.models.parcela import Parcela
from backend.models.socio import Socio


def _seed_unit(test_db):
    """Create a socio + parcela (cabaña, categoria Mediana) + 2 membresias with roles."""
    socio1 = Socio(
        id="s1",
        nombre="Ana",
        dni="30111111",
        fechaAlta=date(2024, 1, 1),
    )
    socio2 = Socio(
        id="s2",
        nombre="Luis",
        dni="30222222",
        fechaAlta=date(2024, 1, 1),
    )
    test_db.add_all([socio1, socio2])
    test_db.flush()  # ensure socios exist before FK references

    parcela = Parcela(
        id="p1",
        nombre="Cabaña E",
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
        vencimiento=date(2026, 1, 1),
        rol=RolMembresia.TITULAR,
        parcelaId="p1",
    )
    m2 = Membresia(
        id="m2",
        socioId="s2",
        area=Area.CABANEROS,
        predio=Predio.ALMAFUERTE,
        estado=EstadoMembresia.ACTIVA,
        vencimiento=date(2026, 1, 1),
        rol=RolMembresia.INTEGRANTE,
        parcelaId="p1",
    )
    test_db.add_all([m1, m2])
    test_db.commit()


class TestMembresiaRolCRUD:
    """Rol persists in create/update/get/response."""

    def test_create_membresia_with_rol(self, test_client, test_db):
        socio = Socio(
            id="s9", nombre="Socio", dni="30999998", fechaAlta=date(2024, 1, 1)
        )
        test_db.add(socio)
        test_db.commit()
        resp = test_client.post(
            "/api/membresias",
            json={
                "id": "m9",
                "socioId": "s9",
                "area": "Cabañeros",
                "predio": "Almafuerte",
                "estado": "activa",
                "vencimiento": "2026-01-01",
                "rol": "Titular",
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["rol"] == "Titular"
        # detalle may be null and is no longer used for role
        persisted = test_db.query(Membresia).filter(Membresia.id == "m9").first()
        assert persisted.rol == RolMembresia.TITULAR

    def test_create_membresia_without_id_generates_one(self, test_client, test_db):
        """POST /api/membresias without an id auto-generates one (RQ 5/10)."""
        socio = Socio(
            id="s11", nombre="Socio", dni="30999996", fechaAlta=date(2024, 1, 1)
        )
        test_db.add(socio)
        test_db.commit()
        resp = test_client.post(
            "/api/membresias",
            json={
                "socioId": "s11",
                "area": "Cabañeros",
                "predio": "Almafuerte",
                "estado": "activa",
                "vencimiento": "2026-01-01",
                "rol": "Integrante",
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["id"].startswith("m")
        assert body["rol"] == "Integrante"
        assert (
            test_db.query(Membresia).filter(Membresia.id == body["id"]).first()
            is not None
        )

    def test_update_membresia_rol(self, test_client, test_db):
        _seed_unit(test_db)
        resp = test_client.put("/api/membresias/m2", json={"rol": "Titular"})
        assert resp.status_code == 200
        assert resp.json()["rol"] == "Titular"
        test_db.expire_all()
        assert (
            test_db.query(Membresia).filter(Membresia.id == "m2").first().rol
            == RolMembresia.TITULAR
        )

    def test_get_membresia_returns_rol(self, test_client, test_db):
        _seed_unit(test_db)
        resp = test_client.get("/api/membresias/m1")
        assert resp.status_code == 200
        assert resp.json()["rol"] == "Titular"

    def test_create_membresia_without_rol_defaults_null(self, test_client, test_db):
        socio = Socio(
            id="s10", nombre="Socio", dni="30999997", fechaAlta=date(2024, 1, 1)
        )
        test_db.add(socio)
        test_db.commit()
        resp = test_client.post(
            "/api/membresias",
            json={
                "id": "m10",
                "socioId": "s10",
                "area": "Windsurf",
                "predio": "Almafuerte",
                "estado": "activa",
                "vencimiento": "2026-01-01",
            },
        )
        assert resp.status_code == 201
        assert resp.json()["rol"] is None


class TestMembresiaGrouping:
    """GET /api/membresias/parcelas returns categoria + rol."""

    def test_grouping_returns_categoria(self, test_client, test_db):
        _seed_unit(test_db)
        resp = test_client.get("/api/membresias/parcelas")
        assert resp.status_code == 200
        result = resp.json()
        assert len(result) == 1
        parcela = result[0]["parcela"]
        assert parcela["id"] == "p1"
        assert parcela["categoria"] == "Mediana"
        assert parcela["tipo"] == "cabaña"

    def test_grouping_returns_rol_per_membresia(self, test_client, test_db):
        _seed_unit(test_db)
        resp = test_client.get("/api/membresias/parcelas")
        membresias = resp.json()[0]["membresias"]
        roles = {m["socioId"]: m["rol"] for m in membresias}
        assert roles["s1"] == "Titular"
        assert roles["s2"] == "Integrante"
        assert all("rol" in m for m in membresias)


class TestDeleteMembresiaPreservesSocio:
    """RQ 10: DELETE /api/membresias/{id} removes the membership, NOT the socio."""

    def _seed_delete(self, test_db):
        """Socio s2 (María) has TWO memberships: m2 (integrante in p1) + m3 (balsa)."""
        socio1 = Socio(
            id="s1", nombre="Ana", dni="30111111", fechaAlta=date(2024, 1, 1)
        )
        socio2 = Socio(
            id="s2", nombre="María", dni="30222222", fechaAlta=date(2024, 1, 1)
        )
        test_db.add_all([socio1, socio2])
        test_db.flush()

        parcela = Parcela(
            id="p1",
            nombre="Cabaña A",
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
            vencimiento=date(2026, 1, 1),
            rol=RolMembresia.TITULAR,
            parcelaId="p1",
        )
        m2 = Membresia(
            id="m2",
            socioId="s2",
            area=Area.CABANEROS,
            predio=Predio.ALMAFUERTE,
            estado=EstadoMembresia.ACTIVA,
            vencimiento=date(2026, 1, 1),
            rol=RolMembresia.INTEGRANTE,
            parcelaId="p1",
        )
        # María's OTHER membership (Balseros, no parcela) — must survive the DELETE.
        m3 = Membresia(
            id="m3",
            socioId="s2",
            area=Area.BALSEROS,
            predio=Predio.ALMAFUERTE,
            estado=EstadoMembresia.ACTIVA,
            vencimiento=date(2026, 2, 1),
            rol=RolMembresia.TITULAR,
            parcelaId=None,
        )
        test_db.add_all([m1, m2, m3])
        test_db.commit()

    def test_delete_membresia_removes_it_and_keeps_socio(self, test_client, test_db):
        self._seed_delete(test_db)

        resp = test_client.delete("/api/membresias/m2")
        assert resp.status_code == 204

        # The membership is gone...
        assert test_client.get("/api/membresias/m2").status_code == 404

        # ...but María's socio record is intact.
        socio_resp = test_client.get("/api/socios/s2")
        assert socio_resp.status_code == 200
        assert socio_resp.json()["id"] == "s2"
        assert socio_resp.json()["nombre"] == "María"

    def test_delete_membresia_leaves_socios_other_memberships_untouched(
        self, test_client, test_db
    ):
        self._seed_delete(test_db)

        assert test_client.delete("/api/membresias/m2").status_code == 204

        # María's other membership (m3) still exists and still belongs to her.
        other = test_client.get("/api/membresias/m3")
        assert other.status_code == 200
        assert other.json()["socioId"] == "s2"

        # The Titular's membership (m1) is untouched.
        assert test_client.get("/api/membresias/m1").status_code == 200


class TestParcelaIdValidation:
    """Server-side parcelaId FK validation when SQLite FK is off in prod."""

    def test_create_membresia_with_unknown_parcelaid_422(self, test_client, test_db):
        socio = Socio(
            id="s11", nombre="Socio", dni="30999996", fechaAlta=date(2024, 1, 1)
        )
        test_db.add(socio)
        test_db.commit()
        resp = test_client.post(
            "/api/membresias",
            json={
                "id": "m11",
                "socioId": "s11",
                "area": "Cabañeros",
                "predio": "Almafuerte",
                "estado": "activa",
                "vencimiento": "2026-01-01",
                "rol": "Integrante",
                "parcelaId": "does-not-exist",
            },
        )
        assert resp.status_code == 422

    def test_create_membresia_with_existing_parcelaid_ok(self, test_client, test_db):
        _seed_unit(test_db)
        socio = Socio(
            id="s12", nombre="Socio", dni="30999995", fechaAlta=date(2024, 1, 1)
        )
        test_db.add(socio)
        test_db.commit()
        resp = test_client.post(
            "/api/membresias",
            json={
                "id": "m12",
                "socioId": "s12",
                "area": "Cabañeros",
                "predio": "Almafuerte",
                "estado": "activa",
                "vencimiento": "2026-01-01",
                "rol": "Integrante",
                "parcelaId": "p1",
            },
        )
        assert resp.status_code == 201
