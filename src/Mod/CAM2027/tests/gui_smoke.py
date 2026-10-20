# SPDX-License-Identifier: LGPL-2.1-or-later
"""Vérification visuelle de l'interface (à lancer avec FreeCAD.exe, pas FreeCADCmd) :

    FreeCAD.exe -M src/Mod/CAM2027 src/Mod/CAM2027/tests/gui_smoke.py

Active l'atelier, déroule la chaîne complète par l'API, ouvre les panneaux,
capture des PNG dans tests/screenshots/ puis quitte FreeCAD. Le code de sortie
n'est pas exploitable : lire tests/screenshots/gui_smoke.txt.
"""

import os
import sys
import tempfile
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
if MOD not in sys.path:
    sys.path.insert(0, MOD)
OUT = os.path.join(HERE, "screenshots")
os.makedirs(OUT, exist_ok=True)
LOG = os.path.join(OUT, "gui_smoke.txt")

import FreeCAD
import FreeCADGui

from PySide import QtCore, QtWidgets  # FreeCAD's PySide shim (PySide2 or PySide6)

lines = []


def log(msg):
    lines.append(str(msg))
    FreeCAD.Console.PrintMessage("[gui_smoke] %s\n" % msg)


def grab(widget, name):
    widget.repaint()
    QtWidgets.QApplication.processEvents()
    pix = widget.grab()
    path = os.path.join(OUT, name)
    pix.save(path)
    log("screenshot %s (%dx%d)" % (name, pix.width(), pix.height()))


def run():
    FreeCADGui.activateWorkbench("CAM2027Workbench")
    log("workbench activated")
    from cam2027.gui import state, panels, commands
    from cam2027.project.project import Project
    from tests.test_pipeline import make_part

    mw = FreeCADGui.getMainWindow()
    tmp = tempfile.mkdtemp(prefix="cam2027-gui-")
    step = os.path.join(tmp, "plate.step")
    make_part(step)
    lib = state.library()
    proj = Project.create("GUI smoke", lib)
    FreeCADGui.ActiveDocument = FreeCADGui.getDocument(proj.doc.Name)
    part = proj.import_model(step, label="Plate").objects[0]
    proj.create_job([part], stock={"kind": "box_margins", "xy": 2.0, "z_top": 1.0})
    endmill = lib.search("6 mm flat end mill")[0]
    asm = lib.assemblies_for_tool(endmill.id)[0]
    clone = proj.job.Model.Group[0]
    proj.add_operation("profile", "Outside contour", asm.id, endmill.presets[0].id, base=[(clone, [])],
                       params={"FinalDepth": 0.0, "StepDown": 5.0})
    results = proj.compute()
    log("operations: %s" % [(r["name"], r["commands"]) for r in results])
    FreeCADGui.SendMsgToActiveView("ViewFit")
    FreeCADGui.activeDocument().activeView().viewIsometric()
    QtWidgets.QApplication.processEvents()
    panels.ensure_project_panel()
    dock_lib = panels.show_tool_library()
    QtWidgets.QApplication.processEvents()
    lib_panel = dock_lib.widget()
    lib_panel.table.selectRow(0)
    QtWidgets.QApplication.processEvents()
    grab(lib_panel, "tool_library.png")
    lib_panel.tabs.setCurrentIndex(1)
    QtWidgets.QApplication.processEvents()
    grab(lib_panel, "tool_presets.png")
    lib_panel.tabs.setCurrentIndex(2)
    QtWidgets.QApplication.processEvents()
    grab(lib_panel, "tool_assembly.png")
    panels.refresh_project_panel()
    QtWidgets.QApplication.processEvents()
    project_panel = panels._docks["Project"].widget()
    log("workflow rows: %d operations listed, steps: %s" % (
        project_panel.tree.topLevelItemCount(),
        [project_panel.step_rows[k][1].text()[:40] for k in ("model", "stock", "ops", "export")]))
    project_panel.tree.setCurrentItem(project_panel.tree.topLevelItem(0))
    project_panel.duplicate_selected()
    log("after duplicate: %d operations" % len(proj.operations()))
    project_panel.move_selected(-1)
    log("after move up: %s" % [o.Label for o in proj.operations()])
    # état « à recalculer » : modification sans recalcul, puis capture
    proj.update_operation(proj.base_operation(proj.operations()[0]), {"StepDown": 4.0})
    panels.refresh_project_panel()
    QtWidgets.QApplication.processEvents()
    log("states: %s, recompute button: %s" % ([project_panel.tree.topLevelItem(i).text(1) for i in range(project_panel.tree.topLevelItemCount())],
                                             project_panel.recompute_button.text()))
    grab(project_panel, "project_panel_stale.png")
    proj.compute()
    panels.refresh_project_panel()
    QtWidgets.QApplication.processEvents()
    grab(project_panel, "project_panel.png")
    # éditeur d'opération (non modal) : onglets générés, lecture des valeurs, application
    from cam2027.gui import opeditor
    op = proj.operations()[0]
    editor = opeditor.open_editor(proj, op)
    QtWidgets.QApplication.processEvents()
    tabs = [editor.tabs.tabText(i) for i in range(editor.tabs.count())]
    avail = QtWidgets.QApplication.primaryScreen().availableGeometry().height()
    log("editor height %d / screen %d (fits: %s)" % (editor.height(), avail, editor.height() <= avail))
    log("editor tabs: %s" % tabs)
    for i in range(editor.tabs.count()):
        editor.tabs.setCurrentIndex(i)
        QtWidgets.QApplication.processEvents()
        grab(editor, "op_editor_%d.png" % i)
    editor.tabs.setCurrentIndex(2)
    log("editor unsaved at open: %s, focus on name: %s" % (editor.has_unsaved_changes(), editor.focusWidget() is editor.name))
    kind, widget = editor.widgets["StepDown"]
    widget.setValue(2.5)
    log("editor unsaved after edit: %s" % editor.has_unsaved_changes())
    box, widgets = editor.dressup_boxes["tags"]
    box.setChecked(True)
    widgets["Count"][1].setValue(3)
    # changement de préréglage depuis l'onglet Outil (même outil : le contrôleur est mis à jour)
    editor.preset_combo.setCurrentIndex(1)
    log("editor apply: %s" % editor.apply())
    log("editor unsaved after apply: %s" % editor.has_unsaved_changes())
    from cam2027.tools import bridge as bridgemod
    log("TC feed after preset change: %.0f" % bridgemod.tool_controller_values(op.ToolController)["feed_mm_min"])
    log("editor status: %s" % editor.status.text())
    log("StepDown after apply: %s" % op.StepDown)
    dress = proj.dressups(op)
    log("dressups after apply: %s, positions %s" % ([d.Name for d in dress], [len(d.Positions) for d in dress if hasattr(d, "Positions")]))
    editor.tabs.setCurrentIndex(editor.tabs.count() - 1)
    QtWidgets.QApplication.processEvents()
    grab(editor, "op_editor_dressups.png")
    editor.accept()
    QtWidgets.QApplication.processEvents()
    # thème clair puis retour au thème système : panneaux et éditeur restylés
    from cam2027.gui import theme
    previous_theme = theme.preference()
    theme.set_preference("light")
    panels.restyle_all()
    QtWidgets.QApplication.processEvents()
    grab(panels._docks["Project"].widget(), "project_panel_light.png")
    light_editor = opeditor.open_editor(proj, proj.base_operation(proj.operations()[0]))
    QtWidgets.QApplication.processEvents()
    grab(light_editor, "op_editor_light.png")
    light_editor.reject()
    theme.set_preference(previous_theme)
    panels.restyle_all()
    log("theme preference restored: %s (effective %s)" % (theme.preference(), theme.resolve()))
    view_path = os.path.join(OUT, "view3d.png")
    FreeCADGui.activeDocument().activeView().saveImage(view_path, 1000, 700, "White")
    log("screenshot view3d.png")
    QtWidgets.QApplication.processEvents()
    grab(mw, "main_window.png")
    # taille minimale visée par la charte : 1280 x 800
    geometry = mw.saveGeometry()
    was_max = mw.isMaximized()
    mw.showNormal()
    mw.resize(1280, 800)
    QtWidgets.QApplication.processEvents()
    log("window at %dx%d" % (mw.width(), mw.height()))
    grab(mw, "main_window_1280x800.png")
    mw.restoreGeometry(geometry)
    if was_max:
        mw.showMaximized()
    QtWidgets.QApplication.processEvents()
    # export dialog rendering (non modal grab)
    text, analysis, issues = proj.preview_gcode()
    log("gcode lines=%d issues=%s" % (analysis["lines"], [l for l, _m in issues]))
    from cam2027.project import export as exportmod
    summary_html = commands._format_summary(exportmod.export_summary(proj, analysis, issues))
    log("summary html: %d chars, has machine validation row: %s" % (len(summary_html), "Validation machine" in summary_html))
    html_checks = commands._format_checks(analysis, issues)
    log("checks html: %d chars, colored=%s" % (len(html_checks), "color:" in html_checks))
    lib_panel.add_starter_tools()
    log("library status: %s" % lib_panel.status.text()[:80])
    tb = [t for t in mw.findChildren(QtWidgets.QToolBar) if t.windowTitle() == "CAM2027"]
    log("toolbar found: %s, actions: %d" % (bool(tb), len(tb[0].actions()) if tb else 0))
    for name, _cls in commands.COMMANDS:
        log("command %s registered: %s" % (name, name in FreeCADGui.listCommands()))
    # projet 2D : dessin SVG, panneau sous le dessin, découpe + poche 2D, capture de la vue
    from tests.test_import import SVG
    from cam2027.project import sheet as sheetmod
    svg = os.path.join(tmp, "drawing.svg")
    with open(svg, "w", encoding="utf-8") as fp:
        fp.write(SVG)
    proj2 = Project.create("GUI sheet", lib)
    FreeCADGui.ActiveDocument = FreeCADGui.getDocument(proj2.doc.Name)
    proj2.import_model(svg)
    vecs = sheetmod.vector_objects(proj2.doc)
    proj2.create_sheet_job(thickness=12.0)
    rect = [v for v in vecs if len(v.Shape.Edges) == 4][0]
    circle = [v for v in vecs if len(v.Shape.Edges) == 1][0]
    small = [t for t in lib.search("3 mm flat end mill") if t.tool_type == "endmill"][0]
    sasm = lib.assemblies_for_tool(small.id)[0]
    proj2.add_operation("profile", "Cut out", asm.id, endmill.presets[0].id,
                        base=[(proj2.drawing_clone(rect), ["Edge%d" % i for i in range(1, 5)])],
                        params={"Side": "Outside", "StartDepth": 0.0, "FinalDepth": -12.0, "StepDown": 4.0})
    proj2.add_operation("pocket2d", "Pocket circle", sasm.id, small.presets[0].id,
                        base=[(proj2.drawing_clone(circle, face=True), ["Face1"])],
                        params={"StartDepth": 0.0, "FinalDepth": -3.0, "StepDown": 1.5})
    r2 = proj2.compute()
    log("sheet project: %s" % [(r["name"], r["commands"], round(r["zmin"] or 0, 2)) for r in r2])
    gdoc2 = FreeCADGui.getDocument(proj2.doc.Name)
    view2 = gdoc2.activeView()
    QtWidgets.QApplication.processEvents()
    log("sheet view: %s, visible: %s" % (type(view2).__name__, [o.Name for o in proj2.doc.Objects
                                          if o.ViewObject is not None and o.ViewObject.Visibility][:12]))
    view2.viewIsometric()
    view2.fitAll()
    QtWidgets.QApplication.processEvents()
    view2.saveImage(os.path.join(OUT, "view3d_sheet.png"), 1000, 700, "White")
    log("screenshot view3d_sheet.png")
    # projet 3D : dôme sur plaque, finition 3D de surface, capture de la vue et de l'éditeur
    import Part
    dome_step = os.path.join(tmp, "dome.step")
    plate = Part.makeBox(60, 40, 5)
    dome = Part.makeSphere(25, FreeCAD.Vector(30, 20, -15)).common(Part.makeBox(60, 40, 30, FreeCAD.Vector(0, 0, 5)))
    plate.fuse(dome).removeSplitter().exportStep(dome_step)
    proj3 = Project.create("GUI 3D", lib)
    FreeCADGui.ActiveDocument = FreeCADGui.getDocument(proj3.doc.Name)
    dome_part = proj3.import_model(dome_step, label="Dome").objects[0]
    proj3.create_job([dome_part], stock={"kind": "box_margins", "xy": 2.0, "z_top": 1.0})
    ball = lib.search("6 mm ball end mill")[0]
    bop, _brec = proj3.add_operation("surface3d", "Dome finishing", lib.assemblies_for_tool(ball.id)[0].id,
                                     ball.presets[0].id, base=[(proj3.job.Model.Group[0], [])],
                                     params={"CutPattern": "ZigZag", "StepOver": 40, "SampleInterval": 0.5,
                                             "BoundBox": "BaseBoundBox", "FinalDepth": 5.0})
    r3 = proj3.compute()
    log("3D project: %s" % [(r["name"], r["commands"], round(r["zmin"] or 0, 2), round(r["zmax"] or 0, 2)) for r in r3])
    view3 = FreeCADGui.getDocument(proj3.doc.Name).activeView()
    view3.viewIsometric()
    view3.fitAll()
    QtWidgets.QApplication.processEvents()
    view3.saveImage(os.path.join(OUT, "view3d_dome.png"), 1000, 700, "White")
    log("screenshot view3d_dome.png")
    ed3 = opeditor.open_editor(proj3, bop)
    log("3D editor tabs: %s" % [ed3.tabs.tabText(i) for i in range(ed3.tabs.count())])
    ed3.tabs.setCurrentIndex(4 if ed3.tabs.count() > 4 else ed3.tabs.count() - 1)
    QtWidgets.QApplication.processEvents()
    grab(ed3, "op_editor_surface3d.png")
    ed3.reject()
    fcstd = os.path.join(tmp, "gui.FCStd")
    proj.save(fcstd)
    log("saved %s" % fcstd)
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
    QtCore.QTimer.singleShot(500, lambda: QtWidgets.QApplication.instance().quit())
