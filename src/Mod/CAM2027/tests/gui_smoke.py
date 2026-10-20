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
    grab(project_panel, "project_panel.png")
    # éditeur d'opération (non modal) : onglets générés, lecture des valeurs, application
    from cam2027.gui import opeditor
    op = proj.operations()[0]
    editor = opeditor.open_editor(proj, op)
    QtWidgets.QApplication.processEvents()
    tabs = [editor.tabs.tabText(i) for i in range(editor.tabs.count())]
    log("editor tabs: %s" % tabs)
    for i in range(editor.tabs.count()):
        editor.tabs.setCurrentIndex(i)
        QtWidgets.QApplication.processEvents()
        grab(editor, "op_editor_%d.png" % i)
    editor.tabs.setCurrentIndex(2)
    kind, widget = editor.widgets["StepDown"]
    widget.setValue(2.5)
    box, widgets = editor.dressup_boxes["tags"]
    box.setChecked(True)
    widgets["Count"][1].setValue(3)
    log("editor apply: %s" % editor.apply())
    log("editor status: %s" % editor.status.text())
    log("StepDown after apply: %s" % op.StepDown)
    dress = proj.dressups(op)
    log("dressups after apply: %s, positions %s" % ([d.Name for d in dress], [len(d.Positions) for d in dress if hasattr(d, "Positions")]))
    editor.tabs.setCurrentIndex(editor.tabs.count() - 1)
    QtWidgets.QApplication.processEvents()
    grab(editor, "op_editor_dressups.png")
    editor.accept()
    QtWidgets.QApplication.processEvents()
    view_path = os.path.join(OUT, "view3d.png")
    FreeCADGui.activeDocument().activeView().saveImage(view_path, 1000, 700, "White")
    log("screenshot view3d.png")
    QtWidgets.QApplication.processEvents()
    grab(mw, "main_window.png")
    # export dialog rendering (non modal grab)
    text, analysis, issues = proj.preview_gcode()
    log("gcode lines=%d issues=%s" % (analysis["lines"], [l for l, _m in issues]))
    tb = [t for t in mw.findChildren(QtWidgets.QToolBar) if t.windowTitle() == "CAM2027"]
    log("toolbar found: %s, actions: %d" % (bool(tb), len(tb[0].actions()) if tb else 0))
    for name, _cls in commands.COMMANDS:
        log("command %s registered: %s" % (name, name in FreeCADGui.listCommands()))
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
