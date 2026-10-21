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
    log("application: %s, window title: %s" % (FreeCAD.ConfigGet("ExeName"), FreeCADGui.getMainWindow().windowTitle()))
    log("workbenches available: %s" % sorted(FreeCADGui.listWorkbenches()))
    log("user data dir: %s" % FreeCAD.getUserAppDataDir())
    from cam2027.gui import state, panels, commands, standalone, welcome
    QtWidgets.QApplication.processEvents()
    log("menus: %s" % [a.text() for a in FreeCADGui.getMainWindow().menuBar().actions()])
    if standalone.is_standalone():
        page = welcome.install()
        assert page is not None and page.isVisible(), "welcome page not shown without a document"
        views = standalone._property_views()
        assert views and not any(v.isVisible() for v in views), "property editor visible outside advanced mode"
        grab(FreeCADGui.getMainWindow(), "standalone_welcome.png")
        log("standalone: welcome page shown, property editor hidden")
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
    log("window title with a project open: %s" % mw.windowTitle())
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
    # projet 4e axe indexé : barreau sur l'axe A, poche du dessus à A0 et du flanc +Y à A90
    from cam2027.project.machine import MachineProfile, RotaryAxis
    bar_step = os.path.join(tmp, "bar.step")
    bar = Part.makeBox(80, 30, 30, FreeCAD.Vector(0, -15, -15))
    bar = bar.cut(Part.makeBox(30, 10, 5, FreeCAD.Vector(25, -5, 10))).cut(Part.makeBox(30, 5, 10, FreeCAD.Vector(25, 10, -5)))
    bar.exportStep(bar_step)
    m4 = MachineProfile("4 axes", controller="grbl", post_processor="grbl", post_processor_args="--no-show-editor --precision=3")
    m4.rotary = RotaryAxis(present=True, about="X", center_offset_mm=(0.0, 0.0), positive_direction="right_hand",
                           min_deg=-360.0, max_deg=360.0)
    proj4 = Project.create("GUI 4 axes", lib, m4)
    FreeCADGui.ActiveDocument = FreeCADGui.getDocument(proj4.doc.Name)
    bar_part = proj4.import_model(bar_step, label="Barreau").objects[0]
    proj4.create_job([bar_part], stock={"kind": "cylinder_x", "radius": 22.0, "length": 84.0, "x_start": -2.0,
                                        "center": (0.0, 0.0)})
    bclone = proj4.job.Model.Group[0]
    floors = {}
    for i, f in enumerate(bclone.Shape.Faces, 1):
        bb = f.BoundBox
        if f.Surface.__class__.__name__ == "Plane" and abs(f.Area - 300.0) < 1e-3:
            if abs(bb.ZMin - 10) < 1e-6 and abs(bb.ZMax - 10) < 1e-6:
                floors["top"] = "Face%d" % i
            if abs(bb.YMin - 10) < 1e-6 and abs(bb.YMax - 10) < 1e-6:
                floors["side"] = "Face%d" % i
    small = [t for t in lib.search("3 mm flat end mill") if t.tool_type == "endmill"][0]
    sasm4 = lib.assemblies_for_tool(small.id)[0]
    proj4.add_operation("pocket2d", "Poche dessus", sasm4.id, small.presets[0].id, base=[(bclone, [floors["top"]])],
                        params={"StepDown": 2.0, "StartDepth": 15.0, "FinalDepth": 10.0}, index_deg=0)
    side4, _r = proj4.add_operation("pocket2d", "Poche flanc", sasm4.id, small.presets[0].id,
                                    base=[(bclone, [floors["side"]])],
                                    params={"StepDown": 2.0, "StartDepth": 15.0, "FinalDepth": 10.0}, index_deg=90)
    r4 = proj4.compute()
    log("4th axis ops: %s" % [(r["name"], r["commands"]) for r in r4])
    panels.refresh_project_panel()
    QtWidgets.QApplication.processEvents()
    pp = panels._docks["Project"].widget()
    log("4th axis rows: %s" % [(pp.tree.topLevelItem(i).text(0), pp.tree.topLevelItem(i).text(2)) for i in range(pp.tree.topLevelItemCount())])
    grab(pp, "project_panel_4axes.png")
    ed4 = opeditor.open_editor(proj4, side4)
    log("4th axis editor index: %s" % ed4.index.text())
    grab(ed4, "op_editor_4axes.png")
    ed4.reject()
    text4, analysis4, issues4 = proj4.preview_gcode()
    log("4th axis gcode A moves: %s, issues: %s" % ([l for l in text4.splitlines() if l.startswith("G0") and " A" in l],
                                                   [lvl for lvl, _m in issues4]))
    view4 = FreeCADGui.getDocument(proj4.doc.Name).activeView()
    view4.viewIsometric()
    view4.fitAll()
    QtWidgets.QApplication.processEvents()
    view4.saveImage(os.path.join(OUT, "view3d_4axes.png"), 1000, 700, "White")
    # contrôle matière (Z-map) puis simulateur FreeCAD réglé et lancé
    import time
    from PySide import QtGui
    FreeCADGui.ActiveDocument = FreeCADGui.getDocument(proj.doc.Name)
    mrep = proj.material_check()
    commands.show_material_result(proj, mrep)
    log("material check: simulated %s, skipped %s, gouge %.3f, leftover max %.2f, removed %.0f mm3, rapids %d" % (
        mrep["simulated"], mrep["skipped"], mrep["gouge_max"], mrep["leftover_max"], mrep["removed_volume"],
        mrep["rapid_hits"]))
    log("material report: %s" % commands.material_report_text(mrep).splitlines()[1:3])
    mcol = mrep["collisions"]
    log("collisions: flute %s, holder %s, clamps %s (%s), rapids %s, events %d" % (
        mcol["flute_length"], mcol["holder"], mcol["clamps"], mcol["clamps_defined"], mcol["rapids"], len(mcol["events"])))
    assert mcol["clamps"] != "ok" or mcol["clamps_defined"], "clamps reported ok without any clamp"
    for o in proj.doc.Objects:
        if o.Name not in ("CAM2027SimStock", "CAM2027SimGouges") and o.ViewObject is not None and o.Name != "Job":
            o.ViewObject.Visibility = False
    viewm = FreeCADGui.getDocument(proj.doc.Name).activeView()
    viewm.viewIsometric()
    viewm.fitAll()
    QtWidgets.QApplication.processEvents()
    viewm.saveImage(os.path.join(OUT, "view3d_material_check.png"), 1000, 700, "White")
    before = set(int(w.winId()) for w in QtGui.QGuiApplication.topLevelWindows())
    ex4 = commands.start_simulator(proj4, play=False)  # opérations sur A décochées (le simulateur ignore A)
    log("simulator 4 axes: excluded %s" % ex4)
    assert ex4 == ["Poche flanc"], ex4
    FreeCADGui.Control.closeDialog()
    QtWidgets.QApplication.processEvents()
    excluded = commands.start_simulator(proj)
    end = time.time() + 3.0
    while time.time() < end:
        QtWidgets.QApplication.processEvents()
        time.sleep(0.05)
    new_windows = [w for w in QtGui.QGuiApplication.topLevelWindows()
                   if int(w.winId()) not in before and w.isVisible() and int(w.winId()) != int(mw.winId())]
    log("simulator: excluded %s, new windows %s, task panel %s" % (
        excluded, [(w.title(), w.width(), w.height()) for w in new_windows], FreeCADGui.Control.activeDialog()))
    for w in new_windows:
        pix = QtGui.QGuiApplication.primaryScreen().grabWindow(w.winId())
        pix.save(os.path.join(OUT, "simulator_window.png"))
        log("screenshot simulator_window.png (%dx%d)" % (pix.width(), pix.height()))
        break
    grab(mw, "simulator_main.png")
    for w in new_windows:
        w.close()
    FreeCADGui.Control.closeDialog()
    QtWidgets.QApplication.processEvents()
    # relief depuis une image : dialogue, création, finition 3D, vue
    import math
    from PySide import QtGui
    from cam2027.gui.reliefdlg import ReliefDialog
    img = QtGui.QImage(120, 80, QtGui.QImage.Format_RGB32)
    for row in range(80):
        for col in range(120):
            r = math.hypot(col - 60, row - 40)
            v = int(255 * (0.5 + 0.5 * math.cos(r / 4.0)) * max(0.0, 1 - r / 45.0))  # ondes concentriques
            img.setPixel(col, row, QtGui.qRgb(v, v, v))
    png = os.path.join(tmp, "waves.png")
    img.save(png)
    rdlg = ReliefDialog(mw, png)
    rdlg.width.setValue(90.0)
    rdlg.height.setValue(4.0)
    QtWidgets.QApplication.processEvents()
    log("relief dialog: length %s, options %s" % (rdlg.length.text(), sorted(rdlg.options())))
    grab(rdlg, "relief_dialog.png")
    ropts = rdlg.options()
    rdlg.reject()
    projr = Project.create("Relief", lib)
    FreeCADGui.ActiveDocument = FreeCADGui.getDocument(projr.doc.Name)
    rres = projr.import_relief(ropts.pop("path"), ropts.pop("width"), ropts.pop("relief_height"), **ropts)
    robj = rres.objects[0]
    log("relief: %s, valid %s, size %.1f x %.1f, warnings %s" % (
        robj.Label, robj.Shape.isValid(), robj.Shape.BoundBox.XLength, robj.Shape.BoundBox.YLength, rres.warnings))
    projr.create_job([robj], stock={"kind": "box_margins", "xy": 2.0, "z_top": 0.0, "z_bottom": 0.0})
    ball = lib.search("6 mm ball end mill")[0]
    projr.add_operation("surface3d", "Relief finishing", lib.assemblies_for_tool(ball.id)[0].id, ball.presets[0].id,
                        base=[(projr.job.Model.Group[0], [])],
                        params={"CutPattern": "ZigZag", "StepOver": 30, "SampleInterval": 0.5,
                                "BoundBox": "BaseBoundBox", "FinalDepth": 3.0})
    log("relief operations: %s" % [(r["name"], r["commands"], r["valid"]) for r in projr.compute()])
    viewr = FreeCADGui.getDocument(projr.doc.Name).activeView()
    viewr.viewIsometric()
    viewr.fitAll()
    QtWidgets.QApplication.processEvents()
    viewr.saveImage(os.path.join(OUT, "view3d_relief.png"), 1000, 700, "White")
    # flux 2D : imbrication, fond plat, incrustation (dialogues)
    from cam2027.gui import sheetdlgs
    from cam2027.project import sheet as sheetmod
    from tests.test_import import SVG
    svg2 = os.path.join(tmp, "drawing2d.svg")
    with open(svg2, "w", encoding="utf-8") as fp:
        fp.write(SVG)
    proj2d = Project.create("Inlay", lib)
    FreeCADGui.ActiveDocument = FreeCADGui.getDocument(proj2d.doc.Name)
    proj2d.import_model(svg2)
    ndlg = sheetdlgs.NestDialog(proj2d, mw)
    ndlg.table.cellWidget(0, 2).setValue(2)
    ndlg.width.setValue(300.0)
    ndlg.length.setValue(200.0)
    QtWidgets.QApplication.processEvents()
    grab(ndlg, "nest_dialog.png")
    nrep = ndlg.apply()
    ndlg.reject()
    log("nest: placed %d, unplaced %s, use %.0f %%" % (len(nrep["placed"]), nrep["unplaced"], 100 * nrep["utilization"]))
    proj2d.create_sheet_job(thickness=12.0)
    log("nest sheet: %s" % [round(v, 1) for v in (proj2d.stock_bounds()[k] for k in ("xmin", "xmax", "ymin", "ymax"))])
    rect2d = [v for v in sheetmod.vector_objects(proj2d.doc) if len(v.Shape.Edges) == 4][0]
    vbit2 = [t for t in lib.search("V-bit") if t.geometry.tip_included_angle_deg == 60.0][0]
    vop2, _r = proj2d.add_operation("vcarve", "Vcarve rect", lib.assemblies_for_tool(vbit2.id)[0].id, vbit2.presets[0].id,
                                    base=[(proj2d.drawing_clone(rect2d, face=True), ["Face1"])], params={"FinalDepth": -2.0})
    fdlg = sheetdlgs.FlatDepthDialog(proj2d, mw, selected_op=vop2)
    fasm_ok = fdlg.buttons.button(QtWidgets.QDialogButtonBox.Ok).isEnabled()
    grab(fdlg, "flat_depth_dialog.png")
    fops = fdlg.apply()
    fdlg.reject()
    idlg = sheetdlgs.InlayDialog(proj2d, mw, selected=[rect2d])
    idlg.female.setValue(4.0)
    idlg.start.setValue(2.0)
    idlg.male.setValue(4.0)
    QtWidgets.QApplication.processEvents()
    log("inlay dialog: %s, ok %s" % (idlg.gaps.text(), idlg.buttons.button(QtWidgets.QDialogButtonBox.Ok).isEnabled()))
    grab(idlg, "inlay_dialog.png")
    ires = idlg.apply()
    idlg.reject()
    r2d = proj2d.compute()
    rmale = ires["male_project"].compute()
    log("flat depth: ok %s, ops %s; inlay: female %d ops, male %d ops, all valid %s" % (
        fasm_ok, [o.Label for o in fops if o is not None], len(ires["female_ops"]), len(ires["male_ops"]),
        all(r["valid"] for r in r2d + rmale)))
    viewi = FreeCADGui.getDocument(ires["male_project"].doc.Name).activeView()
    viewi.viewIsometric()
    viewi.fitAll()
    QtWidgets.QApplication.processEvents()
    viewi.saveImage(os.path.join(OUT, "view3d_inlay_male.png"), 1000, 700, "White")
    # 4e axe continu : gravure enroulée sur un brut rond R20
    import Part
    from cam2027.gui.wrapdlg import WrapDialog
    from cam2027.project.machine import RotaryAxis
    rstep = os.path.join(tmp, "round.step")
    Part.makeCylinder(20, 80, FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(1, 0, 0)).exportStep(rstep)
    projw = Project.create("Wrap", lib)
    FreeCADGui.ActiveDocument = FreeCADGui.getDocument(projw.doc.Name)
    machine = projw.machine
    machine.rotary = RotaryAxis(present=True, about="X", center_offset_mm=(0.0, 0.0),
                                positive_direction="right_hand", min_deg=-720.0, max_deg=720.0)
    projw.set_machine(machine)
    wpart = projw.import_model(rstep, label="Round").objects[0]
    projw.create_job([wpart], stock={"kind": "cylinder_x", "radius": 20.0, "length": 84.0, "x_start": -2.0,
                                     "center": (0.0, 0.0)})
    circ = 2 * math.pi * 20.0
    V = FreeCAD.Vector
    unrolled = projw.doc.addObject("Part::Feature", "Unrolled")
    unrolled.Shape = Part.Compound([
        Part.makePolygon([V(10, 5, 0), V(70, 5, 0), V(70, circ - 5, 0), V(10, circ - 5, 0), V(10, 5, 0)]),
        Part.makeLine(V(15, 10, 0), V(65, circ - 10, 0))])
    projw.doc.recompute()
    unrolled.ViewObject.Visibility = False
    wdlg = WrapDialog(projw, mw, selected=[unrolled])
    QtWidgets.QApplication.processEvents()
    log("wrap dialog: drawing %s, info %s" % (wdlg.drawing.currentText(), wdlg.layout_info.text()[:40]))
    grab(wdlg, "wrap_dialog.png")
    wop = wdlg.apply()
    wdlg.reject()
    wres = {r["name"]: r for r in projw.compute()}[wop.Label]
    wtext, wana, wissues = projw.preview_gcode()
    log("wrap: commands %d, valid %s, A %s, G93 cuts %d, errors %s" % (
        wres["commands"], wres["valid"], wana["bbox"].get("A"), wana["a_wrap_lines"],
        [m for lvl, m in wissues if lvl == "error"]))
    for o in [wpart] + list(projw.job.Model.Group):  # le trajet est 0,5 mm sous la surface
        o.ViewObject.Transparency = 70
    vieww = FreeCADGui.getDocument(projw.doc.Name).activeView()
    vieww.viewIsometric()
    vieww.fitAll()
    QtWidgets.QApplication.processEvents()
    vieww.saveImage(os.path.join(OUT, "view3d_wrap.png"), 1000, 700, "White")
    fcstd = os.path.join(tmp, "gui.FCStd")
    proj.save(fcstd)
    log("saved %s" % fcstd)
    if standalone.is_standalone():
        QtWidgets.QApplication.processEvents()
        assert not page.isVisible(), "welcome page shown over an open document"
        standalone.apply_advanced_mode(True)
        assert all(v.isVisible() for v in standalone._property_views()), "advanced mode did not show the property editor"
        standalone.reset_layout()  # remet aussi le mode avancé à faux
        assert not any(v.isVisible() for v in standalone._property_views()), "default layout kept the property editor"
        real = welcome.recent_projects
        welcome.recent_projects = lambda: [fcstd]
        try:
            page.refresh()
            assert page.recent.count() == 1, "recent project not listed"
        finally:
            welcome.recent_projects = real
        log("standalone: welcome hidden with a document, advanced mode, default layout, recent list OK")
    # accents des titres de menu après les reconstructions de la barre (mode avancé, disposition, atelier)
    FreeCADGui.activateWorkbench("CAM2027Workbench")
    for _k in range(5):
        QtWidgets.QApplication.processEvents()
    titles = [a.text() for a in FreeCADGui.getMainWindow().menuBar().actions()]
    assert not any("Ã" in t for t in titles), "menu title read as Latin-1: %s" % titles
    log("menu titles: %s" % titles)
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
