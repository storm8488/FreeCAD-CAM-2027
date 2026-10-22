# SPDX-License-Identifier: LGPL-2.1-or-later
"""Palpage de l'origine (Fusion *Probe WCS*) : surface Z, coin, centre de trou, en G-code GRBL.

Le programme commence à la position où l'opérateur a amené le palpeur (au-dessus de la pièce, près du coin
pour un coin, dans le trou pour un centre de trou) ; tous les déplacements avant que l'axe soit connu sont
relatifs (G91). Chaque contact (``G38.2``, alarme GRBL si rien n'est touché sur la course) fixe un axe du
repère de travail : ``G10 L20 P<n>`` (repère G54..G59 enregistré) ou ``G92`` (décalage temporaire), en tenant
compte du rayon de la pointe et de l'épaisseur de la plaque de touche. Broche arrêtée (M5) avant de palper.

GRBL n'a ni variables ni calculs : le centre d'un trou ne peut pas être la moyenne de deux contacts. Le centre
est donc fixé par un contact par axe et le diamètre nominal du trou (erreur = moitié de l'écart de diamètre).

Profil machine (``MachineProfile.probe``) : ``present``, ``tip_diameter_mm``, ``plate_thickness_mm``,
``feed_mm_min``, ``travel_mm`` (course de recherche), ``tool_number``. ``verify`` refuse un programme qui
palpe sur un profil sans palpeur, broche en marche ou sans avance.
"""

import re

from ..i18n import Msg, UserError

MODES = ("z", "corner", "hole")
#: coin -> (sens X vers l'extérieur, sens Y vers l'extérieur) ; « front » = Y min, « left » = X min
CORNERS = {"front-left": (-1, -1), "front-right": (1, -1), "back-left": (-1, 1), "back-right": (1, 1)}
WCS = ("G54", "G55", "G56", "G57", "G58", "G59")
DEFAULTS = {"feed_mm_min": 100.0, "travel_mm": 25.0, "plate_thickness_mm": 0.0, "tool_number": 99}
PREFIX = "CAM2027Probe"
KIND = "probe"


class ProbeError(UserError):
    pass


def settings(machine):
    """Réglages du palpeur du profil, complétés des valeurs par défaut ; ``None`` si le profil n'a pas de palpeur."""
    p = dict(getattr(machine, "probe", None) or {})
    if not p.get("present"):
        return None
    for k, v in DEFAULTS.items():
        if p.get(k) is None:
            p[k] = v
    return p


def _f(v):
    return ("%.3f" % v).rstrip("0").rstrip(".") if abs(v) >= 5e-4 else "0"


def probe_gcode(machine, mode, corner="front-left", hole_diameter=None, inset=10.0, clearance=5.0, depth=3.0,
                retract=2.0, wcs="G54", offset_mode="G10"):
    """Lignes de G-code du palpage ``mode`` (« z », « corner », « hole ») ; voir le docstring du module."""
    p = settings(machine)
    if p is None:
        raise ProbeError("The machine profile has no probe: enter the tip diameter in Machining > Probe the origin.")
    if mode not in MODES:
        raise ProbeError("Unknown probing mode: {m}", m=mode)
    if wcs not in WCS:
        raise ProbeError("Unknown work offset: {w}", w=wcs)
    if offset_mode not in ("G10", "G92"):
        raise ProbeError("Unknown offset mode: {m}", m=offset_mode)
    tip = p.get("tip_diameter_mm")
    if mode != "z" and not tip:
        raise ProbeError("Probe tip diameter unknown: enter it in the machine profile.")
    r = 0.5 * float(tip or 0.0)
    feed, travel, plate = float(p["feed_mm_min"]), float(p["travel_mm"]), float(p["plate_thickness_mm"])
    index = WCS.index(wcs) + 1

    def setaxis(axis, value):
        if offset_mode == "G92":
            return "G92 %s%s" % (axis, _f(value))
        return "G10 L20 P%d %s%s" % (index, axis, _f(value))

    out = ["(CAM2027 probe origin: %s%s)" % (mode, " " + corner if mode == "corner" else ""),
           "M5", "G21", "G90", wcs]
    if mode == "z":
        out += ["G91", "G38.2 Z-%s F%s" % (_f(travel), _f(feed)), setaxis("Z", plate), "G0 Z%s" % _f(retract),
                "G90"]
        return out
    if mode == "hole":
        if not hole_diameter or float(hole_diameter) <= 2 * r:
            raise ProbeError("The hole must be wider than the probe tip.")
        half = 0.5 * float(hole_diameter)
        out += ["G91", "G38.2 X%s F%s" % (_f(half + clearance), _f(feed)), setaxis("X", half - r),
                "G90", "G0 X0",
                "G91", "G38.2 Y%s F%s" % (_f(half + clearance), _f(feed)), setaxis("Y", half - r),
                "G90", "G0 X0 Y0"]
        return out
    if corner not in CORNERS:
        raise ProbeError("Unknown corner: {c}", c=corner)
    sx, sy = CORNERS[corner]
    down = retract + depth
    out += ["G91",
            "G38.2 Z-%s F%s" % (_f(travel), _f(feed)), setaxis("Z", plate), "G0 Z%s" % _f(retract),
            # X : hors de la pièce, descente sous le dessus, contact vers la pièce
            "G0 X%s" % _f(sx * (inset + r + clearance)), "G0 Z-%s" % _f(down),
            "G38.2 X%s F%s" % (_f(-sx * (2 * clearance + r)), _f(feed)), setaxis("X", sx * r),
            "G0 X%s" % _f(sx * clearance), "G0 Z%s" % _f(down),
            "G90", "G0 X%s" % _f(-sx * inset),
            "G91",
            "G0 Y%s" % _f(sy * (inset + r + clearance)), "G0 Z-%s" % _f(down),
            "G38.2 Y%s F%s" % (_f(-sy * (2 * clearance + r)), _f(feed)), setaxis("Y", sy * r),
            "G0 Y%s" % _f(sy * clearance), "G0 Z%s" % _f(down),
            "G90", "G0 X0 Y0"]
    return out


# -- vérification à l'export -------------------------------------------------------------------------------

_WORD = re.compile(r"([A-Za-z])\s*([-+]?\d*\.?\d+)")


def analyze(text):
    """Palpages d'un G-code : nombre, sans avance, broche en marche, G10 mal formés, courses (mode relatif)."""
    count = no_feed = spindle_on = bad_g10 = 0
    upper = text.upper()
    if "G38" not in upper and "G10" not in upper:  # programme sans palpage : pas de seconde passe (400 000 lignes : 1 s)
        return {"count": 0, "no_feed": 0, "spindle_on": 0, "bad_g10": 0, "max_travel": 0.0}
    feed = None
    spindle = False
    max_travel = 0.0
    relative = False
    for raw in text.splitlines():
        line = re.sub(r"\(.*?\)", "", raw.split(";")[0]).strip().upper()
        if not line:
            continue
        words = _WORD.findall(line)
        gs = [n for letter, n in words if letter == "G"]
        if "91" in gs:
            relative = True
        if "90" in gs:
            relative = False
        for letter, n in words:
            if letter == "M" and n in ("3", "4", "03", "04"):
                spindle = True
            elif letter == "M" and n in ("5", "05", "2", "30"):
                spindle = False
            elif letter == "F":
                feed = float(n)
        if any(g.startswith("38.") for g in gs):
            count += 1
            if feed is None:
                no_feed += 1
            if spindle:
                spindle_on += 1
            if relative:
                max_travel = max([max_travel] + [abs(float(n)) for letter, n in words if letter in "XYZ"])
        if "10" in gs:
            ls = [float(n) for letter, n in words if letter == "L"]
            ps = [float(n) for letter, n in words if letter == "P"]
            if not ls or ls[0] not in (2.0, 20.0) or not ps or ps[0] not in (1, 2, 3, 4, 5, 6):
                bad_g10 += 1
    return {"count": count, "no_feed": no_feed, "spindle_on": spindle_on, "bad_g10": bad_g10,
            "max_travel": max_travel}


def verify(analysis, machine):
    """Contrôles du palpage (liste de (niveau, message)) ; rien si le programme ne palpe pas."""
    a = analysis.get("probe") or {}
    if not a.get("count"):
        if a.get("bad_g10"):
            return [("error", Msg("{n} G10 line(s) without L2/L20 and P1..P6", n=a["bad_g10"]))]
        return []
    issues = []
    p = settings(machine)
    if p is None:
        issues.append(("error", Msg("{n} probing move(s) (G38.2) but the machine profile has no probe", n=a["count"])))
    else:
        if not p.get("tip_diameter_mm"):
            issues.append(("unverifiable", Msg("probe tip diameter unknown: probed X / Y origins not checked")))
        if a.get("max_travel", 0.0) > float(p["travel_mm"]) + 1e-6:
            issues.append(("warning", Msg("probing move of {d:.1f} mm longer than the probe travel {t:.1f} mm",
                                          d=a["max_travel"], t=float(p["travel_mm"]))))
    if a.get("spindle_on"):
        issues.append(("error", Msg("{n} probing move(s) with the spindle running", n=a["spindle_on"])))
    if a.get("no_feed"):
        issues.append(("error", Msg("{n} probing move(s) without a feed rate", n=a["no_feed"])))
    if a.get("bad_g10"):
        issues.append(("error", Msg("{n} G10 line(s) without L2/L20 and P1..P6", n=a["bad_g10"])))
    return issues


# -- opération dans le projet ------------------------------------------------------------------------------


def is_probe_op(obj):
    return obj.Name.startswith(PREFIX)


def probe_tool(proj):
    """(assemblage, outil, préréglage) du palpeur dans l'instantané du projet, créés au besoin : la fiche de
    préparation et le registre les traitent comme un outil (« Touch probe », T du profil, broche arrêtée)."""
    from . import docobjects
    from ..tools.model import ToolDefinition, ToolAssembly, CuttingPreset

    p = settings(proj.machine)
    tip = float(p.get("tip_diameter_mm") or 2.0)
    number = int(p["tool_number"])
    lib = proj.library
    for asm in lib.assemblies.values():
        tool = lib.tools.get(asm.tool_id)
        if (tool is not None and tool.name == "Touch probe" and asm.output.tool_number == number
                and abs(tool.geometry.diameter - tip) < 1e-6):
            return asm, tool, tool.presets[0]
    tool = lib.add_tool(ToolDefinition("Touch probe", "endmill", dict(diameter=tip, shank_diameter=6.0,
                                                                      overall_length=50.0, flute_length=5.0),
                                       flute_count=1))
    tool.add_preset(CuttingPreset("Probing", usage="general", material="any", spindle_rpm=0,
                                  feed_mm_min=float(p["feed_mm_min"]), plunge_feed_mm_min=float(p["feed_mm_min"])))
    asm = lib.add_assembly(ToolAssembly("T%d Touch probe" % number, tool.id, None, stickout=40.0,
                                        output={"tool_number": number, "manual_tool_change": True}))
    docobjects.ProjectInfo.set_json(proj.info, "LibrarySnapshot", lib.snapshot())
    proj._library = None
    lib = proj.library
    tool = lib.tools[tool.id]
    asm = [a for a in lib.assemblies.values() if a.tool_id == tool.id][0]
    return asm, tool, tool.presets[0]


def add_probe(proj, mode, label=None, **kw):
    """Opération « Palper l'origine » (FreeCAD *Custom*, G-code ci-dessus) placée en tête du programme ;
    contrôleur d'outil du palpeur (numéro du profil, broche arrêtée). Retourne l'opération."""
    import FreeCAD
    import Path.Op.Custom as Custom
    from ..i18n import tr
    from ..tools import bridge
    from . import wrap as wrapmod

    lines = probe_gcode(proj.machine, mode, **kw)
    job = proj.job
    asm, tool, preset = probe_tool(proj)
    values = preset.resolve(tool)
    toolbit, _w = bridge.create_toolbit(proj.doc, tool, label="%s (T%d)" % (tool.name, asm.output.tool_number))
    tc, _ = bridge.create_tool_controller(proj.doc, asm, tool, values, toolbit=toolbit, label="TC: probe")
    tc.SpindleSpeed = 0.0
    if "None" in tc.getEnumerationsOfProperty("SpindleDir"):
        tc.SpindleDir = "None"
    job.Proxy.addToolController(tc)
    previous = FreeCAD.ActiveDocument
    FreeCAD.setActiveDocument(proj.doc.Name)
    try:
        op = Custom.Create(PREFIX, parentJob=job)
    finally:
        if previous is not None and previous.Name != proj.doc.Name:
            FreeCAD.setActiveDocument(previous.Name)
    op.Label = label or tr("Probe the origin ({mode})", mode=tr(MODE_LABELS[mode]))
    op.ToolController = tc
    if "Source" in op.PropertiesList:
        op.Source = "Text"
    op.Gcode = wrapmod.path_gcode(lines)  # F en unité interne de Path (mm/s)
    reg = proj.registry
    reg[op.Name] = {"kind": KIND, "label": op.Label, "order": -1, "assembly_id": asm.id, "tool_id": tool.id,
                    "holder_id": None, "preset_id": preset.id, "values": values, "tool_controller": tc.Name,
                    "toolbit": toolbit.Name, "params": dict(kw, mode=mode), "ignored_params": [], "warnings": [],
                    "index_deg": None}
    proj._save_registry(reg)
    proj.move_operation_to(op, 0)
    proj.doc.recompute()
    return op


MODE_LABELS = {"z": "Z surface", "corner": "corner", "hole": "hole centre"}
