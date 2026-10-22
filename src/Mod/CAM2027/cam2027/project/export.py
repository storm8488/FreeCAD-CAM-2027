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
import contextlib
import os
import re

from .. import compat
from ..i18n import Msg

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


#: saut de A maximal dans un seul mouvement de coupe (l'enroulement découpe à 2°)
MAX_A_STEP_DEG = 45.0


@contextlib.contextmanager
def _identity_placement_passthrough():
    """FreeCAD 1.0 : ``PathUtils.getPathWithPlacement`` passe chaque commande dans ``Command.transform``,
    qui recompose A avec la rotation du placement et le replie dans ±180° même pour un placement
    neutre (A200 devient A-160 : la pièce tournerait de presque un tour pendant une coupe enroulée).
    FreeCAD 1.1 rend le parcours tel quel quand le placement est neutre ; même règle ici, seulement
    pendant l'appel au postprocesseur (aucun fichier FreeCAD modifié)."""
    try:
        from PathScripts import PathUtils
    except ImportError:  # pragma: no cover
        yield
        return
    original = PathUtils.getPathWithPlacement

    def passthrough(pathobj):
        placement = getattr(pathobj, "Placement", None)
        if pathobj.Path is not None and placement is not None and placement.isIdentity():
            return pathobj.Path
        return original(pathobj)

    PathUtils.getPathWithPlacement = passthrough
    try:
        yield
    finally:
        PathUtils.getPathWithPlacement = original


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
    with _identity_placement_passthrough():
        sections = processor.export()
    out = []
    for name, gcode in sections:
        if not isinstance(gcode, str):
            gcode = str(gcode)
        out.append((name, tool_change_stops(gcode)[0]))
    return out


#: M6 mis en commentaire par le postprocesseur ``grbl`` (GRBL 1.1 refuse M6 : error:20)
_COMMENTED_M6 = re.compile(r"^\s*(?:N\d+\s+)?\(\s*M0?6\s+T(\d+)\s*\)\s*$", re.IGNORECASE)


def tool_change_stops(gcode):
    """Changement d'outil manuel : le postprocesseur ``grbl`` met M6 en commentaire et le programme enchaînait
    l'opération suivante avec l'outil précédent (fraise plus grosse = entaille). Chaque M6 commenté qui change
    de numéro d'outil devient broche arrêtée (M5) + pause (M0, reprise par Départ cycle ; CNCjs suspend aussi
    l'envoi) ; le premier outil est celui de la fiche. Retourne ``(gcode, nombre de pauses)``."""
    out, stops, current = [], 0, None
    for line in gcode.splitlines(True):
        m = _COMMENTED_M6.match(line)
        if m is None:
            out.append(line)
            continue
        number = int(m.group(1))
        out.append(line)
        if current is not None and number != current:
            out.append("M5\n(Tool change: load T%d, then resume)\nM0\n" % number)
            stops += 1
        current = number
    return "".join(out), stops


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
    pauses = 0  # M0 (changements d'outil manuels)
    max_feed = 0.0
    spindle = set()
    motion = None  # mode de déplacement modal (G0 / G1 / G2 / G3)
    a_feed_lines = 0  # lignes où A change pendant un mouvement de coupe hors G93 (avance ambiguë)
    a_positions = []  # valeurs successives de A (positionnements)
    inverse_time = False  # G93 actif (4e axe continu : F = 1 / durée du mouvement en minutes)
    a_wrap_lines = 0  # coupes avec A en G93 (enroulement)
    g93_missing_f = 0  # mouvements de coupe en G93 sans mot F (interdit : F n'est pas modal en G93)
    g93_arcs = 0  # arcs en G93 (non produits par CAM2027, non contrôlés)
    max_a_rate = 0.0  # vitesse angulaire maximale de A en G93 (deg/min)
    max_a_step = 0.0  # plus grand changement de A dans un seul mouvement de coupe (deg)
    a_current = None
    for raw in text.splitlines():
        line = raw.split(";")[0]
        line = re.sub(r"\(.*?\)", "", line).strip()
        if not line:
            continue
        lines += 1
        words = _WORD.findall(line)
        for letter, number in words:
            if letter.upper() == "G":
                g = str(int(float(number))) if float(number).is_integer() else number
                if g in ("0", "1", "2", "3"):
                    motion = "G" + g
                elif g == "93":
                    inverse_time = True
                elif g == "94":
                    inverse_time = False
        has_axis = any(letter.upper() in "XYZABC" for letter, _n in words)
        f_words = [float(n) for letter, n in words if letter.upper() == "F"]
        if inverse_time and motion in ("G1", "G2", "G3") and has_axis:
            if not f_words:
                g93_missing_f += 1
            if motion in ("G2", "G3"):
                g93_arcs += 1
        if any(letter.upper() == "A" for letter, _n in words):
            a_value = [float(n) for letter, n in words if letter.upper() == "A"][-1]
            if motion in ("G1", "G2", "G3"):
                if a_current is not None:
                    max_a_step = max(max_a_step, abs(a_value - a_current))
                if inverse_time:
                    a_wrap_lines += 1
                    if a_current is not None and f_words:
                        max_a_rate = max(max_a_rate, abs(a_value - a_current) * f_words[-1])
                else:
                    a_feed_lines += 1
            else:
                a_positions.append(a_value)
            a_current = a_value
        for letter, number in words:
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
                elif code == "M0":
                    pauses += 1
            elif letter in ("X", "Y", "Z", "A", "B", "C"):
                axes.add(letter)
                v = float(number)
                lo, hi = bbox.get(letter, (v, v))
                bbox[letter] = (min(lo, v), max(hi, v))
            elif letter == "F" and not inverse_time:  # en G93, F n'est pas une vitesse en mm/min
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
        "pauses": pauses,
        "max_feed": max_feed,
        "spindle_speeds": sorted(spindle),
        "a_feed_lines": a_feed_lines,
        "a_positions": a_positions,
        "a_wrap_lines": a_wrap_lines,
        "g93_missing_f": g93_missing_f,
        "g93_arcs": g93_arcs,
        "max_a_rate": max_a_rate,
        "max_a_step": max_a_step,
        "ends_in_g93": inverse_time,
        "probe": __import__("cam2027.project.probe", fromlist=["analyze"]).analyze(text),
    }


def verify(analysis, machine, stock_bounds=None):
    """Compare l'analyse au profil machine. Retourne une liste de (niveau, message).

    niveau : ``"error"``, ``"warning"`` ou ``"unverifiable"`` ; message : ``Msg`` (anglais, traduit à l'affichage).
    """
    issues = []
    if analysis["units"] != "mm":
        issues.append(("error", Msg("G-code units are not millimetres (no G21 found)") if analysis["units"] is None
                       else Msg("G-code units are inches (G20)")))
    allowed = ALLOWED_BY_CONTROLLER.get(machine.controller)
    if allowed is None:
        issues.append(("unverifiable", Msg("controller {c!r}: no allowed-code list, commands not checked",
                                           c=machine.controller)))
    else:
        bad = [c for c in analysis["codes"] if c not in allowed]
        if bad:
            issues.append(("error", Msg("commands not supported by {c}: {codes}", c=machine.controller,
                                        codes=", ".join(bad))))
    rot = [a for a in analysis["axes"] if a in ("A", "B", "C")]
    if rot and not machine.rotary.present:
        issues.append(("error", Msg("rotary axis words {words} present but the machine has no rotary axis",
                                    words=", ".join(rot))))
    if "B" in rot or "C" in rot:
        issues.append(("error", Msg("B/C words present: only A (about X) is supported")))
    if "A" in rot and machine.rotary.present:
        issues.extend(_verify_rotary(analysis, machine))
    if analysis.get("g93_missing_f"):
        issues.append(("error", Msg("{n} inverse-time (G93) move(s) without an F word", n=analysis["g93_missing_f"])))
    if analysis.get("g93_arcs"):
        issues.append(("error", Msg("{n} arc(s) in inverse-time mode (G93): not checked, not supported",
                                    n=analysis["g93_arcs"])))
    if analysis.get("ends_in_g93"):
        issues.append(("error", Msg("the program ends in inverse-time mode (G93): G94 missing")))
    for axis, attr in (("X", "travel_x_mm"), ("Y", "travel_y_mm"), ("Z", "travel_z_mm")):
        travel = getattr(machine, attr)
        span = analysis["bbox"].get(axis)
        if span is None:
            continue
        if travel is None:
            issues.append(("unverifiable", Msg("{axis} travel unknown: envelope {lo:.2f}..{hi:.2f} mm not checked",
                                               axis=axis, lo=span[0], hi=span[1])))
        elif span[1] - span[0] > travel + 1e-6:
            issues.append(("error", Msg("{axis} envelope ({size:.2f} mm) exceeds travel ({travel:.2f} mm)",
                                        axis=axis, size=span[1] - span[0], travel=travel)))
    if machine.max_feed_xy_mm_min is None:
        issues.append(("unverifiable", Msg("max feed unknown: F{f:.0f} not checked", f=analysis["max_feed"])))
    elif analysis["max_feed"] > machine.max_feed_xy_mm_min:
        issues.append(("error", Msg("feed F{f:.0f} exceeds machine maximum {m:.0f}", f=analysis["max_feed"],
                                    m=machine.max_feed_xy_mm_min)))
    if analysis["spindle_speeds"]:
        smax = max(analysis["spindle_speeds"])
        smin = min(s for s in analysis["spindle_speeds"] if s > 0) if any(s > 0 for s in analysis["spindle_speeds"]) else 0
        if machine.spindle_max_rpm is None or machine.spindle_min_rpm is None:
            issues.append(("unverifiable", Msg("spindle range unknown: S{lo:.0f}..S{hi:.0f} not checked", lo=smin, hi=smax)))
        else:
            if smax > machine.spindle_max_rpm:
                issues.append(("error", Msg("spindle S{s:.0f} above maximum {m:.0f}", s=smax, m=machine.spindle_max_rpm)))
            if 0 < smin < machine.spindle_min_rpm:
                issues.append(("error", Msg("spindle S{s:.0f} below minimum {m:.0f}", s=smin, m=machine.spindle_min_rpm)))
    if stock_bounds is not None:
        z = analysis["bbox"].get("Z")
        if z is not None and z[0] < stock_bounds["zmin"] - 1e-6:
            issues.append(("warning", Msg("Z goes {d:.2f} mm below the stock bottom", d=stock_bounds["zmin"] - z[0])))
    if not analysis["fixtures"]:
        issues.append(("warning", Msg("no work coordinate system (G54...) in the output")))
    from . import probe as probemod

    issues.extend(probemod.verify(analysis, machine))
    return issues


def _verify_rotary(analysis, machine):
    """Contrôles 4e axe : A en rapide (3+1) ou en coupe seulement en temps inverse G93 (continu), plage,
    vitesse angulaire, firmware."""
    rot = machine.rotary
    issues = []
    if rot.about != "X":
        issues.append(("error", Msg("rotary axis declared about {a}: only A about X is supported", a=rot.about)))
    if analysis.get("a_feed_lines"):
        issues.append(("error", Msg("A changes during {n} cutting move(s) outside inverse-time mode (G93): the feed of a simultaneous X/Z/A move is ambiguous",
                                    n=analysis["a_feed_lines"])))
    if analysis.get("max_a_step", 0.0) > MAX_A_STEP_DEG:
        issues.append(("error", Msg("A jumps by {d:.1f} deg in a single cutting move: the part would spin during the cut",
                                    d=analysis["max_a_step"])))
    if analysis.get("a_wrap_lines"):
        if rot.max_feed_deg_min is None:
            issues.append(("unverifiable", Msg("A axis max feed unknown: rotation up to {r:.0f} deg/min not checked",
                                               r=analysis["max_a_rate"])))
        elif analysis["max_a_rate"] > rot.max_feed_deg_min + 1e-6:
            issues.append(("error", Msg("A rotation {r:.0f} deg/min exceeds the A axis maximum {m:.0f} deg/min",
                                        r=analysis["max_a_rate"], m=rot.max_feed_deg_min)))
    lo, hi = analysis["bbox"].get("A", (None, None))
    if rot.min_deg is None or rot.max_deg is None:
        issues.append(("unverifiable", Msg("A range unknown: A{lo:.3f}..A{hi:.3f} not checked", lo=lo, hi=hi)))
    elif lo < rot.min_deg - 1e-6 or hi > rot.max_deg + 1e-6:
        issues.append(("error", Msg("A{lo:.3f}..A{hi:.3f} outside the A range {a:.3f}..{b:.3f} deg", lo=lo, hi=hi,
                                    a=rot.min_deg, b=rot.max_deg)))
    if machine.controller == "grbl":
        issues.append(("warning", Msg("standard GRBL 1.1 has no A axis: a 4-axis firmware (grblHAL, GRBL 4-axis fork) is required")))
    if rot.positive_direction is None:
        issues.append(("unverifiable", Msg("A positive direction not set in the machine profile")))
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
    try:
        lines.extend(timing_lines(project)[0])
    except Exception as exc:  # l'estimation ne bloque jamais l'export
        lines.extend(["## Estimated machining time", "", "- not estimated: %s" % exc, ""])
    lines.append("## G-code analysis")
    lines.append("")
    lines.append("- Lines: %d, units: %s, axes: %s" % (analysis["lines"], analysis["units"], " ".join(analysis["axes"])))
    lines.append("- Codes: %s" % " ".join(analysis["codes"]))
    for axis in ("X", "Y", "Z", "A"):
        if axis in analysis["bbox"]:
            lo, hi = analysis["bbox"][axis]
            lines.append("- %s: %.3f .. %.3f" % (axis, lo, hi))
    lines.append("- Max feed: F%.0f, spindle: %s, tool changes (M6): %d, pauses (M0): %d" % (
        analysis["max_feed"], ", ".join("S%.0f" % s for s in analysis["spindle_speeds"]), analysis["tool_changes"],
        analysis.get("pauses", 0)))
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


def timing_lines(project):
    """Section « temps estimé » de la fiche (accélération du profil machine, voir ``timing``)."""
    from . import timing

    est = timing.estimate(project)
    lines = ["## Estimated machining time", ""]
    lines.append("- Total: %s (feed and rapid moves with acceleration %g mm/s², rapids at %g mm/min; tool changes not counted)"
                 % (timing.format_duration(est["total"]), est["acceleration"], est["rapid"]))
    lines.append("- Without acceleration (length / feed): %s" % timing.format_duration(est["without_accel"]))
    if est["assumed"]:
        lines.append("- Assumed (machine profile to fill in): %s" % ", ".join(est["assumed"]))
    lines.append("")
    lines.append("| Operation | Time |")
    lines.append("|---|---|")
    for label, t in est["operations"]:
        lines.append("| %s | %s |" % (label, timing.format_duration(t)))
    lines.append("")
    return lines, est


def write_pdf(markdown_text, path, title=""):
    """Fiche de préparation en PDF (A4) depuis le texte Markdown de ``prep_sheet`` : ``QTextDocument`` et
    ``QPdfWriter`` de Qt, sans dépendance. Exige une application Qt (interface) ; retourne le chemin."""
    try:
        from PySide6 import QtCore, QtGui
    except ImportError:  # pragma: no cover - FreeCAD 1.0 (Qt 5)
        from PySide2 import QtCore, QtGui
    if QtCore.QCoreApplication.instance() is None or not isinstance(QtCore.QCoreApplication.instance(), QtGui.QGuiApplication):
        raise RuntimeError("PDF setup sheet: a Qt GUI application is required")
    writer = QtGui.QPdfWriter(path)
    writer.setPageSize(QtGui.QPageSize(QtGui.QPageSize.A4))
    writer.setResolution(150)
    writer.setTitle(title or "CAM2027 setup sheet")
    writer.setCreator("CAM2027")
    doc = QtGui.QTextDocument()
    font = doc.defaultFont()
    font.setPointSizeF(9.0)
    doc.setDefaultFont(font)
    doc.setMarkdown(markdown_text)
    # tableaux Markdown : bordures et marges (setMarkdown ne lit pas la feuille de style)
    for frame in doc.rootFrame().childFrames():
        if isinstance(frame, QtGui.QTextTable):
            tf = frame.format()
            tf.setBorder(0.5)
            tf.setCellPadding(3)
            tf.setCellSpacing(0)
            frame.setFormat(tf)
    if hasattr(doc, "print_"):
        doc.print_(writer)
    else:  # pragma: no cover
        doc.print(writer)
    return path


def export_summary(project, analysis, issues):
    """Récapitulatif avant export : liste de ``(libellé, valeur, niveau, paramètres)``.

    Niveau : ``ok`` / ``info`` / ``warning`` / ``unverifiable`` / ``error``. Les libellés sont
    en anglais (traduits par l'interface, ``valeur`` est un gabarit ``str.format`` sur ``paramètres``). Rien n'est présenté comme vérifié s'il ne l'a pas été :
    les contrôles non exécutés gardent leur niveau « non vérifiable ».
    """
    from .operations import COMPUTE_STATES

    job = project.job
    machine = project.machine
    rows = [
        ("Machine", "%s (%s)" % (machine.name, machine.controller), "info"),
        ("Post processor", "%s %s" % (job.PostProcessor, job.PostProcessorArgs or ""), "info"),
        ("Units", analysis.get("units") or "?", "ok" if analysis.get("units") == "mm" else "warning"),
        ("Work offsets", " ".join(analysis.get("fixtures") or []) or "none", "ok" if analysis.get("fixtures") else "warning"),
        ("Axes used", " ".join(analysis.get("axes") or []), "info"),
    ]
    for op in project.operations():
        state = project.operation_state(op)
        label, level = COMPUTE_STATES[state]
        rows.append(("Operation: %s" % op.Label, label, {"ok": "ok", "muted": "info", "todo": "warning",
                                                       "stale": "warning", "warning": "warning",
                                                       "error": "error"}.get(level, "info")))
    counts = {}
    for lvl, _msg in issues:
        counts[lvl] = counts.get(lvl, 0) + 1
    if counts.get("error"):
        rows.append(("Checks", "{n} blocking", "error", {"n": counts["error"]}))
    elif counts.get("unverifiable") or counts.get("warning"):
        rows.append(("Checks", "{w} warning(s), {u} not verifiable", "unverifiable",
                     {"w": counts.get("warning", 0), "u": counts.get("unverifiable", 0)}))
    else:
        rows.append(("Checks", "no issue among the checks performed", "ok"))
    last = project.last_check() if hasattr(project, "last_check") else None
    if last is None or last.get("fingerprint") != project._paths_fingerprint():
        rows.append(("Material and collision check", "not run for these toolpaths (Simulate > Material and collision check)",
                     "unverifiable"))
    elif last["events"] or (last["gouge_max"] > last["tolerance"]):
        rows.append(("Material and collision check", "{n} problem(s) found", "error",
                     {"n": len(last["events"]) + (1 if last["gouge_max"] > last["tolerance"] else 0)}))
    else:
        rows.append(("Material and collision check", "done: no gouge or collision found (height map, 3 axes)", "ok"))
    return [r if len(r) == 4 else r + ({},) for r in rows]
