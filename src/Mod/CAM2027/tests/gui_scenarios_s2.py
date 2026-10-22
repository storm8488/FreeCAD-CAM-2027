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


def scenarios(h, files, tmp):
    """(nom, fonction) des scénarios S2, dans l'ordre."""
    return (
        ("s2-leads", lambda: scenario_leads(h, "s2-leads", files)),
    )
