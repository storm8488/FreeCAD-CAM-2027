# SPDX-License-Identifier: LGPL-2.1-or-later
"""Relevé visuel de l'interface refondue (à lancer avec freecad.exe, profil temporaire) :

    set FREECAD_USER_HOME=%TEMP%\\cam2027-observe
    freecad.exe -M src\\Mod\\CAM2027 src\\Mod\\CAM2027\\tests\\gui_observe.py

Le logiciel autonome est simulé (accueil, ateliers retirés, barres rangées). Parcours réel par les commandes
et les pages : nouveau projet, import, brut (page), ajout d'opération (page) puis éditeur, modification après
calcul (état périmé), visibilité / inclusion, vérification, export, dessin, profil machine, mode avancé,
disposition par défaut, fermeture (accueil seul). Captures dans ``tests/screenshots/after/`` suffixées par
la taille, le thème et l'échelle ; journal ``observe_<suffixe>.txt`` (finit par ``OK``, aucune ligne
``PROBLEM``). Variables : ``CAM2027_OBS_SIZE`` (1280x800 par défaut), ``CAM2027_OBS_THEME`` (dark / light),
``QT_SCALE_FACTOR`` (1.5, 2)."""

import os
import sys
import tempfile
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
if MOD not in sys.path:
    sys.path.insert(0, MOD)
SIZE = os.environ.get("CAM2027_OBS_SIZE", "1280x800")
THEME = os.environ.get("CAM2027_OBS_THEME", "")
SCALE = os.environ.get("QT_SCALE_FACTOR", "1")
TAG = "%s_%s_x%s" % (SIZE, THEME or "system", SCALE)
OUT = os.path.join(MOD, "tests", "screenshots", "after")
os.makedirs(OUT, exist_ok=True)
LOG = os.path.join(OUT, "observe_%s.txt" % TAG)
lines = []

import FreeCAD
import FreeCADGui
from PySide import QtCore, QtWidgets


def log(msg):
    lines.append(str(msg))
    FreeCAD.Console.PrintMessage("[observe] %s\n" % msg)


def pump(n=8):
    for _ in range(n):
        QtWidgets.QApplication.processEvents()


def grab(widget, name):
    pump(4)
    widget.repaint()
    pump(4)
    pix = widget.grab()
    pix.save(os.path.join(OUT, "%s_%s.png" % (name, TAG)))
    log("shot %s %dx%d" % (name, pix.width(), pix.height()))


def visible_check(mw, name):
    """Aucun bouton de la coquille hors écran, panneaux non superposés, pas de défilement horizontal."""
    from cam2027.gui import shell

    s = shell.shell()
    rect = mw.rect()
    problems = []
    for b in s.space_buttons.values():
        g = b.geometry()
        top = b.mapTo(mw, g.topLeft() - g.topLeft())
        if not rect.contains(top) or b.width() < 40:
            problems.append("space button %s off screen (%s, w=%d)" % (b.text(), top, b.width()))
    for dock in (s.nav_dock, s.insp_dock):
        if dock.isVisible():
            for area in dock.findChildren(QtWidgets.QScrollArea):
                if area.isVisible() and area.horizontalScrollBar().isVisible() and area.horizontalScrollBar().maximum() > 0:
                    problems.append("%s: horizontal scroll in %s" % (dock.objectName(), area.objectName() or area.widget().objectName()))
    mdi = mw.findChild(QtWidgets.QMdiArea)
    log("%s: central %dx%d (window %dx%d), navigator %s, inspector %s, problems %s" % (
        name, mdi.width(), mdi.height(), mw.width(), mw.height(), s.nav_dock.isVisible() and s.nav_dock.width(),
        s.insp_dock.isVisible() and s.insp_dock.width(), problems or "none"))
    if mdi.width() < mw.width() / 2:
        log("PROBLEM %s: central view narrower than half the window" % name)
    for p in problems:
        log("PROBLEM %s: %s" % (name, p))


def run():
    from cam2027.gui import standalone, theme
    standalone.is_standalone = lambda: True  # logiciel tel que livré (accueil, ateliers retirés, barres rangées)
    standalone.install_manipulator()
    if THEME:
        theme.set_preference(THEME)
    mw = FreeCADGui.getMainWindow()
    w, h = [int(v) for v in SIZE.split("x")]
    mw.showNormal()
    mw.resize(w, h)
    pump(10)
    FreeCADGui.activateWorkbench("CAM2027Workbench")
    pump(30)
    mw.findChild(QtWidgets.QMdiArea).closeAllSubWindows()  # page de démarrage FreeCAD (fermée par le profil du logiciel)
    pump(30)
    from cam2027.gui import state, panels, commands, welcome, shell, inspector
    sh = shell.shell()
    log("size %s actual %dx%d theme %s scale %s" % (SIZE, mw.width(), mw.height(), theme.resolve(), SCALE))
    log("menus: %s" % [a.text() for a in mw.menuBar().actions()])
    log("toolbars visible: %s" % [tb.objectName() for tb in mw.findChildren(QtWidgets.QToolBar) if tb.isVisible()])
    log("docks visible: %s" % [(d.objectName(), d.width(), d.height()) for d in mw.findChildren(QtWidgets.QDockWidget) if d.isVisible()])
    grab(mw, "01_welcome")
    visible_check(mw, "welcome")
    # projet par les commandes réelles
    QtWidgets.QInputDialog.getText = staticmethod(lambda *a, **k: ("Boitier", True))
    FreeCADGui.runCommand("CAM2027_NewProject")
    pump(20)
    proj = state.active_project()
    from tests.test_pipeline import make_part
    tmp = tempfile.mkdtemp(prefix="cam2027-obs-")
    step = os.path.join(tmp, "plate.step")
    make_part(step)
    QtWidgets.QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (step, ""))
    FreeCADGui.runCommand("CAM2027_ImportModel")
    pump(20)
    log("after import: space %s, docks %s" % (sh.space, [(d.objectName(), d.width()) for d in mw.findChildren(QtWidgets.QDockWidget) if d.isVisible()]))
    grab(mw, "02_prepare_imported")
    visible_check(mw, "prepare")
    FreeCADGui.runCommand("CAM2027_StockFixture")
    pump(20)
    page = sh.inspector.page
    log("stock page: %s" % (page.windowTitle() if page else None))
    grab(mw, "03_prepare_stock_page")
    visible_check(mw, "stock page")
    page.accept()
    pump(20)
    proj = state.active_project()
    log("job created: %s, space %s" % (proj.has_job, sh.space))
    grab(mw, "04_prepare_done")
    sh.show_space("machine", user=True)
    pump(10)
    FreeCADGui.runCommand("CAM2027_AddOperation")
    pump(20)
    page = sh.inspector.page
    log("add page: %s kind %s" % (page.windowTitle() if page else None, getattr(page, "kind", None)))
    grab(mw, "05_machine_add_operation")
    visible_check(mw, "add operation")
    page.select_strategy("offsetpocket")
    pump(5)
    grab(sh.inspector, "05b_add_operation_pocket")
    page.accept()
    pump(30)
    from cam2027.gui import opeditor
    ed = opeditor._open_editors[-1] if opeditor._open_editors else None
    log("editor open: %s, sections %s" % (ed is not None and ed.isVisible(), [ed.tabs.tabText(i) for i in range(ed.tabs.count())] if ed else None))
    grab(mw, "06_machine_editor")
    visible_check(mw, "editor")
    if ed is not None:
        grab(ed, "06b_editor_only")
        for i in range(ed.tabs.count()):
            ed.tabs.setCurrentIndex(i)
            pump(5)
        ed.tabs.setCurrentIndex(0)
        pump(5)
        log("editor summary: %s | strip: %s" % (ed.summary.text(), ed.key_strip.text().replace("<b>", "").replace("</b>", "")))
        ed.accept()
        pump(20)
    # modification après calcul : état périmé visible
    proj = state.active_project()
    ops = proj.operations()
    log("operations: %s" % [(o.Label, proj.operation_state(o)) for o in ops])
    proj.update_operation(proj.base_operation(ops[0]), {"StepDown": 1.5})
    panels.refresh_project_panel()
    pump(10)
    nav = sh.navigator
    log("after change: states %s, recompute %s" % ([nav.tree.topLevelItem(i).text(1) for i in range(nav.tree.topLevelItemCount())], nav.recompute_button.text()))
    grab(nav, "07_navigator_stale")
    FreeCADGui.runCommand("CAM2027_Compute")
    pump(20)
    # visibilité indépendante de l'export
    item = nav.tree.topLevelItem(0)
    nav.on_item_clicked(item, 4)
    pump(5)
    op0 = proj.doc.getObject(item.data(0, QtCore.Qt.UserRole))
    log("visibility toggled: %s, active %s" % (op0.ViewObject.Visibility, proj.base_operation(op0).Active))
    nav.on_item_clicked(item, 4)
    pump(5)
    # vérifier et exporter
    sh.show_space("verify", user=True)
    pump(10)
    grab(mw, "08_verify_space")
    visible_check(mw, "verify")
    FreeCADGui.runCommand("CAM2027_MaterialCheck")
    pump(30)
    page = sh.inspector.page
    log("verification page: %s status %s rows %d" % (page.windowTitle() if page else None, getattr(page, "status", None), len(getattr(page, "rows", []))))
    grab(mw, "09_verify_material_check")
    visible_check(mw, "verification")
    FreeCADGui.runCommand("CAM2027_Export")
    pump(30)
    page = sh.inspector.page
    log("export page: %s" % (page.windowTitle() if page else None))
    grab(mw, "10_verify_export")
    visible_check(mw, "export")
    page.reject()
    pump(10)
    sh.show_space("draw", user=True)
    pump(10)
    grab(mw, "11_draw_space")
    visible_check(mw, "draw")
    sh.show_space("prepare", user=True)
    FreeCADGui.runCommand("CAM2027_Machine")
    pump(20)
    grab(mw, "12_prepare_machine_page")
    visible_check(mw, "machine page")
    sh.inspector.page.reject()
    pump(10)
    # mode avancé : arbre FreeCAD visible, puis disposition par défaut
    standalone.apply_advanced_mode(True)
    pump(10)
    log("advanced: model dock %s" % [d.isVisible() for d in mw.findChildren(QtWidgets.QDockWidget) if d.objectName() == "Model"])
    grab(mw, "13_advanced_mode")
    standalone.reset_layout()
    pump(10)
    log("after reset: docks %s" % [(d.objectName(), d.width()) for d in mw.findChildren(QtWidgets.QDockWidget) if d.isVisible()])
    # ancien projet : enregistrer, fermer, rouvrir (liste des récents), modifier, annuler, réenregistrer
    fcstd = os.path.join(tmp, "boitier.FCStd")
    proj.save(fcstd)
    FreeCAD.closeDocument(proj.doc.Name)
    pump(30)
    FreeCAD.openDocument(fcstd)
    pump(40)
    from cam2027.project.project import Project
    proj = state.active_project()
    log("reopened: project %s, ops %s, space %s, navigator rows %d" % (
        proj is not None and proj.doc.Label, [(o.Label, proj.operation_state(o)) for o in proj.operations()] if proj else None,
        sh.space, nav.tree.topLevelItemCount()))
    doc = proj.doc
    doc.UndoMode = 1
    nav.tree.setCurrentItem(nav.tree.topLevelItem(0))
    nav.edit_selected()
    pump(20)
    ed = opeditor._open_editors[-1]
    ed.widgets["StepDown"][1].setValue(2.0)
    log("reopened editor: unsaved %s, revert enabled %s" % (ed.has_unsaved_changes(), ed.revert_button.isEnabled()))
    ed.revert()
    pump(20)
    ed = opeditor._open_editors[-1]
    log("after revert: StepDown %s, unsaved %s" % (ed.widgets["StepDown"][1].value(), ed.has_unsaved_changes()))
    ed.widgets["StepDown"][1].setValue(2.0)
    ok = ed.apply()
    log("apply on reopened project: %s, undo names %s" % (ok, list(doc.UndoNames)[:2]))
    ed.accept()
    pump(10)
    doc.undo()
    pump(20)
    log("after undo: StepDown %s, states %s" % (proj.base_operation(proj.operations()[0]).StepDown,
                                                [nav.tree.topLevelItem(i).text(1) for i in range(nav.tree.topLevelItemCount())]))
    proj.save(fcstd)
    # second document : le navigateur suit le document actif
    proj_b = Project.create("Second", state.library())
    FreeCADGui.ActiveDocument = FreeCADGui.getDocument(proj_b.doc.Name)
    pump(30)
    log("second document: navigator shows %s (space %s)" % (state.active_project().doc.Label, sh.space))
    FreeCAD.setActiveDocument(doc.Name)
    FreeCADGui.ActiveDocument = FreeCADGui.getDocument(doc.Name)
    pump(30)
    log("back to first: navigator shows %s, rows %d, space %s" % (state.active_project().doc.Label, nav.tree.topLevelItemCount(), sh.space))
    FreeCAD.closeDocument(proj_b.doc.Name)
    pump(20)
    # fermeture du document : accueil seul
    FreeCAD.closeDocument(doc.Name)
    import time
    end = time.time() + 1.0
    while time.time() < end:
        QtWidgets.QApplication.processEvents()
        time.sleep(0.02)
    log("closed: docks visible %s, welcome %s" % ([d.objectName() for d in mw.findChildren(QtWidgets.QDockWidget) if d.isVisible()],
                                                 welcome._page is not None and welcome._page.isVisible()))
    grab(mw, "14_welcome_again")
    log("OK")


try:
    run()
except Exception:
    log("FAILED\n" + traceback.format_exc())
finally:
    with open(LOG, "w", encoding="utf-8") as fp:
        fp.write("\n".join(lines) + "\n")
    for name in list(FreeCAD.listDocuments()):
        try:
            FreeCAD.closeDocument(name)
        except Exception:
            pass
    QtCore.QTimer.singleShot(800, lambda: QtWidgets.QApplication.instance().quit())
