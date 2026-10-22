# SPDX-License-Identifier: LGPL-2.1-or-later
"""Motifs de parcours : copies d'une ou plusieurs opérations en grille ou en cercle (Usiner > Motif).

Même principe que l'habillage ``Path.Dressup.Array`` de FreeCAD 1.1 (le parcours calculé de l'opération est
recopié, chaque copie transformée par ``PathUtils.applyPlacementToPath``), dans un habillage CAM2027 qui
existe aussi sur 1.0 (où FreeCAD n'a qu'une ancienne opération « Array ») et que l'on place au-dessus des autres
habillages. Différences voulues avec FreeCAD :

- grille en serpentin (lignes alternées), copie (0, 0) = l'original, pas X / pas Y entre centres (Aspire
  « Offset ») ;
- cercle : ``Count`` copies réparties sur ``Angle`` (360° = tour complet sans doublon) autour de ``Centre`` ;
- remontée à la hauteur de dégagement de l'opération entre deux copies ;
- plusieurs opérations : une copie du motif par opération, puis ordre « moins de changements d'outil »
  (Aspire *Minimize Tool Changes*) : les opérations de même outil sont regroupées, dans l'ordre de leur
  première apparition ; le motif complet d'un outil est usiné avant de changer d'outil.
"""

import math

import FreeCAD

from ..i18n import UserError

KINDS = ("Grid", "Circular")
#: paramètres (nom -> genre)
PARAMS = (("Kind", "enum"), ("Columns", "int"), ("Rows", "int"), ("StepX", "length"), ("StepY", "length"),
          ("Count", "int"), ("Centre", "vector"), ("Angle", "angle"))
MAX_COPIES = 500


class PatternError(UserError):
    pass


class ObjectPattern(object):
    """Proxy de l'habillage « motif » (``<op>_DressupPattern``)."""

    def __init__(self, obj, base):
        obj.addProperty("App::PropertyLink", "Base", "Path", "The base toolpath to copy")
        obj.addProperty("App::PropertyEnumeration", "Kind", "Pattern", "Grid or circular pattern")
        obj.Kind = list(KINDS)
        obj.addProperty("App::PropertyInteger", "Columns", "Pattern", "Copies along X (grid)")
        obj.addProperty("App::PropertyInteger", "Rows", "Pattern", "Copies along Y (grid)")
        obj.addProperty("App::PropertyDistance", "StepX", "Pattern", "Distance between columns (grid)")
        obj.addProperty("App::PropertyDistance", "StepY", "Pattern", "Distance between rows (grid)")
        obj.addProperty("App::PropertyInteger", "Count", "Pattern", "Number of copies (circular)")
        obj.addProperty("App::PropertyVectorDistance", "Centre", "Pattern", "Centre of the circle (circular)")
        obj.addProperty("App::PropertyAngle", "Angle", "Pattern", "Total angle (circular, 360 = full turn)")
        obj.Base = base
        obj.Columns, obj.Rows, obj.Count = 2, 1, 4
        obj.StepX, obj.StepY = 50.0, 50.0
        obj.Angle = 360.0
        obj.Proxy = self

    def dumps(self):
        return None

    def loads(self, state):
        return None

    def execute(self, obj):
        import Path
        import Path.Dressup.Utils as DressupUtils
        import PathScripts.PathUtils as PathUtils

        base = obj.Base
        if base is None or not base.isDerivedFrom("Path::Feature") or not base.Path.Commands:
            obj.Path = Path.Path()
            return
        if not getattr(DressupUtils.baseOp(base), "Active", True):
            obj.Path = Path.Path()
            return
        path = PathUtils.getPathWithPlacement(base)
        op = DressupUtils.baseOp(base)
        zs = [c.Parameters["Z"] for c in path.Commands if "Z" in c.Parameters]
        clear = float(getattr(getattr(op, "ClearanceHeight", None), "Value", max(zs) if zs else 0.0))
        clear = max([clear] + zs)
        out = []
        for k, pl in enumerate(placements(obj)):
            if k:
                out.append(Path.Command("G0", {"Z": clear}))
            if pl is None:
                out.extend(path.Commands)
            else:
                out.extend(PathUtils.applyPlacementToPath(pl, path).Commands)
        obj.Path = Path.Path(out)


class ViewProviderPattern(object):
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.obj = vobj.Object

    def claimChildren(self):
        base = getattr(self.obj, "Base", None)
        return [base] if base is not None else []

    def dumps(self):
        return None

    def loads(self, state):
        return None

    def onDelete(self, vobj, args=None):
        return True


def offsets(params):
    """Positions des copies : liste de (dx, dy, angle en degrés autour du centre), la première = l'original."""
    kind = params.get("Kind", "Grid")
    if kind not in KINDS:
        raise PatternError("Unknown pattern kind: {kind}", kind=kind)
    if kind == "Grid":
        cols, rows = int(params.get("Columns", 1)), int(params.get("Rows", 1))
        if cols < 1 or rows < 1:
            raise PatternError("A grid needs at least one row and one column.")
        if cols * rows > MAX_COPIES:
            raise PatternError("At most {n} copies.", n=MAX_COPIES)
        sx, sy = float(params.get("StepX", 0.0)), float(params.get("StepY", 0.0))
        if (cols > 1 and abs(sx) < 1e-6) or (rows > 1 and abs(sy) < 1e-6):
            raise PatternError("The distance between copies must not be zero.")
        out = []
        for r in range(rows):
            order = range(cols) if r % 2 == 0 else range(cols - 1, -1, -1)  # serpentin
            out.extend((c * sx, r * sy, 0.0) for c in order)
        return out
    count = int(params.get("Count", 1))
    if count < 1 or count > MAX_COPIES:
        raise PatternError("A circular pattern needs 1 to {n} copies.", n=MAX_COPIES)
    total = float(params.get("Angle", 360.0))
    if abs(total) < 1e-9:
        raise PatternError("The total angle must not be zero.")
    full = abs(abs(total) - 360.0) < 1e-6
    step = total / count if full or count == 1 else total / (count - 1)
    return [(0.0, 0.0, i * step) for i in range(count)]


def placements(obj):
    """Placements FreeCAD des copies d'un habillage motif (``None`` = original sans transformation)."""
    params = {"Kind": obj.Kind, "Columns": obj.Columns, "Rows": obj.Rows, "StepX": float(obj.StepX),
              "StepY": float(obj.StepY), "Count": obj.Count, "Angle": float(obj.Angle)}
    centre = FreeCAD.Vector(obj.Centre)
    out = []
    for dx, dy, ang in offsets(params):
        if abs(dx) < 1e-12 and abs(dy) < 1e-12 and abs(ang) < 1e-12:
            out.append(None)
            continue
        if ang:
            rot = FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), ang)
            # rotation autour du centre : p' = R (p - c) + c
            move = centre - rot.multVec(centre)
            out.append(FreeCAD.Placement(move, rot))
        else:
            out.append(FreeCAD.Placement(FreeCAD.Vector(dx, dy, 0), FreeCAD.Rotation()))
    return out


def create(doc, job, current, name):
    obj = doc.addObject("Path::FeaturePython", name)
    ObjectPattern(obj, current)
    job.Proxy.addOperation(obj, current)
    if FreeCAD.GuiUp and obj.ViewObject is not None:
        ViewProviderPattern(obj.ViewObject)
    return obj


def set_params(obj, params):
    """Valide (``offsets``) puis applique ; retourne les noms inconnus."""
    from .operations import set_params as set_native

    current = {n: getattr(obj, n) for n, _k in PARAMS if n != "Centre"}
    current = {k: (float(v) if hasattr(v, "Value") else v) for k, v in current.items()}
    current.update({k: v for k, v in (params or {}).items() if k != "Centre"})
    offsets(current)
    return set_native(obj, params or {})


def read_params(obj):
    from .operations import read_params as read_native

    return read_native(obj, [n for n, _k in PARAMS])


def tool_key(proj, op):
    """Identité de l'outil d'une opération (outil de la bibliothèque, sinon contrôleur d'outil)."""
    from . import dressups

    base = dressups.base_operation(op)
    rec = proj.registry.get(base.Name) or {}
    if rec.get("tool_id"):
        return rec["tool_id"]
    tc = getattr(base, "ToolController", None)
    return tc.Name if tc is not None else base.Name


def minimize_tool_changes(proj, ops):
    """Regroupe les opérations ``ops`` par outil (ordre de première apparition), les autres restent à leur place.
    Retourne le nombre de changements d'outil entre opérations consécutives du projet, après."""
    from . import dressups

    names = set(dressups.base_operation(o).Name for o in ops)
    current = list(proj.operations())
    slots = [i for i, o in enumerate(current) if dressups.base_operation(o).Name in names]
    chosen = [current[i] for i in slots]
    order = []
    for o in chosen:
        if tool_key(proj, o) not in order:
            order.append(tool_key(proj, o))
    grouped = sorted(chosen, key=lambda o: order.index(tool_key(proj, o)))  # tri stable
    for slot, o in zip(slots, grouped):
        proj.move_operation_to(o, slot)
    return tool_changes(proj)


def tool_changes(proj):
    """Nombre de changements d'outil entre opérations actives consécutives."""
    from . import dressups

    keys = [tool_key(proj, o) for o in proj.operations() if getattr(dressups.base_operation(o), "Active", True)]
    return sum(1 for a, b in zip(keys, keys[1:]) if a != b)


def add_pattern(proj, ops, params, minimize=True):
    """Motif sur chaque opération de ``ops`` (mêmes réglages) ; retourne les habillages créés."""
    if not ops:
        raise PatternError("Select one or more operations to repeat.")
    offsets(params)
    created = []
    for op in ops:
        obj, _ignored = proj.add_dressup(op, "pattern", params=params)
        created.append(obj)
    if minimize and len(ops) > 1:
        minimize_tool_changes(proj, created)
    return created
