# SPDX-License-Identifier: LGPL-2.1-or-later
"""Scénarios d'interface du flux C4 (jour 4 : fonctions incomplètes), appelés par ``gui_scenarios.py``.

Les aides du pilote (``run_command``, ``project``, ``problem``...) sont passées par ``h`` (globals du script
principal) : ce module ne lance rien à l'import.
"""

import math
import os

import FreeCAD


def _machine_with_a(h):
    """Profil machine : axe A présent autour de X, centre (0, 0), sens main droite, -720..720°."""
    QtWidgets = h["QtWidgets"]

    def machine(dlg):
        checks = [c for c in dlg.findChildren(QtWidgets.QCheckBox) if c.text() == h["tr"]("Rotary axis A present (about X)")]
        checks[0].setChecked(True)
        for combo in dlg.findChildren(QtWidgets.QComboBox):
            i = combo.findData("right_hand")
            if i >= 0:
                combo.setCurrentIndex(i)
        box = dlg.findChildren(QtWidgets.QGroupBox)[0]
        for edit, value in zip(box.findChildren(QtWidgets.QLineEdit), ("0", "0", "-720", "720", "3600")):
            edit.setText(value)
        return True

    h["driver"].handlers[h["tr"]("Machine profile")] = machine


def scenario_rotary_radial(h, scenario, tmp):
    """Usinage rotatif par le dialogue : poche enroulée, fraise plate 3 mm, case « Parois radiales » cochée par
    défaut ; G-code XYZA ; contrôle matière 4e axe par la commande : rapport « carte de rayon », aucune entaille,
    brut simulé affiché autour de l'axe ; poche descendue trop bas par le dialogue de modification : entaille."""
    from tests.test_jour4_c4 import FLOOR_R, POCKET_X, ROT_R, rotary_part

    tr, log, problem = h["tr"], h["log"], h["problem"]
    QtWidgets = h["QtWidgets"]
    step = os.path.join(tmp, "c4-radial.step")
    rotary_part(step)
    h["new_project"](scenario, "Radial walls")
    h["driver"].open_files.append(step)
    h["run_command"](scenario, "CAM2027_ImportModel")
    _machine_with_a(h)
    h["run_command"](scenario, "CAM2027_Machine")

    def round_bar(dlg):
        h["combo_select"](h["find_combo_with"](dlg, "cylinder_x"), "cylinder_x")
        for spin in dlg.findChildren(QtWidgets.QDoubleSpinBox):
            if abs(spin.value() - 25.0) < 1e-9:  # rayon (25 par défaut)
                spin.setValue(ROT_R)
        return True

    h["driver"].handlers[tr("Stock & fixture")] = round_bar
    h["run_command"](scenario, "CAM2027_StockFixture")
    proj = h["project"]()
    if not proj.has_job:
        problem(scenario, "round bar job not created")
        return
    import Part

    V = FreeCAD.Vector
    half = 6.0 / FLOOR_R
    y0, y1 = (math.pi - half) * ROT_R, (math.pi + half) * ROT_R
    dr = proj.doc.addObject("Part::Feature", "Unrolled")
    dr.Shape = Part.makePolygon([V(POCKET_X[0], y0, 0), V(POCKET_X[1], y0, 0), V(POCKET_X[1], y1, 0),
                                 V(POCKET_X[0], y1, 0), V(POCKET_X[0], y0, 0)])
    proj.doc.recompute()
    flat = [t for t in proj.library.search("3 mm flat end mill") if t.tool_type == "endmill"][0]
    asm = proj.library.assemblies_for_tool(flat.id)[0].id
    seen = {}

    def pocket(dlg):
        h["combo_select"](h["find_combo_with"](dlg, "wrap_pocket"), "wrap_pocket")
        h["combo_select"](h["find_combo_with"](dlg, dr.Name), dr.Name)
        dlg.asm.set_assembly(asm)
        dlg._fill_presets()
        dlg.depth.setValue(ROT_R - FLOOR_R)
        dlg.step_down.setValue(3.0)
        seen["radial_visible"] = dlg.radial.isVisible()
        seen["radial_checked"] = dlg.radial.isChecked()
        return True

    h["driver"].handlers[tr("Rotary machining (continuous A axis)")] = pocket
    h["run_command"](scenario, "CAM2027_RotaryMachining")
    proj = h["project"]()
    ops = proj.wrapped_operations()
    log("  radial walls box: %s, operations %s" % (seen, [o.Label for o in ops]))
    if not (seen.get("radial_visible") and seen.get("radial_checked")):
        problem(scenario, "radial walls box not shown checked for a new wrapped pocket: %s" % seen)
    if len(ops) != 1:
        problem(scenario, "wrapped pocket not created")
        return
    op = ops[0]
    rec = proj.registry[op.Name]
    xyza = [g for g in op.Gcode if g.startswith("G1") and " Y" in g and " A" in g]
    log("  params %s, %d XYZA lines" % (rec["params"], len(xyza)))
    if not rec["params"].get("radial_walls") or len(xyza) < 50:
        problem(scenario, "radial walls not applied (%d XYZA lines)" % len(xyza))
    msgs = h["run_command"](scenario, "CAM2027_MaterialCheck")
    text = " | ".join(t for _k, t in msgs)
    rep = proj.last_check() or {}
    if tr("Material check (radius map around the A axis, {res} mm grid)", res="0.5") not in text:
        problem(scenario, "material check report is not the rotary one: %s" % text[:300])
    if rep.get("gouge_max") != 0.0:
        problem(scenario, "gouge reported on the radial-wall pocket: %s" % rep.get("gouge_max"))
    stock = proj.doc.getObject("CAM2027SimStock")
    bb = stock.Mesh.BoundBox if stock is not None else None
    log("  simulated stock box %s" % (bb,))
    if bb is None or bb.ZMin > -ROT_R + 0.5 or bb.ZMax < ROT_R - 0.5:
        problem(scenario, "simulated stock not shown around the A axis")
    # modification par le dialogue (double-clic) : 0,4 mm de trop -> entaille signalée
    from cam2027.gui import rotarydlg

    dlg = rotarydlg.RotaryDialog(proj, op=op)
    dlg.depth.setValue(ROT_R - FLOOR_R + 0.4)
    dlg.step_down.setValue(3.4)
    if not dlg.radial.isChecked():
        problem(scenario, "edit dialog lost the radial walls option")
    dlg.apply()
    h["qt_dispose"](dlg)
    msgs = h["run_command"](scenario, "CAM2027_MaterialCheck")
    gouge = (h["project"]().last_check() or {}).get("gouge_max")
    log("  after 0.4 mm too deep: gouge %s" % gouge)
    if not gouge or abs(gouge - 0.4) > 0.05:
        problem(scenario, "intentional 0.4 mm gouge not found: %s" % gouge)
    if not any(tr("GOUGE: the tool cuts {d} mm into the part (worst at X {x} Y {y}, {n} cells)", d="0.40", x="X",
                  y="Y", n="N").split("0.40")[0] in t for _k, t in msgs):
        problem(scenario, "gouge not reported in the message")
    FreeCAD.closeDocument(proj.doc.Name)
    h["pump"](0.3)


def scenario_vectors(h, scenario, tmp):
    """Dessin paramétrique par les commandes : rectangle (cadre) puis panneau, texte « AB » poché, « Modifier le
    vecteur » -> « ABH » plus grand : poche recalculée (la nouvelle lettre est vidée) ; double-clic sur le texte
    -> déplacé ; polygone, « Modifier les nœuds » : un nœud supprimé."""
    import FreeCADGui
    from cam2027.project import vectors as vecmod

    tr, log, problem = h["tr"], h["log"], h["problem"]
    proj = h["new_project"](scenario, "Drawing")
    seen = {}

    def frame(dlg):
        f = dlg.fields
        f["X"].setValue(80.0), f["Y"].setValue(25.0), f["Width"].setValue(180.0), f["Height"].setValue(70.0)
        return True

    h["driver"].handlers[tr("Rectangle")] = frame
    h["run_command"](scenario, "CAM2027_DrawRectangle")
    h["run_command"](scenario, "CAM2027_StockFixture")  # dessin seul : panneau proposé
    proj = h["project"]()
    if proj is None or not proj.has_job:
        problem(scenario, "sheet job not created from the drawn rectangle")
        return
    font = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "ariblk.ttf")

    def text(dlg, value="AB", size=30.0):
        dlg.text.setText(value)
        i = dlg.font.findData(font)
        if i >= 0:
            dlg.font.setCurrentIndex(i)
        dlg.size.setValue(size)
        seen.setdefault("text_dialogs", []).append(dlg.edit is not None)
        return True

    h["driver"].handlers[tr("Text")] = text
    FreeCADGui.Selection.clearSelection()
    h["run_command"](scenario, "CAM2027_DrawText")
    proj = h["project"]()
    texts = [o for o in proj.doc.Objects if vecmod.is_parametric(o) and o.VectorKind == "text"]
    if len(texts) != 1:
        problem(scenario, "text not created as an editable vector: %s" % [o.Label for o in proj.doc.Objects])
        return
    obj = texts[0]
    lib = proj.library
    tool = [t for t in lib.search("3 mm flat end mill") if t.tool_type == "endmill"][0]
    op, _rec = proj.add_operation("pocket2d", "Pocket text", lib.assemblies_for_tool(tool.id)[0].id,
                                  tool.presets[0].id, base=[(obj, [])],
                                  params={"StartDepth": 0.0, "FinalDepth": -1.0, "StepDown": 1.0})
    h["run_command"](scenario, "CAM2027_Compute")

    def xs(op):
        return [c.Parameters["X"] for c in op.Path.Commands if "X" in c.Parameters and c.Name == "G1"]

    before = max(xs(op) or [0.0])
    FreeCADGui.Selection.clearSelection()
    FreeCADGui.Selection.addSelection(obj)
    h["driver"].handlers[tr("Text")] = lambda dlg: text(dlg, "ABH", 34.0)
    h["run_command"](scenario, "CAM2027_EditVector")
    proj = h["project"]()
    op = proj.doc.getObject(op.Name)
    after = xs(op)
    h_left = obj.Shape.BoundBox.XMax - 20.0
    state = proj.operation_state(op)
    log("  text %r, pocket X max %.1f -> %.1f (H from X %.1f), state %s, faces %d" % (
        obj.Text, before, max(after or [0.0]), h_left, state, len(op.Base[0][1])))
    if obj.Text != "ABH" or not any(x > h_left for x in after):
        problem(scenario, "pocket not recomputed on the edited text (new letter not cleared)")
    if state in ("failed", "todo"):
        problem(scenario, "pocket state after the text edit: %s" % state)
    # double-clic dans l'arborescence : même dialogue, texte déplacé
    def move(dlg):
        dlg.x.setValue(40.0)
        return True

    h["driver"].handlers[tr("Text")] = move
    vobj = obj.ViewObject
    if vobj is None or not hasattr(vobj.Proxy, "doubleClicked"):
        problem(scenario, "text has no view provider for the double-click")
    else:
        vobj.Proxy.doubleClicked(vobj)
        h["pump"](0.2)
        moved = xs(proj.doc.getObject(op.Name))
        log("  after double-click: text X %.1f, pocket X min %.1f" % (obj.X, min(moved or [0.0])))
        if abs(obj.X - 40.0) > 1e-9 or min(moved or [0.0]) < 40.0:
            problem(scenario, "double-click edit did not move the text and its pocket")

    def poly(dlg):
        f = dlg.fields
        f["X"].setValue(140.0), f["Y"].setValue(25.0), f["Radius"].setValue(15.0), f["Sides"].setValue(6)
        return True

    h["driver"].handlers[tr("Polygon")] = poly
    FreeCADGui.Selection.clearSelection()
    h["run_command"](scenario, "CAM2027_DrawPolygon")
    polys = [o for o in proj.doc.Objects if vecmod.is_parametric(o) and o.VectorKind == "polygon"]
    if len(polys) != 1:
        problem(scenario, "polygon not created")
        return
    FreeCADGui.Selection.clearSelection()
    FreeCADGui.Selection.addSelection(polys[0])

    def nodes(dlg):
        seen["nodes"] = dlg.table.rowCount()
        dlg.table.selectRow(0)
        dlg.delete_selected()
        return True

    h["driver"].handlers[tr("Edit nodes")] = nodes
    h["run_command"](scenario, "CAM2027_EditNodes")
    p = polys[0]
    log("  polygon nodes %s -> %s (%s), text dialogs (edit?) %s" % (seen.get("nodes"), len(getattr(p, "Points", [])),
                                                                     p.VectorKind, seen.get("text_dialogs")))
    if seen.get("nodes") != 6 or p.VectorKind != "polyline" or len(p.Points) != 5:
        problem(scenario, "node deletion failed")
    if seen.get("text_dialogs") != [False, True]:
        problem(scenario, "text dialog not reopened for editing: %s" % seen.get("text_dialogs"))
    FreeCAD.closeDocument(proj.doc.Name)
    h["pump"](0.3)


def scenario_nesting(h, scenario, tmp):
    """Imbriquer par le dialogue : latte 100 x 20 « fil le long de Y » (3 copies), cadre et insert gardés ensemble
    (même nom de groupe) : lattes debout (90 / 270°), insert toujours dans la fenêtre du cadre ; le message cite le
    groupe ; réglages gardés sur les dessins."""
    import Part
    from cam2027.project import nesting

    tr, log, problem = h["tr"], h["log"], h["problem"]
    proj = h["new_project"](scenario, "Nesting")
    V = FreeCAD.Vector

    def rect(x0, y0, w, hh):
        return Part.makePolygon([V(x0, y0, 0), V(x0 + w, y0, 0), V(x0 + w, y0 + hh, 0), V(x0, y0 + hh, 0), V(x0, y0, 0)])

    shapes = {"Lath": [rect(0, 0, 100, 20)], "Frame": [rect(0, 0, 60, 60), rect(15, 15, 30, 30)],
              "Insert": [rect(20, 20, 20, 20)]}
    objs = {}
    for name, wires in shapes.items():
        o = proj.doc.addObject("Part::Feature", name)
        o.Shape = Part.Compound(wires)
        objs[name] = o
    proj.doc.recompute()

    def nest(dlg):
        for r, obj in enumerate(dlg.objects):
            if obj.Name == "Lath":
                dlg.table.cellWidget(r, 2).setValue(3)
                h["combo_select"](dlg.table.cellWidget(r, 3), "y")
            elif obj.Name in ("Frame", "Insert"):
                dlg.table.cellWidget(r, 4).setText("inlay")
        dlg.width.setValue(300.0)
        dlg.length.setValue(250.0)
        return True

    h["driver"].handlers[tr("Nest parts on a sheet")] = nest
    msgs = h["run_command"](scenario, "CAM2027_Nest")
    text = " | ".join(t for _k, t in msgs)
    proj = h["project"]()
    laths = [o for o in proj.doc.Objects if o.Name.startswith("Lath") and getattr(o, "Shape", None)]
    standing = [round(o.Shape.BoundBox.YLength, 3) for o in laths]
    frame, insert = proj.doc.getObject("Frame"), proj.doc.getObject("Insert")
    hole = [w for w in frame.Shape.Wires if abs(Part.Face(w).Area - 900.0) < 1e-6][0]
    inside = Part.Face(hole).common(Part.Face(insert.Shape.Wires[0])).Area
    log("  laths %d, heights %s, insert inside the window %.1f mm2, grain property %r" % (
        len(laths), standing, inside, getattr(objs["Lath"], nesting.GRAIN_PROPERTY, None)))
    if len(laths) != 3 or any(abs(v - 100.0) > 1e-3 for v in standing):
        problem(scenario, "laths not nested along the grain (standing): %s" % standing)
    if abs(inside - 400.0) > 1e-3:
        problem(scenario, "insert not kept in the frame window (%.1f mm2 inside)" % inside)
    if tr("Kept together: {parts}", parts="Frame + Insert") not in text:
        problem(scenario, "nesting message does not list the group: %s" % text[:300])
    if getattr(proj.doc.getObject("Frame"), nesting.GROUP_PROPERTY, "") != "inlay":
        problem(scenario, "group not stored on the drawing")
    FreeCAD.closeDocument(proj.doc.Name)
    h["pump"](0.3)


def scenarios(h, files, tmp):
    """(nom, fonction) des scénarios C4, dans l'ordre."""
    h = dict(h)
    from PySide import QtWidgets

    h["QtWidgets"] = QtWidgets
    h["qt_dispose"] = __import__("cam2027.gui.qt", fromlist=["dispose"]).dispose
    return (
        ("c4-rotary-radial", lambda: scenario_rotary_radial(h, "c4-rotary-radial", tmp)),
        ("c4-vectors", lambda: scenario_vectors(h, "c4-vectors", tmp)),
        ("c4-nesting", lambda: scenario_nesting(h, "c4-nesting", tmp)),
    )
