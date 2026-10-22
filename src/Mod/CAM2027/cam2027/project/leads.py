# SPDX-License-Identifier: LGPL-2.1-or-later
"""Entrées et sorties en arc : habillage ``LeadInOut`` de FreeCAD, 1.0 et 1.1 derrière les mêmes paramètres.

Les paramètres CAM2027 portent les noms de FreeCAD 1.1 (``StyleIn``, ``RadiusIn``, ``AngleIn`` et leurs
pendants ``Out``) ; sur 1.0, l'habillage n'a que ``StyleOn`` / ``StyleOff``, ``Length`` / ``LengthOut`` et un
arc fixe d'un quart de tour. Ce module traduit dans les deux sens, comme Fusion qui sépare entrée et sortie :

- ``Arc`` : arc horizontal tangent au parcours (rayon horizontal, angle de balayage) ;
- ``ArcZ`` : arc vertical (rayon vertical, 1.1 seulement) ;
- ``Tangent`` / ``Perpendicular`` : droite tangente ou perpendiculaire.

Rayon par défaut de FreeCAD : 0,75 × diamètre de l'outil (Fusion ne documente pas de valeur).
"""

from .. import compat
from ..i18n import UserError

MODULE = "Path.Dressup.Gui.LeadInOut"
STYLES = ("Arc", "ArcZ", "Tangent", "Perpendicular")
STYLES_10 = ("Arc", "Tangent", "Perpendicular")
#: paramètres CAM2027 (noms 1.1) -> genre pour l'éditeur
PARAMS = (("StyleIn", "enum"), ("RadiusIn", "length"), ("AngleIn", "angle"),
          ("StyleOut", "enum"), ("RadiusOut", "length"), ("AngleOut", "angle"))
#: 1.1 -> 1.0
_NAMES_10 = {"StyleIn": "StyleOn", "StyleOut": "StyleOff", "RadiusIn": "Length", "RadiusOut": "LengthOut"}


class LeadError(UserError):
    pass


def is_v11(obj):
    """Habillage au format FreeCAD 1.1 (``StyleIn``) ou 1.0 (``StyleOn``)."""
    return "StyleIn" in obj.PropertiesList


def create(doc, job, current, name):
    """Crée l'habillage au-dessus de ``current`` et l'ajoute au job (réglages FreeCAD : arcs, rayon 0,75 D)."""
    import importlib

    mod = importlib.import_module(MODULE)
    obj = doc.addObject("Path::FeaturePython", name)
    dbo = mod.ObjectDressup(obj)
    obj.Base = current
    job.Proxy.addOperation(obj, current)
    if is_v11(obj):
        # pas ``setup()`` : son expression ``<Nom>.ToolController...`` échoue quand le nom est une unité (« C », « m »)
        from Path.Base.Util import toolControllerForOp

        tc = toolControllerForOp(current)
        radius = 0.75 * float(tc.Tool.Diameter) if tc is not None else 10.0
        obj.LeadIn = obj.LeadOut = True
        obj.StyleIn = obj.StyleOut = "Arc"
        obj.AngleIn = obj.AngleOut = 90
        obj.RadiusIn = obj.RadiusOut = radius
        obj.InvertIn = obj.InvertOut = obj.RapidPlunge = False
    else:
        dbo.setup(obj)
        obj.IncludeLayers = True  # une entrée à chaque passe de profondeur, comme 1.1
    return obj


def set_params(obj, params):
    """Applique les paramètres CAM2027 ; retourne les noms ignorés (angle de balayage sur 1.0)."""
    from .operations import set_params as set_native

    params = dict(params or {})
    for key in ("StyleIn", "StyleOut"):
        style = params.get(key)
        if style is not None and style not in STYLES:
            raise LeadError("Unknown lead style: {style}", style=style)
    if is_v11(obj):
        for key in ("RadiusIn", "RadiusOut"):
            if key in params and params[key] is not None and float(params[key]) <= 0:
                raise LeadError("The lead radius must be positive.")
        return set_native(obj, params)
    ignored = []
    native = {}
    for key, value in params.items():
        if key in ("StyleIn", "StyleOut") and value not in STYLES_10:
            raise LeadError("Vertical arc leads need FreeCAD 1.1.")
        if key in ("AngleIn", "AngleOut"):
            if abs(float(value) - 90.0) > 1e-6:
                ignored.append(key)  # 1.0 : quart de cercle fixe
            continue
        native[_NAMES_10.get(key, key)] = value
    return ignored + set_native(obj, native)


def read_params(obj):
    """Valeurs courantes sous les noms CAM2027 (mm, degrés)."""
    from .operations import read_params as read_native

    if is_v11(obj):
        return read_native(obj, [n for n, _k in PARAMS])
    raw = read_native(obj, list(_NAMES_10.values()))
    out = {k: raw[v] for k, v in _NAMES_10.items() if v in raw}
    out["AngleIn"] = out["AngleOut"] = 90.0
    return out


def _tool_radius(obj):
    import Path.Dressup.Utils as DressupUtils

    tc = DressupUtils.toolController(obj.Base)
    return 0.5 * float(tc.Tool.Diameter) if tc is not None else 0.0


def _moves(commands, start=None):
    """Mouvements d'avance horizontaux : (nom, début, fin, centre ou None)."""
    import math

    pos = list(start or (0.0, 0.0, 0.0))
    out = []
    for c in commands:
        p = c.Parameters
        new = [p.get("X", pos[0]), p.get("Y", pos[1]), p.get("Z", pos[2])]
        name = c.Name.replace("G0", "G") if c.Name in ("G01", "G02", "G03") else c.Name
        if name in ("G1", "G2", "G3") and math.hypot(new[0] - pos[0], new[1] - pos[1]) > 1e-9:
            centre = (pos[0] + p.get("I", 0.0), pos[1] + p.get("J", 0.0)) if name != "G1" else None
            out.append((name, tuple(pos), tuple(new), centre))
        pos = new
    return out


def _samples(move, step):
    import math

    name, a, b, centre = move
    if centre is None:
        n = max(1, int(math.ceil(math.dist(a[:2], b[:2]) / step)))
        return [tuple(a[k] + (b[k] - a[k]) * i / n for k in range(3)) for i in range(n + 1)]
    r = math.dist(a[:2], centre)
    t0 = math.atan2(a[1] - centre[1], a[0] - centre[0])
    t1 = math.atan2(b[1] - centre[1], b[0] - centre[0])
    sweep = t1 - t0
    if name == "G3" and sweep <= 0:
        sweep += 2 * math.pi
    elif name == "G2" and sweep >= 0:
        sweep -= 2 * math.pi
    n = max(1, int(math.ceil(abs(sweep) * r / step)))
    return [(centre[0] + r * math.cos(t0 + sweep * i / n), centre[1] + r * math.sin(t0 + sweep * i / n),
             a[2] + (b[2] - a[2]) * i / n) for i in range(n + 1)]


def collisions(obj, shapes, step=0.5, tol=0.02):
    """Points (x, y, z) des mouvements ajoutés par l'habillage où la fraise touche la pièce.

    Seuls les mouvements absents du parcours de base sont contrôlés (l'opération répond des siens) ; en chaque
    point, la distance entre l'axe de la fraise (de la pointe au-dessus de la pièce) et les solides doit valoir au
    moins le rayon de l'outil."""
    import FreeCAD
    import Part

    radius = _tool_radius(obj)
    if not shapes or radius <= 0:
        return []
    key = lambda m: (m[0],) + tuple(round(v, 3) for v in m[1] + m[2])
    base = set(key(m) for m in _moves(obj.Base.Path.Commands))
    top = max(s.BoundBox.ZMax for s in shapes) + 1.0
    bb = shapes[0].BoundBox
    for s in shapes[1:]:
        bb.add(s.BoundBox)
    above = {}  # pièce au-dessus du plan de la pointe (le fond sous la fraise ne compte pas)

    def part_above(z):
        k = round(z, 3)
        if k not in above:
            box = Part.makeBox(bb.XLength + 2 * radius + 20, bb.YLength + 2 * radius + 20, top - k,
                               FreeCAD.Vector(bb.XMin - radius - 10, bb.YMin - radius - 10, k + 1e-3))
            above[k] = [c for c in (s.common(box) for s in shapes) if c.Solids]
        return above[k]

    hits = []
    for move in _moves(obj.Path.Commands):
        if key(move) in base:
            continue
        for x, y, z in _samples(move, step):
            if z >= top - 1.0:
                continue
            solids = part_above(z)
            if not solids:
                continue
            axis = Part.LineSegment(FreeCAD.Vector(x, y, z + 2e-3), FreeCAD.Vector(x, y, top)).toShape()
            if min(axis.distToShape(s)[0] for s in solids) < radius - tol:
                hits.append((round(x, 3), round(y, 3), round(z, 3)))
                break
    return hits


def secure(obj, shapes):
    """Recalcule l'habillage et l'éloigne de la pièce : sur 1.1, le point de départ est déplacé le long du
    parcours (``OffsetIn`` / ``OffsetOut``, recouvrement comme Fusion) tant qu'une entrée touche la pièce.
    Retourne les points de contact restants (liste vide = sûr)."""
    def refresh():
        if obj.Base.State and ("Touched" in obj.Base.State or "Invalid" in obj.Base.State):
            obj.Base.recompute()
        obj.recompute()
        return collisions(obj, shapes)

    if is_v11(obj):
        obj.OffsetIn = obj.OffsetOut = 0
    hits = refresh()
    if hits and is_v11(obj):
        reach = max(float(obj.RadiusIn), float(obj.RadiusOut)) + _tool_radius(obj)
        for k in range(1, 7):
            obj.OffsetIn = obj.OffsetOut = k * reach
            hits = refresh()
            if not hits:
                break
        if hits:
            obj.OffsetIn = obj.OffsetOut = 0
            obj.recompute()
    return hits


def styles():
    """Styles proposés par la version de FreeCAD en cours."""
    return STYLES if compat.freecad_version() >= (1, 1) else STYLES_10


def first_cut_arc(path_commands):
    """Premier mouvement d'avance horizontal du parcours : (nom, paramètres) ; sert aux tests et au contrôle."""
    z = None
    for c in path_commands:
        p = c.Parameters
        if c.Name in ("G1", "G01", "G2", "G02", "G3", "G03"):
            moves_xy = "X" in p or "Y" in p
            if moves_xy:
                return c.Name, dict(p)
        if "Z" in p:
            z = p["Z"]
    return None, {"Z": z}


__all__ = ["create", "collisions", "secure", "set_params", "read_params", "styles", "is_v11", "LeadError", "PARAMS", "STYLES"]
