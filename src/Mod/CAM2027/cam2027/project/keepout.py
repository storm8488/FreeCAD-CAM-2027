# SPDX-License-Identifier: LGPL-2.1-or-later
"""Zones interdites (« keep-out » d'Aspire 12) : boîtes que les rapides contournent par le haut.

- zones : boîtes ``Part::Box`` du groupe ``CAM2027KeepOut`` (dessinées par l'utilisateur), plus les brides du
  montage (groupe ``CAM2027Fixture``) quand le projet le demande (``AvoidClamps``) ;
- à la fin du calcul de chaque opération (``ObjectOp.execute`` de FreeCAD, complété ici), chaque rapide G0 dont
  la fraise (rayon de l'outil + marge, vu de dessus) passerait au-dessus d'une zone plus bas que son dessus +
  marge est remplacé par : montée verticale à ce Z, déplacement à ce Z, descente au point d'arrivée. Le premier
  déplacement latéral d'une opération (sa position de départ dépend de l'opération précédente) se fait au-dessus
  de toutes les zones. Les mouvements de coupe ne sont jamais modifiés ;
- une coupe (G1 / G2 / G3) qui entre dans une zone est une **erreur** : position et opération rapportées à
  l'export (bloquant) et par ``issues``.

Le parcours reste celui de FreeCAD en dehors de ces rapides. Les habillages (attaches, entrées...) recalculés
sur une opération reprennent son parcours déjà corrigé ; leurs propres rapides ne sont pas modifiés (le contrôle
de collision les voit).
"""

import math

import FreeCAD

from ..i18n import Msg

GROUP = "CAM2027KeepOut"
#: marge par défaut au-dessus et autour d'une zone (mm)
DEFAULT_MARGIN = 2.0
#: note posée sur une opération dont une coupe entre dans une zone (lue par ``issues``)
VIOLATION_PROPERTY = "KeepOutViolations"
_RAPIDS = ("G0", "G00")
_MOVES = ("G0", "G00", "G1", "G01", "G2", "G02", "G3", "G03")


# -- zones ------------------------------------------------------------------------------------------------


def _group(doc, create=False):
    group = doc.getObject(GROUP)
    if group is None and create:
        group = doc.addObject("App::DocumentObjectGroup", GROUP)
        group.Label = "Keep-out zones"
    return group


def zones(doc):
    group = _group(doc)
    return list(group.Group) if group is not None else []


def settings(doc):
    """``(marge, brides évitées)`` du document (propriétés du groupe des zones)."""
    group = _group(doc)
    if group is None:
        return DEFAULT_MARGIN, False
    return float(getattr(group, "Margin", DEFAULT_MARGIN)), bool(getattr(group, "AvoidClamps", False))


def configure(doc, margin=None, avoid_clamps=None):
    group = _group(doc, create=True)
    if "Margin" not in group.PropertiesList:
        group.addProperty("App::PropertyFloat", "Margin", "CAM2027", "Clearance above and around keep-out zones (mm)")
        group.Margin = DEFAULT_MARGIN
    if "AvoidClamps" not in group.PropertiesList:
        group.addProperty("App::PropertyBool", "AvoidClamps", "CAM2027", "Rapid moves avoid the clamps too")
        group.AvoidClamps = False
    if margin is not None:
        group.Margin = float(margin)
    if avoid_clamps is not None:
        group.AvoidClamps = bool(avoid_clamps)
    touch_operations(doc)
    return group


def add_zone(doc, xmin, ymin, xmax, ymax, ztop, zbottom=None, label=None):
    """Zone interdite rectangulaire (vue de dessus) de ``zbottom`` (par défaut ``ztop`` − 1000) à ``ztop``."""
    if xmax - xmin <= 1e-6 or ymax - ymin <= 1e-6:
        raise ValueError("empty keep-out zone")
    zbottom = float(ztop) - 1000.0 if zbottom is None else float(zbottom)
    group = configure(doc)
    box = doc.addObject("Part::Box", "KeepOut")
    box.Label = label or "Keep-out %d" % (len(group.Group) + 1)
    box.Length, box.Width, box.Height = float(xmax - xmin), float(ymax - ymin), float(ztop) - zbottom
    box.Placement = FreeCAD.Placement(FreeCAD.Vector(float(xmin), float(ymin), zbottom), FreeCAD.Rotation())
    group.addObject(box)
    if box.ViewObject is not None:
        box.ViewObject.ShapeColor = (0.8, 0.1, 0.1)
        box.ViewObject.Transparency = 70
    touch_operations(doc)
    doc.recompute()
    return box


def remove_zone(doc, box):
    group = _group(doc)
    if group is not None:
        group.removeObject(box)
    doc.removeObject(box.Name)
    touch_operations(doc)
    doc.recompute()


def obstacles(doc):
    """``[(libellé, BoundBox)]`` : zones dessinées, et brides si le projet les fait éviter."""
    from . import stock

    out = [(z.Label, z.Shape.BoundBox) for z in zones(doc) if getattr(z, "Shape", None) is not None]
    _margin, avoid = settings(doc)
    if avoid:
        out += [(c.Label, c.Shape.BoundBox) for c in stock.clamps(doc) if getattr(c, "Shape", None) is not None]
    return out


def touch_operations(doc):
    """Les zones ne sont pas des dépendances FreeCAD des opérations : les marquer à recalculer."""
    import Path.Op.Base as PathOp

    for o in doc.Objects:
        proxy = getattr(o, "Proxy", None)
        if isinstance(proxy, PathOp.ObjectOp):
            o.touch()


# -- correction des rapides --------------------------------------------------------------------------------


def _clip(x0, y0, x1, y1, rect):
    """Intervalle ``(ta, tb)`` du segment dans le rectangle (Liang-Barsky), ``None`` s'il ne le traverse pas."""
    xmin, ymin, xmax, ymax = rect
    dx, dy = x1 - x0, y1 - y0
    ta, tb = 0.0, 1.0
    for p, q in ((-dx, x0 - xmin), (dx, xmax - x0), (-dy, y0 - ymin), (dy, ymax - y0)):
        if abs(p) < 1e-12:
            if q < 0:
                return None
            continue
        t = q / p
        if p < 0:
            ta = max(ta, t)
        else:
            tb = min(tb, t)
        if ta > tb:
            return None
    return ta, tb


def blocking_top(p0, p1, boxes, reach, margin):
    """Plus haut des Z au-dessus desquels doit passer le segment p0 → p1 (pointe de la fraise) pour éviter les
    zones (élargies de ``reach`` vue de dessus) ; ``None`` s'il n'en touche aucune."""
    worst = None
    for _name, bb in boxes:
        rect = (bb.XMin - reach, bb.YMin - reach, bb.XMax + reach, bb.YMax + reach)
        span = _clip(p0[0], p0[1], p1[0], p1[1], rect)
        if span is None:
            continue
        ta, tb = span
        za = p0[2] + (p1[2] - p0[2]) * ta
        zb = p0[2] + (p1[2] - p0[2]) * tb
        if min(za, zb) < bb.ZMax + margin - 1e-6 and max(za, zb) > bb.ZMin - 1e-6:
            top = bb.ZMax + margin
            worst = top if worst is None else max(worst, top)
    return worst


def reroute(commands, boxes, radius, margin):
    """Commandes Path avec les rapides relevés au-dessus des zones ; ``(commandes, coupes_dans_une_zone)``.

    ``coupes_dans_une_zone`` : ``[(n° de commande, (x, y, z), zone)]`` (premier point de chaque zone)."""
    import Path

    if not boxes:
        return list(commands), []
    reach = radius + margin
    safe_all = max(bb.ZMax for _n, bb in boxes) + margin
    out = []
    pos = None
    known_xy = False
    hits = {}
    for index, c in enumerate(commands, 1):
        name = c.Name.upper()
        p = c.Parameters
        if name not in _MOVES:
            out.append(c)
            continue
        if pos is None:
            pos = [p.get("X", 0.0), p.get("Y", 0.0), p.get("Z", 0.0)]
            known_xy = "X" in p and "Y" in p
            if name in _RAPIDS and not known_xy and "Z" in p and p["Z"] < safe_all:
                c = Path.Command(c.Name, dict(p, Z=safe_all))  # départ inconnu : au-dessus de toutes les zones
                pos[2] = safe_all
            out.append(c)
            continue
        end = [p.get("X", pos[0]), p.get("Y", pos[1]), p.get("Z", pos[2])]
        lateral = abs(end[0] - pos[0]) > 1e-9 or abs(end[1] - pos[1]) > 1e-9
        if name in _RAPIDS and lateral:
            if not known_xy:
                top = safe_all  # la position réelle vient de l'opération précédente
            else:
                top = blocking_top(pos, end, boxes, reach, margin)
            if top is not None and min(pos[2], end[2]) < top:
                z_hop = max(top, pos[2], end[2])
                if pos[2] < z_hop:
                    out.append(Path.Command("G0", {"Z": z_hop}))
                out.append(Path.Command("G0", {"X": end[0], "Y": end[1], "Z": z_hop}))
                if end[2] < z_hop:
                    out.append(Path.Command("G0", {"Z": end[2]}))
            else:
                out.append(c)
            known_xy = True
        else:
            if name not in _RAPIDS and known_xy:
                for zone, bb in boxes:
                    if zone in hits:
                        continue
                    if _cut_touches(pos, end, c, bb, radius):
                        hits[zone] = (index, tuple(pos), zone)
            out.append(c)
            known_xy = known_xy or lateral
        pos = end
    return out, sorted(hits.values())


def _cut_touches(p0, p1, c, bb, radius):
    """Une coupe (arc pris par sa boîte englobante, prudent) entre-t-elle dans la zone élargie du rayon ?"""
    name = c.Name.upper()
    if name in ("G2", "G02", "G3", "G03"):
        p = c.Parameters
        cx, cy = p0[0] + p.get("I", 0.0), p0[1] + p.get("J", 0.0)
        r = math.hypot(p0[0] - cx, p0[1] - cy)
        from . import sim

        segs, _end = sim.path_segments([c], start=p0)
        pts = [s[1] for s in segs] + [s[2] for s in segs]
        del r, cx, cy
    else:
        pts = None
    rect = (bb.XMin - radius, bb.YMin - radius, bb.XMax + radius, bb.YMax + radius)
    pairs = [(pts[k], pts[k + 1]) for k in range(len(pts) - 1)] if pts else [(p0, p1)]
    for a, b in pairs:
        span = _clip(a[0], a[1], b[0], b[1], rect)
        if span is None:
            continue
        ta, tb = span
        za = a[2] + (b[2] - a[2]) * ta
        zb = a[2] + (b[2] - a[2]) * tb
        if min(za, zb) < bb.ZMax - 1e-6 and max(za, zb) > bb.ZMin - 1e-6:
            return True
    return False


def _tool_radius(obj):
    from . import dressups

    tc = getattr(obj, "ToolController", None) or getattr(dressups.base_operation(obj), "ToolController", None)
    tool = getattr(tc, "Tool", None) if tc is not None else None
    try:
        return float(tool.Diameter) / 2.0
    except Exception:
        return 0.0


def apply(obj):
    """Corrige le parcours de l'opération ``obj`` (appelé à la fin de son calcul)."""
    import Path

    doc = obj.Document
    if doc is None:
        return
    boxes = obstacles(doc)
    note = []
    if boxes and obj.Path is not None and obj.Path.Commands:
        margin, _avoid = settings(doc)
        original = obj.Path.Commands
        commands, hits = reroute(original, boxes, _tool_radius(obj), margin)
        if len(commands) != len(original) or any(a is not b for a, b in zip(commands, original)):
            obj.Path = Path.Path(commands)
        note = ["%d|%.3f|%.3f|%.3f|%s" % (i, q[0], q[1], q[2], zone) for i, q, zone in hits]
    if note or VIOLATION_PROPERTY in obj.PropertiesList:
        if VIOLATION_PROPERTY not in obj.PropertiesList:
            obj.addProperty("App::PropertyStringList", VIOLATION_PROPERTY, "CAM2027", "Cuts entering a keep-out zone")
            obj.setEditorMode(VIOLATION_PROPERTY, 1)
        if list(getattr(obj, VIOLATION_PROPERTY)) != note:
            setattr(obj, VIOLATION_PROPERTY, note)


def patch_operations():
    """Complète ``ObjectOp.execute`` de FreeCAD : correction des rapides après le calcul de toute opération."""
    import Path.Op.Base as PathOp

    cls = PathOp.ObjectOp
    original = cls.execute
    if getattr(original, "cam2027_keepout", False):
        return

    def execute(self, obj):
        result = original(self, obj)
        try:
            apply(obj)
        except Exception as exc:  # jamais d'opération perdue à cause du correctif
            FreeCAD.Console.PrintWarning("CAM2027 keep-out: %s\n" % exc)
        return result

    execute.cam2027_keepout = True
    cls.execute = execute


def issues(project):
    """Erreurs d'export : coupes entrant dans une zone interdite (opération, n° de commande, position)."""
    out = []
    if not project.has_job:
        return out
    for obj in project.operations():
        for raw in getattr(obj, VIOLATION_PROPERTY, None) or []:
            index, x, y, z, zone = raw.split("|", 4)
            out.append(("error", Msg("{op}: a cut enters the keep-out zone {zone}, command {n}, tip at X{x} Y{y} Z{z}",
                                     op=obj.Label, zone=zone, n=int(index), x=x, y=y, z=z)))
    return out


def zone_boxes(doc):
    """Zones dessinées ``[(libellé, BoundBox)]`` pour le contrôle de collision (les brides y sont déjà)."""
    return [(z.Label, z.Shape.BoundBox) for z in zones(doc) if getattr(z, "Shape", None) is not None]


patch_operations()
