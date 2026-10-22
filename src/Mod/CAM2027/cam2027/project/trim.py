# SPDX-License-Identifier: LGPL-2.1-or-later
"""Découpe d'un parcours calculé sans recalcul (Fusion « Toolpath trimming », habillage « Limiter à une zone »).

Moteur commun à deux habillages CAM2027 :

- **Limiter à une zone** (``KIND``) : polygone (contour fermé du dessin ou rectangle), coupe gardée dedans
  ou dehors ;
- **reprise de matière** (``rest.py``) : coupe gardée seulement là où la fraise rencontre de la matière
  laissée par les opérations précédentes.

Principe (celui de ``Path.Dressup.Boundary`` de FreeCAD, qui coupe avec un solide par booléens et diffère
entre 1.0 et 1.1 ; ici un prédicat sur des points, vectorisé) : chaque mouvement de coupe (G1, G2, G3) est
échantillonné ; les morceaux gardés restent tels quels (arc entier gardé = commande d'origine), les bords
sont affinés par dichotomie ; les rapides d'origine ne sont gardés que s'ils relient deux morceaux gardés
sans rien de coupé entre eux. Ailleurs, la **liaison est recalculée** : remontée à la hauteur de dégagement,
rapide au-dessus du point suivant, descente rapide à la hauteur de sécurité, plongée en avance verticale.
Le reste du parcours n'est pas recalculé.
"""

import math

import FreeCAD

from ..i18n import Msg, UserError

KIND = "trim"
SUFFIX = "_DressupTrim"
LABEL = "Limit to an area"
#: pas d'échantillonnage des mouvements de coupe (mm) et itérations de dichotomie aux bords
SAMPLE_STEP = 0.2
REFINE_STEPS = 14
_EPS = 1e-6
_MOTION = ("G0", "G00", "G1", "G01", "G2", "G02", "G3", "G03")


def _np():
    import numpy

    return numpy


# -- moteur -------------------------------------------------------------------------------------------------


def _arc_points(p0, p1, params, cw, step):
    cx, cy = p0[0] + params.get("I", 0.0), p0[1] + params.get("J", 0.0)
    a0 = math.atan2(p0[1] - cy, p0[0] - cx)
    a1 = math.atan2(p1[1] - cy, p1[0] - cx)
    radius = math.hypot(p0[0] - cx, p0[1] - cy)
    sweep = a1 - a0
    if cw and sweep >= -1e-12:
        sweep -= 2 * math.pi
    elif not cw and sweep <= 1e-12:
        sweep += 2 * math.pi
    n = max(2, int(math.ceil(abs(sweep) * radius / step)))
    pts = []
    for k in range(n + 1):
        a = a0 + sweep * k / n
        pts.append((cx + radius * math.cos(a), cy + radius * math.sin(a), p0[2] + (p1[2] - p0[2]) * k / n))
    pts[-1] = tuple(p1)
    return pts


def _samples(poly, step):
    """Points échantillonnés le long d'une polyligne : ``(points, abscisses)``."""
    pts, ts = [], []
    s = 0.0
    for a, b in zip(poly[:-1], poly[1:]):
        length = math.sqrt(sum((b[i] - a[i]) ** 2 for i in range(3)))
        n = max(1, int(math.ceil(length / step)))
        start = 0 if not pts else 1
        for k in range(start, n + 1):
            f = k / float(n)
            pts.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f))
            ts.append(s + length * f)
        s += length
    return pts, ts


def _point_at(poly, cum, t):
    """Point de la polyligne à l'abscisse ``t``."""
    for k in range(1, len(poly)):
        if t <= cum[k] + 1e-12 or k == len(poly) - 1:
            a, b = poly[k - 1], poly[k]
            seg = cum[k] - cum[k - 1]
            f = 0.0 if seg <= 0 else min(1.0, max(0.0, (t - cum[k - 1]) / seg))
            return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f)
    return poly[-1]


def _cumulative(poly):
    cum = [0.0]
    for a, b in zip(poly[:-1], poly[1:]):
        cum.append(cum[-1] + math.sqrt(sum((b[i] - a[i]) ** 2 for i in range(3))))
    return cum


def _same(p, q):
    return p is not None and q is not None and all(abs(p[i] - q[i]) < 1e-4 for i in range(3))


def trim_commands(commands, keep, clearance, safe, plunge_feed=None, step=SAMPLE_STEP, refine=True):
    """Garde les morceaux des mouvements de coupe où ``keep`` est vrai ; retourne ``(commandes, stats)``.

    ``keep(points)`` : tableau ``(n, 3)`` -> tableau booléen ``(n,)``, appelé une fois sur tous les
    échantillons (puis sur des points isolés pour affiner les bords). ``clearance`` / ``safe`` : hauteurs de
    dégagement et de sécurité de l'opération ; ``plunge_feed`` : avance de plongée (unités de Path).
    ``stats`` : ``{"cut_in", "cut_out", "kept_moves", "links"}`` (longueurs de coupe en mm avant / après).
    """
    import Path

    np = _np()
    # 1) positions modales et polylignes des mouvements de coupe
    moves = []  # (commande, nom, p0, p1, polyligne ou None)
    pos = None
    for c in commands:
        name = c.Name.upper()
        if name not in _MOTION:
            moves.append((c, name, None, None, None))
            continue
        p = c.Parameters
        if pos is None:
            end = (p.get("X", 0.0), p.get("Y", 0.0), p.get("Z", 0.0))
            moves.append((c, name, None, end, None))
            pos = end
            continue
        end = (p.get("X", pos[0]), p.get("Y", pos[1]), p.get("Z", pos[2]))
        poly = None
        if name in ("G1", "G01"):
            poly = [pos, end]
        elif name in ("G2", "G02", "G3", "G03"):
            poly = _arc_points(pos, end, p, name in ("G2", "G02"), step)
        moves.append((c, name, pos, end, poly))
        pos = end
    # 2) un seul appel du prédicat sur tous les échantillons
    all_pts, spans = [], []
    for c, name, p0, p1, poly in moves:
        if poly is None:
            spans.append(None)
            continue
        pts, ts = _samples(poly, step)
        spans.append((len(all_pts), len(pts), ts))
        all_pts.extend(pts)
    mask = np.asarray(keep(np.array(all_pts, dtype=float)), dtype=bool) if all_pts else np.zeros(0, dtype=bool)

    def keep_one(pt):
        return bool(np.asarray(keep(np.array([pt], dtype=float)), dtype=bool)[0])

    # 3) sortie
    out = []
    pending_rapids = []  # rapides d'origine en attente : gardés seulement si la coupe suivante continue d'ici
    pos_out = None
    stats = {"cut_in": 0.0, "cut_out": 0.0, "kept_moves": 0, "links": 0}
    vfeed = {} if not plunge_feed else {"F": float(plunge_feed)}

    def link(target, feed):
        nonlocal pos_out
        stats["links"] += 1
        if pos_out is None or pos_out[2] < clearance:
            out.append(Path.Command("G0", {"Z": clearance}))
        out.append(Path.Command("G0", {"X": target[0], "Y": target[1]}))
        if target[2] < safe:
            out.append(Path.Command("G0", {"Z": safe}))
            out.append(Path.Command("G1", dict({"Z": target[2]}, **(vfeed or feed))))
        else:
            out.append(Path.Command("G0", {"Z": target[2]}))
        pos_out = target

    for (c, name, p0, p1, poly), span in zip(moves, spans):
        if p0 is None and p1 is None:
            out.append(c)  # commentaire, M, etc.
            continue
        if p0 is None:  # premier mouvement : position de départ
            pending_rapids.append((c, None, p1))
            continue
        if name in ("G0", "G00"):
            pending_rapids.append((c, p0, p1))
            continue
        start, count, ts = span
        m = mask[start:start + count]
        cum = _cumulative(poly)
        stats["cut_in"] += cum[-1]
        feed = {"F": c.Parameters["F"]} if "F" in c.Parameters else {}
        if m.all():
            if not _same(pos_out, p0):
                if _rapids_usable(pending_rapids, pos_out, p0):
                    out.extend(r for r, _s, _e in pending_rapids)
                else:
                    link(p0, feed)
            pending_rapids = []
            out.append(c)
            pos_out = p1
            stats["cut_out"] += cum[-1]
            stats["kept_moves"] += 1
            continue
        if not m.any():
            pending_rapids = []
            continue
        # morceaux gardés : suites d'échantillons vrais, bords affinés par dichotomie
        runs = []
        k = 0
        n = len(m)
        while k < n:
            if not m[k]:
                k += 1
                continue
            j = k
            while j + 1 < n and m[j + 1]:
                j += 1
            t0, t1 = ts[k], ts[j]
            if refine and k > 0:
                lo, hi = ts[k - 1], ts[k]  # lo : dehors, hi : dedans
                for _ in range(REFINE_STEPS):
                    mid = 0.5 * (lo + hi)
                    if keep_one(_point_at(poly, cum, mid)):
                        hi = mid
                    else:
                        lo = mid
                t0 = hi
            if refine and j < n - 1:
                lo, hi = ts[j], ts[j + 1]  # lo : dedans, hi : dehors
                for _ in range(REFINE_STEPS):
                    mid = 0.5 * (lo + hi)
                    if keep_one(_point_at(poly, cum, mid)):
                        lo = mid
                    else:
                        hi = mid
                t1 = lo
            if t1 > t0 + 1e-9:
                runs.append((t0, t1))
            k = j + 1
        for t0, t1 in runs:
            a = _point_at(poly, cum, t0)
            if not _same(pos_out, a):
                if t0 <= 1e-12 and _rapids_usable(pending_rapids, pos_out, a):
                    out.extend(r for r, _s, _e in pending_rapids)
                else:
                    link(a, feed)
            pending_rapids = []
            inner = [poly[i] for i in range(1, len(poly) - 1) if t0 < cum[i] < t1]
            b = _point_at(poly, cum, t1)
            for q in inner + [b]:
                out.append(Path.Command("G1", dict({"X": q[0], "Y": q[1], "Z": q[2]}, **feed)))
            pos_out = b
            stats["cut_out"] += t1 - t0
        stats["kept_moves"] += 1
        pending_rapids = []
    if pos_out is not None and pos_out[2] < clearance:
        out.append(Path.Command("G0", {"Z": clearance}))
    return out, stats


def _rapids_usable(rapids, pos_out, target):
    """Les rapides d'origine en attente relient-ils la position courante à ``target`` sans rien sauter ?"""
    if not rapids or not _same(rapids[-1][2], target):
        return False
    first = rapids[0][1]
    return pos_out is None if first is None else _same(pos_out, first)


# -- prédicats ---------------------------------------------------------------------------------------------


def polygon_keep(polygon, inside=True):
    """Prédicat « dans le polygone XY » (ou dehors) : ``polygon`` = liste de points (x, y[, z]) fermée ou non."""
    np = _np()
    poly = np.array([(p[0], p[1]) for p in polygon], dtype=float)
    if len(poly) >= 2 and np.allclose(poly[0], poly[-1]):
        poly = poly[:-1]
    if len(poly) < 3:
        raise UserError("limit to an area: the boundary needs a closed contour (at least 3 points)")
    x0, y0 = poly[:, 0], poly[:, 1]
    x1, y1 = np.roll(x0, -1), np.roll(y0, -1)

    def keep(points):
        px = points[:, 0][:, None]
        py = points[:, 1][:, None]
        crosses = ((y0[None, :] > py) != (y1[None, :] > py))
        with np.errstate(divide="ignore", invalid="ignore"):
            xint = x0[None, :] + (py - y0[None, :]) * (x1 - x0)[None, :] / (y1 - y0)[None, :]
        hit = crosses & (px < xint)
        res = (hit.sum(axis=1) % 2) == 1
        return res if inside else ~res

    def chunked(points):
        if len(points) * len(poly) <= 4_000_000:
            return keep(points)
        step = max(1, 4_000_000 // len(poly))
        return np.concatenate([keep(points[s:s + step]) for s in range(0, len(points), step)])

    return chunked


def polygon_from_shape(shape, deflection=0.05):
    """Points XY du contour fermé le plus grand d'une forme (face, fil fermé, esquisse, objet du dessin)."""
    wires = []
    for face in getattr(shape, "Faces", []):
        wires.append(face.OuterWire)
    if not wires:
        wires = [w for w in getattr(shape, "Wires", []) if w.isClosed()]
    if not wires:
        import Part

        edges = getattr(shape, "Edges", [])
        if edges:
            try:
                for w in Part.sortEdges(edges):
                    wire = Part.Wire(w)
                    if wire.isClosed():
                        wires.append(wire)
            except Exception:
                pass
    if not wires:
        raise UserError("limit to an area: select a closed contour (a face, a closed wire or a drawing contour)")
    wire = max(wires, key=lambda w: w.BoundBox.XLength * w.BoundBox.YLength)
    pts = wire.discretize(Deflection=deflection)
    return [(p.x, p.y) for p in pts]


def rectangle(xmin, ymin, xmax, ymax):
    if xmax <= xmin or ymax <= ymin:
        raise UserError("limit to an area: the rectangle is empty (min must be below max)")
    return [(xmin, ymin), (xmax, ymin), (xmax, ymax), (xmin, ymax)]


# -- habillage FreeCAD -------------------------------------------------------------------------------------


def op_heights(obj):
    """(dégagement, sécurité, avance de plongée) de l'opération sous l'habillage."""
    from .dressups import base_operation

    base = base_operation(obj)
    clearance = float(base.ClearanceHeight.Value) if hasattr(base, "ClearanceHeight") else 10.0
    safe = float(base.SafeHeight.Value) if hasattr(base, "SafeHeight") else clearance
    tc = getattr(base, "ToolController", None)
    vfeed = float(tc.VertFeed.Value) if tc is not None and hasattr(tc, "VertFeed") else None
    return clearance, max(safe, -1e9), vfeed or None


class TrimDressup(object):
    """Habillage « Limiter à une zone » : propriétés ``Base``, ``Polygon`` (points XY), ``Inside``."""

    def __init__(self, obj, base):
        obj.addProperty("App::PropertyLink", "Base", "Base", "The base path to modify")
        obj.addProperty("App::PropertyVectorList", "Polygon", "Boundary", "Boundary polygon (XY)")
        obj.addProperty("App::PropertyBool", "Inside", "Boundary", "Keep the cuts inside the boundary (else outside)")
        obj.addProperty("App::PropertyString", "BoundarySource", "Boundary", "Where the boundary comes from")
        obj.Base = base
        obj.Inside = True
        obj.Proxy = self

    def dumps(self):
        return None

    def loads(self, state):
        return None

    def execute(self, obj):
        import Path

        if obj.Base is None or not hasattr(obj.Base, "Path") or len(obj.Polygon) < 3:
            obj.Path = Path.Path()
            return
        clearance, safe, vfeed = op_heights(obj)
        cmds, _stats = trim_commands(obj.Base.Path.Commands, polygon_keep([(v.x, v.y) for v in obj.Polygon], obj.Inside),
                                     clearance, safe, vfeed)
        obj.Path = Path.Path(cmds)


class ViewProviderTrim(object):
    def __init__(self, vobj):
        vobj.Proxy = self
        self.obj = vobj.Object

    def attach(self, vobj):
        self.obj = vobj.Object

    def claimChildren(self):
        base = getattr(self.obj, "Base", None)
        return [base] if base is not None else []

    def dumps(self):
        return None

    def loads(self, state):
        return None


def add_dressup_object(project, op, suffix, proxy_factory, label):
    """Crée un habillage CAM2027 au-dessus de ``op`` (ou de son habillage le plus haut) ; il le remplace dans le
    groupe « Operations » comme les habillages FreeCAD (``dressups.add_dressup``)."""
    from . import dressups as dressupmod

    job = project.job
    base = dressupmod.base_operation(op)
    current = dressupmod.top_of(job, base)
    if any(d.Name.startswith(base.Name + suffix) for d in dressupmod.dressup_chain(current)):
        raise UserError("{op} already has this dressup", op=base.Label)
    doc = job.Document
    obj = doc.addObject("Path::FeaturePython", base.Name + suffix)
    proxy_factory(obj, current)
    obj.Label = "%s + %s" % (base.Label, label)
    group = list(job.Operations.Group)
    if current in group:
        group[group.index(current)] = obj
    else:
        group.append(obj)
    job.Operations.Group = group
    if FreeCAD.GuiUp and obj.ViewObject is not None:
        try:
            ViewProviderTrim(obj.ViewObject)
            if current.ViewObject is not None:
                current.ViewObject.Visibility = False
            obj.ViewObject.Visibility = True
        except Exception as exc:
            FreeCAD.Console.PrintWarning("CAM2027: dressup view provider: %s\n" % exc)
    return obj


def find_dressup(project, op, suffix):
    from . import dressups as dressupmod

    base = dressupmod.base_operation(op)
    for d in dressupmod.dressup_chain(dressupmod.top_of(project.job, base)):
        if d.Name.startswith(base.Name + suffix):
            return d
    return None


def set_limit(project, op, polygon=None, inside=True, source=""):
    """Ajoute ou met à jour l'habillage « Limiter à une zone » de ``op`` ; ``polygon`` None = le retirer."""
    from . import dressups as dressupmod

    existing = find_dressup(project, op, SUFFIX)
    if polygon is None:
        if existing is not None:
            dressupmod.remove_dressup(project.job, existing)
            project._renumber()
        return None
    pts = [(float(p[0]), float(p[1])) for p in polygon]
    polygon_keep(pts)  # contrôle : au moins 3 points
    obj = existing or add_dressup_object(project, op, SUFFIX, TrimDressup, tr_label(LABEL))
    obj.Polygon = [FreeCAD.Vector(x, y, 0) for x, y in pts]
    obj.Inside = bool(inside)
    obj.BoundarySource = source or ""
    project._renumber()
    obj.recompute()
    return obj


def limit_params(project, op):
    """``None`` ou ``{"polygon", "inside", "source"}`` de l'habillage « Limiter à une zone »."""
    obj = find_dressup(project, op, SUFFIX)
    if obj is None:
        return None
    return {"polygon": [(v.x, v.y) for v in obj.Polygon], "inside": bool(obj.Inside), "source": obj.BoundarySource}


def tr_label(text):
    from ..i18n import tr

    return tr(text).lower()
