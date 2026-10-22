# SPDX-License-Identifier: LGPL-2.1-or-later
"""Scénarios d'interface du flux B4 (jour 3), lancés par ``gui_scenarios.py`` : dialogues touchés par les
correctifs, pilotés comme un utilisateur (commande du menu, dialogue rempli, résultat vérifié)."""

import os

#: chauffage Vz330 de l'utilisateur (assemblage de deux corps) ; scénario sauté s'il est absent
HEATER = os.path.join(os.path.expanduser("~"), "Downloads", "Vz330 Concept Chamber Heater v1.step")


def scenario_holes_bodies(h, scenario, tmp):
    """Chauffage Vz330 (deux corps) : Usiner > Perçage intelligent perce tous ses trous sans entaille ni rapide dans
    la matière (avant : 2,3 mm d'entaille sur les entretoises, prises pour des trous Ø10). L'import de l'interface
    donne un modèle (composé des deux corps) ; si le job en a deux (import par l'API), les trous des deux corps et
    les trous couverts (message) sont vérifiés aussi."""
    import FreeCAD
    from cam2027.gui import holes as holesgui

    if not os.path.isfile(HEATER):
        h["log"]("  skipped: %s not found" % HEATER)
        return
    tr = h["tr"]
    proj = h["new_project"](scenario, "Holes bodies")
    h["driver"].open_files.append(HEATER)
    h["run_command"](scenario, "CAM2027_ImportModel")
    h["run_command"](scenario, "CAM2027_StockFixture")
    proj = h["project"]()
    models = len(proj.job.Model.Group)  # interface : un modèle (composé des deux corps) ; API : deux
    seen = {}

    def accept(dlg):
        if not isinstance(dlg, holesgui.HoleDialog):
            return False
        seen["bodies"] = sorted(set(getattr(getattr(hh, "obj", None), "Name", "?") for hh in dlg.holes))
        seen["holes"] = len(dlg.holes)
        seen["covered"] = len(getattr(dlg, "covered", []))
        seen["status"] = dlg.status.text()
        return True

    h["driver"].handlers[tr("Hole recognition and drilling")] = accept
    msgs = h["run_command"](scenario, "CAM2027_Holes")
    if seen.get("holes", 0) < 16 or (models == 2 and (len(seen.get("bodies", [])) != 2 or not seen.get("covered")
                                                      or str(seen.get("covered")) not in seen.get("status", ""))):
        h["problem"](scenario, "%d model(s): %s holes on bodies %s, covered %s, dialog status %r" % (
            models, seen.get("holes"), seen.get("bodies"), seen.get("covered"), seen.get("status")))
    ops = proj.operations()
    states = [proj.operation_state(o) for o in ops]
    if not ops or any(s in ("failed", "todo") for s in states):
        h["problem"](scenario, "operations %s states %s" % ([o.Label for o in ops], states))
    rep = proj.material_check()
    if rep["gouge_max"] > 0.0 or rep["rapid_hits"]:
        h["problem"](scenario, "gouge %.3f at %s, rapid hits %d" % (rep["gouge_max"], rep["gouge_at"], rep["rapid_hits"]))
    h["log"]("  heater holes ok: %d model(s), %d holes on %s, %d covered, %d operations, gouge %.3f, messages %s" % (
        models, seen.get("holes", 0), seen.get("bodies"), seen.get("covered", 0), len(ops), rep["gouge_max"],
        [t[:100] for _k, t in msgs]))
    FreeCAD.closeDocument(proj.doc.Name)
    h["pump"](0.3)


def scenario_probe_inner(h, scenario, files):
    """Usiner > Palper l'origine, « coin intérieur » arrière droit : coin choisi dans le dialogue, aperçu à deux
    G38.2 (X et Y, pas de Z), opération de palpage en tête du programme."""
    import FreeCAD
    from cam2027.gui import probe as probegui
    from cam2027.project import probe as probemod

    tr = h["tr"]
    proj = h["new_project"](scenario, "Probe inner")
    h["driver"].open_files.append(files["step"])
    h["run_command"](scenario, "CAM2027_ImportModel")
    h["run_command"](scenario, "CAM2027_StockFixture")
    proj = h["project"]()
    seen = {}

    def fill(dlg):
        if not isinstance(dlg, probegui.ProbeDialog):
            return False
        dlg.tip.setValue(2.0)
        h["combo_select"](dlg.mode, "inner_corner")
        h["combo_select"](dlg.corner, "back-right")
        seen["corner_enabled"] = dlg.corner.isEnabled()
        seen["preview"] = dlg.preview.toPlainText()
        dlg.grab().save(os.path.join(h["OUT"], "dialogs", "probe-inner-corner.png"))
        return True

    h["driver"].handlers[tr("Probe the origin")] = fill
    msgs = h["run_command"](scenario, "CAM2027_Probe")
    lines = seen.get("preview", "").splitlines()
    probes = [l for l in lines if l.startswith("G38.2")]
    if not seen.get("corner_enabled") or len(probes) != 2 or any("Z" in l for l in probes):
        h["problem"](scenario, "inner corner preview: corner enabled %s, probing lines %s" % (seen.get("corner_enabled"), probes))
    ops = proj.operations()
    if not ops or not probemod.is_probe_op(ops[0]) or "inner" not in proj.registry[ops[0].Name]["params"].get("mode", ""):
        h["problem"](scenario, "probe operation: %s" % [(o.Name, proj.registry.get(o.Name, {}).get("params")) for o in ops])
    h["log"]("  inner corner probe ok: %s, messages %s" % (probes, [t[:100] for _k, t in msgs]))
    FreeCAD.closeDocument(proj.doc.Name)
    h["pump"](0.3)


def scenarios(h, files, tmp):
    """(nom, fonction) des scénarios B4, dans l'ordre."""
    return (
        ("b4-holes-bodies", lambda: scenario_holes_bodies(h, "b4-holes-bodies", tmp)),
        ("b4-probe-inner", lambda: scenario_probe_inner(h, "b4-probe-inner", files)),
    )
