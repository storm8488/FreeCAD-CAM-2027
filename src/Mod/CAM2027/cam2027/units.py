# SPDX-License-Identifier: LGPL-2.1-or-later
"""Conventions d'unités de CAM2027.

Toutes les valeurs stockées dans les modèles Python et les fichiers JSON sont
en unités internes fixes :

- longueurs : millimètres (``mm``)
- avances : millimètres par minute (``mm/min``)
- avance par dent / par tour : millimètres (``mm``)
- vitesse de broche : tours par minute (``rpm``)
- vitesse de coupe : mètres par minute (``m/min``)
- angles : degrés

Les chaînes de type ``"5.0000 mm"`` ou ``"1200 mm/min"`` produites par FreeCAD
sont acceptées en entrée via :func:`to_mm` et :func:`to_float`.
"""

import math
import re

_NUMBER = re.compile(r"^\s*([-+]?\d*[.,]?\d+(?:[eE][-+]?\d+)?)\s*([a-zA-Z/°\"']*)\s*$")

# Facteurs de conversion vers l'unité interne pour chaque grandeur.
_LENGTH_FACTORS = {
    "": 1.0,
    "mm": 1.0,
    "cm": 10.0,
    "m": 1000.0,
    "in": 25.4,
    '"': 25.4,
    "inch": 25.4,
    "thou": 0.0254,
    "mil": 0.0254,
}
_FEED_FACTORS = {
    "": 1.0,
    "mm/min": 1.0,
    "mm/s": 60.0,
    "m/min": 1000.0,
    "in/min": 25.4,
    "ipm": 25.4,
}
_SPEED_FACTORS = {"": 1.0, "rpm": 1.0, "1/min": 1.0}
_ANGLE_FACTORS = {"": 1.0, "deg": 1.0, "°": 1.0, "rad": 180.0 / math.pi}


def _parse(value, factors, what):
    if isinstance(value, bool):
        raise ValueError("%s : booléen inattendu" % what)
    if isinstance(value, (int, float)):
        return float(value)
    if hasattr(value, "Value") and hasattr(value, "Unit"):
        # FreeCAD.Units.Quantity : Value est déjà exprimé en unité interne FreeCAD (mm, deg)
        return float(value.Value)
    if value is None:
        raise ValueError("%s : valeur manquante" % what)
    m = _NUMBER.match(str(value))
    if not m:
        raise ValueError("%s : valeur illisible %r" % (what, value))
    number = float(m.group(1).replace(",", "."))
    unit = m.group(2)
    if unit not in factors:
        raise ValueError("%s : unité non prise en charge %r" % (what, unit))
    return number * factors[unit]


def to_mm(value):
    return _parse(value, _LENGTH_FACTORS, "longueur")


def to_mm_min(value):
    return _parse(value, _FEED_FACTORS, "avance")


def to_rpm(value):
    return _parse(value, _SPEED_FACTORS, "vitesse de broche")


def to_deg(value):
    return _parse(value, _ANGLE_FACTORS, "angle")


def to_float(value):
    """Nombre sans unité (dents, coefficients)."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    m = _NUMBER.match(str(value))
    if not m:
        raise ValueError("nombre illisible %r" % (value,))
    return float(m.group(1).replace(",", "."))


def fmt_mm(value, digits=3):
    return "%.*f mm" % (digits, value)


def fmt_feed(value):
    return "%.0f mm/min" % value


def fmt_rpm(value):
    return "%.0f rpm" % value


def fmt_deg(value):
    return "%.2f°" % value
