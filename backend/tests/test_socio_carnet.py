"""Tests for carnet capabilities: numero_socio + foto (membership ID cards).

Mirrors the house test style: ``test_client`` fixture (auth auto-attached),
in-memory SQLite per test, photos generated with Pillow.
"""

from io import BytesIO

import pytest
from PIL import Image

from backend.models.socio import Socio

MAX_FOTO_BYTES = 5 * 1024 * 1024


def _make_jpeg(size=(100, 100), color=(255, 0, 0)) -> bytes:
    """Return a small in-memory JPEG (red square by default)."""
    buf = BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG")
    return buf.getvalue()


def _socio_payload(**overrides):
    payload = {
        "nombre": "Socio Carnet",
        "dni": "30123456",
        "telefono": "",
        "email": "",
        "direccion": "",
        "activo": True,
    }
    payload.update(overrides)
    return payload


class TestNumeroSocioAutomatico:
    """Auto-assigned sequential numero_socio on create."""

    def test_first_socio_gets_00001(self, test_client):
        resp = test_client.post("/api/socios", json=_socio_payload(dni="30123456"))
        assert resp.status_code == 201
        assert resp.json()["numeroSocio"] == "00001"

    def test_second_socio_gets_00002(self, test_client):
        test_client.post("/api/socios", json=_socio_payload(dni="30123456"))
        resp = test_client.post("/api/socios", json=_socio_payload(dni="30123457"))
        assert resp.status_code == 201
        assert resp.json()["numeroSocio"] == "00002"

    def test_sequential_ascending(self, test_client):
        for i in range(5):
            resp = test_client.post(
                "/api/socios", json=_socio_payload(dni=f"3012345{i+1}")
            )
            assert resp.status_code == 201
            assert resp.json()["numeroSocio"] == f"{i + 1:05d}"

    def test_honors_explicit_numero_socio(self, test_client):
        resp = test_client.post(
            "/api/socios", json=_socio_payload(dni="30123456", numeroSocio="00420")
        )
        assert resp.status_code == 201
        assert resp.json()["numeroSocio"] == "00420"

    def test_continues_after_explicit_value(self, test_client):
        test_client.post(
            "/api/socios", json=_socio_payload(dni="30123456", numeroSocio="00420")
        )
        resp = test_client.post("/api/socios", json=_socio_payload(dni="30123457"))
        assert resp.status_code == 201
        assert resp.json()["numeroSocio"] == "00421"

    def test_empty_explicit_numero_socio_rejected(self, test_client):
        resp = test_client.post(
            "/api/socios", json=_socio_payload(dni="30123456", numeroSocio="")
        )
        assert resp.status_code == 422

    def test_duplicate_explicit_numero_socio_rejected(self, test_client):
        """Duplicate numeroSocio violates the unique constraint at DB level.
        The router doesn't catch IntegrityError (same behavior as duplicate DNI)."""
        test_client.post(
            "/api/socios", json=_socio_payload(dni="30123456", numeroSocio="00001")
        )
        with pytest.raises(Exception, match="UNIQUE"):
            test_client.post(
                "/api/socios", json=_socio_payload(dni="30123457", numeroSocio="00001")
            )

    def test_update_keeps_numero_socio(self, test_client):
        resp = test_client.post(
            "/api/socios", json=_socio_payload(dni="30123456", id="sUpd")
        )
        assert resp.json()["numeroSocio"] == "00001"
        resp = test_client.put("/api/socios/sUpd", json={"nombre": "Actualizado"})
        assert resp.status_code == 200
        assert resp.json()["numeroSocio"] == "00001"

    def test_update_can_set_numero_socio(self, test_client):
        test_client.post(
            "/api/socios", json=_socio_payload(dni="30123456", id="sUpd2")
        )
        resp = test_client.put("/api/socios/sUpd2", json={"numeroSocio": "00099"})
        assert resp.status_code == 200
        assert resp.json()["numeroSocio"] == "00099"


class TestSocioCarnetResponseShape:
    """SocioResponse exposes numeroSocio + tieneFoto but NEVER raw foto bytes."""

    def test_create_and_get_include_carnet_fields(self, test_client):
        test_client.post("/api/socios", json=_socio_payload(dni="30123456"))
        resp = test_client.get("/api/socios")
        assert resp.status_code == 200
        body = resp.json()
        assert "foto" not in body[0], "raw foto bytes must never be serialized"
        assert body[0]["numeroSocio"] == "00001"
        assert body[0]["tieneFoto"] is False

    def test_single_socio_response_omits_foto(self, test_client):
        test_client.post("/api/socios", json=_socio_payload(dni="30123456"))
        socios = test_client.get("/api/socios").json()
        sid = socios[0]["id"]
        single = test_client.get(f"/api/socios/{sid}").json()
        assert "foto" not in single
        assert single["numeroSocio"] == "00001"
        assert single["tieneFoto"] is False

    def test_list_payload_has_no_bloat_fields(self, test_client):
        for i in range(3):
            test_client.post(
                "/api/socios", json=_socio_payload(dni=f"3012345{i + 1}")
            )
        for socio in test_client.get("/api/socios").json():
            assert set(socio.keys()) == {
                "nombre",
                "dni",
                "telefono",
                "email",
                "direccion",
                "fechaAlta",
                "activo",
                "categoria",
                "id",
                "createdBy",
                "updatedBy",
                "numeroSocio",
                "tieneFoto",
                "estado",
                "nominacion",
            }


class TestSocioFotoUpload:
    """POST/GET /api/socios/{id}/foto carnet photo flow."""

    def _create_socio(self, test_client, socio_id="sFoto"):
        resp = test_client.post(
            "/api/socios", json=_socio_payload(dni="30123456", id=socio_id)
        )
        assert resp.status_code == 201
        return socio_id

    def test_upload_and_get_roundtrip(self, test_client, test_db):
        socio_id = self._create_socio(test_client)
        image = _make_jpeg()

        resp = test_client.post(
            "/api/socios/sFoto/foto",
            files={"foto": ("foto.jpg", image, "image/jpeg")},
        )
        assert resp.status_code == 200
        assert resp.json() == {"tieneFoto": True}

        # Stored as bytea on the socio row.
        socio = test_db.query(Socio).filter(Socio.id == socio_id).one()
        assert socio.foto is not None and len(socio.foto) > 0

        get = test_client.get("/api/socios/sFoto/foto")
        assert get.status_code == 200
        assert get.headers["content-type"] == "image/jpeg"
        assert get.content == socio.foto

        # SocioResponse now reports tieneFoto true.
        body = test_client.get("/api/socios/sFoto").json()
        assert body["tieneFoto"] is True

    def test_upload_resizes_large_image_to_800px(self, test_client):
        self._create_socio(test_client)
        image = _make_jpeg(size=(2000, 1000))

        resp = test_client.post(
            "/api/socios/sFoto/foto",
            files={"foto": ("foto.jpg", image, "image/jpeg")},
        )
        assert resp.status_code == 200

        stored = test_client.get("/api/socios/sFoto/foto").content
        with Image.open(BytesIO(stored)) as img:
            assert img.format == "JPEG"
            assert max(img.size) == 800

    def test_upload_rejects_non_image_content_type(self, test_client):
        self._create_socio(test_client)
        resp = test_client.post(
            "/api/socios/sFoto/foto",
            files={"foto": ("nota.txt", b"hola", "text/plain")},
        )
        assert resp.status_code == 415

    def test_upload_rejects_garbage_image(self, test_client):
        self._create_socio(test_client)
        resp = test_client.post(
            "/api/socios/sFoto/foto",
            files={"foto": ("foto.jpg", b"not really an image", "image/jpeg")},
        )
        assert resp.status_code == 415

    def test_upload_rejects_oversize(self, test_client):
        self._create_socio(test_client)
        huge = b"\xff\xd8\xff\xe0" * (MAX_FOTO_BYTES // 4 + 1)
        resp = test_client.post(
            "/api/socios/sFoto/foto",
            files={"foto": ("foto.jpg", huge, "image/jpeg")},
        )
        assert resp.status_code == 413

    def test_upload_missing_socio_404(self, test_client):
        resp = test_client.post(
            "/api/socios/nope/foto",
            files={"foto": ("foto.jpg", _make_jpeg(), "image/jpeg")},
        )
        assert resp.status_code == 404

    def test_get_without_foto_404(self, test_client):
        self._create_socio(test_client)
        resp = test_client.get("/api/socios/sFoto/foto")
        assert resp.status_code == 404

    def test_get_missing_socio_404(self, test_client):
        resp = test_client.get("/api/socios/nope/foto")
        assert resp.status_code == 404

    def test_upload_replaces_previous_foto(self, test_client, test_db):
        self._create_socio(test_client)
        first = _make_jpeg(color=(255, 0, 0))

        resp = test_client.post(
            "/api/socios/sFoto/foto",
            files={"foto": ("a.jpg", first, "image/jpeg")},
        )
        assert resp.status_code == 200

        second = _make_jpeg(size=(60, 60), color=(0, 0, 255))
        resp = test_client.post(
            "/api/socios/sFoto/foto",
            files={"foto": ("b.jpg", second, "image/jpeg")},
        )
        assert resp.status_code == 200

        socio = test_db.query(Socio).filter(Socio.id == "sFoto").one()
        with Image.open(BytesIO(socio.foto)) as img:
            assert img.size == (60, 60)
            r, g, b = img.getpixel((1, 1))
            assert abs(r - 0) <= 3 and abs(g - 0) <= 3 and abs(b - 255) <= 3

    def test_delete_clears_foto(self, test_client, test_db):
        self._create_socio(test_client)
        resp = test_client.post(
            "/api/socios/sFoto/foto",
            files={"foto": ("foto.jpg", _make_jpeg(), "image/jpeg")},
        )
        assert resp.status_code == 200

        resp = test_client.delete("/api/socios/sFoto/foto")
        assert resp.status_code == 204

        socio = test_db.query(Socio).filter(Socio.id == "sFoto").one()
        assert socio.foto is None

        body = test_client.get("/api/socios/sFoto").json()
        assert body["tieneFoto"] is False

        # GET now 404s, matching the "no photo" contract.
        get = test_client.get("/api/socios/sFoto/foto")
        assert get.status_code == 404

    def test_delete_missing_socio_404(self, test_client):
        resp = test_client.delete("/api/socios/nope/foto")
        assert resp.status_code == 404

    def test_delete_without_foto_is_ok(self, test_client):
        self._create_socio(test_client)
        resp = test_client.delete("/api/socios/sFoto/foto")
        assert resp.status_code == 204