"""Unit tests for numeracion service."""

from datetime import date

from backend.models.socio import Socio
from backend.services.numeracion import siguiente_numero_comprobante


def _ensure_socio(db, socio_id: str = "s1"):
    """Create a minimal socio to satisfy FK constraints."""
    socio = Socio(
        id=socio_id,
        nombre="Test Socio",
        dni="30000000",
        telefono="",
        email="",
        direccion="",
        fechaAlta=date(2025, 1, 1),
        activo=True,
    )
    db.merge(socio)
    db.flush()


class TestNumeracion:
    """Tests for sequential payment receipt numbering."""

    def test_first_number_on_empty_db(self, test_db):
        """First payment gets 0001-00000001."""
        result = siguiente_numero_comprobante(test_db)
        assert result == "0001-00000001"

    def test_second_number(self, test_db):
        """After one payment, next is 0002-00000002."""
        from backend.models.pago import Pago

        _ensure_socio(test_db, "s1")
        pago = Pago(
            id="p1",
            numero="0001-00000001",
            socioId="s1",
            fecha=date(2025, 1, 15),
            medio="efectivo",
            total=5000.0,
        )
        test_db.add(pago)
        test_db.commit()

        result = siguiente_numero_comprobante(test_db)
        assert result == "0002-00000002"

    def test_sequential_after_multiple(self, test_db):
        """After three payments, next is 0004-00000004."""
        from backend.models.pago import Pago

        _ensure_socio(test_db, "s1")
        for i in range(1, 4):
            pago = Pago(
                id=f"p{i}",
                numero=f"{i:04d}-{i:08d}",
                socioId="s1",
                fecha=date(2025, 1, 15),
                medio="efectivo",
                total=5000.0,
            )
            test_db.add(pago)
        test_db.commit()

        result = siguiente_numero_comprobante(test_db)
        assert result == "0004-00000004"

    def test_format_is_dash_separated(self, test_db):
        """Output always has prefix-8digit format."""
        result = siguiente_numero_comprobante(test_db)
        parts = result.split("-")
        assert len(parts) == 2
        assert len(parts[0]) == 4
        assert len(parts[1]) == 8
