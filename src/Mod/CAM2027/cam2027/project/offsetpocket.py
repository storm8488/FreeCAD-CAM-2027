# SPDX-License-Identifier: LGPL-2.1-or-later
"""Poche 2D par décalages (moteur CAM2027) : stratégie ``offsetpocket``.

Remplace ``Path.Op.PocketShape`` pour les poches à parois verticales : faces planes horizontales choisies (faces
générées d'un dessin, fonds de poche d'un solide), chacune réduite du rayon de la fraise (+ surépaisseur) puis
décalée vers l'intérieur pas à pas (``flatfinish.offset_loops``, OpenCascade) ; passes de l'intérieur vers
l'extérieur, la dernière longeant exactement les parois. Profondeur : de la profondeur de départ au fond de la
face (fond de poche d'un solide) ou à la profondeur finale (face d'un dessin), par pas axial ; chaque fond est
atteint dans la même opération. Entrée dans la matière en **hélice** (arcs G2) au centre de la zone la plus
large, plongée droite seulement si l'hélice ne tient pas (signalée). D'une passe à la suivante la fraise reste en
bas quand le trajet direct reste dans la zone permise.
"""

import math

import FreeCAD
import Part

from ..i18n import UserError
from . import flatfinish
from .stockrough import _helix, moves_to_commands  # noqa: F401  (mêmes mouvements : link / plunge / arc / cut)

KIND = "offsetpocket"
Z_TOL = 1e-3


def regions(base, start):
    """``[(z_fond, face polygonale)]`` depuis ``[(objet, sous-éléments)]`` : faces planes horizontales des
    objets (toutes les faces d'un objet sans sous-élément). Une face au-dessus ou au niveau de ``start`` (face
    d'un dessin posée sur le dessus du brut) n'a pas de fond propre : ``None``."""
    out = []
    for obj, subs in base or []:
        shape = getattr(obj, "Shape", None)
        if shape is None:
            continue
        names = [s for s in (subs or []) if s.startswith("Face")] or ["Face%d" % (i + 1) for i in range(len(shape.Faces))]
        for name in names:
            face = shape.getElement(name)
            if not isinstance(face.Surface, Part.Plane) or face.BoundBox.ZLength > 1e-6:
                continue
            poly = flatfinish.polygon_face(face)
            if poly is None or not poly.Faces:
                continue
            z = face.BoundBox.ZMin
            out.append((None if z >= start - Z_TOL else z, poly))
    return out


def helix_centre(region, radius, leave, limit):
    """``(rayon d'hélice, centre)`` dans la zone la plus large où l'hélice tient, sinon ``(None, None)``."""
    h = min(radius, (limit / 2.0) if limit > 0 else 0.75 * radius)
    for hr in (h, h / 2.0):
        if hr < 0.1:
            break
        core = flatfinish.inset(region, radius + leave + hr)
        faces = getattr(core, "Faces", []) if core is not None else []
        if faces:
            face = max(faces, key=lambda f: f.Area)
            c = face.CenterOfMass
            if face.isInside(c, 1e-6, True):
                return hr, (c.x, c.y)
            v = face.OuterWire.Vertexes[0].Point
            return hr, (v.x, v.y)
    return None, None


def pocket_moves(region, floor, start, final, step_down, radius, step, leave, helix_angle, helix_limit):
    """Mouvements d'une zone : ``(genre, x, y, z)`` ou ``("arc", x, y, z, i, j)`` ; retourne
    ``(mouvements, statistiques)`` (``helix`` / ``plunges`` entrées, ``narrow`` 1 si la fraise ne tient pas)."""
    stats = {"helix": 0, "plunges": 0, "narrow": 0}
    bottom = final if floor is None else max(floor, final)
    if start - bottom <= 1e-6:
        return [], stats
    loops0 = flatfinish.offset_loops(region, radius + leave, step, 0.0)
    if not loops0:
        stats["narrow"] = 1
        return [], stats
    loops0.sort(key=lambda kp: -kp[0])  # de l'intérieur vers l'extérieur
    try:
        allowed = flatfinish.inset(region, radius + leave - 1e-3)
    except Exception:
        allowed = None
    hr, centre = helix_centre(region, radius, leave, helix_limit)
    zr = region.BoundBox.ZMin  # les tests « dans la zone » se font à la hauteur de la face (isInside est 3D)
    levels = []
    z = start
    while z - step_down > bottom + 1e-6:
        z -= step_down
        levels.append(z)
    levels.append(bottom)
    moves = []
    pos = None
    z_prev = start
    for z in levels:
        loops = [(k, [(x, y, z) for x, y, _z in pts]) for k, pts in loops0]
        first = flatfinish._closest_start(loops[0][1], centre)[0] if centre else loops[0][1][0]
        # entrée : hélice au centre de la zone la plus large, depuis le niveau précédent
        if hr is not None and allowed is not None and flatfinish._inside(
                allowed, [((centre[0] + first[0]) / 2.0, (centre[1] + first[1]) / 2.0, zr)]):
            pts, arcs = _helix(centre, hr, z_prev + 0.2 if z_prev < start else start, z, helix_angle)
            moves.append(("link", pts[0][0], pts[0][1], z))
            moves.append(("plunge", pts[0][0], pts[0][1], pts[0][2]))
            moves.extend(("arc",) + a for a in arcs)
            moves.append(("plunge", centre[0], centre[1], z))
            stats["helix"] += 1
            pos = (centre[0], centre[1], z)
        else:
            pos = None
        for _k, pts in loops:
            pts = flatfinish._closest_start(pts, pos)
            s = pts[0]
            direct = (pos is not None and allowed is not None
                      and math.hypot(s[0] - pos[0], s[1] - pos[1]) <= 2.0 * step + 1e-6
                      and flatfinish._inside(allowed, [((pos[0] + s[0]) / 2.0, (pos[1] + s[1]) / 2.0, zr)]))
            if pos is not None and not direct and allowed is not None and flatfinish._inside(
                    allowed, [((pos[0] + s[0]) / 2.0, (pos[1] + s[1]) / 2.0, zr), (s[0], s[1], zr)]):
                direct = True  # liaison plus longue mais entièrement dans la zone permise (milieu et fin)
            if direct:
                moves.append(("cut", s[0], s[1], z))
            else:
                if pos is None and hr is None:
                    stats["plunges"] += 1
                moves.append(("link", s[0], s[1], z))
                moves.append(("plunge", s[0], s[1], z))
            for p in pts[1:] + [pts[0]]:
                moves.append(("cut", p[0], p[1], z))
            pos = s
        z_prev = z
    return moves, stats


# -- opération FreeCAD -------------------------------------------------------------------------------------

import Path.Op.Base as PathOp  # noqa: E402  (FreeCAD CAM : chargé seulement dans FreeCAD)


class ObjectOffsetPocket(PathOp.ObjectOp):
    """Opération ``offsetpocket`` (proxy enregistré dans le document : classe au niveau du module)."""

    def opFeatures(self, obj):
        return (PathOp.FeatureTool | PathOp.FeatureDepths | PathOp.FeatureStepDown | PathOp.FeatureHeights
                | PathOp.FeatureBaseFaces | PathOp.FeatureCoolant)

    def initOperation(self, obj):
        obj.addProperty("App::PropertyPercent", "StepOver", "Pocket", "Distance between passes, % of the tool diameter")
        obj.addProperty("App::PropertyDistance", "StockToLeave", "Pocket", "Radial stock left on the walls")
        obj.addProperty("App::PropertyAngle", "HelixAngle", "Pocket", "Ramp angle of the helical entry (deg)")
        obj.addProperty("App::PropertyDistance", "HelixDiameterLimit", "Pocket", "Maximum helix diameter (0 = automatic)")
        obj.addProperty("App::PropertyString", "Report", "Pocket", "Last computation")
        obj.StepOver = 40
        obj.StockToLeave = 0.0
        obj.HelixAngle = 3.0
        obj.HelixDiameterLimit = 0.0

    def opExecute(self, obj):
        import Path

        base = list(obj.Base or [])
        if not base:
            raise UserError("2D pocket: select the faces to pocket (drawing faces or pocket floors)")
        start = float(obj.StartDepth.Value)
        zones = regions(base, start)
        if not zones:
            raise UserError("2D pocket: no flat horizontal face in the selection")
        step = 2.0 * self.radius * max(1, min(100, int(obj.StepOver))) / 100.0
        total = {"helix": 0, "plunges": 0, "narrow": 0}
        moves = []
        for floor, region in zones:
            mv, st = pocket_moves(region, floor, start, float(obj.FinalDepth.Value), float(obj.StepDown.Value),
                                  self.radius, step, float(obj.StockToLeave.Value), float(obj.HelixAngle.Value),
                                  float(obj.HelixDiameterLimit.Value))
            moves.extend(mv)
            for k in total:
                total[k] += st[k]
        cmds = moves_to_commands(moves, obj.ClearanceHeight.Value, obj.SafeHeight.Value, self.horizFeed, self.vertFeed)
        if cmds:
            self.commandlist.append(Path.Command("G0", {"Z": obj.ClearanceHeight.Value}))
        self.commandlist.extend(cmds)
        obj.Report = "%d zone(s), %d helical entries, %d straight plunges, %d zone(s) too narrow for the tool" % (
            len(zones), total["helix"], total["plunges"], total["narrow"])
        if total["narrow"] == len(zones):
            FreeCAD.Console.PrintWarning("CAM2027 %s: every zone is narrower than the tool\n" % obj.Label)


def Create(name, obj=None, parentJob=None):
    """Comme les modules ``Path.Op.*`` : crée l'objet et son proxy dans le document actif."""
    if obj is None:
        obj = FreeCAD.ActiveDocument.addObject("Path::FeaturePython", name)
    obj.Proxy = ObjectOffsetPocket(obj, name, parentJob)
    return obj


def __getattr__(name):
    # ``operations.create_operation`` cherche le module d'interface (``Command.res``) pour le fournisseur de vue
    if name == "Command":
        from ..gui import flatpage

        return flatpage.command(KIND)
    raise AttributeError(name)
