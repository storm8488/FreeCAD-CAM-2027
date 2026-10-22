# SPDX-License-Identifier: LGPL-2.1-or-later
"""Scénarios d'interface du flux S5 (nuit 2), lancés par ``gui_scenarios.py`` avec ses aides (``gs``)."""

import os

import FreeCAD
import FreeCADGui


def _sheet_project(gs, scenario, name, svg):
    proj = gs.new_project(scenario, name)
    gs.driver.open_files.append(svg)
    gs.run_command(scenario, "CAM2027_ImportModel")

    def sheet(dlg):
        gs.combo_select(gs.find_combo_with(dlg, "sheet"), "sheet")
        return True

    gs.driver.handlers[gs.tr("Stock & fixture")] = sheet
    gs.run_command(scenario, "CAM2027_StockFixture")
    proj = gs.project()
    if proj is None or not proj.has_job:
        gs.problem(scenario, "sheet job not created for %s" % name)
        return None
    return proj


def scenario_templates(gs, scenario, tmp):
    """Découpe + poche + V-carve par « Ajouter une opération », modèle enregistré, appliqué à un 2e SVG."""
    from tests.test_nuit_s5 import SVG_A, SVG_B

    paths = {}
    for key, text in (("a", SVG_A), ("b", SVG_B)):
        paths[key] = os.path.join(tmp, "tpl_%s.svg" % key)
        with open(paths[key], "w", encoding="utf-8") as fp:
            fp.write(text)
    proj = _sheet_project(gs, scenario, "Template A", paths["a"])
    if proj is None:
        return
    doc = proj.doc
    for vec, strategy in (("outline", "profile"), ("hole", "pocket2d"), ("star_w", "vcarve")):
        obj = doc.getObject(vec) or doc.getObject(vec.replace("_w", ""))
        FreeCADGui.Selection.clearSelection()
        FreeCADGui.Selection.addSelection(obj)
        gs.driver.handlers[gs.tr("Add operation")] = lambda dlg, s=strategy: (gs.combo_select(gs.find_combo_with(dlg, s), s), True)[1]
        gs.run_command(scenario, "CAM2027_AddOperation")
        gs.accept_open_editors(scenario)
    if len(gs.project().operations()) != 3:
        gs.problem(scenario, "3 operations expected on drawing A, got %d" % len(gs.project().operations()))
        return
    out = os.path.join(tmp, "sign.cam2027template")
    gs.driver.save_files.append(out)
    gs.run_command(scenario, "CAM2027_SaveTemplate")
    if not os.path.isfile(out):
        gs.problem(scenario, "template file not written")
        return
    FreeCAD.closeDocument(doc.Name)
    gs.pump(0.3)
    proj = _sheet_project(gs, scenario, "Template B", paths["b"])
    if proj is None:
        return
    gs.driver.open_files.append(out)
    gs.run_command(scenario, "CAM2027_ApplyTemplate")
    proj = gs.project()
    states = [(o.Label, proj.operation_state(o)) for o in proj.operations()]
    gs.log("  template applied: %s" % states)
    if len(states) != 3:
        gs.problem(scenario, "3 operations expected from the template, got %d" % len(states))
    for label, st in states:
        if st != "computed":
            gs.problem(scenario, "operation %s is %s after applying the template" % (label, st))
    FreeCAD.closeDocument(proj.doc.Name)
    gs.pump(0.3)


def entries(gs, files, tmp):
    """(nom, fonction) des scénarios S5 pour la boucle de ``gui_scenarios.main``."""
    return (
        ("s5-templates", lambda: scenario_templates(gs, "s5-templates", tmp)),
    )
