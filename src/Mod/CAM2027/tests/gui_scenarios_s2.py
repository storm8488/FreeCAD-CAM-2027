# SPDX-License-Identifier: LGPL-2.1-or-later
"""Scénarios d'interface du flux S2 (entrées/sorties, motifs, perçage, palpage), appelés par ``gui_scenarios.py``.

Les aides du pilote (``run_command``, ``project``, ``problem``...) sont passées par ``h`` (globals du script
principal) : ce module ne lance rien à l'import.
"""

import math
import os


def scenario_leads(h, scenario, files):
    """Contour de la pièce, onglet « Entrée, sortie et attaches » : arc d'entrée de R3 coché et appliqué comme un
    utilisateur, premier mouvement de coupe en arc, contrôle matière sans entaille."""
    import FreeCAD
    from PySide import QtWidgets
    from cam2027.gui import opeditor
    from cam2027.project import dressups as dressupmod

    tr = h["tr"]
    proj = h["new_project"](scenario, "Leads")
    h["driver"].open_files.append(files["step"])
    h["run_command"](scenario, "CAM2027_ImportModel")
    h["run_command"](scenario, "CAM2027_StockFixture")
    h["FreeCADGui"].Selection.clearSelection()
    h["driver"].handlers[tr("Add operation")] = lambda dlg: (
        h["combo_select"](h["find_combo_with"](dlg, "profile"), "profile"), True)[1]
    h["run_command"](scenario, "CAM2027_AddOperation")
    h["accept_open_editors"](scenario)
    proj = h["project"]()
    op = proj.base_operation(proj.operations()[0])
    ed = opeditor.open_editor(proj, op)
    h["pump"](0.3)
    if "leads" not in ed.dressup_boxes:
        h["problem"](scenario, "no lead-in/lead-out box in the editor of a contour")
        ed.done(0)
        return
    box, widgets = ed.dressup_boxes["leads"]
    if box.title() != tr("Lead-in and lead-out"):
        h["problem"](scenario, "lead box title %r" % box.title())
    box.setChecked(True)
    widgets["RadiusIn"][1].setValue(3.0)
    widgets["RadiusOut"][1].setValue(3.0)
    ed.tabs.setCurrentIndex(ed.tabs.count() - 1)
    area = ed.tabs.currentWidget()
    if isinstance(area, QtWidgets.QScrollArea):
        area.ensureWidgetVisible(box)
    h["pump"](0.2)
    ed.grab().save(os.path.join(h["OUT"], "dialogs", "editor-leads.png"))
    if not ed.apply():
        h["problem"](scenario, "editor apply with leads failed: %s" % ed.status.text())
    ed.accept()
    h["pump"](0.2)
    chain = proj.dressups(op)
    kinds = [dressupmod.dressup_kind(d) for d in chain]
    if kinds[:1] != ["leads"]:
        h["problem"](scenario, "leads dressup not on top of the contour: %s" % kinds)
        return
    from cam2027.project import leads

    first = leads._moves(chain[0].Path.Commands)[:1]
    if not first or first[0][0] not in ("G2", "G3") or abs(math.dist(first[0][1][:2], first[0][3]) - 3.0) > 1e-3:
        h["problem"](scenario, "first cutting move is not a R3 arc: %s" % (first,))
    msgs = h["run_command"](scenario, "CAM2027_MaterialCheck")
    rep = getattr(proj, "last_material_report", None)
    gouge = rep.get("gouge_max") if isinstance(rep, dict) else None
    if gouge is None:
        gouge = proj.material_check()["gouge_max"]
    if gouge > 0.0:
        h["problem"](scenario, "leads gouge the part: %.3f mm" % gouge)
    h["log"]("  leads ok: %s, gouge %.3f, messages %s" % (chain[0].Label, gouge, [t[:80] for _k, t in msgs]))
    FreeCAD.closeDocument(proj.doc.Name)
    h["pump"](0.3)


def scenario_pattern(h, scenario, files):
    """Plateau de 6 alvéoles : poche de la première sélectionnée dans la vue, Usiner > Motif en grille 3 x 2 (pas
    28 / 26) rempli dans le dialogue ; les 6 alvéoles usinées dans la carte de hauteur, aucune entaille."""
    import FreeCAD
    from PySide import QtWidgets
    from cam2027.project import dressups as dressupmod, patterns as patmod
    from cam2027.gui import patterns as patgui

    tr = h["tr"]
    proj = h["new_project"](scenario, "Pattern")
    h["driver"].open_files.append(files["step"])
    h["run_command"](scenario, "CAM2027_ImportModel")
    h["run_command"](scenario, "CAM2027_StockFixture")
    proj = h["project"]()
    clone = proj.job.Model.Group[0]
    floor = None
    for i, f in enumerate(clone.Shape.Faces, 1):
        bb = f.BoundBox
        if f.Surface.__class__.__name__ == "Plane" and abs(bb.ZMax - 4.0) < 1e-6 and abs(bb.XMin - 6.0) < 1e-6 \
                and abs(bb.YMin - 6.0) < 1e-6:
            floor = "Face%d" % i
    gui = h["FreeCADGui"]
    gui.Selection.clearSelection()
    gui.Selection.addSelection(proj.doc.Name, clone.Name, floor)
    h["driver"].handlers[tr("Add operation")] = lambda dlg: (
        h["combo_select"](h["find_combo_with"](dlg, "pocket"), "pocket"), True)[1]
    h["run_command"](scenario, "CAM2027_AddOperation")
    h["accept_open_editors"](scenario)
    ops = proj.operations()
    if len(ops) != 1:
        h["problem"](scenario, "expected one pocket, got %s" % [o.Label for o in ops])
        return
    op = proj.base_operation(ops[0])
    gui.Selection.clearSelection()
    gui.Selection.addSelection(op)

    def fill(dlg):
        if not isinstance(dlg, patgui.PatternDialog):
            return False
        if dlg.checked_operations() != [op]:
            h["problem"](scenario, "selected operation not checked in the pattern dialog")
        h["combo_select"](dlg.kind, "Grid")
        dlg.columns.setValue(3)
        dlg.rows.setValue(2)
        dlg.step_x.setValue(28.0)
        dlg.step_y.setValue(26.0)
        dlg.grab().save(os.path.join(h["OUT"], "dialogs", "pattern-filled.png"))
        return True

    h["driver"].handlers[tr("Toolpath pattern")] = fill
    msgs = h["run_command"](scenario, "CAM2027_Pattern")
    tops = proj.operations()
    if len(tops) != 1 or dressupmod.dressup_kind(tops[0]) != "pattern":
        h["problem"](scenario, "pattern not on top of the pocket: %s" % [o.Name for o in tops])
        return
    if not any(k == "info" and tr("{n} operation(s) repeated; tool changes: {t}.", n=1, t=0) in t for k, t in msgs):
        h["problem"](scenario, "no pattern confirmation: %s" % msgs)
    rep = proj.material_check()
    z = proj.last_zmap
    floors = [float(z.top[int((6 + i * 28 + 12 - z.x0) / z.res), int((6 + j * 26 + 11 - z.y0) / z.res)])
              for j in range(2) for i in range(3)]
    if rep["gouge_max"] > 0.0 or any(abs(f - 4.0) > 0.02 for f in floors):
        h["problem"](scenario, "pattern: gouge %.3f, floors %s" % (rep["gouge_max"], floors))
    h["log"]("  pattern ok: %s, floors %s, gouge %.3f, tool changes %d" % (tops[0].Label, floors, rep["gouge_max"],
                                                                         patmod.tool_changes(proj)))
    FreeCAD.closeDocument(proj.doc.Name)
    h["pump"](0.3)


def scenario_holes(h, scenario, tmp):
    """Plaque à 3 tailles de trous : Usiner > Perçage intelligent avec la bibliothèque de démarrage (foret de 3,
    fraises de 3 et 6, outil en V à 90°) ; une opération par étape et par taille, trous usinés dans la carte de
    hauteur, aucune entaille."""
    import FreeCAD
    from cam2027.gui import holes as holesgui
    from tests.test_nuit_s2 import HOLES, make_hole_plate

    tr = h["tr"]
    step = os.path.join(tmp, "holes.step")
    make_hole_plate(step)
    proj = h["new_project"](scenario, "Holes")
    h["driver"].open_files.append(step)
    h["run_command"](scenario, "CAM2027_ImportModel")
    h["run_command"](scenario, "CAM2027_StockFixture")
    proj = h["project"]()
    seen = {}

    def accept(dlg):
        if not isinstance(dlg, holesgui.HoleDialog):
            return False
        seen["groups"] = dlg.table.rowCount()
        seen["preview"] = [dlg.preview.item(i).text() for i in range(dlg.preview.count())]
        return True

    h["driver"].handlers[tr("Hole recognition and drilling")] = accept
    msgs = h["run_command"](scenario, "CAM2027_Holes")
    if seen.get("groups") != 3:
        h["problem"](scenario, "hole groups in the dialog: %s" % seen.get("groups"))
    ops = proj.operations()
    labels = [proj.base_operation(o).Label for o in ops]
    if len(ops) != len(seen.get("preview", [])) or len(ops) < 5:
        h["problem"](scenario, "operations %s for preview %s" % (labels, seen.get("preview")))
    states = [proj.operation_state(o) for o in ops]
    if any(s in ("failed", "todo") for s in states):
        h["problem"](scenario, "states %s" % states)
    rep = proj.material_check()
    z = proj.last_zmap
    deep = []
    for d, pts in HOLES.items():
        for x, y in pts:
            deep.append(round(float(z.top[int((x - z.x0) / z.res), int((y - z.y0) / z.res)]), 2))
    if rep["gouge_max"] > 0.0 or max(deep) > 4.3:
        h["problem"](scenario, "holes: gouge %.3f, centre heights %s" % (rep["gouge_max"], deep))
    h["log"]("  holes ok: %s, centre heights %s, gouge %.3f, messages %s" % (labels, deep, rep["gouge_max"],
                                                                             [t[:120] for _k, t in msgs]))
    FreeCAD.closeDocument(proj.doc.Name)
    h["pump"](0.3)


def scenarios(h, files, tmp):
    """(nom, fonction) des scénarios S2, dans l'ordre."""
    return (
        ("s2-leads", lambda: scenario_leads(h, "s2-leads", files)),
        ("s2-pattern", lambda: scenario_pattern(h, "s2-pattern", files)),
        ("s2-holes", lambda: scenario_holes(h, "s2-holes", tmp)),
    )
