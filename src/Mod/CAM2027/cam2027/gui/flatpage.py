# SPDX-License-Identifier: LGPL-2.1-or-later
"""Fournisseur de vue des opérations CAM2027 calculées en Python (finition des plats, reprise des angles) :
ressources attendues par ``Path.Op.Gui.Base.ViewProvider`` et page du panneau de tâches de FreeCAD (double-clic
dans l'arbre), qui renvoie à l'éditeur d'opération de CAM2027."""

import Path.Op.Gui.Base as PathOpGui

from .qt import QtWidgets
from ..i18n import tr


class Page(PathOpGui.TaskPanelPage):
    def getForm(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        label = QtWidgets.QLabel(tr("This operation is set in the CAM2027 operation editor (double-click it in the Project panel)."))
        label.setWordWrap(True)
        lay.addWidget(label)
        return w


class _Command(object):
    def __init__(self, res):
        self.res = res


_COMMANDS = {}


def command(kind):
    if kind not in _COMMANDS:
        import importlib

        from ..project.operations import STRATEGIES

        meta = STRATEGIES[kind]
        mod = importlib.import_module(meta["module"])
        _COMMANDS[kind] = _Command(PathOpGui.CommandResources(kind, mod.Create, Page, "CAM_3DSurface",
                                                              meta["label"], None, meta["label"]))
    return _COMMANDS[kind]
