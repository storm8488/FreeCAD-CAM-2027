# SPDX-License-Identifier: LGPL-2.1-or-later
"""Détection de la version de FreeCAD et de l'API outils disponible.

Deux générations d'API CAM coexistent :
- ``legacy`` (FreeCAD 1.0.x) : ``Path.Tool.Bit.Factory`` et fichiers ``.fctb``.
- ``assets`` (FreeCAD 1.1.x et suivants) : ``Path.Tool.toolbit.ToolBit.from_dict``.

Le reste de l'atelier ne doit jamais tester la version directement : il passe
par ``tool_api()`` et par les fonctions de ``cam2027.tools.bridge``.
"""

import importlib.util

import FreeCAD

from .version import FREECAD_MIN_VERSION


def freecad_version():
    """Retourne (majeur, mineur, correctif) de FreeCAD en entiers."""
    raw = FreeCAD.Version()
    parts = []
    for item in raw[:3]:
        digits = ""
        for ch in str(item):
            if ch.isdigit():
                digits += ch
            else:
                break
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def freecad_version_string():
    v = freecad_version()
    return ".".join(str(p) for p in v)


def check_minimum_version():
    v = freecad_version()
    if v < FREECAD_MIN_VERSION:
        raise RuntimeError("CAM2027 requires FreeCAD >= {required} (found: {found})".format(required=".".join(map(str, FREECAD_MIN_VERSION)), found=freecad_version_string()),
                           )
    return v


def tool_api():
    """``"assets"`` si le nouveau système d'outils est présent, sinon ``"legacy"``."""
    if importlib.util.find_spec("Path.Tool.toolbit") is not None:
        return "assets"
    return "legacy"


def has_opencamlib():
    """OpenCamLib est nécessaire aux opérations 3D (Surface, Waterline)."""
    return (
        importlib.util.find_spec("ocl") is not None
        or importlib.util.find_spec("opencamlib") is not None
    )


def gui_up():
    return bool(getattr(FreeCAD, "GuiUp", False))


def environment_report():
    """Dictionnaire résumant l'environnement, affiché dans « À propos » et les journaux."""
    return {
        "freecad_version": freecad_version_string(),
        "freecad_build": " ".join(str(x) for x in FreeCAD.Version()[3:6]),
        "tool_api": tool_api(),
        "opencamlib": has_opencamlib(),
        "gui": gui_up(),
        "user_config_dir": FreeCAD.getUserConfigDir(),
        "user_app_data_dir": FreeCAD.getUserAppDataDir(),
    }
