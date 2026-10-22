# SPDX-License-Identifier: LGPL-2.1-or-later
"""Scénarios d'interface du flux B5 (jour 3 : entrées / sorties et outils), appelés par ``gui_scenarios.py``.

Les aides du pilote (``run_command``, ``project``, ``problem``...) sont passées par ``h`` (globals du script
principal) : ce module ne lance rien à l'import.
"""

import os


def scenario_export_two_tools(h, scenario, files, tmp):
    """Deux opérations, deux outils, export par la commande « Exporter » comme un utilisateur : le fichier écrit
    s'arrête (M5 puis M0) entre les deux outils, la fiche liste les deux outils, aucun commentaire imbriqué."""
    tr = h["tr"]
    proj = h["new_project"](scenario, "Two tools")
    h["driver"].open_files.append(files["step"])
    h["run_command"](scenario, "CAM2027_ImportModel")
    h["run_command"](scenario, "CAM2027_StockFixture")
    proj = h["project"]()
    if proj is None or not proj.has_job:
        h["problem"](scenario, "no job")
        return
    clone = proj.job.Model.Group[0]
    lib = proj.library
    for name, label, depth in (("3 mm flat end mill", "Small contour", 6.0), ("6 mm flat end mill", "Big contour", 0.0)):
        t = [t for t in lib.search(name) if t.tool_type == "endmill"][0]
        asm = lib.assemblies_for_tool(t.id)[0]
        proj.add_operation("profile", label, asm.id, t.presets[0].id, base=[(clone, [])],
                           params={"FinalDepth": depth, "StepDown": 6.0, "Side": "Outside"})
    proj.duplicate_operation(proj.operations()[-1])  # « Big contour (copy) » : parenthèses dans le libellé
    h["run_command"](scenario, "CAM2027_Compute")
    h["run_command"](scenario, "CAM2027_MaterialCheck")
    out = os.path.join(tmp, "%s.nc" % scenario)
    h["driver"].handlers[tr("Export G-code")] = lambda dlg: h["_export"](dlg, out)
    msgs = h["run_command"](scenario, "CAM2027_Export")
    if not os.path.isfile(out):
        h["problem"](scenario, "export wrote no file: %s" % [t[:200] for _k, t in msgs])
        return
    with open(out, encoding="utf-8") as fp:
        text = fp.read()
    lines = [l.strip() for l in text.splitlines()]
    stops = [i for i, l in enumerate(lines) if l == "M0"]
    h["log"]("  %d lines, %d stop(s) M0" % (len(lines), len(stops)))
    if len(stops) != 1 or lines[stops[0] - 2] != "M5":
        h["problem"](scenario, "expected one M5 / M0 stop between the two tools, got %s" % stops)
    nested = [l for l in lines if l.startswith("(") and "(" in l[1:-1]]
    if nested:
        h["problem"](scenario, "nested comment(s) in the G-code: %s" % nested[:3])
    sheet = os.path.splitext(out)[0] + "-setup.md"
    if not os.path.isfile(sheet):
        h["problem"](scenario, "no setup sheet")
    else:
        with open(sheet, encoding="utf-8") as fp:
            tools = fp.read().split("## Tools")[1].split("## Operations")[0]
        if "3 mm flat end mill" not in tools or "6 mm flat end mill" not in tools:
            h["problem"](scenario, "setup sheet tools: %s" % tools.strip()[:300])
    h["FreeCAD"].closeDocument(proj.doc.Name)
    h["pump"](0.3)


def scenario_fusion_twice(h, scenario):
    """Bibliothèque d'outils > Importer Fusion..., deux fois le même export réel (profil temporaire) : la seconde
    fois rien n'est ajouté et le rapport le dit ; aucun numéro d'outil en double."""
    from cam2027.gui import panels, state

    fixture = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "fusion-library-lunyee.tools")
    dock = panels.show_tool_library()
    p = dock.widget()
    lib = state.library()
    counts = []
    texts = []

    def grab_report(dlg):
        texts.append(dlg.text())
        return True

    for _i in range(2):
        h["driver"].open_files.append(fixture)
        h["driver"].handlers[h["tr"]("Fusion import report")] = grab_report
        try:
            p.import_fusion()
        except Exception:
            import traceback

            h["problem"](scenario, "import_fusion raised:\n%s" % traceback.format_exc())
        h["pump"](0.2)
        counts.append(len(lib.tools))
    h["log"]("  tools after each import %s, reports %s" % (counts, texts))
    if len(counts) == 2 and counts[1] != counts[0]:
        h["problem"](scenario, "second import of the same file added %d tool(s)" % (counts[1] - counts[0]))
    numbers = [a.output.tool_number for a in lib.assemblies.values()]
    if len(numbers) != len(set(numbers)):
        h["problem"](scenario, "duplicate tool numbers after the Fusion import: %s" % sorted(numbers))
    if len(texts) == 2 and h["tr"]("Imported {n} tool(s), skipped {s} (details below).", n=0, s=11) != texts[1]:
        h["problem"](scenario, "second report %r" % texts[1])
    h["driver"].take()
    dock.hide()


def scenarios(h, files, tmp):
    """(nom, fonction) des scénarios B5, dans l'ordre."""
    return (
        ("b5-export-two-tools", lambda: scenario_export_two_tools(h, "b5-export-two-tools", files, tmp)),
        ("b5-fusion-twice", lambda: scenario_fusion_twice(h, "b5-fusion-twice")),
    )
