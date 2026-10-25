# SPDX-License-Identifier: LGPL-2.1-or-later
"""Coquille de l'interface : une organisation métier unique.

* en haut : identité discrète, nom du projet et état d'enregistrement, commandes globales (nouveau, ouvrir,
  enregistrer, annuler, rétablir, cadrer), quatre espaces PRÉPARER | DESSINER | USINER | VÉRIFIER ET EXPORTER,
  boutons des panneaux ;
* à gauche : le navigateur métier (``navigator.Navigator``, dock ``CAM2027_Project``) ;
* au centre : la pièce ou le dessin (vue FreeCAD, inchangée) ;
* à droite : un seul panneau contextuel (``inspector.Inspector``, dock ``CAM2027_Inspector``) ;
* en bas : sélection, calcul en cours, problèmes à consulter (barre d'état FreeCAD, avec ses unités).

Passer d'un espace à l'autre ne touche ni la sélection, ni la caméra, ni le document, ni la page ouverte dans
le panneau contextuel. À moins de ``NARROW_WIDTH`` px de large, un seul des deux panneaux latéraux est
développé à la fois ; l'autre se rouvre par son bouton de la barre. L'arbre FreeCAD (« Modèle ») reste
disponible en mode avancé. Dans un FreeCAD complet (mode atelier), rien des autres ateliers n'est masqué.
"""

import FreeCAD
import FreeCADGui

from .qt import QtCore, QtGui, QtWidgets
from ..i18n import tr
from . import theme

#: (clé, libellé anglais, icône)
SPACES = (("prepare", "Prepare", "space-prepare"), ("draw", "Draw", "space-draw"),
          ("machine", "Machining", "space-machine"), ("verify", "Check and export", "space-verify"))
#: en dessous, un seul panneau latéral développé (la vue centrale garde au moins la moitié de la largeur)
NARROW_WIDTH = 1600
NAVIGATOR_WIDTH = 320
INSPECTOR_WIDTH = 440
PARAM = "User parameter:BaseApp/Preferences/CAM2027"
#: barres FreeCAD rangées par la coquille dans le logiciel autonome (leurs commandes restent dans les menus)
STANDALONE_HIDDEN_TOOLBARS = ("File", "Edit", "View", "Structure", "Help", "Macro", "Clipboard", "CAM2027", "CAM2027 Drawing")


def one_panel_only(window_width, narrow_width=NARROW_WIDTH):
    """Règle de largeur (pure, testée) : vrai quand un seul panneau latéral peut être développé."""
    return window_width < narrow_width


def default_space(has_project, has_job, has_operations):
    """Espace proposé à l'ouverture d'un document : Préparer tant que le job n'existe pas, Usiner ensuite."""
    if not has_project or not has_job:
        return "prepare"
    return "machine" if has_operations else "machine"


class _SelectionObserver(object):
    def __init__(self, shell):
        self.shell = shell

    def addSelection(self, *_a):
        self.shell.refresh_selection()

    def removeSelection(self, *_a):
        self.shell.refresh_selection()

    def setSelection(self, *_a):
        self.shell.refresh_selection()

    def clearSelection(self, *_a):
        self.shell.refresh_selection()


class Shell(QtCore.QObject):
    def __init__(self, mw, standalone):
        super(Shell, self).__init__(mw)
        self.mw = mw
        self.standalone = standalone
        self.space = None
        self._spaces_by_doc = {}
        from .navigator import Navigator
        from .inspector import Inspector

        self.navigator = Navigator()
        self.inspector = Inspector()
        self.inspector.on_empty = self._inspector_empty
        self.inspector.on_page = self._inspector_page
        self._build_bar()
        self._build_docks()
        self._build_status()
        mw.installEventFilter(self)
        area = mw.findChild(QtWidgets.QMdiArea)
        if area is not None:
            # document ouvert / fermé, page de démarrage fermée : panneaux masqués tant qu'il n'y a pas de document
            area.subWindowActivated.connect(lambda _w: QtCore.QTimer.singleShot(0, self.refresh_visibility))
        self._observer = _SelectionObserver(self)
        FreeCADGui.Selection.addObserver(self._observer)
        self._shortcuts = []
        shortcut_cls = getattr(QtGui, "QShortcut", None) or QtWidgets.QShortcut
        for i, (key, _label, _icon) in enumerate(SPACES):
            sc = shortcut_cls(QtGui.QKeySequence("Ctrl+%d" % (i + 1)), mw)
            sc.activated.connect(lambda k=key: self.show_space(k, user=True))
            self._shortcuts.append(sc)
        self.show_space(FreeCAD.ParamGet(PARAM).GetString("Space", "prepare"))
        self.restyle()
        self.refresh()

    # -- barre supérieure ------------------------------------------------------------------------------------

    def _std_actions(self, names):
        out = []
        for name in names:
            if name == "|":
                out.append(None)
                continue
            try:
                cmd = FreeCADGui.Command.get(name)
                actions = cmd.getAction() if cmd is not None else []
            except Exception:
                actions = []
            if actions:
                out.append(actions[0])
        return out

    def _build_bar(self):
        bar = self.bar = QtWidgets.QToolBar("CAM2027", self.mw)
        bar.setObjectName("CAM2027_Shell")
        bar.setMovable(False)
        bar.setFloatable(False)
        bar.setIconSize(QtCore.QSize(20, 20))
        bar.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)
        bar.toggleViewAction().setVisible(False)
        self.mark = QtWidgets.QLabel()
        self.mark.setObjectName("shellMark")
        self.mark.setContentsMargins(6, 0, 4, 0)
        bar.addWidget(self.mark)
        self.project_label = QtWidgets.QLabel()
        self.project_label.setObjectName("shellProject")
        self.project_label.setContentsMargins(0, 0, 10, 0)
        bar.addWidget(self.project_label)
        for action in self._std_actions(("CAM2027_NewProject", "Std_Open", "Std_Save", "|", "Std_Undo", "Std_Redo", "|",
                                         "Std_ViewFitAll", "Std_ViewGroup")):
            if action is None:
                bar.addSeparator()
            else:
                bar.addAction(action)
        bar.addSeparator()
        left_spacer = QtWidgets.QWidget()
        left_spacer.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        bar.addWidget(left_spacer)
        self.space_buttons = {}
        for key, label, icon in SPACES:
            button = QtWidgets.QToolButton()
            button.setObjectName("spaceButton")
            button.setProperty("space", key)
            button.setText(tr(label).upper())
            button.setCheckable(True)
            button.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
            button.setToolTip(tr("{space} (Ctrl+{n})", space=tr(label), n=[s[0] for s in SPACES].index(key) + 1))
            button.clicked.connect(lambda _c=False, k=key: self.show_space(k, user=True))
            bar.addWidget(button)
            self.space_buttons[key] = button
        right_spacer = QtWidgets.QWidget()
        right_spacer.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        bar.addWidget(right_spacer)
        action_cls = getattr(QtGui, "QAction", None) or QtWidgets.QAction  # Qt6 : QtGui, Qt5 : QtWidgets
        self.nav_toggle = action_cls(tr("Navigator"), bar)
        self.nav_toggle.setCheckable(True)
        self.nav_toggle.setToolTip(tr("Show or hide the navigator (left panel)"))
        self.nav_toggle.setIcon(theme.icon("panel-left", theme.chrome()))
        self.nav_toggle.triggered.connect(lambda on: self._toggle_dock("navigator", on))
        bar.addAction(self.nav_toggle)
        self.inspector_toggle = action_cls(tr("Task panel"), bar)
        self.inspector_toggle.setCheckable(True)
        self.inspector_toggle.setToolTip(tr("Show or hide the task panel (right panel)"))
        self.inspector_toggle.setIcon(theme.icon("panel-right", theme.chrome()))
        self.inspector_toggle.triggered.connect(lambda on: self._toggle_dock("inspector", on))
        bar.addAction(self.inspector_toggle)
        for action in self._std_actions(("CAM2027_ToolLibrary", "CAM2027_AdvancedMode")):
            bar.addAction(action)
        self.mw.addToolBar(QtCore.Qt.TopToolBarArea, bar)
        self.mw.insertToolBarBreak(bar)  # la barre occupe sa propre ligne, au-dessus des autres
        bar.show()

    def _build_docks(self):
        mw = self.mw
        self.nav_dock = QtWidgets.QDockWidget(tr("Navigator"), mw)
        self.nav_dock.setObjectName("CAM2027_Project")
        self.nav_dock.setWidget(self.navigator)
        self.nav_dock.setAllowedAreas(QtCore.Qt.LeftDockWidgetArea | QtCore.Qt.RightDockWidgetArea)
        self.nav_dock.setFeatures(QtWidgets.QDockWidget.DockWidgetMovable | QtWidgets.QDockWidget.DockWidgetClosable)
        mw.addDockWidget(QtCore.Qt.LeftDockWidgetArea, self.nav_dock)
        self.insp_dock = QtWidgets.QDockWidget(tr("Task"), mw)
        self.insp_dock.setObjectName("CAM2027_Inspector")
        self.inspector.setMinimumWidth(360)
        self.insp_dock.setWidget(self.inspector)
        self.insp_dock.setAllowedAreas(QtCore.Qt.LeftDockWidgetArea | QtCore.Qt.RightDockWidgetArea)
        self.insp_dock.setFeatures(QtWidgets.QDockWidget.DockWidgetMovable | QtWidgets.QDockWidget.DockWidgetClosable)
        mw.addDockWidget(QtCore.Qt.RightDockWidgetArea, self.insp_dock)
        self.insp_dock.hide()
        for dock in (self.nav_dock, self.insp_dock):
            dock.visibilityChanged.connect(lambda _v: self._sync_toggles())
        try:
            mw.resizeDocks([self.nav_dock, self.insp_dock], [NAVIGATOR_WIDTH, INSPECTOR_WIDTH], QtCore.Qt.Horizontal)
        except Exception:
            pass
        from . import panels

        panels._docks["Project"] = self.nav_dock

    def _build_status(self):
        status = self.mw.statusBar()
        self.sel_label = QtWidgets.QLabel()
        self.sel_label.setObjectName("shellSelection")
        self.sel_label.setContentsMargins(6, 0, 6, 0)
        status.addWidget(self.sel_label)
        self.problems_button = QtWidgets.QToolButton()
        self.problems_button.setObjectName("shellProblems")
        self.problems_button.setAutoRaise(True)
        self.problems_button.setToolTip(tr("Problems to review: open Check and export"))
        self.problems_button.clicked.connect(lambda: self.show_space("verify", user=True))
        status.addWidget(self.problems_button)

    # -- espaces -----------------------------------------------------------------------------------------------

    def show_space(self, key, user=False):
        keys = [s[0] for s in SPACES]
        if key not in keys:
            key = "prepare"
        self.space = key
        for k, b in self.space_buttons.items():
            b.setChecked(k == key)
        self.navigator.set_space(key)
        if self.standalone:
            for tb in self.mw.findChildren(QtWidgets.QToolBar):
                if tb.objectName() == "CAM2027 Drawing":
                    tb.setVisible(False)  # outils de dessin dans le navigateur de l'espace Dessiner
        doc = FreeCAD.ActiveDocument
        if doc is not None:
            self._spaces_by_doc[doc.Name] = key
        if user:
            FreeCAD.ParamGet(PARAM).SetString("Space", key)
            if not self.nav_dock.isVisible() and FreeCAD.listDocuments():
                self._toggle_dock("navigator", True)
        return key

    def space_for_document(self, doc):
        """Espace mémorisé pour ce document, sinon proposé d'après son état."""
        if doc is None:
            return self.space or "prepare"
        if doc.Name in self._spaces_by_doc:
            return self._spaces_by_doc[doc.Name]
        from . import state

        proj = state.active_project()
        return default_space(proj is not None, proj is not None and proj.has_job,
                             bool(proj.operations()) if proj is not None and proj.has_job else False)

    # -- panneaux ----------------------------------------------------------------------------------------------

    def _toggle_dock(self, which, on):
        dock, other = (self.nav_dock, self.insp_dock) if which == "navigator" else (self.insp_dock, self.nav_dock)
        dock.setVisible(on)
        if on and one_panel_only(self.mw.width()) and other.isVisible():
            other.hide()
        self._sync_toggles()

    def _sync_toggles(self):
        self.nav_toggle.setChecked(self.nav_dock.isVisible())
        self.inspector_toggle.setChecked(self.insp_dock.isVisible())
        self.inspector_toggle.setEnabled(self.inspector.page is not None or self.insp_dock.isVisible())

    def _inspector_page(self, _page):
        """Une tâche s'ouvre : le panneau contextuel se montre (et, en fenêtre étroite, prend la place du navigateur)."""
        if not self.insp_dock.isVisible():
            self.insp_dock.show()
        try:
            self.mw.resizeDocks([self.insp_dock], [INSPECTOR_WIDTH], QtCore.Qt.Horizontal)
        except Exception:
            pass
        self.apply_width_rule()
        self._sync_toggles()

    def _inspector_empty(self):
        self.insp_dock.hide()
        if not self.nav_dock.isVisible() and FreeCAD.listDocuments():
            self.nav_dock.show()
        self._sync_toggles()

    def apply_width_rule(self):
        """À moins de NARROW_WIDTH px : un seul panneau développé (celui de la tâche en cours)."""
        if not one_panel_only(self.mw.width()):
            return
        if self.nav_dock.isVisible() and self.insp_dock.isVisible():
            self.nav_dock.hide()
            self._sync_toggles()

    def eventFilter(self, obj, event):
        if obj is self.mw:
            t = event.type()
            if t == QtCore.QEvent.Resize:
                QtCore.QTimer.singleShot(0, self.apply_width_rule)
            elif t in (QtCore.QEvent.WindowTitleChange, QtCore.QEvent.ModifiedChange):
                QtCore.QTimer.singleShot(0, self.refresh_project_label)
        return False

    # -- rafraîchissement ----------------------------------------------------------------------------------------

    def refresh_visibility(self):
        """Panneaux latéraux masqués tant qu'aucune fenêtre de document n'est ouverte (logiciel autonome)."""
        docs = bool(FreeCAD.listDocuments())
        area = self.mw.findChild(QtWidgets.QMdiArea)
        if area is not None and not area.subWindowList():
            docs = False  # fenêtres de document fermées (le document peut rester listé un instant)
        if self.standalone and not docs:
            # accueil seul : aucun panneau latéral tant qu'aucun document n'est ouvert
            self.nav_dock.hide()
            self.insp_dock.hide()
        elif docs and not self.nav_dock.isVisible() and not self.insp_dock.isVisible():
            self.nav_dock.show()
            if not getattr(self, "_nav_sized", False):
                self._nav_sized = True
                QtCore.QTimer.singleShot(0, lambda: self._resize_dock(self.nav_dock, NAVIGATOR_WIDTH))
        self._sync_toggles()

    def refresh(self):
        from . import state

        proj = state.active_project()
        for key, b in self.space_buttons.items():
            b.setEnabled(proj is not None or key == "prepare")
        self.refresh_visibility()
        self.navigator.refresh()
        self.refresh_project_label()
        self.refresh_selection()
        n = sum(1 for i in range(self.navigator.problems.count()) if self.navigator.problems.item(i).data(QtCore.Qt.UserRole))
        self.problems_button.setText(tr("{n} problem(s) to review", n=n) if n else tr("No problem to review"))
        self.problems_button.setVisible(proj is not None)
        self._sync_toggles()

    def _resize_dock(self, dock, width):
        try:
            self.mw.resizeDocks([dock], [width], QtCore.Qt.Horizontal)
        except Exception:
            pass

    def refresh_project_label(self):
        doc = FreeCAD.ActiveDocument
        if doc is None:
            self.project_label.setText("<span style='color:%s'>%s</span>" % (theme.color("muted"), tr("No project")))
            return
        modified = self.mw.isWindowModified()
        state_text = tr("not saved") if modified else tr("saved")
        self.project_label.setText("<b>%s</b> <span style='color:%s'>· %s</span>" % (
            doc.Label, theme.color("warning" if modified else "muted"), state_text))
        self.project_label.setToolTip(doc.FileName or tr("Not saved yet (File > Save)"))

    def refresh_selection(self):
        try:
            sel = FreeCADGui.Selection.getSelectionEx()
        except Exception:
            sel = []
        if not sel:
            self.sel_label.setText(tr("Selection: none"))
            return
        subs = [s for e in sel for s in e.SubElementNames]
        kinds = {"Face": tr("face(s)"), "Edge": tr("edge(s)"), "Vertex": tr("vertex/vertices")}
        counts = {}
        for s in subs:
            key = next((k for k in kinds if s.startswith(k)), None)
            if key:
                counts[key] = counts.get(key, 0) + 1
        objects = sorted({e.Object.Label for e in sel})
        parts = ["%d %s" % (n, kinds[k]) for k, n in counts.items()] or [tr("{n} object(s)", n=len(objects))]
        self.sel_label.setText(tr("Selection: {what} ({objects})", what=", ".join(parts), objects=", ".join(objects[:3])))

    def restyle(self):
        theme.apply(self.navigator)
        theme.apply(self.inspector)
        self.bar.setStyleSheet(theme.shell_stylesheet())
        chrome = theme.chrome()
        for key, label, icon in SPACES:
            try:
                self.space_buttons[key].setIcon(theme.icon(icon, chrome))
            except FileNotFoundError:
                pass
        for action, icon in ((self.nav_toggle, "panel-left"), (self.inspector_toggle, "panel-right")):
            try:
                action.setIcon(theme.icon(icon, chrome))
            except FileNotFoundError:
                pass
        try:
            self.mark.setPixmap(theme.icon("cmd-about", chrome).pixmap(18, 18))
        except FileNotFoundError:
            self.mark.setText("CAM2027")
        self.mark.setToolTip("CAM2027")
        self.refresh_project_label()


_shell = None


def install(standalone=None):
    """Pose la coquille sur la fenêtre principale (une fois) ; retourne-la."""
    global _shell
    if _shell is not None:
        return _shell
    from . import standalone as standalone_mod

    mw = FreeCADGui.getMainWindow()
    if mw is None:
        return None
    _shell = Shell(mw, standalone_mod.is_standalone() if standalone is None else standalone)
    return _shell


def shell():
    return _shell if _shell is not None else install()


def inspector():
    return shell().inspector


def navigator():
    return shell().navigator


def show_space(key):
    s = shell()
    if s is not None:
        s.show_space(key)


def refresh():
    if _shell is not None:
        _shell.refresh()


def document_activated(doc):
    """Document activé (ouverture, onglet) : espace mémorisé pour ce document ou espace proposé (le
    rafraîchissement suit, par ``panels.refresh_project_panel``)."""
    if _shell is None:
        return
    _shell.show_space(_shell.space_for_document(doc))
