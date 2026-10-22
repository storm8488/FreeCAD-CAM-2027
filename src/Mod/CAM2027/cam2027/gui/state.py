# SPDX-License-Identifier: LGPL-2.1-or-later
"""État partagé de l'interface : bibliothèque utilisateur et projet actif."""

import os

import FreeCAD

from ..tools.library import starter_library, default_library_path, load_or_recover
from ..project.project import Project
from ..project import docobjects

_library = None


def library():
    """Bibliothèque utilisateur (créée depuis la bibliothèque de démarrage au premier lancement)."""
    global _library
    if _library is None:
        path = default_library_path()
        if os.path.isfile(path):
            _library, warning = load_or_recover(path)
            if warning is not None:
                _warn_library(warning)
        else:
            _library = starter_library()
            _library.save(path)
    return _library


def _warn_library(warning):
    from ..i18n import tr_msg

    FreeCAD.Console.PrintWarning("CAM2027: %s\n" % tr_msg(warning))
    if FreeCAD.GuiUp:
        from .qt import QtWidgets
        import FreeCADGui

        QtWidgets.QMessageBox.warning(FreeCADGui.getMainWindow(), "CAM2027", tr_msg(warning))


def set_library(lib):
    global _library
    _library = lib


def active_project():
    """Projet du document actif, ou None si ce n'est pas un projet CAM2027."""
    doc = FreeCAD.ActiveDocument
    if doc is None or docobjects.find_info(doc) is None:
        return None
    try:
        return Project.from_document(doc)
    except ValueError:
        return None
