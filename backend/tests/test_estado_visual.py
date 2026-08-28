"""Unit tests for estado_visual service."""

from datetime import date, timedelta

from backend.services.estado_visual import calcular_estado_visual


class TestEstadoVisual:
    """Tests for calcular_estado_visual — the display status function."""

    # --- Persisted states override date logic ---

    def test_baja_always_returns_baja(self):
        """baja is a persisted terminal state, ignores vencimiento."""
        future = date.today() + timedelta(days=365)
        assert calcular_estado_visual("baja", future) == "baja"

    def test_suspendida_always_returns_suspendida(self):
        """suspendida overrides date logic."""
        future = date.today() + timedelta(days=365)
        assert calcular_estado_visual("suspendida", future) == "suspendida"

    def test_baja_with_past_vencimiento(self):
        """baja state persists even if vencimiento is long past."""
        past = date.today() - timedelta(days=400)
        assert calcular_estado_visual("baja", past) == "baja"

    def test_suspendida_with_past_vencimiento(self):
        """suspendida persists even with past vencimiento."""
        past = date.today() - timedelta(days=400)
        assert calcular_estado_visual("suspendida", past) == "suspendida"

    # --- Date-based logic for activa estado ---

    def test_vencida_when_past(self):
        """vencimiento < today → vencida."""
        past = date.today() - timedelta(days=1)
        assert calcular_estado_visual("activa", past) == "vencida"

    def test_vencida_long_past(self):
        """vencimiento far in the past → still vencida."""
        past = date.today() - timedelta(days=365)
        assert calcular_estado_visual("activa", past) == "vencida"

    def test_por_vencer_tomorrow(self):
        """vencimiento tomorrow (1 day) → por_vencer."""
        tomorrow = date.today() + timedelta(days=1)
        assert calcular_estado_visual("activa", tomorrow) == "por_vencer"

    def test_por_vencer_in_30_days(self):
        """vencimiento exactly 30 days → por_vencer (inclusive boundary)."""
        in_30 = date.today() + timedelta(days=30)
        assert calcular_estado_visual("activa", in_30) == "por_vencer"

    def test_por_vencer_in_15_days(self):
        """vencimiento in 15 days → por_vencer."""
        in_15 = date.today() + timedelta(days=15)
        assert calcular_estado_visual("activa", in_15) == "por_vencer"

    def test_activa_31_days(self):
        """vencimiento in 31 days → activa (beyond the 30-day window)."""
        in_31 = date.today() + timedelta(days=31)
        assert calcular_estado_visual("activa", in_31) == "activa"

    def test_activa_far_future(self):
        """vencimiento far in the future → activa."""
        future = date.today() + timedelta(days=365)
        assert calcular_estado_visual("activa", future) == "activa"

    # --- Edge cases: today = vencimiento ---

    def test_today_equals_vencimiento_is_por_vencer(self):
        """vencimiento == today → por_vencer (today <= today + 30)."""
        today = date.today()
        assert calcular_estado_visual("activa", today) == "por_vencer"

    def test_yesterday_is_vencida(self):
        """vencimiento == yesterday → vencida."""
        yesterday = date.today() - timedelta(days=1)
        assert calcular_estado_visual("activa", yesterday) == "vencida"

    # --- vencida estado with future vencimiento edge ---

    def test_vencida_estado_with_future_vencimiento(self):
        """persisted 'vencida' estado is NOT treated as a persisted state
        by the service — it falls through to date logic. Future vencimiento
        → activa (this is a known design choice: vencida is always computed)."""
        future = date.today() + timedelta(days=365)
        # The service only recognizes "baja" and "suspendida" as persisted.
        # "vencida" goes through date logic.
        assert calcular_estado_visual("vencida", future) == "activa"

    def test_vencida_estado_with_past_vencimiento(self):
        """persisted 'vencida' estado + past vencimiento → vencida (via date)."""
        past = date.today() - timedelta(days=10)
        assert calcular_estado_visual("vencida", past) == "vencida"
