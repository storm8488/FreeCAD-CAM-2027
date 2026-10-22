# SPDX-License-Identifier: LGPL-2.1-or-later
"""Perçage intelligent : reconnaissance des trous et séquence d'opérations proposée (Fusion *Hole Recognition*).

1. **Reconnaissance** (``find_holes``) : faces cylindriques d'axe Z de la pièce, regroupées par axe et rayon
   (un STEP coupe souvent un cylindre en deux demi-faces), gardées si elles font le tour complet, si le centre
   est vide (trou, pas tenon) et si le haut débouche à l'air (accessible par le dessus). Pour chaque trou :
   centre, diamètre, haut, fond, débouchant ou borgne, chanfrein d'entrée (cône coaxial au-dessus du cylindre :
   diamètre du haut, angle inclus).
2. **Séquence** (``plan``) par groupe de trous identiques (diamètre, haut, fond, débouchant), dans l'ordre de
   Fusion : pointage (outil en V à 90°, diamètre de pointage 0,9 × trou) → perçage (foret au diamètre à 0,02 mm,
   débourrage G83 quand la profondeur dépasse 3 D, pas de débourrage = D ; débouchant : pointe complète sous le
   fond + 0,5 mm) ou, sans foret, alésage hélicoïdal à la fraise → chanfrein (outil en V du même angle que le
   cône, plongé au centre jusqu'au diamètre du haut du chanfrein) → filetage à la fraise à fileter si une
   désignation est donnée pour ce diamètre. Taraudage (``Path.Op.Tapping``) : non proposé, la bibliothèque n'a
   pas de type « taraud ».
3. **Création** (``apply_plan``) : une opération par étape et par groupe, dans l'ordre des étapes (tous les
   pointages, puis tous les perçages... : un seul changement d'outil par étape).

``expand_cycles`` traduit les cycles de perçage (G73/G81/G82/G83, G98/G99) en mouvements G0/G1 pour la
simulation matière.
"""

import math

import FreeCAD

from ..i18n import Msg, UserError

STEPS = ("spot", "drill", "chamfer", "thread")
STEP_LABELS = {"spot": "Spot drilling", "drill": "Drilling", "bore": "Bore milling", "chamfer": "Hole chamfer",
               "thread": "Thread milling"}
#: profondeur au-delà de laquelle le perçage débourre (Fusion : cycle « Deep drilling » conseillé au-delà de 3 D)
PECK_RATIO = 3.0
#: dépassement sous le fond d'un trou débouchant (mm, en plus de la pointe du foret)
BREAK_THROUGH = 0.5
#: diamètre de pointage = facteur × diamètre du trou (pointage plus petit que le trou : aucune marque hors du trou)
SPOT_RATIO = 0.9
DRILL_TOL = 0.02


class HoleError(UserError):
    pass


class Hole(object):
    def __init__(self, x, y, diameter, top, bottom, through, faces, chamfer_diameter=None, chamfer_angle=None):
        self.x, self.y, self.diameter = x, y, diameter
        self.top, self.bottom, self.through = top, bottom, through
        self.faces = faces
        self.chamfer_diameter, self.chamfer_angle = chamfer_diameter, chamfer_angle

    @property
    def depth(self):
        return self.top - self.bottom

    def key(self):
        return (round(self.diameter, 2), round(self.top, 2), round(self.bottom, 2), self.through,
                None if self.chamfer_diameter is None else round(self.chamfer_diameter, 2))

    def __repr__(self):
        return "Hole(%.2f at %.2f,%.2f z %.2f..%.2f%s%s)" % (
            self.diameter, self.x, self.y, self.bottom, self.top, " through" if self.through else "",
            " chamfer %.2f" % self.chamfer_diameter if self.chamfer_diameter else "")


def _vertical(axis, tol=1e-6):
    return abs(abs(axis.z) - 1.0) < tol


def find_holes(obj, tol=1e-4):
    """Trous d'axe Z accessibles par le dessus de la forme de ``obj`` (clone du modèle du job)."""
    shape = obj.Shape
    bb = shape.BoundBox
    cylinders = {}
    cones = []
    for i, f in enumerate(shape.Faces, 1):
        s = f.Surface
        kind = s.__class__.__name__
        if kind == "Cylinder" and _vertical(s.Axis):
            key = (round(s.Center.x, 3), round(s.Center.y, 3), round(s.Radius, 4))
            u0, u1, _v0, _v1 = f.ParameterRange
            entry = cylinders.setdefault(key, {"faces": [], "sweep": 0.0, "zmin": f.BoundBox.ZMin,
                                               "zmax": f.BoundBox.ZMax})
            entry["faces"].append("Face%d" % i)
            entry["sweep"] += abs(u1 - u0)
            entry["zmin"] = min(entry["zmin"], f.BoundBox.ZMin)
            entry["zmax"] = max(entry["zmax"], f.BoundBox.ZMax)
        elif kind == "Cone" and _vertical(s.Axis):
            cones.append((i, f))
    holes = []
    for (cx, cy, r), e in cylinders.items():
        if e["sweep"] < 2 * math.pi - 1e-3:
            continue  # congé, arrondi d'angle : pas un trou
        top, bottom = e["zmax"], e["zmin"]
        mid = FreeCAD.Vector(cx, cy, 0.5 * (top + bottom))
        if shape.isInside(mid, tol, True):
            continue  # tenon (matière au centre)
        # chanfrein d'entrée : cône coaxial posé sur le haut du cylindre, plus large en haut
        chamfer_d = chamfer_angle = None
        for i, f in cones:
            s = f.Surface
            if abs(s.Apex.x - cx) > 1e-3 or abs(s.Apex.y - cy) > 1e-3:
                continue
            if abs(f.BoundBox.ZMin - top) > 1e-3:
                continue
            r_top = 0.5 * max(f.BoundBox.XLength, f.BoundBox.YLength)
            if r_top <= r + 1e-4:
                continue
            chamfer_d = 2.0 * r_top
            chamfer_angle = 2.0 * math.degrees(s.SemiAngle)
            e["faces"].append("Face%d" % i)
            top = f.BoundBox.ZMax
            break
        above = FreeCAD.Vector(cx, cy, top + 0.05)
        if top < bb.ZMax - 1e-6 and shape.isInside(above, tol, True):
            continue  # fermé au-dessus (trou par en dessous, perçage transversal...)
        below = FreeCAD.Vector(cx, cy, bottom - 0.05)
        through = bottom <= bb.ZMin + 1e-6 or not shape.isInside(below, tol, True)
        holes.append(Hole(cx, cy, 2.0 * r, top, bottom, through, e["faces"], chamfer_d, chamfer_angle))
    holes.sort(key=lambda h: (h.diameter, h.y, h.x))
    return holes


def groups(holes):
    """Trous identiques (diamètre, haut, fond, débouchant, chanfrein) : ``[(trou modèle, [trous])]``."""
    out = {}
    for h in holes:
        out.setdefault(h.key(), []).append(h)
    return [(v[0], v) for _k, v in sorted(out.items())]


# -- choix des outils ------------------------------------------------------------------------------------


def _assemblies(lib, tool):
    asms = lib.assemblies_for_tool(tool.id)
    return asms[0] if asms and tool.presets else None


def _tools(lib, types):
    return sorted((t for t in lib.tools.values() if t.tool_type in types and _assemblies(lib, t) is not None),
                  key=lambda t: t.name)


def _preset(tool, usage):
    for p in tool.presets:
        if p.usage == usage:
            return p
    return tool.presets[0]


def pick_drill(lib, diameter):
    drills = [t for t in _tools(lib, ("drill",)) if abs(t.geometry.diameter - diameter) <= DRILL_TOL]
    return min(drills, key=lambda t: abs(t.geometry.diameter - diameter)) if drills else None


def pick_bore_mill(lib, diameter):
    """Fraise deux tailles pour l'alésage hélicoïdal : la plus grosse qui laisse au moins 0,5 mm de jeu."""
    mills = [t for t in _tools(lib, ("endmill",)) if t.geometry.diameter <= diameter - 0.5]
    if not mills:
        return None
    return max(mills, key=lambda t: (t.geometry.diameter, getattr(t.geometry, "flute_style", None) != "compression"))


def pick_vtool(lib, angle=90.0, min_diameter=0.0):
    tools = [t for t in _tools(lib, ("chamfer", "vbit", "engrave"))
             if t.geometry.tip_included_angle_deg and abs(t.geometry.tip_included_angle_deg - angle) <= 1.0
             and t.geometry.diameter > min_diameter]
    return min(tools, key=lambda t: (t.tool_type != "chamfer", t.geometry.diameter)) if tools else None


def _v_depth(tool, diameter):
    """Profondeur de plongée d'un outil en V pour obtenir ``diameter`` au niveau de départ."""
    half = math.radians(tool.geometry.tip_included_angle_deg / 2.0)
    tip = float(getattr(tool.geometry, "tip_diameter", 0.0) or 0.0)
    return max(0.0, (diameter - tip) / 2.0 / math.tan(half))


def _drill_tip(tool):
    angle = tool.geometry.tip_included_angle_deg or 118.0
    return tool.geometry.diameter / 2.0 / math.tan(math.radians(angle / 2.0))


# -- séquence ----------------------------------------------------------------------------------------------


def plan(lib, holes, threads=None, spot=True):
    """Séquence proposée : liste d'étapes ``{"step", "group", "holes", "tool", "preset", "kind", "params"}`` et
    notes (trous laissés de côté). ``threads`` : diamètre arrondi à 0,01 -> désignation (« M8 »)."""
    from . import operations as opsmod

    threads = {round(float(k), 2): v for k, v in (threads or {}).items()}
    steps, notes = [], []
    for model, members in groups(holes):
        d = model.diameter
        drill = pick_drill(lib, d)
        mill = None if drill else pick_bore_mill(lib, d)
        if drill is None and mill is None:
            notes.append(Msg("No drill of {d} mm and no end mill small enough in the library: {n} hole(s) left out",
                             d="%.2f" % d, n=len(members)))
            continue
        if spot and drill is not None:
            vt = pick_vtool(lib, 90.0)
            if vt is not None:
                steps.append({"step": "spot", "kind": "drilling", "tool": vt, "holes": members, "model": model,
                              "params": {"StartDepth": model.top, "FinalDepth": model.top - _v_depth(vt, SPOT_RATIO * d),
                                         "ExtraOffset": "None"}})
            else:
                notes.append(Msg("No 90° spot drill or V-bit in the library: holes of {d} mm not spot drilled",
                                 d="%.2f" % d))
        if drill is not None:
            params = {"StartDepth": model.top, "ExtraOffset": "None", "FinalDepth": model.bottom}
            if model.through:
                params["FinalDepth"] = model.bottom - BREAK_THROUGH
                params["ExtraOffset"] = "Drill Tip"
            if model.depth > PECK_RATIO * d:
                params["PeckEnabled"] = True
                params["PeckDepth"] = d
            steps.append({"step": "drill", "kind": "drilling", "tool": drill, "holes": members, "model": model,
                          "params": params})
        else:
            steps.append({"step": "drill", "kind": "helix", "tool": mill, "holes": members, "model": model,
                          "params": {"StartDepth": model.top,
                                     "FinalDepth": model.bottom if not model.through else model.bottom - BREAK_THROUGH},
                          "bore": True})
        if model.chamfer_diameter:
            vt = pick_vtool(lib, model.chamfer_angle or 90.0, min_diameter=model.chamfer_diameter)
            if vt is None:
                notes.append(Msg("No V tool of {a}° wider than {d} mm: chamfer of the {h} mm holes not machined",
                                 a="%.0f" % (model.chamfer_angle or 90.0), d="%.2f" % model.chamfer_diameter,
                                 h="%.2f" % d))
            else:
                steps.append({"step": "chamfer", "kind": "drilling", "tool": vt, "holes": members, "model": model,
                              "params": {"StartDepth": model.top,
                                         "FinalDepth": model.top - _v_depth(vt, model.chamfer_diameter),
                                         "ExtraOffset": "None"}})
        name = threads.get(round(d, 2))
        if name:
            tm = [t for t in _tools(lib, ("threadmill",)) if t.geometry.diameter < d]
            if not tm:
                notes.append(Msg("No thread mill smaller than {d} mm: thread {t} not machined", d="%.2f" % d, t=name))
            else:
                full = name if name in opsmod.thread_names(opsmod.DEFAULT_THREAD_TYPE) else _thread_name(name)
                steps.append({"step": "thread", "kind": "threadmill", "tool": tm[0], "holes": members, "model": model,
                              "params": {"ThreadName": full}})
    order = {"spot": 0, "drill": 1, "chamfer": 2, "thread": 3}
    steps.sort(key=lambda s: (order[s["step"]], s["tool"].name, s["model"].diameter))
    return steps, notes


def _thread_name(short):
    """« M8 » -> désignation de la table FreeCAD (« M8 »...) ; laissée telle quelle si absente."""
    from . import operations as opsmod

    for n in opsmod.thread_names(opsmod.DEFAULT_THREAD_TYPE):
        if n.split()[0] == short or n.startswith(short + "x") or n.startswith(short + " "):
            return n
    return short


def step_label(step):
    return "%s Ø%.2f" % (STEP_LABELS["bore" if step.get("bore") else step["step"]], step["model"].diameter)


def apply_plan(proj, clone, steps):
    """Crée une opération par étape ; retourne la liste des opérations (dans l'ordre d'usinage)."""
    from ..i18n import tr

    ops = []
    for st in steps:
        tool = st["tool"]
        asm = _assemblies(proj.library, tool)
        preset = _preset(tool, "drilling" if st["kind"] == "drilling" else "general")
        faces = [f for h in st["holes"] for f in h.faces
                 if clone.Shape.Faces[int(f[4:]) - 1].Surface.__class__.__name__ == "Cylinder"]
        name = tr(STEP_LABELS["bore" if st.get("bore") else st["step"]]) + " Ø%.2f" % st["model"].diameter
        op, _rec = proj.add_operation(st["kind"], name, asm.id, preset.id, base=[(clone, faces)],
                                      params=dict(st["params"]))
        ops.append(op)
    return ops


# -- simulation des cycles ---------------------------------------------------------------------------------


def expand_cycles(commands):
    """Commandes avec les cycles de perçage remplacés par leurs mouvements (G0 au plan R, G1 au fond, retrait
    G0 au plan R en G99 ou à la hauteur de départ en G98) ; les autres commandes passent telles quelles."""
    import Path

    out = []
    pos = {"X": None, "Y": None, "Z": None}
    retract_mode = "G98"
    modal = {}
    for c in commands:
        name = c.Name.upper()
        p = c.Parameters
        if name in ("G98", "G99"):
            retract_mode = name
            out.append(c)
            continue
        if name in ("G73", "G81", "G82", "G83", "G85", "G86", "G89"):
            modal.update({k: v for k, v in p.items() if k in ("Z", "R", "F")})
            x, y = p.get("X", pos["X"]), p.get("Y", pos["Y"])
            z0 = pos["Z"] if pos["Z"] is not None else modal.get("R", 0.0)
            r = modal.get("R", z0)
            zb = modal.get("Z", r)
            out.append(Path.Command("G0", {"X": x, "Y": y}))
            if r < z0:
                out.append(Path.Command("G0", {"Z": r}))
            out.append(Path.Command("G1", {"Z": zb}))
            back = r if retract_mode == "G99" else max(z0, r)
            out.append(Path.Command("G0", {"Z": back}))
            pos.update({"X": x, "Y": y, "Z": back})
            continue
        for k in ("X", "Y", "Z"):
            if k in p:
                pos[k] = p[k]
        out.append(c)
    return out


def has_cycles(commands):
    return any(c.Name.upper() in ("G73", "G81", "G82", "G83", "G85", "G86", "G89") for c in commands)
