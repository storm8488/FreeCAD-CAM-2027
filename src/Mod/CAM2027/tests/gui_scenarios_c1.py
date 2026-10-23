# SPDX-License-Identifier: LGPL-2.1-or-later
"""Scénarios d'interface du flux C1 du jour 4 (bugs connus), appelés par ``gui_scenarios.py``.

Les aides du pilote (``run_command``, ``project``, ``problem``...) sont passées par ``h`` (globals du script
principal) : ce module ne lance rien à l'import.
"""

import os


def _project_with(h, scenario, name, path):
    """Nouveau projet, pièce ``path`` importée, brut par défaut : comme l'utilisateur."""
    h["new_project"](scenario, name)
    h["driver"].open_files.append(path)
    h["run_command"](scenario, "CAM2027_ImportModel")
    h["run_command"](scenario, "CAM2027_StockFixture")
    h["FreeCADGui"].Selection.clearSelection()
    return h["project"]()


def _add(h, scenario, strategy):
    """Ajouter une opération (stratégie ``strategy``, outil proposé, pièce entière) ; messages affichés."""
    h["FreeCADGui"].Selection.clearSelection()
    h["driver"].handlers[h["tr"]("Add operation")] = lambda dlg: (
        h["combo_select"](h["find_combo_with"](dlg, strategy), strategy), True)[1]
    msgs = h["run_command"](scenario, "CAM2027_AddOperation")
    h["accept_open_editors"](scenario)
    return msgs


def scenario_dogbone_editor(h, scenario, files):
    """Éditeur d'une adaptative : pas de case « Dogbones » (l'ajout est toujours refusé) ; elle reste pour un
    contour et une poche."""
    import FreeCAD
    from cam2027.gui import opeditor

    proj = _project_with(h, scenario, "C1 dogbones", files["step"])
    for k in ("adaptive", "pocket", "profile"):
        _add(h, scenario, k)
    proj = h["project"]()
    seen = {}
    for op in proj.operations():
        base = proj.base_operation(op)
        ed = opeditor.open_editor(proj, base)
        h["pump"](0.3)
        seen.setdefault(ed.kind, "dogbone" in ed.dressup_boxes)
        ed.done(0)
        h["pump"](0.2)
    if seen != {"adaptive": False, "pocket": True, "profile": True}:
        h["problem"](scenario, "Dogbones box offered for %s" % seen)
    h["log"]("  dogbones box per strategy: %s" % seen)
    FreeCAD.closeDocument(proj.doc.Name)
    h["pump"](0.3)


def _double_click(h, proj, obj):
    """Double-clic dans l'arbre (``setEdit``) : page de tâches ouverte ? Puis Annuler."""
    import FreeCADGui

    gdoc = FreeCADGui.getDocument(proj.doc.Name)
    FreeCADGui.Control.closeDialog()
    gdoc.setEdit(obj.Name)
    h["pump"](0.3)
    opened = FreeCADGui.Control.activeDialog()
    FreeCADGui.Control.closeDialog()
    try:
        gdoc.resetEdit()
    except Exception:
        pass
    if proj.doc.HasPendingTransaction:
        proj.doc.abortTransaction()
    h["pump"](0.2)
    return bool(opened)


def scenario_leads_task_page(h, scenario, files, tmp):
    """Contour + entrée / sortie cochées dans l'éditeur : l'habillage a son fournisseur de vue (double-clic =
    page de tâches de FreeCAD), aucune page ouverte d'office à la création, et de même après réouverture."""
    import FreeCAD
    from cam2027.gui import opeditor
    from cam2027.project import dressups as dressupmod
    from cam2027.project.project import Project

    proj = _project_with(h, scenario, "C1 leads", files["step"])
    _add(h, scenario, "profile")
    proj = h["project"]()
    op = proj.base_operation(proj.operations()[0])
    ed = opeditor.open_editor(proj, op)
    h["pump"](0.3)
    box, _widgets = ed.dressup_boxes["leads"]
    box.setChecked(True)
    if not ed.apply():
        h["problem"](scenario, "editor apply with leads failed: %s" % ed.status.text())
    ed.accept()
    h["pump"](0.3)
    stray = h["FreeCADGui"].Control.activeDialog()
    top = proj.dressups(op)[0]
    if dressupmod.dressup_kind(top) != "leads":
        h["problem"](scenario, "leads not on top: %s" % [d.Name for d in proj.dressups(op)])
        return
    vp = getattr(top.ViewObject, "Proxy", None)
    first = _double_click(h, proj, top)
    path = os.path.join(tmp, "%s.FCStd" % scenario)
    proj.doc.saveAs(path)
    name = top.Name
    FreeCAD.closeDocument(proj.doc.Name)
    h["pump"](0.3)
    doc = FreeCAD.openDocument(path)
    h["FreeCADGui"].ActiveDocument = h["FreeCADGui"].getDocument(doc.Name)
    h["pump"](0.5)
    proj = Project.from_document(doc)
    again = _double_click(h, proj, doc.getObject(name))
    h["log"]("  leads view provider %s, task page at creation %s, double-click %s, after reopening %s"
             % (type(vp).__name__, bool(stray), first, again))
    if vp is None or not first or not again or stray:
        h["problem"](scenario, "leads dressup: view provider %s, task page opened at creation %s, double-click %s, "
                               "after reopening %s" % (type(vp).__name__, bool(stray), first, again))
    FreeCAD.closeDocument(doc.Name)
    h["pump"](0.3)


def scenario_helix_message(h, scenario, tmp):
    """Hélice sur une plaque aux trous de 2 mm, outil proposé : le message dit que les trous sont plus petits que
    la fraise et donne le plus grand (avant : « aucun parcours sur la pièce entière »)."""
    import FreeCAD
    import Part

    plate = Part.makeBox(60, 40, 10)
    for i in range(3):
        plate = plate.cut(Part.makeCylinder(1.0, 12, FreeCAD.Vector(10 + 15 * i, 20, -1)))
    path = os.path.join(tmp, "small-holes.step")
    plate.exportStep(path)
    proj = _project_with(h, scenario, "C1 helix", path)
    msgs = _add(h, scenario, "helix")
    texts = [t for _k, t in msgs]
    wanted = h["tr"]("The holes of the part are smaller than the {d} mm tool (largest: {fit} mm): choose a smaller tool.",
                     d="X", fit="2").split("X")[0]
    if proj.operations() or not any(t.startswith(wanted) and "2 mm" in t for t in texts):
        h["problem"](scenario, "helix refusal message: %s, operations %s" % (texts, [o.Label for o in proj.operations()]))
    h["log"]("  helix messages: %s" % [t[:140] for t in texts])
    FreeCAD.closeDocument(proj.doc.Name)
    h["pump"](0.3)


def scenarios(h, files, tmp):
    """(nom, fonction) des scénarios C1, dans l'ordre."""
    return (
        ("c1-dogbone-editor", lambda: scenario_dogbone_editor(h, "c1-dogbone-editor", files)),
        ("c1-leads-task-page", lambda: scenario_leads_task_page(h, "c1-leads-task-page", files, tmp)),
        ("c1-helix-message", lambda: scenario_helix_message(h, "c1-helix-message", tmp)),
    )
