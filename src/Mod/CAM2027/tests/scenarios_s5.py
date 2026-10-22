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


def scenario_vectors(gs, scenario):
    """Texte sur un arc (dialogue Texte), décalage de 2 mm (dialogue), panneau, poche 2D sur le décalage ;
    miroir, copies circulaires et union par leurs dialogues."""
    proj = gs.new_project(scenario, "Drawing")
    if proj is None:
        return

    def text(dlg):
        dlg.text.setText("CAM 27")
        gs.combo_select(dlg.layout_kind, "arc")
        dlg.radius.setValue(35.0)
        dlg.span.setValue(160.0)
        dlg.size.setValue(10.0)
        return True

    gs.driver.handlers[gs.tr("Text")] = text
    gs.run_command(scenario, "CAM2027_DrawText")
    proj = gs.project()
    texts = [o for o in proj.doc.Objects if o.Label == "CAM 27"]
    if not texts:
        gs.problem(scenario, "no text vector created by the Text dialog")
        return
    FreeCADGui.Selection.clearSelection()
    FreeCADGui.Selection.addSelection(texts[0])

    def offset(dlg):
        dlg.distance.setValue(2.0)
        return True

    gs.driver.handlers[gs.tr("Offset vector")] = offset
    gs.run_command(scenario, "CAM2027_OffsetVector")
    grown = [o for o in proj.doc.Objects if o.Label.startswith("CAM 27") and o.Label != "CAM 27"]
    if not grown:
        gs.problem(scenario, "no offset vector created")
        return
    for name, title in (("CAM2027_MirrorVector", "Mirror vector"), ("CAM2027_CircularCopies", "Circular copies"),
                        ("CAM2027_CombineVectors", "Combine vectors")):
        FreeCADGui.Selection.clearSelection()
        FreeCADGui.Selection.addSelection(grown[0])
        FreeCADGui.Selection.addSelection(texts[0])  # union : le décalage et le texte
        gs.driver.handlers[gs.tr(title)] = lambda dlg: True
        before = len(proj.doc.Objects)
        msgs = gs.run_command(scenario, name)
        if msgs or len(proj.doc.Objects) <= before:
            gs.problem(scenario, "%s created nothing: %s" % (name, msgs))
    # le panneau et la poche : seulement le texte et son décalage
    for o in list(proj.doc.Objects):
        if o not in (texts[0], grown[0]) and o.TypeId == "Part::Feature" and o.Name.startswith("Vector"):
            proj.doc.removeObject(o.Name)

    def sheet(dlg):
        gs.combo_select(gs.find_combo_with(dlg, "sheet"), "sheet")
        return True

    gs.driver.handlers[gs.tr("Stock & fixture")] = sheet
    gs.run_command(scenario, "CAM2027_StockFixture")
    proj = gs.project()
    if not proj.has_job:
        gs.problem(scenario, "sheet job not created under the drawn text")
        return
    FreeCADGui.Selection.clearSelection()
    FreeCADGui.Selection.addSelection(grown[0])
    gs.driver.handlers[gs.tr("Add operation")] = lambda dlg: (gs.combo_select(gs.find_combo_with(dlg, "pocket2d"), "pocket2d"), True)[1]
    gs.run_command(scenario, "CAM2027_AddOperation")
    gs.accept_open_editors(scenario)
    gs.run_command(scenario, "CAM2027_Compute")
    proj = gs.project()
    states = [(o.Label, proj.operation_state(o), len(proj.base_operation(o).Base[0][1])) for o in proj.operations()]
    gs.log("  pocket on the offset text: %s" % states)
    if len(states) != 1 or states[0][1] != "computed":
        gs.problem(scenario, "pocket 2D on the offset text not computed: %s" % states)
    FreeCAD.closeDocument(proj.doc.Name)
    gs.pump(0.3)


def scenario_bitmap(gs, scenario, tmp):
    """Vectoriser une image (dialogue), panneau, poche 2D sur le tracé, puis Photo V-Carve d'un dégradé."""
    import math

    from tests.test_nuit_s5 import write_image

    logo = write_image(os.path.join(tmp, "s5_logo.png"), 100, 60, lambda i, j: 0.0 if 8.0 <= math.hypot(i - 30, j - 30) <= 20.0
                       or (65 <= i <= 85 and 20 <= j <= 40) else 1.0)
    photo = write_image(os.path.join(tmp, "s5_photo.png"), 121, 81,
                        lambda i, j: 0.5 + 0.5 * math.cos(math.hypot(i - 60, j - 40) / 8.0))
    proj = gs.new_project(scenario, "Bitmap")
    if proj is None:
        return

    def trace(dlg):
        dlg.width.setValue(99.0)
        return True

    gs.driver.open_files.append(logo)
    gs.driver.handlers[gs.tr("Trace bitmap")] = trace
    gs.run_command(scenario, "CAM2027_TraceBitmap")
    proj = gs.project()
    traced = [o for o in proj.doc.Objects if o.Label == "s5_logo"]
    if not traced:
        gs.problem(scenario, "Trace bitmap created no vector")
        return

    def sheet(dlg):
        gs.combo_select(gs.find_combo_with(dlg, "sheet"), "sheet")
        return True

    gs.driver.handlers[gs.tr("Stock & fixture")] = sheet
    gs.run_command(scenario, "CAM2027_StockFixture")
    proj = gs.project()
    if not proj.has_job:
        gs.problem(scenario, "sheet job not created under the traced image")
        return
    FreeCADGui.Selection.clearSelection()
    FreeCADGui.Selection.addSelection(traced[0])
    gs.driver.handlers[gs.tr("Add operation")] = lambda dlg: (gs.combo_select(gs.find_combo_with(dlg, "pocket2d"), "pocket2d"), True)[1]
    gs.run_command(scenario, "CAM2027_AddOperation")
    gs.accept_open_editors(scenario)

    def photo_dlg(dlg):
        dlg.width.setValue(60.0)
        dlg.depth.setValue(1.5)
        return True

    gs.driver.open_files.append(photo)
    gs.driver.handlers[gs.tr("Photo V-carve")] = photo_dlg
    gs.run_command(scenario, "CAM2027_PhotoVCarve")
    gs.run_command(scenario, "CAM2027_Compute")
    proj = gs.project()
    states = [(o.Label, proj.operation_state(o), len(o.Path.Commands)) for o in proj.operations()]
    gs.log("  traced pocket and photo V-carve: %s" % states)
    if len(states) != 2:
        gs.problem(scenario, "2 operations expected (pocket on the trace, photo V-carve), got %s" % states)
    for label, st, n in states:
        if st != "computed" or n < 10:
            gs.problem(scenario, "operation %s is %s (%d moves)" % (label, st, n))
    FreeCAD.closeDocument(proj.doc.Name)
    gs.pump(0.3)


def scenario_setup_pdf(gs, scenario, files, tmp):
    """Panneau, contour, fiche de préparation en PDF par la commande ; le PDF est relu (en-tête, pages, temps)."""
    import re

    proj = _sheet_project(gs, scenario, "Setup PDF", files["svg"])
    if proj is None:
        return
    from cam2027.project import sheet as sheetmod

    rect = [v for v in sheetmod.vector_objects(proj.doc) if len(v.Shape.Edges) == 4]
    FreeCADGui.Selection.clearSelection()
    FreeCADGui.Selection.addSelection(rect[0])
    gs.driver.handlers[gs.tr("Add operation")] = lambda dlg: (gs.combo_select(gs.find_combo_with(dlg, "profile"), "profile"), True)[1]
    gs.run_command(scenario, "CAM2027_AddOperation")
    gs.accept_open_editors(scenario)
    gs.run_command(scenario, "CAM2027_Compute")
    out = os.path.join(tmp, "setup sheet.pdf")
    gs.driver.save_files.append(out)
    gs.run_command(scenario, "CAM2027_SetupSheetPdf")
    if not os.path.isfile(out):
        gs.problem(scenario, "setup sheet PDF not written")
        return
    with open(out, "rb") as fp:
        data = fp.read()
    pages = len(re.findall(rb"/Type\s*/Page[^s]", data))
    gs.log("  setup sheet PDF: %d bytes, %d page(s)" % (len(data), pages))
    if not data.startswith(b"%PDF") or pages < 1 or len(data) < 2000:
        gs.problem(scenario, "setup sheet PDF unreadable (%d bytes, %d pages)" % (len(data), pages))
    FreeCAD.closeDocument(proj.doc.Name)
    gs.pump(0.3)


def entries(gs, files, tmp):
    """(nom, fonction) des scénarios S5 pour la boucle de ``gui_scenarios.main``."""
    return (
        ("s5-templates", lambda: scenario_templates(gs, "s5-templates", tmp)),
        ("s5-vectors", lambda: scenario_vectors(gs, "s5-vectors")),
        ("s5-bitmap", lambda: scenario_bitmap(gs, "s5-bitmap", tmp)),
        ("s5-setup-pdf", lambda: scenario_setup_pdf(gs, "s5-setup-pdf", files, tmp)),
    )
