# SPDX-License-Identifier: LGPL-2.1-or-later
"""Scénarios d'interface du flux S1 (nuit 2) : reprise de matière, découpe dans une zone, finitions des zones
plates et des angles. Appelés par ``gui_scenarios.py`` (``g`` = ce module, pour ses outils de pilotage)."""

import os

import FreeCAD
import FreeCADGui
from PySide import QtWidgets


def _add_operation(g, scenario, strategy, tool_name=None):
    """« Ajouter une opération » comme l'utilisateur : stratégie, puis outil choisi dans le champ Outil ; retourne
    l'éditeur ouvert (non modal) ou None."""
    from cam2027.gui import opeditor, toolpicker

    proj = g.project()

    def fill(dlg):
        g.combo_select(g.find_combo_with(dlg, strategy), strategy)
        if tool_name:
            lib = proj.library
            tool = next(t for t in lib.tools.values() if t.name == tool_name)
            field = dlg.findChildren(toolpicker.ToolField)[0]
            field.user_chose = True
            field.set_assembly(lib.assemblies_for_tool(tool.id)[0].id)
        return True

    before = set(opeditor._open_editors)
    FreeCADGui.Selection.clearSelection()
    g.driver.handlers[g.tr("Add operation")] = fill
    g.run_command(scenario, "CAM2027_AddOperation")
    opened = [e for e in opeditor._open_editors if e not in before]
    if not opened:
        g.problem(scenario, "Add operation (%s) opened no editor" % strategy)
        return None
    return opened[-1]


def _cut_points(path):
    pos, pts = {}, []
    for c in path.Commands:
        for k in "XYZ":
            if k in c.Parameters:
                pos[k] = c.Parameters[k]
        if c.Name in ("G1", "G2", "G3") and len(pos) == 3:
            pts.append((pos["X"], pos["Y"], pos["Z"]))
    return pts


def scenario_rest_and_area(g, scenario, files):
    """Ébauche adaptative Ø6 puis adaptative Ø3 en reprise (onglet « Reprise et zone » de l'éditeur), contrôle
    matière ; puis la reprise limitée à un rectangle (moitié gauche) depuis le même onglet."""
    from cam2027.project import rest, trim

    proj = g.new_project(scenario, "S1 rest")
    if proj is None:
        return
    g.driver.open_files.append(files["step"])
    g.run_command(scenario, "CAM2027_ImportModel")
    g.run_command(scenario, "CAM2027_StockFixture")
    ed = _add_operation(g, scenario, "adaptive", "6 mm flat end mill 2F")
    if ed is None:
        return
    ed.accept()
    ed = _add_operation(g, scenario, "adaptive", "3 mm flat end mill 2F")
    if ed is None:
        return
    tab = getattr(ed, "rest_limit", None)
    if tab is None or tab.rest_box is None:
        g.problem(scenario, "the editor has no rest machining box for an adaptive operation")
        ed.reject()
        return
    titles = [ed.tabs.tabText(i) for i in range(ed.tabs.count())]
    if g.tr("Rest & area") not in titles:
        g.problem(scenario, "no 'Rest & area' tab in the editor: %s" % titles)
    ed.tabs.setCurrentIndex(titles.index(g.tr("Rest & area")))
    tab.rest_box.setChecked(True)
    tab.ignore.setValue(0.1)
    g.pump(0.2)
    ed.grab().save(os.path.join(g.OUT, "dialogs", "s1_rest_tab.png"))
    op = ed.op
    ed.accept()
    g.pump(0.3)
    if ed.isVisible():
        g.problem(scenario, "editor did not close after enabling rest machining: %s" % ed.status.text())
        ed.done(0)
    proj = g.project()
    dress = trim.find_dressup(proj, op, rest.SUFFIX)
    if dress is None:
        g.problem(scenario, "rest machining was not added by the editor")
        return
    kept, full = _cut_points(dress.Path), _cut_points(op.Path)
    g.log("  rest: %d of %d cut points kept, %s" % (len(kept), len(full), dress.Report))
    if not kept or len(kept) >= len(full):
        g.problem(scenario, "rest machining kept %d of %d cut points" % (len(kept), len(full)))
    msgs = g.run_command(scenario, "CAM2027_MaterialCheck")
    rep = proj.last_check() if hasattr(proj, "last_check") else None
    g.log("  check: %s" % (rep and {k: rep.get(k) for k in ("gouge_max", "removed_volume")}))
    if rep and rep.get("gouge_max", 0) > 0.03:
        g.problem(scenario, "gouge after rest machining: %s" % rep.get("gouge_max"))
    # zone : moitié gauche du plateau seulement, rectangle saisi dans le même onglet
    from cam2027.gui import opeditor

    ed = opeditor.open_editor(proj, op)
    g.pump(0.3)
    tab = ed.rest_limit
    tab.limit_box.setChecked(True)
    tab.use_rectangle()
    b = proj.stock_bounds()
    xmid = (b["xmin"] + b["xmax"]) / 2.0
    for key, value in (("xmin", b["xmin"] - 1), ("ymin", b["ymin"] - 1), ("xmax", xmid), ("ymax", b["ymax"] + 1)):
        tab.rect[key].setValue(value)
    g.combo_select(tab.keep, True)
    ed.tabs.setCurrentIndex([ed.tabs.tabText(i) for i in range(ed.tabs.count())].index(g.tr("Rest & area")))
    g.pump(0.2)
    ed.grab().save(os.path.join(g.OUT, "dialogs", "s1_area_tab.png"))
    ed.accept()
    g.pump(0.3)
    proj = g.project()
    area = trim.find_dressup(proj, op, trim.SUFFIX)
    if area is None:
        g.problem(scenario, "limit to an area was not added by the editor")
        return
    inside = _cut_points(area.Path)
    outside = [p for p in inside if p[0] > xmid + 1e-3]
    g.log("  area: %d cut points kept (of %d), %d beyond X %.2f" % (len(inside), len(kept), len(outside), xmid))
    if not inside or outside:
        g.problem(scenario, "limit to an area: %d points kept, %d outside" % (len(inside), len(outside)))
    g.run_command(scenario, "CAM2027_Compute")
    states = [proj.operation_state(o) for o in proj.operations()]
    if any(s in ("failed", "todo") for s in states):
        g.problem(scenario, "operation states after compute: %s" % states)
    g.check_docks(scenario)
    FreeCAD.closeDocument(proj.doc.Name)
    g.pump(0.3)


def scenario_flat(g, scenario, files):
    """Finition des zones plates sans sélection (dessus et fonds trouvés seuls), outil choisi dans le dialogue,
    éditeur accepté, calcul, contrôle matière."""
    from cam2027.project import flatfinish

    proj = g.new_project(scenario, "S1 flat")
    if proj is None:
        return
    g.driver.open_files.append(files["step"])
    g.run_command(scenario, "CAM2027_ImportModel")
    g.run_command(scenario, "CAM2027_StockFixture")
    ed = _add_operation(g, scenario, "flat3d", "3 mm flat end mill 2F")
    if ed is None:
        return
    titles = [ed.tabs.tabText(i) for i in range(ed.tabs.count())]
    g.log("  editor tabs: %s" % titles)
    op = ed.op
    ed.accept()
    g.pump(0.3)
    proj = g.project()
    g.run_command(scenario, "CAM2027_Compute")
    state = proj.operation_state(op)
    pts = _cut_points(op.Path)
    levels = sorted(set(round(p[2], 3) for p in pts))
    g.log("  flat: state %s, %d cut points, levels %s, %s" % (state, len(pts), levels, op.Report))
    if state != "computed" or levels != [4.0, 12.0]:
        g.problem(scenario, "flat finishing: state %s, levels %s (expected 4 and 12)" % (state, levels))
    g.run_command(scenario, "CAM2027_MaterialCheck")
    rep = proj.last_check()
    if rep is None or rep.get("gouge_max", 1) > 0.03:
        g.problem(scenario, "gouge after flat finishing: %s" % (rep and rep.get("gouge_max")))
    g.check_docks(scenario)
    FreeCAD.closeDocument(proj.doc.Name)
    g.pump(0.3)


def scenario_pencil(g, scenario, files):
    """Reprise des angles avec la boule de 6 mm (référence 18 mm par défaut) : angles des alvéoles du plateau."""
    proj = g.new_project(scenario, "S1 pencil")
    if proj is None:
        return
    g.driver.open_files.append(files["step"])
    g.run_command(scenario, "CAM2027_ImportModel")
    g.run_command(scenario, "CAM2027_StockFixture")
    ed = _add_operation(g, scenario, "pencil", "6 mm ball end mill 2F")
    if ed is None:
        return
    op = ed.op
    ed.accept()
    g.pump(0.3)
    proj = g.project()
    g.run_command(scenario, "CAM2027_Compute")
    state = proj.operation_state(op)
    pts = _cut_points(op.Path)
    g.log("  pencil: state %s, %d cut points, %s" % (state, len(pts), op.Report))
    if state != "computed" or not pts:
        g.problem(scenario, "pencil: state %s, %d cut points" % (state, len(pts)))
    g.run_command(scenario, "CAM2027_MaterialCheck")
    rep = proj.last_check()
    if rep is None or rep.get("gouge_max", 1) > 0.03:
        g.problem(scenario, "gouge after pencil: %s" % (rep and rep.get("gouge_max")))
    g.check_docks(scenario)
    FreeCAD.closeDocument(proj.doc.Name)
    g.pump(0.3)


def scenarios(g, files, tmp):
    """Entrées pour la liste de ``gui_scenarios.main``."""
    return (("s1-rest-area", lambda: scenario_rest_and_area(g, "s1-rest-area", files)),
            ("s1-flat", lambda: scenario_flat(g, "s1-flat", files)),
            ("s1-pencil", lambda: scenario_pencil(g, "s1-pencil", files)))
