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
        # bride basse entre les poches : au-dessus du dégagement (15) mais sous le porte-outil quand la fraise est
        # dans une poche (une bride de 40 mm à 9 mm de la poche touche le porte-outil : collision réelle, bloquante)
        dlg.xmin.setValue(38.0)
        dlg.xmax.setValue(42.0)
        dlg.ymin.setValue(-10.0)
        dlg.ymax.setValue(70.0)
        dlg.ztop.setValue(20.0)
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


def scenario_nest_shapes(scenario, tmp):
    """SVG d'une pièce en L : 12 copies imbriquées par forme réelle (dialogue, défaut), aucune pièce à moins de
    l'espacement d'une autre, puis panneau et contour."""
    from cam2027.project import nesting, sheet as sheetmod

    svg = os.path.join(tmp, "l_part.svg")
    with open(svg, "w", encoding="utf-8") as fp:
        fp.write('<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" width="80mm" height="80mm" '
                 'viewBox="0 0 80 80"><path d="M 5 5 L 65 5 L 65 25 L 25 25 L 25 65 L 5 65 Z" fill="none" stroke="black"/></svg>')
    G.new_project(scenario, "NestShapes")
    G.driver.open_files.append(svg)
    G.run_command(scenario, "CAM2027_ImportModel")

    def nest(dlg):
        dlg.table.cellWidget(0, 2).setValue(12)
        dlg.width.setValue(300.0)
        dlg.length.setValue(220.0)
        dlg.spacing.setValue(5.0)
        if dlg.mode.currentData() != 15.0:
            G.problem(scenario, "true-shape nesting is not the default")
        return True

    G.driver.handlers[G.tr("Nest parts on a sheet")] = nest
    msgs = G.run_command(scenario, "CAM2027_Nest")
    proj = G.project()
    objs = [o for o in sheetmod.vector_objects(proj.doc) if sheetmod.closed_wires(o)]
    if len(objs) != 12:
        G.problem(scenario, "expected 12 drawings after nesting, found %d" % len(objs))
        return
    faces = [nesting.silhouette(o.Shape) for o in objs]
    worst = min(faces[a].distToShape(faces[b])[0] for a in range(len(faces)) for b in range(a + 1, len(faces)))
    out = [o.Label for o, f in zip(objs, faces) if f.BoundBox.XMin < 10 - 1e-6 or f.BoundBox.YMin < 10 - 1e-6
           or f.BoundBox.XMax > 290 + 1e-6 or f.BoundBox.YMax > 210 + 1e-6]
    G.log("  12 L parts nested, min gap %.2f mm, outside the margin: %s" % (worst, out))
    if worst < 5.0 - 1e-3 or out:
        G.problem(scenario, "nested parts too close (%.2f mm) or outside the sheet margin %s" % (worst, out))
    if any(k == "warn" for k, _t in msgs):
        G.problem(scenario, "nesting warned: %s" % msgs)
    G.driver.handlers[G.tr("Stock & fixture")] = lambda dlg: (G.combo_select(G.find_combo_with(dlg, "sheet"), "sheet"), True)[1]
    G.run_command(scenario, "CAM2027_StockFixture")
    proj = G.project()
    if not proj.has_job:
        G.problem(scenario, "no sheet job after the nesting")
        return
    sb = proj.stock_bounds()
    if (round(sb["length"], 3), round(sb["width"], 3)) != (300.0, 220.0):
        G.problem(scenario, "sheet job is not the nesting sheet: %s" % sb)
    G.check_docks(scenario)


def scenario_bulk_edit(scenario, tmp):
    """Trois opérations, puis « Comparer et modifier » depuis le panneau : hauteur de dégagement changée sur les
    trois d'un coup, recalculées."""
    G.new_project(scenario, "BulkEdit")
    G.driver.open_files.append(_two_pocket_part(tmp))
    G.run_command(scenario, "CAM2027_ImportModel")
    G.run_command(scenario, "CAM2027_StockFixture")
    for strategy in ("profile", "adaptive", "pocket"):
        FreeCADGui.Selection.clearSelection()
        G.driver.handlers[G.tr("Add operation")] = (
            lambda dlg, k=strategy: (G.combo_select(G.find_combo_with(dlg, k), k), True)[1])
        G.run_command(scenario, "CAM2027_AddOperation")
        G.accept_open_editors(scenario)
    G.run_command(scenario, "CAM2027_Compute")
    proj = G.project()
    ops = [proj.base_operation(o) for o in proj.operations()]
    if len(ops) < 3:
        G.problem(scenario, "expected 3 operations, found %d" % len(ops))
        return
    seen = {}

    def edit(dlg):
        names = [r["name"] for r in dlg.rows]
        seen["rows"] = len(names)
        if "ClearanceHeight" not in names:
            G.problem(scenario, "clearance height is not a shared row: %s" % names)
            return False
        dlg.diff_only.setChecked(True)
        seen["hidden"] = sum(1 for r in range(dlg.table.rowCount()) if dlg.table.isRowHidden(r))
        dlg.diff_only.setChecked(False)
        dlg.set_value("ClearanceHeight", "33")
        return True

    G.driver.handlers[G.tr("Compare and edit operations")] = edit
    p = G.panel()
    from cam2027.gui.qt import QtWidgets

    buttons = [b for b in p.findChildren(QtWidgets.QPushButton) if b.text() == G.tr("Compare and edit operations")]
    if not buttons:
        G.problem(scenario, "no Compare and edit button in the Project panel")
        return
    buttons[0].click()  # comme l'utilisateur, depuis le panneau
    G.pump(0.5)
    for kind, text in G.driver.take():
        G.log("  bulk edit %s: %s" % (kind, text.replace("\n", " | ")[:200]))
    G.log("  shared rows %s, hidden with differences only %s" % (seen.get("rows"), seen.get("hidden")))
    if not seen.get("hidden"):
        G.problem(scenario, "Differences only hid no row")
    proj = G.project()
    for op in ops:
        z = float(op.ClearanceHeight.getValueAs("mm"))
        zmax = max([c.Parameters["Z"] for c in op.Path.Commands if "Z" in c.Parameters] or [0])
        state = proj.operation_state(op)
        G.log("  %s: clearance %.2f, path Z max %.2f, %s" % (op.Label, z, zmax, state))
        if abs(z - 33.0) > 1e-6 or abs(zmax - 33.0) > 1e-3 or state in ("failed", "todo", "stale"):
            G.problem(scenario, "%s not updated: clearance %.2f, Z max %.2f, state %s" % (op.Label, z, zmax, state))
    G.check_docks(scenario)
