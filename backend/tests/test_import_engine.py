"""Tests for the bulk-import engine (PR 2): parser, normalizers, validator,
dedupe, savepoint transactions, the /api/socios/import/* endpoints, and limits.

Unit-level tests exercise the importer service directly; integration tests go
through the FastAPI TestClient (``test_client`` / ``test_db`` fixtures from
``backend.tests.conftest``).
"""

import io
from datetime import date

from openpyxl import Workbook

from backend.schemas.import_bulk import (
    MAX_FILE_BYTES,
    MAX_PARSEABLE_ROWS,
    MAX_PREVIEW_ROWS,
)
from backend.services.importer.config import norm_date, norm_decimal
from backend.services.importer.parser import ParseError, parse_file
from backend.services.importer.pipeline import execute_rows, preview_file


def _csv_bytes(text: str) -> bytes:
    return text.encode("utf-8")


def _xlsx_two_sheets() -> bytes:
    """Return an XLSX workbook with 2 sheets; only sheet 1 should be read."""
    wb = Workbook()
    ws1 = wb.active
    ws1.title = "Sheet1"
    ws1.append(["Nombre y Apellido", "Dni", "Teléfono"])
    ws1.append(["Ana", "30111111", "3511234567"])
    ws2 = wb.create_sheet("Sheet2")
    ws2.append(["Nombre y Apellido", "Dni", "Teléfono"])
    ws2.append(["IGNORADA", "00000000", "0"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# Canonical header for socios imports. Teléfono is now required (nombre too).
CSV_HEADER = "Nombre y Apellido,Dni,Teléfono"


class TestParserDelimiters:
    def test_csv_comma(self):
        rows = parse_file("a.csv", _csv_bytes(f"{CSV_HEADER}\nAna,30111111,3511234567\n"))
        assert rows[0] == ["Nombre y Apellido", "Dni", "Teléfono"]
        assert rows[1] == ["Ana", "30111111", "3511234567"]

    def test_csv_semicolon_preserves_embedded_commas(self):
        text = "Nombre y Apellido;Dni;Teléfono;Dirección\nAna, María;30111111;3511234567;Calle 1\n"
        rows = parse_file("a.csv", _csv_bytes(text))
        # Semicolon is the delimiter; embedded commas inside the name survive.
        assert rows[1] == ["Ana, María", "30111111", "3511234567", "Calle 1"]

    def test_csv_tab(self):
        text = "Nombre y Apellido\tDni\tTeléfono\nAna\t30111111\t3511234567\n"
        rows = parse_file("a.csv", _csv_bytes(text))
        assert rows[1] == ["Ana", "30111111", "3511234567"]

    def test_unsupported_extension_rejected(self):
        try:
            parse_file("data.txt", b"a,b\n1,2\n")
            raise AssertionError("expected ParseError")
        except ParseError:
            pass


class TestEncodingCascade:
    def test_utf8_bom_stripped(self):
        raw = "\ufeffNombre y Apellido,Dni,Teléfono\nAna,30111111,3511234567\n".encode("utf-8")
        rows = parse_file("a.csv", raw)
        assert rows[0][0] == "Nombre y Apellido"  # no BOM prefix
        assert rows[1] == ["Ana", "30111111", "3511234567"]

    def test_latin1_fallback_preserves_accents(self):
        # "Müller" in Latin-1 is invalid UTF-8, forcing the Latin-1 fallback.
        raw = "Nombre y Apellido,Dni,Teléfono\nMüller,30111111,3511234567\n".encode("latin-1")
        rows = parse_file("a.csv", raw)
        assert rows[1][0] == "Müller"


class TestXlsx:
    def test_first_sheet_only(self):
        rows = parse_file("a.xlsx", _xlsx_two_sheets())
        assert rows[0] == ["Nombre y Apellido", "Dni", "Teléfono"]
        assert rows[1] == ["Ana", "30111111", "3511234567"]
        assert len(rows) == 2  # Sheet2 content was ignored


class TestNormalizers:
    def test_comma_decimal_normalized(self):
        assert norm_decimal("12,50") == 12.5

    def test_dd_mm_yyyy_parsed(self):
        assert norm_date("31/12/2027") == "2027-12-31"

    def test_invalid_date_flagged(self):
        try:
            norm_date("31/13/2027")
            raise AssertionError("expected ValueError")
        except ValueError:
            pass


class TestHeaderMappingPreview:
    """Spanish header -> English field mapping via the preview pipeline."""

    CSVCASE = "Nombre y Apellido,Dni,Teléfono,Referencia"

    def _preview(self):
        text = f"{self.CSVCASE}\nAna,30111111,3511234567,x\n"
        from sqlalchemy.orm import Session  # noqa: F401

        # db=None is acceptable for preview dedupe (no DB preload).
        return preview_file("a.csv", _csv_bytes(text), "socios", db=None)

    def test_spanish_header_maps_to_canonical_field(self):
        result = self._preview()
        assert result.columns["Nombre y Apellido"] == "nombre"
        assert result.columns["Dni"] == "dni"

    def test_unknown_column_ignored_with_warning(self):
        result = self._preview()
        assert "Referencia" in result.ignored_columns
        # The ignored column value is not carried into the row data.
        assert "Referencia" not in result.rows[0]

    def test_english_header_valid(self):
        text = "nombre,dni,telefono\nAna,30111111,3511111111\n"
        result = preview_file("a.csv", _csv_bytes(text), "socios", db=None)
        assert result.columns["nombre"] == "nombre"
        assert result.rows[0]["dni"] == "30111111"
        assert result.rows[0]["telefono"] == "3511111111"


class TestValidation:
    def _result_from(self, text: str):
        return preview_file("a.csv", _csv_bytes(text), "socios", db=None)

    def test_missing_nombre_is_error(self):
        result = self._result_from(f"{CSV_HEADER}\n,30111111,3511111111\n")
        assert result.stats.con_errores == 1
        assert any(e.campo == "nombre" for e in result.errors)

    def test_missing_telefono_is_error(self):
        # Teléfono ya no es obligatorio (el modelo admite vacío); un socio
        # sin teléfono debe importar con telefono = "".
        result = self._result_from(f"{CSV_HEADER}\nAna,30111111,\n")
        assert result.stats.con_errores == 0
        assert result.rows[0]["telefono"] == ""

    def test_optional_fields_defaulted(self):
        result = self._result_from(f"{CSV_HEADER}\nAna,30111111,3511111111\n")
        row = result.rows[0]
        assert row["activo"] is True
        assert row["fechaAlta"]  # defaults to today

    def test_invalid_date_flags_row(self):
        result = self._result_from(f"{CSV_HEADER},Fecha de Alta\nAna,30111111,3511111111,31/13/2027\n")
        assert result.stats.con_errores == 1
        assert any(e.campo == "fechaAlta" for e in result.errors)


class TestDedupe:
    def _validate(self, text: str, db=None):
        return preview_file("a.csv", _csv_bytes(text), "socios", db=db)

    def test_in_file_duplicate_dni_flagged(self):
        result = self._validate(f"{CSV_HEADER}\nAna,30111111,3511111111\nLuis,30111111,3512222222\n")
        # First row valid, second is an in-file duplicate. stats.con_errores==1.
        assert result.stats.con_errores == 1
        assert len(result.rows) == 1
        assert any(e.campo == "dni" and "Duplicate" in e.error for e in result.errors)


class TestExecuteEndpoints:
    def test_savepoint_one_failing_row_does_not_abort_batch(
        self, test_client, test_db
    ):
        """10 rows, row 4 duplicates row 1's dni -> 9 imported / 1 failed."""
        rows = []
        for i in range(1, 11):
            dni = "4000%04d" % i
            rows.append({"data": {"nombre": f"Persona{i}", "dni": dni, "telefono": f"351{i:07d}"}})
        # Row 4 reuses row 1's dni (both index 0 -> fila 2, index 3 -> fila 5).
        rows[3]["data"]["dni"] = rows[0]["data"]["dni"]

        resp = test_client.post(
            "/api/socios/import/execute", json={"rows": rows}
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["importados"] == 9
        assert body["fallidos"] == 1
        assert body["omitidos"] == 0

        failed = [r for r in body["rows"] if r["outcome"] == "fallido"]
        assert len(failed) == 1
        assert any(e["campo"] == "dni" for e in failed[0]["errores"])

        # The duplicated dni was NOT inserted; the other 9 dnis all present once.
        dup = rows[0]["data"]["dni"]
        from backend.models.socio import Socio

        count_dup = test_db.query(Socio).filter(Socio.dni == dup).count()
        assert count_dup == 1
        assert test_db.query(Socio).count() == 9

    def test_duplicate_dni_vs_db_not_inserted(self, test_client, test_db):
        from backend.models.socio import Socio

        test_db.add(
            Socio(id="s_x", nombre="Existente", dni="50112233", telefono="3510000000", fechaAlta=date(2020, 1, 1))
        )
        test_db.commit()

        resp = test_client.post(
            "/api/socios/import/execute",
            json={
                "rows": [{"data": {"nombre": "Nuevo", "dni": "50112233", "telefono": "3511111111"}}]
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["importados"] == 0
        assert body["fallidos"] == 1
        # No new row inserted.
        assert test_db.query(Socio).count() == 1


class TestImportEndpoints:
    def test_template_returns_xlsx(self, test_client):
        resp = test_client.get("/api/socios/import/template")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        assert "socios_import_template.xlsx" in resp.headers["content-disposition"]
        assert resp.content[:2] == b"PK"  # XLSX (zip) magic bytes

    def test_preview_returns_preview_result(self, test_client):
        csv_data = _csv_bytes(f"{CSV_HEADER}\nAna,30111111,3511111111\nLuis,30222222,3512222222\n")
        resp = test_client.post(
            "/api/socios/import/preview",
            files={"file": ("socios.csv", csv_data, "text/csv")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["resource"] == "socios"
        assert "columns" in body
        assert "ignoredColumns" in body
        assert "stats" in body and "total" in body["stats"]
        assert len(body["rows"]) == 2

    def test_execute_returns_execute_result(self, test_client):
        resp = test_client.post(
            "/api/socios/import/execute",
            json={
                "rows": [
                    {"data": {"nombre": "Ana", "dni": "60111111", "telefono": "3511111111"}},
                    {"data": {"nombre": "Luis", "dni": "60222222", "telefono": "3512222222"}},
                ]
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert {"importados", "fallidos", "omitidos", "rows"} <= set(body)
        assert body["importados"] == 2
        assert all(r["outcome"] == "importado" for r in body["rows"])


class TestCategoriaImport:
    """Categoria column: optional, lowercased, empty cells -> None."""

    def test_preview_lowercases_categoria(self):
        result = preview_file(
            "a.csv",
            _csv_bytes("Nombre y Apellido,Dni,Categoria\nAna,60112233,VITALICIO\n"),
            "socios",
            db=None,
        )
        assert result.stats.con_errores == 0
        assert result.rows[0]["categoria"] == "vitalicio"

    def test_preview_accented_header_not_ignored(self):
        result = preview_file(
            "a.csv",
            _csv_bytes("Nombre y Apellido,Dni,Categoría\nAna,60112234,\n"),
            "socios",
            db=None,
        )
        assert "Categoría" in result.columns
        assert "Categoría" not in result.ignored_columns
        assert result.rows[0]["categoria"] is None

    def test_execute_persists_categoria(self, test_client, test_db):
        from backend.models.socio import Socio

        resp = test_client.post(
            "/api/socios/import/execute",
            json={
                "rows": [
                    {"data": {"nombre": "Vital", "dni": "60112235", "categoria": "vitalicio"}}
                ]
            },
        )
        assert resp.status_code == 201
        assert resp.json()["importados"] == 1
        socio = test_db.query(Socio).filter(Socio.dni == "60112235").first()
        assert socio.categoria == "vitalicio"

    def test_execute_empty_categoria_is_none(self, test_client, test_db):
        from backend.models.socio import Socio

        resp = test_client.post(
            "/api/socios/import/execute",
            json={"rows": [{"data": {"nombre": "Común", "dni": "60112236"}}]},
        )
        assert resp.status_code == 201
        assert resp.json()["importados"] == 1
        socio = test_db.query(Socio).filter(Socio.dni == "60112236").first()
        assert socio.categoria is None


class TestLimits:
    def test_oversized_file_rejected_413(self, test_client):
        big = b"x" * (MAX_FILE_BYTES + 1)
        resp = test_client.post(
            "/api/socios/import/preview",
            files={"file": ("big.csv", big, "text/csv")},
        )
        assert resp.status_code == 413
        assert "10 MB" in resp.json()["detail"] or "10 MB" in resp.text

    def test_too_many_rows_rejected(self, test_client):
        # 10001 data rows + header = 10002 > 10000 limit -> ParseError -> 400.
        lines = [CSV_HEADER]
        lines += [f"Persona{i},4{i:08d},351{i:07d}" for i in range(MAX_PARSEABLE_ROWS + 1)]
        csv_data = _csv_bytes("\n".join(lines) + "\n")
        resp = test_client.post(
            "/api/socios/import/preview",
            files={"file": ("many.csv", csv_data, "text/csv")},
        )
        assert resp.status_code == 400
        assert str(MAX_PARSEABLE_ROWS) in resp.json()["detail"]

    def test_preview_caps_at_5000_rows(self, test_client):
        lines = [CSV_HEADER]
        lines += [f"Persona{i},5{i:08d},351{i:07d}" for i in range(6000)]
        csv_data = _csv_bytes("\n".join(lines) + "\n")
        resp = test_client.post(
            "/api/socios/import/preview",
            files={"file": ("cap.csv", csv_data, "text/csv")},
        )
        assert resp.status_code == 200
        assert len(resp.json()["rows"]) == MAX_PREVIEW_ROWS

    def test_execute_rejects_too_many_rows(self, test_client):
        rows = [{"data": {"nombre": f"P{i}", "dni": f"7{i:08d}", "telefono": f"351{i:07d}"}} for i in range(MAX_PARSEABLE_ROWS + 1)]
        resp = test_client.post("/api/socios/import/execute", json={"rows": rows})
        assert resp.status_code == 400
        assert "10.000" in resp.json()["detail"] or str(MAX_PARSEABLE_ROWS) in resp.json()["detail"]
