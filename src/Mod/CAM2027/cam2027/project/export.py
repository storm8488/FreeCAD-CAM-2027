# SPDX-License-Identifier: LGPL-2.1-or-later
"""Export G-code, analyse du résultat et fiche de préparation.

L'export passe par ``Path.Post.Processor.PostProcessorFactory`` (les mêmes
postprocesseurs que l'atelier CAM de FreeCAD). Avant écriture, le G-code est
analysé : unités, codes utilisés, axes, repères, enveloppe XYZ. Les contrôles
qui dépendent de données machine inconnues sont signalés « non vérifiable ».

Aucune transmission à CNCjs n'est faite ici : l'utilisateur charge le fichier
lui-même.
"""

import datetime
import os
import re

from .. import compat

_WORD = re.compile(r"([A-Za-z])\s*([-+]?\d*\.?\d+)")

# codes acceptés par défaut pour un contrôleur GRBL (v1.1)
GRBL_ALLOWED = {
    "G0", "G1", "G2", "G3", "G4", "G10", "G17", "G18", "G19", "G20", "G21", "G28", "G30", "G38.2", "G38.3",
    "G38.4", "G38.5", "G40", "G43.1", "G49", "G53", "G54", "G55", "G56", "G57", "G58", "G59", "G61", "G80",
    "G90", "G91", "G91.1", "G92", "G92.1", "G93", "G94",
    "M0", "M1", "M2", "M30", "M3", "M4", "M5", "M7", "M8", "M9", "M56",
}
ALLOWED_BY_CONTROLLER = {"grbl": GRBL_ALLOWED}


def available_postprocessors():
    import Path.Preferences

    return sorted(Path.Preferences.allAvailablePostProcessors())


def postprocess(job, post_name=None, post_args=None):
    """Retourne la liste ``[(nom_section, gcode), ...]`` produite par le postprocesseur."""
    from Path.Post.Processor import PostProcessorFactory

    if post_name:
        job.PostProcessor = post_name
    if post_args is not None:
        job.PostProcessorArgs = post_args
    if not job.PostProcessor:
        raise ValueError("aucun postprocesseur sélectionné")
    processor = PostProcessorFactory.get_post_processor(job, job.PostProcessor)
    if processor is None:
        raise ValueError("postprocesseur introuvable : %s" % job.PostProcessor)
    sections = processor.export()
    out = []
    for name, gcode in sections:
        if not isinstance(gcode, str):
            gcode = str(gcode)
        out.append((name, gcode))
    return out


def write_gcode(sections, path):
    """Écrit les sections dans ``path`` (plusieurs sections -> suffixes)."""
    written = []
    if len(sections) == 1:
        with open(path, "w", encoding="utf-8", newline="\n") as fp:
            fp.write(sections[0][1])
        written.append(path)
    else:
        root, ext = os.path.splitext(path)
        for idx, (name, gcode) in enumerate(sections):
            safe = re.sub(r"[^A-Za-z0-9_-]+", "_", str(name)) or str(idx)
            p = "%s-%s%s" % (root, safe, ext)
            with open(p, "w", encoding="utf-8", newline="\n") as fp:
                fp.write(gcode)
            written.append(p)
    return written


def analyze_gcode(text):
    """Analyse statique d'un G-code : codes, axes, unités, repères, enveloppe, lignes."""
    codes = set()
    axes = set()
    bbox = {}
    units = None
    fixtures = set()
    lines = 0
    tool_changes = 0
    max_feed = 0.0
    spindle = set()
    for raw in text.splitlines():
        line = raw.split(";")[0]
        line = re.sub(r"\(.*?\)", "", line).strip()
        if not line:
            continue
        lines += 1
        for letter, number in _WORD.findall(line):
            letter = letter.upper()
            if letter in ("G", "M"):
                code = letter + (number.rstrip("0").rstrip(".") if "." in number else str(int(float(number))))
                codes.add(code)
                if code == "G20":
                    units = "inch"
                elif code == "G21":
                    units = "mm"
                elif code in ("G54", "G55", "G56", "G57", "G58", "G59"):
                    fixtures.add(code)
                elif code == "M6":
                    tool_changes += 1
            elif letter in ("X", "Y", "Z", "A", "B", "C"):
                axes.add(letter)
                v = float(number)
                lo, hi = bbox.get(letter, (v, v))
                bbox[letter] = (min(lo, v), max(hi, v))
            elif letter == "F":
                max_feed = max(max_feed, float(number))
            elif letter == "S":
                spindle.add(float(number))
    return {
        "lines": lines,
        "codes": sorted(codes),
        "axes": sorted(axes),
        "units": units,
        "fixtures": sorted(fixtures),
        "bbox": bbox,
        "tool_changes": tool_changes,
        "max_feed": max_feed,
        "spindle_speeds": sorted(spindle),
    }


def verify(analysis, machine, stock_bounds=None):
    """Compare l'analyse au profil machine. Retourne une liste de (niveau, message).

    niveau : ``"error"``, ``"warning"`` ou ``"unverifiable"``.
    """
    issues = []
    if analysis["units"] != "mm":
        issues.append(("error", "G-code units are not millimetres (no G21 found)" if analysis["units"] is None
                       else "G-code units are inches (G20)"))
    allowed = ALLOWED_BY_CONTROLLER.get(machine.controller)
    if allowed is None:
        issues.append(("unverifiable", "controller %r: no allowed-code list, commands not checked" % machine.controller))
    else:
        bad = [c for c in analysis["codes"] if c not in allowed]
        if bad:
            issues.append(("error", "commands not supported by %s: %s" % (machine.controller, ", ".join(bad))))
    rot = [a for a in analysis["axes"] if a in ("A", "B", "C")]
    if rot and not machine.rotary.present:
        issues.append(("error", "rotary axis words %s present but the machine has no rotary axis" % ", ".join(rot)))
    if "B" in rot or "C" in rot:
        issues.append(("error", "B/C words present: only A (about X) is supported"))
    for axis, attr in (("X", "travel_x_mm"), ("Y", "travel_y_mm"), ("Z", "travel_z_mm")):
        travel = getattr(machine, attr)
        span = analysis["bbox"].get(axis)
        if span is None:
            continue
        if travel is None:
            issues.append(("unverifiable", "%s travel unknown: envelope %.2f..%.2f mm not checked" % (axis, span[0], span[1])))
        elif span[1] - span[0] > travel + 1e-6:
            issues.append(("error", "%s envelope (%.2f mm) exceeds travel (%.2f mm)" % (axis, span[1] - span[0], travel)))
    if machine.max_feed_xy_mm_min is None:
        issues.append(("unverifiable", "max feed unknown: F%.0f not checked" % analysis["max_feed"]))
    elif analysis["max_feed"] > machine.max_feed_xy_mm_min:
        issues.append(("error", "feed F%.0f exceeds machine maximum %.0f" % (analysis["max_feed"], machine.max_feed_xy_mm_min)))
    if analysis["spindle_speeds"]:
        smax = max(analysis["spindle_speeds"])
        smin = min(s for s in analysis["spindle_speeds"] if s > 0) if any(s > 0 for s in analysis["spindle_speeds"]) else 0
        if machine.spindle_max_rpm is None or machine.spindle_min_rpm is None:
            issues.append(("unverifiable", "spindle range unknown: S%.0f..S%.0f not checked" % (smin, smax)))
        else:
            if smax > machine.spindle_max_rpm:
                issues.append(("error", "spindle S%.0f above maximum %.0f" % (smax, machine.spindle_max_rpm)))
            if 0 < smin < machine.spindle_min_rpm:
                issues.append(("error", "spindle S%.0f below minimum %.0f" % (smin, machine.spindle_min_rpm)))
    if stock_bounds is not None:
        z = analysis["bbox"].get("Z")
        if z is not None and z[0] < stock_bounds["zmin"] - 1e-6:
            issues.append(("warning", "Z goes %.2f mm below the stock bottom" % (stock_bounds["zmin"] - z[0])))
    if not analysis["fixtures"]:
        issues.append(("warning", "no work coordinate system (G54...) in the output"))
    return issues


def prep_sheet(project, sections, analysis, issues, out_paths):
    """Fiche de préparation (Markdown) : outils, brut, origine, post, contrôles."""
    job = project.job
    lib = project.library
    lines = []
    lines.append("# Setup sheet — %s" % project.doc.Label)
    lines.append("")
    lines.append("- Date: %s" % datetime.datetime.now().replace(microsecond=0).isoformat())
    lines.append("- CAM2027 %s on FreeCAD %s" % (project.app_version, compat.freecad_version_string()))
    lines.append("- Machine: %s (controller: %s)" % (project.machine.name, project.machine.controller))
    lines.append("- Post processor: %s %s" % (job.PostProcessor, job.PostProcessorArgs))
    lines.append("- Output: %s" % ", ".join(out_paths))
    lines.append("- Work coordinate systems: %s" % ", ".join(job.Fixtures))
    sb = project.stock_bounds()
    lines.append("- Stock: %.2f x %.2f x %.2f mm, X %.2f..%.2f, Y %.2f..%.2f, Z %.2f..%.2f"
                 % (sb["length"], sb["width"], sb["height"], sb["xmin"], sb["xmax"], sb["ymin"], sb["ymax"],
                    sb["zmin"], sb["zmax"]))
    lines.append("")
    lines.append("## Tools")
    lines.append("")
    lines.append("| T | Assembly | Tool | Type | D (mm) | Flutes | Stickout (mm) | Holder | Change |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    seen = set()
    for op_name, rec in sorted(project.registry.items(), key=lambda kv: kv[1].get("order", 0)):
        asm = lib.assembly(rec["assembly_id"])
        if asm.id in seen:
            continue
        seen.add(asm.id)
        tool = lib.tool(asm.tool_id)
        holder = lib.holder(asm.holder_id).name if asm.holder_id else "-"
        lines.append("| %d | %s | %s | %s | %.3f | %d | %.1f | %s | %s |" % (
            asm.output.tool_number, asm.name, tool.name, tool.type_label(), tool.geometry.diameter,
            tool.flute_count, asm.stickout or 0.0, holder, "manual" if asm.output.manual_tool_change else "auto"))
    lines.append("")
    lines.append("## Operations")
    lines.append("")
    lines.append("| # | Operation | Strategy | T | Preset | Spindle (rpm) | Feed (mm/min) | Plunge (mm/min) |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for idx, (op_name, rec) in enumerate(sorted(project.registry.items(), key=lambda kv: kv[1].get("order", 0)), 1):
        asm = lib.assembly(rec["assembly_id"])
        v = rec["values"]
        lines.append("| %d | %s | %s | %d | %s | %.0f | %.0f | %.0f |" % (
            idx, rec.get("label", op_name), rec["kind"], asm.output.tool_number, v["preset_name"],
            v["spindle_rpm"], v["feed_mm_min"], v["plunge_feed_mm_min"]))
    lines.append("")
    lines.append("## G-code analysis")
    lines.append("")
    lines.append("- Lines: %d, units: %s, axes: %s" % (analysis["lines"], analysis["units"], " ".join(analysis["axes"])))
    lines.append("- Codes: %s" % " ".join(analysis["codes"]))
    for axis in ("X", "Y", "Z", "A"):
        if axis in analysis["bbox"]:
            lo, hi = analysis["bbox"][axis]
            lines.append("- %s: %.3f .. %.3f" % (axis, lo, hi))
    lines.append("- Max feed: F%.0f, spindle: %s, tool changes (M6): %d" % (
        analysis["max_feed"], ", ".join("S%.0f" % s for s in analysis["spindle_speeds"]), analysis["tool_changes"]))
    lines.append("")
    lines.append("## Checks")
    lines.append("")
    if not issues:
        lines.append("- no issue found (checks limited to the items listed in the documentation)")
    for level, msg in issues:
        lines.append("- [%s] %s" % (level.upper(), msg))
    lines.append("")
    missing = project.machine.unknown_fields()
    if missing:
        lines.append("Machine data still to fill in: %s" % ", ".join(missing))
    lines.append("")
    return "\n".join(lines)
