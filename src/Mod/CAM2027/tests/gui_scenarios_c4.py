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


def scenarios(h, files, tmp):
    """(nom, fonction) des scénarios C4, dans l'ordre."""
    h = dict(h)
    from PySide import QtWidgets

    h["QtWidgets"] = QtWidgets
    h["qt_dispose"] = __import__("cam2027.gui.qt", fromlist=["dispose"]).dispose
    return (
        ("c4-rotary-radial", lambda: scenario_rotary_radial(h, "c4-rotary-radial", tmp)),
    )
