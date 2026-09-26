"""Tests for the generic bulk-import engine wired for "membresias".

Covers the per-row DNI-exists check (user decision "Exigir DNI existente"),
arancel resolution by nombre within area+predio, execute persistence via the
resource ``build`` hook, and the /api/membresias/import/* endpoints. Uses the
same conventions (``test_client`` / ``test_db`` fixtures, ``preview_file`` /
``execute_rows`` direct calls) as ``test_import_engine.py``.
"""

from datetime import date

from backend.models.arancel import Arancel
from backend.models.enums import Area, EstadoMembresia, Predio
from backend.models.membresia import Membresia
from backend.models.socio import Socio
from backend.services.importer.pipeline import preview_file

MEMBRESIAS_CSV = "DNI,Área,Predio,Vencimiento,Estado,Arancel,Detalle"


def _csv_bytes(text: str) -> bytes:
    return text.encode("utf-8")


def _add_socio(
    db,
    dni: str,
    socio_id: str | None = None,
    nombre: str = "Ana Pérez",
) -> Socio:
    socio = Socio(
        id=socio_id or f"s_{dni}",
        nombre=nombre,
        dni=dni,
        telefono="3510000000",
        fechaAlta=date(2020, 1, 1),
    )
    db.add(socio)
    return socio


def _add_arancel(
    db,
    nombre: str,
    area: Area,
    predio: Predio,
) -> Arancel:
    arancel = Arancel(
        id=f"a_{nombre}",
        nombre=nombre,
        area=area,
        predio=predio,
        monto=100.0,
        vigenteDesde=date(2024, 1, 1),
    )
    db.add(arancel)
    return arancel


class TestPreviewDniExists:
    def test_dni_not_in_padron_flags_row(self, test_db):
        text = (
            f"{MEMBRESIAS_CSV}\n"
            "99999999,Guardería,Almafuerte,31/12/2027,,\n"
        )
        result = preview_file(
            "m.csv", _csv_bytes(text), "membresias", db=test_db
        )
        assert result.stats.con_errores == 1
        assert result.stats.validas == 0
        assert len(result.rows) == 0
        assert any(e.campo == "dni" for e in result.errors)
        assert any("no existe" in e.error for e in result.errors)

    def test_existent_socio_rows_are_valid(self, test_db):
        socio = _add_socio(test_db, "30111111")
        test_db.commit()
        text = (
            f"{MEMBRESIAS_CSV}\n"
            "30111111,Guardería,Almafuerte,31/12/2027,,\n"
            "30111111,Windsurf,Almafuerte,31/12/2027,activa,\n"
            "30111111,Balseros,Embalse,31/12/2027,vencida,\n"
        )
        result = preview_file(
            "m.csv", _csv_bytes(text), "membresias", db=test_db
        )
        assert result.stats.con_errores == 0
        assert len(result.rows) == 3
        assert result.rows[0]["dni"] == "30111111"
        assert result.rows[0]["area"] == "Guardería"
        assert result.rows[1]["estado"] == "activa"
        assert result.rows[2]["predio"] == "Embalse"

    def test_missing_estado_defaults_to_activa(self, test_db):
        _add_socio(test_db, "30111111")
        test_db.commit()
        text = (
            f"{MEMBRESIAS_CSV}\n"
            "30111111,Guardería,Almafuerte,31/12/2027,,\n"
        )
        result = preview_file(
            "m.csv", _csv_bytes(text), "membresias", db=test_db
        )
        assert result.stats.con_errores == 0
        assert result.rows[0]["estado"] == "activa"

    def test_missing_vencimiento_is_error(self, test_db):
        _add_socio(test_db, "30111111")
        test_db.commit()
        text = (
            f"{MEMBRESIAS_CSV}\n"
            "30111111,Guardería,Almafuerte,,\n"
        )
        result = preview_file(
            "m.csv", _csv_bytes(text), "membresias", db=test_db
        )
        assert result.stats.con_errores == 1
        assert any(e.campo == "vencimiento" for e in result.errors)

    def test_invalid_area_value_flags_row(self, test_db):
        _add_socio(test_db, "30111111")
        test_db.commit()
        text = (
            f"{MEMBRESIAS_CSV}\n"
            "30111111,Canchas,Almafuerte,31/12/2027,,\n"
        )
        result = preview_file(
            "m.csv", _csv_bytes(text), "membresias", db=test_db
        )
        assert result.stats.con_errores == 1
        assert any(e.campo == "area" for e in result.errors)


class TestPreviewArancelResolution:
    def test_arancel_resolved_by_nombre_within_area_predio(self, test_db):
        _add_socio(test_db, "30111111")
        _add_arancel(test_db, "Mensualidad Guardería", Area.GUARDERIA, Predio.ALMAFUERTE)
        test_db.commit()
        text = (
            f"{MEMBRESIAS_CSV}\n"
            "30111111,Guardería,Almafuerte,31/12/2027,activa,Mensualidad Guardería,\n"
        )
        result = preview_file(
            "m.csv", _csv_bytes(text), "membresias", db=test_db
        )
        assert result.stats.con_errores == 0
        assert result.rows[0]["arancelId"] == "a_Mensualidad Guardería"

    def test_arancel_wrong_area_for_predio_flags_row(self, test_db):
        _add_socio(test_db, "30111111")
        _add_arancel(test_db, "Mensualidad Guardería", Area.GUARDERIA, Predio.ALMAFUERTE)
        test_db.commit()
        text = (
            f"{MEMBRESIAS_CSV}\n"
            "30111111,Windsurf,Almafuerte,31/12/2027,activa,Mensualidad Guardería,\n"
        )
        result = preview_file(
            "m.csv", _csv_bytes(text), "membresias", db=test_db
        )
        assert result.stats.con_errores == 1
        assert any(e.campo == "arancel" for e in result.errors)


class TestExecuteMembresias:
    def test_execute_creates_rows_and_batch_continues(self, test_client, test_db):
        socio = _add_socio(test_db, "30111111")
        _add_arancel(test_db, "Mensualidad Guardería", Area.GUARDERIA, Predio.ALMAFUERTE)
        test_db.commit()

        rows = [
            {
                "data": {
                    "dni": "30111111",
                    "area": "Guardería",
                    "predio": "Almafuerte",
                    "vencimiento": "2027-12-31",
                    "estado": "activa",
                    "arancel": "Mensualidad Guardería",
                    "arancelId": "a_Mensualidad Guardería",
                    "detalle": None,
                }
            },
            {
                "data": {
                    "dni": "30111111",
                    "area": "Balseros",
                    "predio": "Embalse",
                    "vencimiento": "2027-12-31",
                    "estado": "vencida",
                    "arancel": None,
                    "detalle": "Box 4",
                }
            },
            {
                "data": {
                    "dni": "99999999",
                    "area": "Windsurf",
                    "predio": "Almafuerte",
                    "vencimiento": "2027-12-31",
                    "estado": "activa",
                    "arancel": None,
                    "detalle": None,
                }
            },
        ]

        resp = test_client.post("/api/membresias/import/execute", json={"rows": rows})
        assert resp.status_code == 201
        body = resp.json()
        assert body["importados"] == 2
        assert body["fallidos"] == 1
        assert body["omitidos"] == 0

        failed = [r for r in body["rows"] if r["outcome"] == "fallido"]
        assert len(failed) == 1
        assert failed[0]["fila"] == 4  # index 2 -> +2 header row
        assert any("no existe" in e["error"] for e in failed[0]["errores"])

        # Only the two valid rows persisted; the unknown-DNI row was rolled back
        # at its savepoint and did not abort the batch.
        ms = test_db.query(Membresia).all()
        assert len(ms) == 2

        guarderia = (
            test_db.query(Membresia).filter(Membresia.area == Area.GUARDERIA).one()
        )
        assert guarderia.socioId == socio.id
        assert guarderia.predio == Predio.ALMAFUERTE
        assert guarderia.estado == EstadoMembresia.ACTIVA
        assert guarderia.vencimiento == date(2027, 12, 31)
        assert guarderia.arancelId == "a_Mensualidad Guardería"
        assert guarderia.detalle is None

        balsa = (
            test_db.query(Membresia).filter(Membresia.area == Area.BALSEROS).one()
        )
        assert balsa.socioId == socio.id
        assert balsa.predio == Predio.EMBALSE
        assert balsa.estado == EstadoMembresia.VENCIDA
        assert balsa.arancelId is None
        assert balsa.detalle == "Box 4"


class TestMembresiasImportEndpoints:
    def test_template_returns_xlsx(self, test_client):
        resp = test_client.get("/api/membresias/import/template")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        assert "membresias_import_template.xlsx" in resp.headers["content-disposition"]
        assert resp.content[:2] == b"PK"  # XLSX (zip) magic bytes

    def test_preview_endpoint_checks_socio_exists(self, test_client, test_db):
        _add_socio(test_db, "30111111")
        test_db.commit()
        csv_data = _csv_bytes(
            f"{MEMBRESIAS_CSV}\n"
            "30111111,Guardería,Almafuerte,31/12/2027,,\n"
            "88888888,Windsurf,Almafuerte,31/12/2027,,\n"
        )
        resp = test_client.post(
            "/api/membresias/import/preview",
            files={"file": ("membresias.csv", csv_data, "text/csv")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["resource"] == "membresias"
        assert body["stats"]["conErrores"] == 1
        assert len(body["rows"]) == 1
        assert any(e["campo"] == "dni" for e in body["errors"])

    def test_dynamic_route_still_resolves(self, test_client, test_db):
        """GET /api/membresias/{id} must keep working after the import routes."""
        socio = _add_socio(test_db, "30111111", socio_id="s_route")
        test_db.commit()
        test_db.add(
            Membresia(
                id="m_route",
                socioId=socio.id,
                area=Area.GUARDERIA,
                predio=Predio.ALMAFUERTE,
                estado=EstadoMembresia.ACTIVA,
                vencimiento=date(2027, 12, 31),
            )
        )
        test_db.commit()

        resp = test_client.get("/api/membresias/m_route")
        assert resp.status_code == 200
        assert resp.json()["id"] == "m_route"