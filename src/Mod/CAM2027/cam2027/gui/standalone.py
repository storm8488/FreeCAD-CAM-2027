# SPDX-License-Identifier: LGPL-2.1-or-later
"""Logiciel autonome CAM2027 (distribution fabriquée par ``scripts/build-distribution.ps1``).

Dans la distribution, ``bin/branding.xml`` nomme l'application « CAM2027 ». Les modules FreeCAD
gardés comme bibliothèques du moteur CAM (Part, Mesh, Draft, Sketcher…) déclarent encore leur
atelier au démarrage : ils sont retirés de l'interface ici, il ne reste que CAM2027. Rien de cela
n'a lieu quand l'atelier est chargé dans un FreeCAD ordinaire.
"""

import FreeCAD

APP_NAME = "CAM2027"
KEEP = ("CAM2027Workbench", "NoneWorkbench")


def is_standalone():
    try:
        return FreeCAD.ConfigGet("ExeName") == APP_NAME
    except Exception:
        return False


def strip_workbenches():
    """Retire du sélecteur tous les ateliers sauf CAM2027 ; retourne la liste retirée."""
    import FreeCADGui

    removed = []
    for name in sorted(FreeCADGui.listWorkbenches()):
        if name in KEEP:
            continue
        try:
            FreeCADGui.removeWorkbench(name)
            removed.append(name)
        except Exception as exc:  # un atelier impossible à retirer ne doit pas bloquer le démarrage
            FreeCAD.Console.PrintWarning("CAM2027: workbench %s not removed: %s\n" % (name, exc))
    return removed


def load_gui_modules():
    """Modules graphiques du moteur CAM normalement chargés par l'atelier CAM (désormais retiré)."""
    for name in ("PartGui", "PathGui", "MeshGui"):
        try:
            __import__(name)
        except ImportError as exc:
            FreeCAD.Console.PrintWarning("CAM2027: %s not loaded: %s\n" % (name, exc))


def window_title():
    from ..version import __version__

    return "%s %s" % (APP_NAME, __version__)


def _freecad_version():
    v = FreeCAD.Version()
    return "%s.%s.%s" % (v[0], v[1], v[2])


def fix_title(title):
    """« Projet - CAM2027 1.1.4 » -> « Projet - CAM2027 0.1.3 » (version de FreeCAD remplacée)."""
    wrong = "%s %s" % (APP_NAME, _freecad_version())
    return title.replace(wrong, window_title()) if wrong in title else title


_title_filter = None


def apply_title():
    """Titre « CAM2027 <version> » maintenu : FreeCAD recompose le titre à chaque document avec sa version."""
    import FreeCADGui
    from .qt import QtCore

    global _title_filter
    mw = FreeCADGui.getMainWindow()

    class TitleFilter(QtCore.QObject):
        def eventFilter(self, obj, event):
            if event.type() == QtCore.QEvent.WindowTitleChange:
                fixed = fix_title(obj.windowTitle())
                if fixed != obj.windowTitle():
                    obj.setWindowTitle(fixed)
            return False

    if _title_filter is None:
        _title_filter = TitleFilter(mw)
        mw.installEventFilter(_title_filter)
    current = mw.windowTitle().replace("[*]", "").strip()
    if current in ("", APP_NAME) or current.startswith(APP_NAME + " "):
        mw.setWindowTitle("[*] " + window_title())
    else:
        mw.setWindowTitle(fix_title(mw.windowTitle()))
    return mw.windowTitle()
