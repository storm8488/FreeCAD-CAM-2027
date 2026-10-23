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

        from cam2027.i18n import tr

        commands.register()
        self.appendToolbar("CAM2027", commands.TOOLBAR)
        self.appendToolbar("CAM2027 Drawing", commands.aspirecmds.DRAWING_MENU)  # S5 : dessin vectoriel
        # menus par étape du métier : Préparer / Usiner / Simuler / Exporter
        for title, names in commands.STAGE_MENUS:
            self.appendMenu(tr(title), names)
        from cam2027.gui import standalone

        if not standalone.is_standalone():
            self.appendMenu("CAM2027", commands.WORKBENCH_MENU)
        FreeCAD.Console.PrintLog("CAM2027 workbench initialised\n")

    def Activated(self):
        import FreeCAD
        from cam2027.gui import panels, prefs, standalone

        if standalone.is_standalone() and not getattr(self.__class__, "_stripped", False):
            standalone.load_gui_modules()
            removed = standalone.strip_workbenches()
            self.__class__._stripped = True
            standalone.apply_title()
            standalone.hide_workbench_selector()
            from cam2027.gui import welcome

            welcome.install()
            standalone.install_task_dock_tidier()
            standalone.enable_crash_log()
            FreeCAD.Console.PrintLog("CAM2027: standalone, %d workbenches removed\n" % len(removed))

        done = None
        try:
            done = prefs.apply_cam_only_profile()
        except Exception as exc:  # jamais bloquer l'atelier pour une préférence
            FreeCAD.Console.PrintWarning("CAM2027: CAM-only profile not applied: %s\n" % exc)
        else:
            if done:
                FreeCAD.Console.PrintLog("CAM2027: CAM-only profile applied (%d theme keys, %d workbenches hidden)\n"
                                         % (done["dark_pack"], len(done["hidden"])))
        try:
            # après le pack « FreeCAD Dark », qui contient ses propres couleurs de parcours
            prefs.apply_scene_colors(force=bool(done))
        except Exception as exc:
            FreeCAD.Console.PrintWarning("CAM2027: scene colours not applied: %s\n" % exc)
        panels.ensure_project_panel()
        self._fix_menu_titles()
        from PySide import QtCore
        from cam2027.gui import commands

        QtCore.QTimer.singleShot(0, commands.refresh_icons)  # barres construites juste après Activated
        try:
            from cam2027.gui import alpha

            alpha.install_status_badge()
        except Exception as exc:  # jamais bloquer l'atelier pour le repère alpha
            FreeCAD.Console.PrintWarning("CAM2027: alpha badge not installed: %s\n" % exc)
        if standalone.is_standalone():
            standalone.apply_advanced_mode()

    @staticmethod
    def _fix_menu_titles():
        from cam2027.gui import commands, standalone
        from cam2027.i18n import tr
        from PySide import QtCore

        titles = [tr(title) for title, _names in commands.STAGE_MENUS]
        # les menus de l'atelier sont construits juste après Activated
        QtCore.QTimer.singleShot(0, lambda: standalone.guard_menu_titles(titles))

    def Deactivated(self):
        pass

    def GetClassName(self):
        return "Gui::PythonWorkbench"


FreeCADGui.addWorkbench(CAM2027Workbench())


def _cam2027_standalone_menus():
    # logiciel autonome : menus / barres FreeCAD réduits au métier, avant la première construction
    from cam2027.gui import standalone

    if standalone.is_standalone():
        standalone.install_manipulator()


_cam2027_standalone_menus()
