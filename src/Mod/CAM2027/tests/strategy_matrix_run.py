# SPDX-License-Identifier: LGPL-2.1-or-later
"""Une case de la matrice stratégies × pièces, lancée par ``run_strategy_matrix.py`` dans son propre processus
CAM2027.exe (un gel ou un plantage n'arrête pas les autres cases).

Variables : ``CAM2027_MATRIX_FILE`` (pièce : chemin ou « plate » / « dome »), ``CAM2027_MATRIX_STRATEGY``,
``CAM2027_MATRIX_OUT`` (fichier résultat JSON). Le scénario passe par les vraies commandes : import, brut,
« Ajouter une opération » (outil compatible, géométrie automatique), recalcul, contrôle matière.
"""

import faulthandler
import json
import os
import sys
import tempfile
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
if MOD not in sys.path:
    sys.path.insert(0, MOD)

OUT = os.environ["CAM2027_MATRIX_OUT"]
faulthandler.enable(open(OUT + ".fault.txt", "w"), all_threads=True)
result = {"file": os.environ.get("CAM2027_MATRIX_FILE"), "strategy": os.environ.get("CAM2027_MATRIX_STRATEGY"),
          "steps": [], "messages": []}


def save():
    with open(OUT, "w", encoding="utf-8") as fp:
        json.dump(result, fp, ensure_ascii=False, indent=1)


def step(name):
    result["steps"].append([name, round(time.time() - T0, 2)])
    save()


import FreeCAD
import FreeCADGui
from PySide import QtCore, QtWidgets

T0 = time.time()


def pump(t=0.2):
    end = time.time() + t
    while time.time() < end:
        QtWidgets.QApplication.processEvents()
        time.sleep(0.02)


def make_part(kind, tmp):
    import Part

    V = FreeCAD.Vector
    if kind == "plate":
        from tests.test_pipeline import make_part as mp

        path = os.path.join(tmp, "plate.step")
        mp(path)
        return path
    if kind == "dome":
        plate = Part.makeBox(60, 40, 5)
        dome = Part.makeSphere(25.0, V(30, 20, -15)).common(Part.makeBox(60, 40, 30, V(0, 0, 5)))
        path = os.path.join(tmp, "dome.step")
        plate.fuse(dome).removeSplitter().exportStep(path)
        return path
    return kind


def run():
    from cam2027.gui import commands
    from cam2027.gui import opeditor
    from cam2027.gui import state

    files = []
    commands._warn = lambda t: result["messages"].append(["warn", t])
    commands._info = lambda t: result["messages"].append(["info", t])
    QtWidgets.QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (files.pop(0) if files else "", ""))
    QtWidgets.QInputDialog.getText = staticmethod(lambda *a, **k: ("Matrix", True))
    QtWidgets.QMessageBox.question = staticmethod(lambda *a, **k: QtWidgets.QMessageBox.Yes)
    strategy = result["strategy"]

    def exec_dialog(dlg):
        title = dlg.windowTitle()
        from cam2027.i18n import tr

        if title == tr("Add operation"):
            for c in dlg.findChildren(QtWidgets.QComboBox):
                i = c.findData(strategy)
                if i >= 0:
                    c.setCurrentIndex(i)
            asm = [c for c in dlg.findChildren(QtWidgets.QComboBox) if c.count() and c.itemData(0) and
                   str(c.itemData(0)).count("-") >= 2]
            result["tool"] = asm[0].currentText() if asm else None
        dlg.show()
        pump(0.1)
        dlg.accept()
        return QtWidgets.QDialog.Accepted

    commands.exec_dialog = exec_dialog
    FreeCADGui.activateWorkbench("CAM2027Workbench")
    pump(1.0)
    tmp = tempfile.mkdtemp(prefix="cam2027-mx-")
    path = make_part(result["file"], tmp)
    cmds = dict(commands.COMMANDS)
    files.append(path)
    cmds["CAM2027_ImportModel"]().Activated()
    step("import")
    cmds["CAM2027_StockFixture"]().Activated()
    step("stock")
    proj = state.active_project()
    if proj is None or not proj.has_job:
        result["outcome"] = "no-job"
        return
    FreeCADGui.Selection.clearSelection()
    cmds["CAM2027_AddOperation"]().Activated()
    step("add-operation")
    for ed in list(opeditor._open_editors):
        ed.accept()
    pump(0.2)
    proj = state.active_project()
    ops = proj.operations()
    if not ops:
        result["outcome"] = "refused" if result["messages"] else "refused-silently"
        return
    states = [proj.operation_state(o) for o in ops]
    result["states"] = states
    from cam2027.project.operations import toolpath_summary

    result["summary"] = [{k: v for k, v in toolpath_summary(o).items() if k in ("commands", "zmin", "zmax", "length_mm")}
                         for o in ops]
    step("computed")
    if any(s == "failed" for s in states):
        result["outcome"] = "failed"
        return
    try:
        rep = proj.material_check()
        result["check"] = {"gouge_max": rep["gouge_max"], "removed_cm3": rep["removed_volume"] / 1000.0,
                           "events": [e[0] for e in rep["collisions"]["events"]]}
    except Exception as exc:
        result["check"] = {"error": str(exc)}
    step("material-check")
    result["outcome"] = "computed"


def main():
    try:
        run()
    except Exception:
        result["outcome"] = "exception"
        result["traceback"] = traceback.format_exc()
    result["seconds"] = round(time.time() - T0, 1)
    save()
    for name in list(FreeCAD.listDocuments()):  # sinon FreeCAD demande d'enregistrer et ne quitte pas
        try:
            FreeCAD.closeDocument(name)
        except Exception:
            pass
    QtCore.QTimer.singleShot(200, QtWidgets.QApplication.instance().quit)


QtCore.QTimer.singleShot(1500, main)
