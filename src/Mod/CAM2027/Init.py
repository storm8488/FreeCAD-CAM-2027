# SPDX-License-Identifier: LGPL-2.1-or-later
"""Initialisation sans interface de l'atelier CAM2027 (FreeCADCmd et FreeCAD)."""

import FreeCAD

try:
    import cam2027.compat as _compat

    _compat.check_minimum_version()
    FreeCAD.Console.PrintLog(
        "CAM2027 %s loaded (FreeCAD %s, tool API %s)\n"
        % (__import__("cam2027").__version__, _compat.freecad_version_string(), _compat.tool_api())
    )
except Exception as exc:  # pragma: no cover - visible dans la console FreeCAD
    FreeCAD.Console.PrintError("CAM2027: initialisation failed: %s\n" % exc)
