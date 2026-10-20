# SPDX-License-Identifier: LGPL-2.1-or-later
"""Enregistrement de l'atelier CAM2027 dans l'interface FreeCAD.

FreeCAD exécute ce fichier avec des espaces de noms séparés : tout ce dont la
classe a besoin est défini dans ses méthodes (pas de variables de module).
"""

import FreeCADGui


class CAM2027Workbench(FreeCADGui.Workbench):
    MenuText = "CAM2027"
    ToolTip = "CAM2027 - wood / plastics / aluminium CAM, XYZ and XYZ+A"

    def __init__(self):
        import os
        import sys

        icon = ""
        for p in sys.path:
            cand = os.path.join(p, "Resources", "icons", "CAM2027.svg")
            if os.path.isfile(cand):
                icon = cand
                break
        self.__class__.Icon = icon

    def Initialize(self):
        import FreeCAD
        from cam2027.gui import commands

        commands.register()
        self.appendToolbar("CAM2027", commands.TOOLBAR)
        self.appendMenu("CAM2027", commands.MENU)
        FreeCAD.Console.PrintLog("CAM2027 workbench initialised\n")

    def Activated(self):
        from cam2027.gui import panels

        panels.ensure_project_panel()

    def Deactivated(self):
        pass

    def GetClassName(self):
        return "Gui::PythonWorkbench"


FreeCADGui.addWorkbench(CAM2027Workbench())
