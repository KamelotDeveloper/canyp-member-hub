"""Telefonos helpers — CANYP.

Norma (convención con la comisión):
- La base guarda el teléfono nacional "pelado": sin +54, sin 15, sin el 0 de
  prefijo, sin espacios ni guiones. Ej: ``3515719614``.
- La app asume +54 fijo al construir enlaces de WhatsApp (``549`` + número).

``normalizar_telefono`` qué hace con distintas formas de carga:
- "3571591614"            -> "3571591614"
- "0351-5719614"          -> "3515719614"   (saca 0 + separadores)
- "351 15 5719614"        -> "3515719614"   (saca el 15 embebido)
- "+54 9 351 571-9614"    -> "3515719614"   (saca código país y el 9)
- "" / None               -> ""
"""

from __future__ import annotations

import re

_NON_DIGIT = re.compile(r"\D")
# "0" (prefijo troncal) + área de 2-3 dígitos + "15" + 6-8 dígitos — el formato
# clásico pre-numeración única (ej. 011-15-5555-1234, 0351-15-5719614). Solo se
# toca cuando el número trae MÁS de 10 dígitos y el resultado es un nacional de
# exactamente 10 (área+abonado), para no romper números modernos con "15".
_EMBEDDED_15 = re.compile(r"^(\d{2,3})15(\d{6,8})$")


def normalizar_telefono(value: str | None) -> str:
    """Normalize an Argentine phone to the national 'pelado' format (10/11 digits)."""
    digits = _NON_DIGIT.sub("", value or "")
    if not digits:
        return ""

    # Código de país +54...
    if digits.startswith("54"):
        digits = digits[2:]
    # ...seguido del 9 de móvil internacional (549...).
    if digits.startswith("9") and len(digits) >= 11:
        digits = digits[1:]
    # Prefijo troncal 0 (0351...).
    if digits.startswith("0"):
        digits = digits[1:]

    # Formato clásico "0xx-15-xxxxxxx": el 15 embebido se borra solo cuando el
    # total supera 10 dígitos y el resultado es un nacional de 10 (2-3 de área).
    if len(digits) > 10:
        m = _EMBEDDED_15.match(digits)
        if m and len(m.group(1) + m.group(2)) == 10:
            digits = m.group(1) + m.group(2)

    return digits