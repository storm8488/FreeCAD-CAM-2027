# SPDX-License-Identifier: LGPL-2.1-or-later
"""Scénarios d'interface du flux S3 (recto-verso, zones interdites, édition groupée), appelés par
``gui_scenarios.py`` avec ses outils (pilote des dialogues, ``run_command``, ``problem``...)."""

import math
import os

import FreeCAD
import FreeCADGui

G = None  # outils de gui_scenarios.py, posés par lui avant l'appel


def _two_sided_part(tmp):
    import Part

    V = FreeCAD.Vector
    shape = Part.makeBox(80, 60, 10).cut(Part.makeCylinder(12, 3, V(25, 30, 7))).cut(Part.makeCylinder(10, 4, V(57, 30, 0)))
    path = os.path.join(tmp, "two_sided.step")
    shape.exportStep(path)
    return path


def _face_at(clone, z, area):
    for i, f in enumerate(clone.Shape.Faces, 1):
        if f.Surface.__class__.__name__ == "Plane" and abs(f.BoundBox.ZMin - z) < 1e-6 and abs(f.BoundBox.ZMax - z) < 1e-6 \
                and abs(f.Area - area) < 1.0:
            return "Face%d" % i
    return None


def _add_pocket(scenario, clone, face):
    FreeCADGui.Selection.clearSelection()
    FreeCADGui.Selection.addSelection(clone, face)
    G.driver.handlers[G.tr("Add operation")] = lambda dlg: (G.combo_select(G.find_combo_with(dlg, "pocket"), "pocket"), True)[1]
    G.run_command(scenario, "CAM2027_AddOperation")
    G.accept_open_editors(scenario)
    FreeCADGui.Selection.clearSelection()


def scenario_two_sided(scenario, tmp):
    """Pièce avec une poche de chaque côté : recto-verso par le dialogue, bascule A / B dans le panneau,
    une poche par face, contrôle matière enchaîné, export d'un fichier par face."""
    from cam2027.project import twosided

    proj = G.new_project(scenario, "TwoSided")
    G.driver.open_files.append(_two_sided_part(tmp))
    G.run_command(scenario, "CAM2027_ImportModel")
    G.run_command(scenario, "CAM2027_StockFixture")
    proj = G.project()
    if not proj.has_job:
        G.problem(scenario, "no job after Stock & fixture")
        return
    p = G.panel()
    if p.side_bar.isVisible():
        G.problem(scenario, "side A / B switch shown on a one-sided project")

    def setup(dlg):
        G.combo_select(G.find_combo_with(dlg, "Y"), "X")
        G.combo_select(G.find_combo_with(dlg, "corner"), "corner")
        return True

    G.driver.handlers[G.tr("Two-sided machining")] = setup
    G.run_command(scenario, "CAM2027_TwoSided")
    proj = G.project()
    if not twosided.is_two_sided(proj):
        G.problem(scenario, "Two-sided machining did not create side B")
        return
    G.pump(0.3)
    if not p.side_bar.isVisible() or not p.side_bar.buttons["A"].isChecked():
        G.problem(scenario, "side switch not shown or side A not current")
    clone = proj.job.Model.Group[0]
    _add_pocket(scenario, clone, _face_at(clone, 7.0, math.pi * 144))
    p.side_bar.buttons["B"].click()  # comme l'utilisateur : bouton « Face B » du panneau
    G.pump(0.3)
    proj = G.project()
    if twosided.current_side(proj) != "B" or not p.side_bar.buttons["B"].isChecked():
        G.problem(scenario, "the Side B button did not switch to side B")
        return
    if proj.operations():
        G.problem(scenario, "side B shows the operations of side A")
    clone = proj.job.Model.Group[0]
    face = _face_at(clone, 6.0, math.pi * 100)
    if face is None:
        G.problem(scenario, "pocket floor of side B not facing up on the flipped part")
        return
    _add_pocket(scenario, clone, face)
    G.run_command(scenario, "CAM2027_Compute")
    proj = G.project()
    names = {s: [o.Label for o in twosided.jobs(proj)[s].Operations.Group] for s in ("A", "B")}
    G.log("  operations per side %s" % names)
    if len(names["A"]) != 1 or len(names["B"]) != 1:
        G.problem(scenario, "expected one operation per side: %s" % names)
    msgs = G.run_command(scenario, "CAM2027_MaterialCheck")
    report = " ".join(t for k, t in msgs if k == "info")
    side_b = G.tr("Side {s}: removed {v} cm3, gouge {g} mm, stock left max {m} mm", s="B", v="", g="", m="").split(":")[0]
    if side_b not in report:
        G.problem(scenario, "material check report has no side B line")
    last = proj.last_check()
    if last is None or last["gouge_max"] > last["tolerance"]:
        G.problem(scenario, "gouge after the two-sided check: %s" % (last and last["gouge_max"]))
    out = os.path.join(tmp, "two_sided.nc")
    G.driver.handlers[G.tr("Export G-code")] = lambda dlg: G._export(dlg, out)
    G.run_command(scenario, "CAM2027_Export")
    for side in ("A", "B"):
        path = os.path.join(tmp, "two_sided-%s.nc" % side)
        if not os.path.isfile(path):
            G.problem(scenario, "no G-code file for side %s" % side)
        sheet = os.path.join(tmp, "two_sided-%s-setup.md" % side)
        if not os.path.isfile(sheet) or "Two-sided machining - side %s" % side not in open(sheet, encoding="utf-8").read():
            G.problem(scenario, "setup sheet of side %s without the two-sided section" % side)
    G.check_docks(scenario)


def _two_pocket_part(tmp):
    import Part

    plate = Part.makeBox(80, 60, 10)
    for x in (10.0, 50.0):
        plate = plate.cut(Part.makeBox(20, 30, 4, FreeCAD.Vector(x, 15, 6)))
    path = os.path.join(tmp, "two_pockets.step")
    plate.exportStep(path)
    return path


def scenario_keepout(scenario, tmp):
    """Bride dessinée comme zone interdite entre deux poches, par le dialogue : plus aucun rapide au travers,
    contrôle des brides OK, export possible."""
    from cam2027.project import keepout, sim

    G.new_project(scenario, "KeepOut")
    G.driver.open_files.append(_two_pocket_part(tmp))
    G.run_command(scenario, "CAM2027_ImportModel")
    G.run_command(scenario, "CAM2027_StockFixture")
    proj = G.project()
    clone = proj.job.Model.Group[0]
    floors = ["Face%d" % i for i, f in enumerate(clone.Shape.Faces, 1)
              if f.Surface.__class__.__name__ == "Plane" and abs(f.BoundBox.ZMax - 6.0) < 1e-6 and abs(f.BoundBox.ZMin - 6.0) < 1e-6]
    FreeCADGui.Selection.clearSelection()
    for f in floors:
        FreeCADGui.Selection.addSelection(clone, f)
    G.driver.handlers[G.tr("Add operation")] = lambda dlg: (G.combo_select(G.find_combo_with(dlg, "pocket"), "pocket"), True)[1]
    G.run_command(scenario, "CAM2027_AddOperation")
    G.accept_open_editors(scenario)
    FreeCADGui.Selection.clearSelection()
    G.run_command(scenario, "CAM2027_Compute")

    def zone(dlg):
        dlg.xmin.setValue(36.0)
        dlg.xmax.setValue(44.0)
        dlg.ymin.setValue(-10.0)
        dlg.ymax.setValue(70.0)
        dlg.ztop.setValue(40.0)
        from cam2027.gui.qt import QtWidgets

        for b in dlg.findChildren(QtWidgets.QPushButton):
            if b.text() == G.tr("Add zone"):
                b.click()
        if dlg.table.rowCount() != 1:
            G.problem(scenario, "the new zone is not listed in the dialog")
        return True

    G.driver.handlers[G.tr("Keep-out zones")] = zone
    G.run_command(scenario, "CAM2027_KeepOut")
    proj = G.project()
    boxes = keepout.zone_boxes(proj.doc)
    if len(boxes) != 1:
        G.problem(scenario, "expected one keep-out zone, found %d" % len(boxes))
        return
    pos, crossing = None, 0
    for op in proj.operations():
        segs, pos = sim.path_segments(op.Path.Commands, pos)
        r = keepout._tool_radius(op)
        crossing += sum(1 for rapid, p0, p1 in segs if rapid and keepout.blocking_top(p0, p1, boxes, r, 0.0) is not None)
    G.log("  rapids through the zone: %d" % crossing)
    if crossing:
        G.problem(scenario, "%d rapid move(s) still cross the keep-out zone" % crossing)
    G.run_command(scenario, "CAM2027_MaterialCheck")
    last = proj.last_check()
    if last is None or last["status"]["clamps"] != "ok":
        G.problem(scenario, "clamp / zone collision check not OK: %s" % (last and last["status"]))
    out = os.path.join(tmp, "keepout.nc")
    G.driver.handlers[G.tr("Export G-code")] = lambda dlg: G._export(dlg, out)
    G.run_command(scenario, "CAM2027_Export")
    if not os.path.isfile(out):
        G.problem(scenario, "no G-code written with the keep-out zone")
    G.check_docks(scenario)
