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
        _avoid_keepout(obj)


def _avoid_keepout(obj):
    """Rapides des copies relevés au-dessus des zones interdites (l'original est déjà corrigé, pas ses copies)."""
    from . import keepout

    try:
        keepout.apply(obj)
    except Exception as exc:  # jamais de parcours perdu à cause du correctif
        FreeCAD.Console.PrintWarning("CAM2027 keep-out: %s\n" % exc)


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


def footprint(base):
    """Emprise XY de la coupe de ``base`` (parcours d'avance élargi du rayon de l'outil) : (xmin, ymin, xmax,
    ymax), ``None`` sans mouvement de coupe. Un arc compte pour son cercle entier (prudent)."""
    import Path.Dressup.Utils as DressupUtils
    import PathScripts.PathUtils as PathUtils

    if base is None or not base.isDerivedFrom("Path::Feature") or not base.Path.Commands:
        return None
    xs, ys = [], []
    pos = [0.0, 0.0]
    for c in PathUtils.getPathWithPlacement(base).Commands:
        p = c.Parameters
        new = [p.get("X", pos[0]), p.get("Y", pos[1])]
        name = c.Name.replace("G0", "G") if c.Name in ("G01", "G02", "G03") else c.Name
        if name in ("G1", "G2", "G3"):
            xs += [pos[0], new[0]]
            ys += [pos[1], new[1]]
            if name != "G1" and ("I" in p or "J" in p):
                cx, cy = pos[0] + p.get("I", 0.0), pos[1] + p.get("J", 0.0)
                r = math.hypot(pos[0] - cx, pos[1] - cy)
                xs += [cx - r, cx + r]
                ys += [cy - r, cy + r]
        pos = new
    if not xs:
        return None
    tc = DressupUtils.toolController(base)
    r = 0.5 * float(tc.Tool.Diameter) if tc is not None else 0.0
    return (min(xs) - r, min(ys) - r, max(xs) + r, max(ys) + r)


def default_steps(base):
    """Pas X / Y par défaut : emprise de la coupe plus un diamètre d'outil de matière entre deux copies (copies
    côte à côte qui ne se touchent pas) ; ``None`` sans parcours. Avant : 50 mm, des copies dans la pièce (45 mm
    d'entaille sur le chauffage Vz330, 4 mm sur le plateau)."""
    import Path.Dressup.Utils as DressupUtils

    fp = footprint(base)
    if fp is None:
        return None
    tc = DressupUtils.toolController(base)
    gap = float(tc.Tool.Diameter) if tc is not None else 1.0
    return tuple(math.ceil((hi - lo + gap) * 10.0 - 1e-6) / 10.0 for lo, hi in ((fp[0], fp[2]), (fp[1], fp[3])))


def _copy_boxes(params, fp, centre):
    """Emprises des copies (même ordre que ``offsets``) ; cercle : boîte des 4 coins tournés."""
    out = []
    for dx, dy, ang in offsets(params):
        corners = [(fp[0], fp[1]), (fp[2], fp[1]), (fp[2], fp[3]), (fp[0], fp[3])]
        if ang:
            a = math.radians(ang)
            ca, sa = math.cos(a), math.sin(a)
            corners = [(centre[0] + ca * (x - centre[0]) - sa * (y - centre[1]),
                        centre[1] + sa * (x - centre[0]) + ca * (y - centre[1])) for x, y in corners]
        out.append((min(x for x, _y in corners) + dx, min(y for _x, y in corners) + dy,
                    max(x for x, _y in corners) + dx, max(y for _x, y in corners) + dy))
    return out


def _cut_points(base):
    """Points XY du parcours de coupe de ``base`` (centre de la fraise, tous les quarts de rayon au plus 1 mm,
    sans doublon) et rayon de l'outil."""
    import Path.Dressup.Utils as DressupUtils
    import PathScripts.PathUtils as PathUtils
    from . import leads, sim

    np = sim._np()
    tc = DressupUtils.toolController(base)
    r = 0.5 * float(tc.Tool.Diameter) if tc is not None else 0.0
    step = max(0.05, min(1.0, 0.25 * r))
    pts = [q[:2] for m in leads._moves(PathUtils.getPathWithPlacement(base).Commands) for q in leads._samples(m, step)]
    P = np.array(pts, dtype=float).reshape(-1, 2)
    if len(P):
        P = np.unique(np.round(P / (0.5 * step)), axis=0) * (0.5 * step)
    return P, r


def _moved(P, offset, centre):
    """Points ``P`` d'une copie (décalage de ``offsets``)."""
    from . import sim

    dx, dy, ang = offset
    if ang:
        a = math.radians(ang)
        ca, sa = math.cos(a), math.sin(a)
        x, y = P[:, 0] - centre[0], P[:, 1] - centre[1]
        return sim._np().stack([centre[0] + ca * x - sa * y, centre[1] + sa * x + ca * y], axis=1)
    return P + (dx, dy)


def _close(A, B, d):
    """Un point de ``A`` à moins de ``d`` d'un point de ``B`` : casiers de côté ``d`` (numpy), distance exacte pour
    les seuls points de ``A`` dont un casier voisin contient un point de ``B``."""
    from . import sim

    np = sim._np()
    if d <= 0 or not len(A) or not len(B):
        return False
    lo = np.minimum(A.min(axis=0), B.min(axis=0))
    ia, ib = np.floor((A - lo) / d).astype(np.int64) + 1, np.floor((B - lo) / d).astype(np.int64) + 1
    width = int(max(ia[:, 1].max(), ib[:, 1].max())) + 2
    kb = ib[:, 0] * width + ib[:, 1]
    order = np.argsort(kb, kind="stable")
    kb = kb[order]
    for ox in (-1, 0, 1):
        for oy in (-1, 0, 1):
            ka = (ia[:, 0] + ox) * width + ia[:, 1] + oy
            left = np.searchsorted(kb, ka, "left")
            right = np.searchsorted(kb, ka, "right")
            for i in np.nonzero(right > left)[0]:
                near = B[order[left[i]:right[i]]]
                if (((near - A[i]) ** 2).sum(axis=1) < d * d).any():
                    return True
    return False


def check_copies(base, params, stock=None, centre=(0.0, 0.0), tol=1e-3):
    """Refus clair (``PatternError``) si deux copies de la coupe de ``base`` se recouvrent (la fraise d'une copie
    passe à moins d'un diamètre de celle d'une autre) ou si une copie sort du brut ``stock`` (boîte englobante
    FreeCAD) plus que l'original n'en sort déjà (un contour déborde du brut de son rayon d'outil). Rien à contrôler
    sans parcours calculé."""
    fp = footprint(base)
    if fp is None:
        return
    boxes = _copy_boxes(params, fp, centre)
    points, radius = None, 0.0
    for i, a in enumerate(boxes):
        for j in range(i + 1, len(boxes)):
            b = boxes[j]
            if not (a[0] < b[2] - tol and b[0] < a[2] - tol and a[1] < b[3] - tol and b[1] < a[3] - tol):
                continue
            if points is None:
                points, radius = _cut_points(base)
                moved = [_moved(points, off, centre) for off in offsets(params)]
            # emprises qui se croisent : la fraise d'une copie passe-t-elle à moins d'un diamètre de l'autre ?
            # (deux poches d'une même opération, copies intercalées : pas de recouvrement réel)
            if _close(moved[i], moved[j], 2.0 * radius - tol):
                if params.get("Kind", "Grid") == "Grid":
                    steps = default_steps(base)
                    raise PatternError("Copies {a} and {b} of the pattern overlap: the distance between copies must be "
                                       "at least the size of the cut ({w:.1f} x {h:.1f} mm), {sx:.1f} x {sy:.1f} mm "
                                       "with a tool diameter of material between them.", a=i + 1, b=j + 1,
                                       w=fp[2] - fp[0], h=fp[3] - fp[1], sx=steps[0], sy=steps[1])
                raise PatternError("Copies {a} and {b} of the pattern overlap: fewer copies, a smaller angle or a centre "
                                   "farther from the toolpath.", a=i + 1, b=j + 1)
    if stock is None:
        return
    # débordement admis de chaque côté : celui de l'original
    allowed = (min(stock.XMin, fp[0]) - tol, min(stock.YMin, fp[1]) - tol,
               max(stock.XMax, fp[2]) + tol, max(stock.YMax, fp[3]) + tol)
    for i, b in enumerate(boxes):
        out = max(allowed[0] - b[0], allowed[1] - b[1], b[2] - allowed[2], b[3] - allowed[3])
        if out > 0:
            raise PatternError("Copy {n} of the pattern leaves the stock by {d:.1f} mm: enlarge the stock (Stock and "
                               "fixture) or use fewer copies.", n=i + 1, d=out + tol)


def check_ops(proj, ops, params):
    """``check_copies`` pour chaque opération (son habillage le plus haut, celui que le motif enveloppera)."""
    from . import dressups

    stock = getattr(getattr(proj.job, "Stock", None), "Shape", None)
    centre = tuple(params.get("Centre") or (0.0, 0.0))[:2]
    for op in ops:
        check_copies(dressups.top_of(proj.job, dressups.base_operation(op)), params,
                     stock.BoundBox if stock is not None and not stock.isNull() else None, centre=centre)


def _stock_box(obj):
    import PathScripts.PathUtils as PathUtils

    job = PathUtils.findParentJob(obj)
    stock = getattr(job, "Stock", None)
    shape = getattr(stock, "Shape", None)
    return shape.BoundBox if shape is not None and not shape.isNull() else None


def create(doc, job, current, name):
    obj = doc.addObject("Path::FeaturePython", name)
    ObjectPattern(obj, current)
    steps = default_steps(current)
    if steps:
        obj.StepX, obj.StepY = steps
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
    centre = (params or {}).get("Centre") or (obj.Centre.x, obj.Centre.y)
    check_copies(obj.Base, current, _stock_box(obj), centre=tuple(centre)[:2])
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
    check_ops(proj, ops, params)
    created = []
    for op in ops:
        obj, _ignored = proj.add_dressup(op, "pattern", params=params)
        created.append(obj)
    if minimize and len(ops) > 1:
        minimize_tool_changes(proj, created)
    return created
