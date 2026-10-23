# SPDX-License-Identifier: LGPL-2.1-or-later
"""Version alpha : repère permanent dans la barre d'état, avec les liens « Signaler un bug » et « Proposer une
idée » (formulaires GitHub, voir ``cam2027.feedback``), toujours visibles pendant les essais."""

import FreeCADGui

from .qt import QtCore, QtWidgets
from ..i18n import tr

BADGE_NAME = "CAM2027AlphaBadge"


def install_status_badge():
    """Ajoute le repère à la barre d'état (une fois) ; retourne le ``QLabel``."""
    from . import commands

    mw = FreeCADGui.getMainWindow()
    label = mw.findChild(QtWidgets.QLabel, BADGE_NAME)
    if label is not None:
        return label
    label = QtWidgets.QLabel()
    label.setObjectName(BADGE_NAME)
    label.setTextFormat(QtCore.Qt.RichText)
    label.setText('<span style="background-color:#C2410C; color:#FFFFFF;">&nbsp;<b>ALPHA</b>&nbsp;</span>&nbsp; '
                  '<a href="bug">%s</a> &middot; <a href="idea">%s</a>&nbsp;' % (tr("Report a bug"), tr("Suggest a feature")))
    label.setToolTip(tr("Alpha version: check every toolpath (simulation, material check, dry run above the part) before cutting."))
    label.linkActivated.connect(commands.open_feedback)
    mw.statusBar().addPermanentWidget(label)
    return label
