# SPDX-License-Identifier: LGPL-2.1-or-later
"""Page d'accueil du logiciel CAM2027 : posée sur la zone centrale tant qu'aucun document n'est ouvert."""

import os
import runpy

import FreeCAD
import FreeCADGui

from ..i18n import tr
from . import theme
from .qt import QtCore, QtGui, QtWidgets

MOD_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BRANDING = os.path.join(MOD_DIR, "Resources", "branding")


def logo_path(effective_theme):
    """Logo horizontal adapté au fond (texte clair sur thème sombre, foncé sur thème clair) et à la langue (ligne
    « FAO · USINAGE CNC » ou « CAM · CNC MACHINING »)."""
    from .. import i18n

    suffix = "" if i18n.language() == "fr" else "-en"
    return os.path.join(BRANDING, "cam2027-logo-%s%s.png" % ("dark" if effective_theme == "dark" else "light", suffix))
DEMO = os.path.join(MOD_DIR, "tests", "gui_demo.py")
MAX_RECENT = 8


def recent_projects():
    """Projets récents de FreeCAD (préférence RecentFiles), seulement ceux qui existent encore."""
    p = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/RecentFiles")
    paths = []
    for i in range(p.GetInt("RecentFiles", 0) or 20):
        path = p.GetString("MRU%d" % i, "")
        if path and path.lower().endswith(".fcstd") and os.path.isfile(path) and path not in paths:
            paths.append(path)
    return paths[:MAX_RECENT]


class WelcomePage(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super(WelcomePage, self).__init__(parent)
        self.setObjectName("CAM2027_Welcome")
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        outer = QtWidgets.QVBoxLayout(self)
        outer.addStretch(1)
        box = QtWidgets.QWidget()
        box.setMinimumWidth(320)
        box.setMaximumWidth(560)
        lay = QtWidgets.QVBoxLayout(box)
        lay.setSpacing(12)
        self.logo = QtWidgets.QLabel()
        lay.addWidget(self.logo, 0, QtCore.Qt.AlignHCenter)
        sub = QtWidgets.QLabel(tr("CAM software: prepare, machine, simulate, export."))
        sub.setAlignment(QtCore.Qt.AlignHCenter)
        theme.set_role(sub, "muted")
        lay.addWidget(sub)
        row = QtWidgets.QVBoxLayout()  # en colonne : la zone centrale peut être étroite (1280 px)
        self.b_new = QtWidgets.QPushButton(tr("New project"))
        self.b_new.setIcon(theme.icon("new-project"))
        theme.set_role(self.b_new, "primary")
        self.b_new.clicked.connect(lambda: FreeCADGui.runCommand("CAM2027_NewProject"))
        self.b_open = QtWidgets.QPushButton(tr("Open a project..."))
        self.b_open.setIcon(theme.icon("open-project"))
        self.b_open.clicked.connect(lambda: FreeCADGui.runCommand("Std_Open"))
        self.b_demo = QtWidgets.QPushButton(tr("Guided demo"))
        self.b_demo.setIcon(theme.icon("play"))
        self.b_demo.setToolTip(tr("Builds a demo project step by step, with an explanation at each step"))
        self.b_demo.setEnabled(os.path.isfile(DEMO))
        self.b_demo.clicked.connect(self.run_demo)
        for b in (self.b_new, self.b_open, self.b_demo):
            row.addWidget(b)
        lay.addLayout(row)
        title = QtWidgets.QLabel(tr("Recent projects"))
        theme.set_role(title, "section")
        lay.addWidget(title)
        self.recent = QtWidgets.QListWidget()
        self.recent.setMinimumHeight(160)
        self.recent.itemActivated.connect(self._open_item)
        self.recent.itemClicked.connect(self._open_item)
        lay.addWidget(self.recent)
        self.empty = QtWidgets.QLabel(tr("No recent project."))
        theme.set_role(self.empty, "muted")
        lay.addWidget(self.empty)
        outer.addWidget(box, 0, QtCore.Qt.AlignHCenter)
        outer.addStretch(2)
        self.restyle()
        self.refresh()

    def restyle(self):
        effective = theme.apply(self)
        path = logo_path(effective)
        if os.path.isfile(path):
            self.logo.setPixmap(QtGui.QPixmap(path).scaledToWidth(400, QtCore.Qt.SmoothTransformation))
        else:
            self.logo.setText("CAM2027")
            theme.set_role(self.logo, "section")

    def refresh(self):
        self.recent.clear()
        for path in recent_projects():
            item = QtWidgets.QListWidgetItem("%s    %s" % (os.path.splitext(os.path.basename(path))[0],
                                                          os.path.dirname(path)))
            item.setData(QtCore.Qt.UserRole, path)
            item.setToolTip(path)
            self.recent.addItem(item)
        has = self.recent.count() > 0
        self.recent.setVisible(has)
        self.empty.setVisible(not has)

    def _open_item(self, item):
        path = item.data(QtCore.Qt.UserRole)
        if path and os.path.isfile(path):
            FreeCAD.openDocument(path)

    def run_demo(self):
        runpy.run_path(DEMO, run_name="cam2027_demo")


class _Follower(QtCore.QObject):
    """Garde la page à la taille de la zone centrale et la montre seulement sans document ouvert."""

    def __init__(self, area, page):
        super(_Follower, self).__init__(area)
        self.area = area
        self.page = page
        area.installEventFilter(self)
        # différé : à la fermeture, la dernière fenêtre est encore listée pendant le signal
        area.subWindowActivated.connect(lambda _w: QtCore.QTimer.singleShot(0, self.update))

    def eventFilter(self, obj, event):
        if obj is self.area and event.type() == QtCore.QEvent.Resize:
            self.page.setGeometry(self.area.rect())
        return False

    def update(self):
        empty = not self.area.subWindowList()
        if empty and not self.page.isVisible():
            self.page.refresh()
        self.page.setGeometry(self.area.rect())
        self.page.setVisible(empty)
        if empty:
            self.page.raise_()


_page = None


def install():
    """Pose la page d'accueil sur la zone centrale (une fois) ; retourne la page."""
    global _page
    if _page is not None:
        return _page
    area = FreeCADGui.getMainWindow().findChild(QtWidgets.QMdiArea)
    if area is None:
        return None
    _page = WelcomePage(area)
    _page._follower = _Follower(area, _page)
    _page._follower.update()
    return _page


def restyle():
    if _page is not None:
        _page.restyle()
