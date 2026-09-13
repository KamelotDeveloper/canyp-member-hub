"""Tests for phone normalization (convención +54 anclado, formato pelado)."""

import pytest

from backend.services.telefonos import normalizar_telefono


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Ya pelado: no se toca.
        ("3571591614", "3571591614"),
        ("3515719614", "3515719614"),
        # Separadores y espacios.
        ("0351-5719-614", "3515719614"),
        ("351 571 9614", "3515719614"),
        # Prefijo troncal 0.
        ("03515719614", "3515719614"),
        # Código de país completo.
        ("+54 351 5719614", "3515719614"),
        ("+54 9 351 571-9614", "3515719614"),
        ("5493515719614", "3515719614"),
        # Formato clásico con 15 embebido (12+ dígitos).
        ("0351-15-5719614", "3515719614"),
        ("351-15-5719614", "3515719614"),
        # Buenos Aires 11 con 15 embebido.
        ("011-15-5555-1234", "1155551234"),
        # Vacio/None.
        ("", ""),
        (None, ""),
        ("   ", ""),
    ],
)
def test_normalizar_telefono(raw, expected):
    assert normalizar_telefono(raw) == expected


def test_no_rompe_numero_moderno_con_15_interno():
    # Números modernos de 10 dígitos NO se tocan aunque contengan "15".
    assert normalizar_telefono("3511511234") == "3511511234"


def test_celular_con_9_local_se_limpia():
    # "9 351..." (11+ dígitos) es el 9 de móvil local viejo: se limpia.
    assert normalizar_telefono("93515719614") == "3515719614"