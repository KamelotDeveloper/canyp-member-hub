"""Unit tests for the 10->10 renewal cycle (services/renovacion.py)."""

from datetime import date

import pytest

from backend.models.enums import Area, EstadoMembresia, Predio
from backend.models.membresia import Membresia
from backend.models.socio import Socio
from backend.services.renovacion import dia10, renovar_membresias


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


def _reload(db, mid: str) -> Membresia:
    """Drop the identity map so the assertion reads what was committed."""
    db.expire_all()
    return db.query(Membresia).filter(Membresia.id == mid).first()


class TestDia10:
    """The date anchor: first day-10 ON OR AFTER the payment date (CBM-01)."""

    @pytest.mark.parametrize(
        ("pago", "expected"),
        [
            # Antes del dia 10: cubre la ventana en curso.
            (date(2026, 9, 5), date(2026, 9, 10)),
            # Exactamente el dia 10: cubre la ventana que empieza ese dia (>=, no >).
            (date(2026, 9, 10), date(2026, 9, 10)),
            # Despues del dia 10: sigue dentro del periodo actual, no salta al siguiente.
            (date(2026, 9, 15), date(2026, 10, 10)),
            (date(2026, 9, 30), date(2026, 10, 10)),
            # Cruce de anio.
            (date(2026, 11, 20), date(2026, 12, 10)),
            (date(2026, 12, 5), date(2026, 12, 10)),
            (date(2026, 12, 31), date(2027, 1, 10)),
            # Meses de 31 dias: el anclaje no se desborda.
            (date(2026, 1, 31), date(2026, 2, 10)),
            (date(2026, 3, 20), date(2026, 4, 10)),
            # Mes de 30 dias y bisiesto.
            (date(2026, 4, 15), date(2026, 5, 10)),
            (date(2028, 2, 29), date(2028, 3, 10)),
        ],
    )
    def test_day10_anchors_on_the_tenth(self, pago, expected):
        assert dia10(pago) == expected

    @pytest.mark.parametrize(
        "pago",
        [date(2026, 1, 1), date(2026, 9, 10), date(2026, 9, 11), date(2026, 12, 31)],
    )
    def test_day10_always_lands_on_day_ten(self, pago):
        assert dia10(pago).day == 10


class TestRenovacion:
    """Renewal: vencimiento = max(vencimiento, dia10(fecha_pago)), estado = activa."""

    def test_renew_expired_membership(self, test_db):
        """Expired membership → renew to the next day-10, not to a yearly date."""
        _ensure_socios(test_db, ["s1"])
        _make_membresia(test_db, "m1", "s1", EstadoMembresia.ACTIVA.value, date(2026, 8, 10))

        # Paid on the 5th: the window 10/09 -> 10/10 is already in progress.
        renovar_membresias(test_db, ["m1"], date(2026, 9, 5))

        m = _reload(test_db, "m1")
        assert m.vencimiento == date(2026, 9, 10)
        assert m.vencimiento.day == 10
        assert m.estado == EstadoMembresia.ACTIVA

    def test_renew_active_membership_does_not_advance_in_window(self, test_db):
        """A membership already covering the window is left untouched."""
        _ensure_socios(test_db, ["s1"])
        _make_membresia(test_db, "m1", "s1", EstadoMembresia.ACTIVA.value, date(2026, 9, 10))

        # Paid on the 5th, but 10/09 is still ahead: no extra month is granted.
        renovar_membresias(test_db, ["m1"], date(2026, 9, 5))

        m = _reload(test_db, "m1")
        assert m.vencimiento == date(2026, 9, 10)

    def test_renew_on_the_tenth_covers_that_same_window(self, test_db):
        """Payment on the 10th renews to the 10th (>= semantics, not >)."""
        _ensure_socios(test_db, ["s1"])
        _make_membresia(test_db, "m1", "s1", EstadoMembresia.ACTIVA.value, date(2026, 8, 10))

        renovar_membresias(test_db, ["m1"], date(2026, 9, 10))

        m = _reload(test_db, "m1")
        assert m.vencimiento == date(2026, 9, 10)

    def test_renew_late_payment_covers_current_period(self, test_db):
        """Paid after the 10th: the CURRENT period is covered, no jump to the next."""
        _ensure_socios(test_db, ["s1"])
        _make_membresia(test_db, "m1", "s1", EstadoMembresia.ACTIVA.value, date(2026, 10, 10))

        # 15/09 pays the 10/09 -> 10/10 window: vencimiento stays 10/10.
        renovar_membresias(test_db, ["m1"], date(2026, 9, 15))

        m = _reload(test_db, "m1")
        assert m.vencimiento == date(2026, 10, 10)

    def test_renew_overdue_advances_to_next_day10(self, test_db):
        """Payment well past the expiry advances to the next day-10 after it."""
        _ensure_socios(test_db, ["s1"])
        _make_membresia(test_db, "m1", "s1", EstadoMembresia.ACTIVA.value, date(2026, 10, 10))

        # Spec "pago tardío": 20/11 → 10/12, with no recargo added here.
        renovar_membresias(test_db, ["m1"], date(2026, 11, 20))

        m = _reload(test_db, "m1")
        assert m.vencimiento == date(2026, 12, 10)

    def test_renew_31_day_month_does_not_overflow(self, test_db):
        """A late-January payment anchors on 10/02, not 09/02 or 03/02."""
        _ensure_socios(test_db, ["s1"])
        _make_membresia(test_db, "m1", "s1", EstadoMembresia.ACTIVA.value, date(2026, 1, 10))

        renovar_membresias(test_db, ["m1"], date(2026, 1, 31))

        m = _reload(test_db, "m1")
        assert m.vencimiento == date(2026, 2, 10)

    def test_renew_suspended_membership(self, test_db):
        """Suspended membership → renewal sets estado = activa, on a day-10 date."""
        _ensure_socios(test_db, ["s1"])
        _make_membresia(
            test_db, "m1", "s1", EstadoMembresia.SUSPENDIDA.value, date(2026, 8, 10)
        )

        renovar_membresias(test_db, ["m1"], date(2026, 9, 15))

        m = _reload(test_db, "m1")
        assert m.estado == EstadoMembresia.ACTIVA
        assert m.vencimiento == date(2026, 10, 10)

    def test_renew_multiple_memberships(self, test_db):
        """Mixed batch: the overdue one advances, the paid-ahead one does not."""
        _ensure_socios(test_db, ["s1", "s2"])
        # m1 overdue → must advance to 10/10.
        _make_membresia(test_db, "m1", "s1", EstadoMembresia.ACTIVA.value, date(2026, 8, 10))
        # m2 paid ahead (covers 10/10 -> 10/11) → must stay at 10/11.
        _make_membresia(test_db, "m2", "s2", EstadoMembresia.ACTIVA.value, date(2026, 11, 10))

        renovar_membresias(test_db, ["m1", "m2"], date(2026, 9, 15))

        assert _reload(test_db, "m1").vencimiento == date(2026, 10, 10)
        assert _reload(test_db, "m2").vencimiento == date(2026, 11, 10)

    def test_renew_nonexistent_membership_ignored(self, test_db):
        """Renewing a non-existent id does not crash."""
        # Should not raise
        renovar_membresias(test_db, ["nonexistent"], date(2026, 9, 5))

    def test_base_is_max_and_never_shrinks(self, test_db):
        """vencimiento = max(vencimiento, dia10(fecha)): paid-ahead is never shortened."""
        _ensure_socios(test_db, ["s1"])
        paid_ahead = date(2026, 12, 10)
        _make_membresia(test_db, "m1", "s1", EstadoMembresia.ACTIVA.value, paid_ahead)

        # The payment only covers 10/09; the membership stays covered until 10/12.
        renovar_membresias(test_db, ["m1"], date(2026, 9, 5))

        m = _reload(test_db, "m1")
        assert m.vencimiento == paid_ahead
        assert m.vencimiento > dia10(date(2026, 9, 5))

    def test_second_charge_in_same_window_is_a_no_op(self, test_db):
        """A repeat charge inside the same window does not advance coverage."""
        _ensure_socios(test_db, ["s1"])
        _make_membresia(test_db, "m1", "s1", EstadoMembresia.ACTIVA.value, date(2026, 10, 10))

        # 25/09 already set 10/10...
        renovar_membresias(test_db, ["m1"], date(2026, 9, 25))
        assert _reload(test_db, "m1").vencimiento == date(2026, 10, 10)

        # ...a second charge on 28/09 must stay at 10/10, never 11/10.
        renovar_membresias(test_db, ["m1"], date(2026, 9, 28))
        m = _reload(test_db, "m1")
        assert m.vencimiento == date(2026, 10, 10)
        assert m.vencimiento != date(2026, 11, 10)
