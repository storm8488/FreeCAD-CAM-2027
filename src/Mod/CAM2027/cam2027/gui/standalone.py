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


def hide_workbench_selector():
    """Retire le sélecteur d'atelier (barre « Workbench » et Affichage > Sélecteur d'atelier) :
    dans le logiciel il n'y a qu'un atelier, la liste ne montrerait que CAM2027 et « <none> »."""
    import FreeCADGui
    from .qt import QtWidgets

    mw = FreeCADGui.getMainWindow()
    FreeCAD.ParamGet("User parameter:BaseApp/MainWindow/Toolbars").SetBool("Workbench", False)
    hidden = 0
    for tb in mw.findChildren(QtWidgets.QToolBar):
        if tb.objectName() == "Workbench":
            for action in list(tb.actions()):
                tb.removeAction(action)
            tb.toggleViewAction().setVisible(False)
            tb.hide()
            hidden += 1
    for top in mw.menuBar().actions():
        menu = top.menu()
        if menu is None:
            continue
        for action in list(menu.actions()):
            sub = action.menu()
            if sub is not None and any(a.text() == APP_NAME for a in sub.actions()):
                menu.removeAction(action)  # Affichage > Sélecteur d'atelier
                hidden += 1
    return hidden


# -- menus et barres d'outils du logiciel (WorkbenchManipulator de FreeCAD) -------------------------

#: commandes FreeCAD retirées des menus (modélisation, macros, outils de développement, liens FreeCAD)
REMOVED_MENU_ITEMS = (
    # Fichier : « Nouveau document » remplacé par « Nouveau projet », import / export génériques remplacés
    "Std_New", "Std_Revert", "Std_Import", "Std_Export", "Std_MergeProjects", "Std_ProjectInfo", "Std_Print",
    "Std_PrintPreview", "Std_PrintPdf",
    # Édition : outils de modélisation et de sélection avancée
    "Std_Cut", "Std_Copy", "Std_Paste", "Std_DuplicateSelection", "Std_BoxSelection", "Std_BoxElementSelection",
    "Std_SelectAll", "Std_Delete", "Std_SendToPythonConsole", "Std_Placement", "Std_TransformManip",
    "Std_Alignment", "Std_Edit", "Std_Properties", "Std_UserEditMode",
    # Affichage : outils de modélisation / démonstration
    "Std_ViewCreate", "Std_FreezeViews", "Std_SelBoundingBox", "Std_ViewDockUndockFullscreen",
    "Std_ToggleClipPlane", "Std_TextureMapping", "Std_ViewVR", "Std_ToggleNavigation", "Std_RandomColor",
    "Std_Workbench", "Std_LinkSelectActions", "Std_TreeViewActions", "&Stereo",
    # Aide : liens vers FreeCAD (le logiciel n'est pas une version officielle de FreeCAD)
    "Std_FreeCADUserHub", "Std_FreeCADForum", "Std_ReportBug", "Std_DevHandbook", "Std_PythonHelp",
    "Std_FreeCADWebsite", "Std_FreeCADDonation", "Std_OnlineHelp", "Std_About", "Std_WhatsThis",
    "Std_RestartInSafeMode",
    # menus entiers
    "&Tools", "&Macro", "&Windows",
)

#: barres d'outils FreeCAD retirées
REMOVED_TOOLBARS = ("Clipboard", "Macro", "Structure", "Help", "Workbench", "Individual Views")


class CamOnlyManipulator(object):
    """Menus / barres d'outils réduits au métier FAO (réappliqué par FreeCAD à chaque reconstruction)."""

    def modifyMenuBar(self):
        # ajouts d'abord : leurs repères (Std_WhatsThis…) sont retirés ensuite
        changes = [
            {"insert": "CAM2027_NewProject", "menuItem": "Std_Open"},
            {"insert": "CAM2027_ImportModel", "menuItem": "Std_RecentFiles", "after": ""},
            {"append": "CAM2027_Theme", "menuItem": "Std_DrawStyle"},
            {"append": "CAM2027_AdvancedMode", "menuItem": "Std_DrawStyle"},
            {"append": "CAM2027_ResetLayout", "menuItem": "Std_DrawStyle"},
            {"append": "CAM2027_About", "menuItem": "Std_WhatsThis"},
        ]
        changes += [{"remove": name} for name in REMOVED_MENU_ITEMS]
        return changes

    def modifyToolBars(self):
        changes = [{"remove": name} for name in REMOVED_TOOLBARS]
        changes += [
            {"remove": "Std_New"},  # « Nouveau projet » est déjà en tête de la barre CAM2027
            {"remove": "Std_TreeViewActions"},
            {"remove": "Std_Measure"},
        ]
        return changes


_manipulator = None


def install_manipulator():
    """Enregistre le manipulateur (une fois) ; FreeCAD l'applique à la construction des menus."""
    import FreeCADGui

    global _manipulator
    if _manipulator is None:
        _manipulator = CamOnlyManipulator()
        FreeCADGui.addWorkbenchManipulator(_manipulator)
    return _manipulator


def fix_menu_titles(titles):
    """Rétablit les accents des titres de menu (FreeCAD relit le titre UTF-8 en Latin-1 : « PrÃ©parer »)."""
    import FreeCADGui

    wanted = {t.encode("utf-8").decode("latin-1"): t for t in titles if t != t.encode("utf-8").decode("latin-1")}
    if not wanted:
        return 0
    fixed = 0
    for action in FreeCADGui.getMainWindow().menuBar().actions():
        if action.text() in wanted:
            action.setText(wanted[action.text()])
            fixed += 1
    return fixed


# -- mode avancé et disposition par défaut ---------------------------------------------------------

PARAM = "User parameter:BaseApp/Preferences/CAM2027"


def advanced_mode():
    """Mode avancé : éditeur de propriétés FreeCAD visible (préférence, faux par défaut)."""
    import FreeCAD

    return FreeCAD.ParamGet(PARAM).GetBool("AdvancedMode", False)


def _property_views():
    import FreeCADGui
    from .qt import QtWidgets

    return [w for w in FreeCADGui.getMainWindow().findChildren(QtWidgets.QWidget)
            if w.metaObject().className() == "Gui::PropertyView"]


def apply_advanced_mode(on=None):
    """Montre / cache l'éditeur de propriétés (l'arbre du modèle reste visible) ; retourne le nombre touché."""
    import FreeCAD

    if on is None:
        on = advanced_mode()
    else:
        FreeCAD.ParamGet(PARAM).SetBool("AdvancedMode", bool(on))
    views = _property_views()
    for view in views:
        view.setVisible(bool(on))
    return len(views)


#: panneaux FreeCAD masqués par la disposition par défaut
HIDDEN_DOCKS = ("Report view", "Python console", "Selection view")


def reset_layout():
    """Disposition par défaut : modèle à gauche, projet à droite, bibliothèque en bas, barres visibles."""
    import FreeCADGui
    from .qt import QtCore, QtWidgets

    mw = FreeCADGui.getMainWindow()
    areas = {"Model": QtCore.Qt.LeftDockWidgetArea, "CAM2027_Project": QtCore.Qt.RightDockWidgetArea,
             "CAM2027_ToolLibrary": QtCore.Qt.BottomDockWidgetArea}
    for dock in mw.findChildren(QtWidgets.QDockWidget):
        name = dock.objectName()
        if name in areas:
            dock.setFloating(False)
            mw.addDockWidget(areas[name], dock)
            dock.show()
        elif name in HIDDEN_DOCKS:
            dock.hide()
    for tb in mw.findChildren(QtWidgets.QToolBar):
        if tb.objectName() in ("File", "Edit", "View", "CAM2027"):
            tb.show()
    apply_advanced_mode(False)
