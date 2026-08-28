"""Unit tests for renovacion service."""

from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

from backend.models.enums import Area, EstadoMembresia, Predio
from backend.models.membresia import Membresia
from backend.models.socio import Socio
from backend.services.renovacion import renovar_membresias


def _ensure_socios(db, socio_ids: list[str]):
    """Create minimal socios to satisfy FK constraints."""
    for i, sid in enumerate(socio_ids):
        socio = Socio(
            id=sid,
            nombre=f"Test Socio {sid}",
            dni=f"3000000{i}",
            telefono="",
            email="",
            direccion="",
            fechaAlta=date(2025, 1, 1),
            activo=True,
        )
        db.add(socio)
    db.flush()


def _make_membresia(db, mid: str, socio_id: str, estado: str, vencimiento: date) -> Membresia:
    """Helper: insert a membresia directly."""
    m = Membresia(
        id=mid,
        socioId=socio_id,
        area=Area.BALSEROS,
        predio=Predio.EMBALSE,
        estado=estado,
        vencimiento=vencimiento,
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


class TestRenovacion:
    """Tests for membership renewal logic."""

    def test_renew_expired_membership(self, test_db):
        """Expired membership → renew from max(vencimiento, fecha_pago) + 12 months."""
        _ensure_socios(test_db, ["s1"])
        past = date.today() - timedelta(days=60)
        _make_membresia(test_db, "m1", "s1", EstadoMembresia.ACTIVA.value, past)

        pago_fecha = date.today() - timedelta(days=10)
        renovar_membresias(test_db, ["m1"], pago_fecha)

        test_db.expire_all()
        m = test_db.query(Membresia).filter(Membresia.id == "m1").first()
        # base = max(past, pago_fecha) = pago_fecha (10 days ago)
        expected = pago_fecha + relativedelta(months=12)
        assert m.vencimiento == expected
        assert m.estado == EstadoMembresia.ACTIVA

    def test_renew_active_membership(self, test_db):
        """Active membership → renew from vencimiento + 12 months."""
        _ensure_socios(test_db, ["s1"])
        future = date.today() + timedelta(days=180)
        _make_membresia(test_db, "m1", "s1", EstadoMembresia.ACTIVA.value, future)

        pago_fecha = date.today()
        renovar_membresias(test_db, ["m1"], pago_fecha)

        test_db.expire_all()
        m = test_db.query(Membresia).filter(Membresia.id == "m1").first()
        expected = future + relativedelta(months=12)
        assert m.vencimiento == expected
        assert m.estado == EstadoMembresia.ACTIVA

    def test_renew_suspended_membership(self, test_db):
        """Suspended membership → renewal sets estado = activa."""
        _ensure_socios(test_db, ["s1"])
        past = date.today() - timedelta(days=10)
        _make_membresia(test_db, "m1", "s1", EstadoMembresia.SUSPENDIDA.value, past)

        renovar_membresias(test_db, ["m1"], date.today())

        test_db.expire_all()
        m = test_db.query(Membresia).filter(Membresia.id == "m1").first()
        assert m.estado == EstadoMembresia.ACTIVA

    def test_renew_multiple_memberships(self, test_db):
        """Can renew several memberships in one call."""
        _ensure_socios(test_db, ["s1", "s2"])
        past1 = date.today() - timedelta(days=30)
        future2 = date.today() + timedelta(days=100)
        _make_membresia(test_db, "m1", "s1", EstadoMembresia.ACTIVA.value, past1)
        _make_membresia(test_db, "m2", "s2", EstadoMembresia.ACTIVA.value, future2)

        renovar_membresias(test_db, ["m1", "m2"], date.today())

        test_db.expire_all()
        m1 = test_db.query(Membresia).filter(Membresia.id == "m1").first()
        m2 = test_db.query(Membresia).filter(Membresia.id == "m2").first()
        # m1 expired → renew from today
        assert m1.vencimiento == date.today() + relativedelta(months=12)
        # m2 active → renew from vencimiento
        assert m2.vencimiento == future2 + relativedelta(months=12)

    def test_renew_nonexistent_membership_ignored(self, test_db):
        """Renewing a non-existent id does not crash."""
        # Should not raise
        renovar_membresias(test_db, ["nonexistent"], date.today())

    def test_base_is_max_of_vencimiento_and_pago(self, test_db):
        """When pago date > vencimiento, renewal base is pago date."""
        _ensure_socios(test_db, ["s1"])
        past = date.today() - timedelta(days=5)
        _make_membresia(test_db, "m1", "s1", EstadoMembresia.ACTIVA.value, past)

        pago_future = date.today() + timedelta(days=10)
        renovar_membresias(test_db, ["m1"], pago_future)

        test_db.expire_all()
        m = test_db.query(Membresia).filter(Membresia.id == "m1").first()
        expected = pago_future + relativedelta(months=12)
        assert m.vencimiento == expected
