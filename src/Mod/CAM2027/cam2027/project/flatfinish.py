# SPDX-License-Identifier: LGPL-2.1-or-later
"""Finition des zones plates (Fusion « Flat », type Offset, « Multiple Depths ») : stratégie ``flat3d``.

Zones plates = faces planes horizontales **accessibles par le dessus** de la pièce : dessus de la pièce
(``top_faces``) et fonds de poche sans matière au-dessus (``pocket_floor_faces``), ou les faces sélectionnées.
Elles sont regroupées par hauteur ; à chaque hauteur, les faces voisines sont réunies, puis réduites du rayon
de la fraise (plus la surépaisseur latérale) : la fraise reste **contenue dans la zone** (Fusion « Tool
containment »). Passes décalées (offset) de l'intérieur vers l'extérieur, la dernière longeant les parois en
avalant (sens trigonométrique autour d'une poche, horaire autour d'un îlot, broche horaire), toutes **à la
hauteur exacte du plat** (+ surépaisseur axiale, 0 par défaut comme les finitions de Fusion). D'une passe à la
suivante la fraise reste en bas quand le trajet direct reste dans la zone ; sinon remontée à la hauteur de
sécurité, rapide, plongée en avance verticale.
"""

import math

import FreeCAD

from ..i18n import Msg, UserError

KIND = "flat3d"
#: tolérance de regroupement des hauteurs (mm) et déflexion de discrétisation des contours
Z_TOL = 1e-3
DEFLECTION = 0.01


def flat_faces(obj):
    """Noms des faces plates accessibles de ``obj`` : dessus de la pièce et fonds de poche dégagés."""
    from .operations import top_faces, pocket_floor_faces

    names = list(top_faces(obj))
    for name in pocket_floor_faces(obj):
        if name not in names:
            names.append(name)
    return names


def flat_regions(base):
    """``[(z, [faces])]`` du plus haut au plus bas depuis ``[(objet, sous-éléments)]`` (sans sous-élément : toutes
    les zones plates accessibles de l'objet)."""
    import Part

    groups = {}
    for obj, subs in base or []:
        shape = getattr(obj, "Shape", None)
        if shape is None or not shape.Solids:
            continue
        names = [s for s in (subs or []) if s.startswith("Face")] or flat_faces(obj)
        for name in names:
            face = shape.getElement(name)
            if not isinstance(face.Surface, Part.Plane) or face.BoundBox.ZLength > 1e-6:
                continue
            z = face.BoundBox.ZMin
            key = next((k for k in groups if abs(k - z) <= Z_TOL), z)
            groups.setdefault(key, []).append(face)
    return [(z, groups[z]) for z in sorted(groups, reverse=True)]


def _polygon_wire(wire, z, ccw=True):
    import Part

    pts = [(p.x, p.y) for p in wire.discretize(Deflection=DEFLECTION)]
    if len(pts) > 1 and math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) < 1e-7:
        pts = pts[:-1]
    if len(pts) < 3:
        return None
    if (_signed_area(pts) > 0) != ccw:
        pts.reverse()
    return Part.makePolygon([FreeCAD.Vector(x, y, z) for x, y in pts + pts[:1]])


def polygon_face(face):
    """Copie polygonale (contours discrétisés à 0,01 mm, orientation imposée) d'une face plane horizontale : les
    décalages d'OpenCascade échouent sur certaines faces trouées à bords B-spline (disque WobbleRing : « result
    of offsetting is null », ou décalage vers l'intérieur plus grand que la face)."""
    import Part

    z = face.BoundBox.ZMin
    outer = _polygon_wire(face.OuterWire, z)
    if outer is None:
        return None
    result = Part.Face(outer)
    for w in face.Wires:
        if w.isSame(face.OuterWire):
            continue
        hole = _polygon_wire(w, z)
        if hole is not None:
            result = result.cut(Part.Face(hole))
    return result


def _merged(faces):
    """Zones d'une hauteur : faces polygonales réunies (faces voisines fusionnées)."""
    polys = [p for p in (polygon_face(f) for f in faces) if p is not None and p.Faces]
    if not polys:
        return None
    if len(polys) == 1:
        return polys[0]
    fused = polys[0].multiFuse(polys[1:])
    try:
        fused = fused.removeSplitter()
    except Exception:
        pass
    return fused


def _signed_area(pts):
    return 0.5 * sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))


def _loop_points(wire, z, ccw):
    pts = [(p.x, p.y) for p in wire.discretize(Deflection=DEFLECTION)]
    if len(pts) > 1 and math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) < 1e-6:
        pts = pts[:-1]
    if len(pts) < 2:
        return None
    if (_signed_area(pts) > 0) != ccw:
        pts.reverse()
    return [(x, y, z) for x, y in pts]


def _grown(face, d):
    """``face`` grossie de ``d`` (réduite si ``d`` < 0), quelle que soit l'orientation de son contour (un contour de
    trou repris tel quel donne une face « retournée » que ``makeOffset2D`` réduit au lieu de la grossir)."""
    results = []
    for sign in (1.0, -1.0):
        try:
            r = face.makeOffset2D(sign * d, 0, False, False, False)
        except Exception:
            continue
        if r.Faces:
            results.append(r)
    if not results:
        return None
    pick = max if d > 0 else min
    return pick(results, key=lambda r: r.Area)


def inset(face, d):
    """Face réduite de ``d`` (contour extérieur vers l'intérieur, trous agrandis), jamais hors de ``face`` ; None
    si rien ne reste ou si le résultat n'est pas sûr. ``makeOffset2D`` sur une face percée donne parfois une
    forme plus grande que la face (fond hexagonal percé du disque WobbleRing : 54,9 mm² pour 26,5) : chaque
    contour est décalé seul, et le résultat est refusé s'il dépasse de la face (aire, points des contours).
    ``face`` peut être une coque ou un composé de faces planes : chacune est réduite."""
    import Part

    if d <= 0:
        return face
    if face.ShapeType != "Face":
        parts = [inset(f, d) for f in face.Faces]
        faces = [f for p in parts if p is not None for f in p.Faces]
        if not faces:
            return None
        return faces[0] if len(faces) == 1 else Part.makeCompound(faces)
    try:
        res = _grown(Part.Face(face.OuterWire), -d)
        if res is None or not res.Faces:
            return None
        for wire in face.Wires:
            if not wire.isSame(face.OuterWire):
                hole = _grown(Part.Face(wire), d)
                if hole is None:
                    return None
                res = res.cut(hole)
    except Exception:
        return None  # contour impossible à décaler : zone refusée plutôt qu'un parcours douteux
    faces = [f for f in res.Faces if f.Area > 1e-9]
    if not faces or sum(f.Area for f in faces) > face.Area + 1e-6:
        return None
    for f in faces:
        for w in f.Wires:
            for p in w.discretize(Deflection=0.05):
                if not face.isInside(p, 1e-3, True):
                    return None
    return faces[0] if len(faces) == 1 else Part.makeCompound(faces)


def offset_loops(region, offset, step, z):
    """Boucles des passes d'une zone (forme plane) : décalages successifs vers l'intérieur à partir de ``offset``,
    espacés de ``step``. Retourne ``[(niveau, points)]`` ; contours extérieurs dans le sens trigonométrique,
    contours d'îlots dans le sens horaire (avalant, broche horaire)."""
    loops = []
    k = 0
    area = region.Area
    while k < 10000:
        d = offset + k * step
        off = inset(region, d)
        faces = getattr(off, "Faces", []) if off is not None else []
        if not faces or (d > 0 and off.Area >= area - 1e-9):  # rien, ou un décalage qui ne réduit pas : arrêt
            break
        for face in faces:
            outer = face.OuterWire
            for wire in face.Wires:
                is_outer = wire.isSame(outer)
                pts = _loop_points(wire, z, ccw=is_outer)
                if pts:
                    loops.append((k, pts))
        k += 1
    return loops


def _closest_start(pts, pos):
    if pos is None:
        return pts
    i = min(range(len(pts)), key=lambda k: (pts[k][0] - pos[0]) ** 2 + (pts[k][1] - pos[1]) ** 2)
    return pts[i:] + pts[:i]


def _inside(region, points):
    for p in points:
        if not region.isInside(FreeCAD.Vector(p[0], p[1], p[2]), 1e-4, True):
            return False
    return True


def flat_moves(regions, radius, stepover, leave=0.0, axial=0.0):
    """Mouvements ``(genre, x, y, z)`` (``plunge`` / ``cut`` / ``link``, ``link`` = remontée + rapide) pour des zones
    ``[(z, [faces])]`` ; retourne aussi le nombre de zones trop étroites pour la fraise."""
    moves = []
    too_narrow = 0
    step = max(0.01, stepover)
    for z, faces in regions:
        zc = z + axial
        region = _merged(faces)
        if region is None:
            too_narrow += len(faces)
            continue
        for part in region.Faces:
            # zone permise pour le centre de la fraise : la face réduite du rayon (+ surépaisseur)
            loops = offset_loops(part, radius + leave, step, zc)
            if not loops:
                too_narrow += 1
                continue
            try:
                allowed = inset(part, radius + leave - 1e-3)
            except Exception:
                allowed = None
            loops.sort(key=lambda kp: -kp[0])  # de l'intérieur vers l'extérieur
            pos = None
            for _k, pts in loops:
                pts = _closest_start(pts, pos)
                start = pts[0]
                direct = (pos is not None and allowed is not None and abs(pos[2] - zc) < 1e-9
                          and math.hypot(start[0] - pos[0], start[1] - pos[1]) <= 2.0 * step + 1e-6
                          and _inside(allowed, [((pos[0] + start[0]) / 2.0, (pos[1] + start[1]) / 2.0, zc)]))
                if direct:
                    moves.append(("cut", start[0], start[1], zc))
                else:
                    moves.append(("link", start[0], start[1], zc))
                    moves.append(("plunge", start[0], start[1], zc))
                for p in pts[1:] + [pts[0]]:
                    moves.append(("cut", p[0], p[1], zc))
                pos = start
    return moves, too_narrow


def moves_to_commands(moves, clearance, safe, horiz_feed, vert_feed):
    """Commandes Path (avances en unités de Path) depuis ``flat_moves``."""
    import Path

    cmds = []
    z_cur = None
    for kind, x, y, z in moves:
        if kind == "link":
            cmds.append(Path.Command("G0", {"Z": clearance}))
            cmds.append(Path.Command("G0", {"X": x, "Y": y}))
            cmds.append(Path.Command("G0", {"Z": safe}))
            z_cur = safe
        elif kind == "plunge":
            cmds.append(Path.Command("G1", {"X": x, "Y": y, "Z": z, "F": vert_feed}))
            z_cur = z
        else:
            cmds.append(Path.Command("G1", {"X": x, "Y": y, "Z": z, "F": horiz_feed}))
            z_cur = z
    return cmds


# -- opération FreeCAD -------------------------------------------------------------------------------------

import Path.Op.Base as PathOp  # noqa: E402  (FreeCAD CAM : chargé seulement dans FreeCAD)


class ObjectFlat(PathOp.ObjectOp):
    """Opération ``flat3d`` (proxy enregistré dans le document : classe au niveau du module)."""

    def opFeatures(self, obj):
        return (PathOp.FeatureTool | PathOp.FeatureDepths | PathOp.FeatureHeights | PathOp.FeatureBaseFaces
                | PathOp.FeatureCoolant)

    def initOperation(self, obj):
        obj.addProperty("App::PropertyPercent", "StepOver", "Flat", "Distance between passes, % of the tool diameter")
        obj.addProperty("App::PropertyDistance", "StockToLeave", "Flat", "Radial stock to leave on the walls")
        obj.addProperty("App::PropertyDistance", "DepthOffset", "Flat", "Axial stock to leave on the flats")
        obj.addProperty("App::PropertyString", "Report", "Flat", "Last computation")
        obj.StepOver = 40
        obj.StockToLeave = 0.0
        obj.DepthOffset = 0.0

    def opExecute(self, obj):
        import Path

        base = list(obj.Base or []) or [(m, []) for m in self.model]
        regions = flat_regions(base)
        if not regions:
            obj.Report = "no flat horizontal area reachable from above"
            FreeCAD.Console.PrintWarning("CAM2027 %s: no flat horizontal area reachable from above\n" % obj.Label)
            return
        step = 2.0 * self.radius * max(1, min(100, int(obj.StepOver))) / 100.0
        moves, narrow = flat_moves(regions, self.radius, step, float(obj.StockToLeave.Value),
                                   float(obj.DepthOffset.Value))
        cmds = moves_to_commands(moves, obj.ClearanceHeight.Value, obj.SafeHeight.Value, self.horizFeed, self.vertFeed)
        if cmds:
            self.commandlist.append(Path.Command("G0", {"Z": obj.ClearanceHeight.Value}))
        self.commandlist.extend(cmds)
        obj.Report = "%d flat height(s), %d zone(s) too narrow for the tool" % (len(regions), narrow)


def Create(name, obj=None, parentJob=None):
    """Comme les modules ``Path.Op.*`` : crée l'objet et son proxy dans le document actif."""
    if obj is None:
        obj = FreeCAD.ActiveDocument.addObject("Path::FeaturePython", name)
    obj.Proxy = ObjectFlat(obj, name, parentJob)
    return obj


def check_flats(models):
    """Refus clair quand la pièce n'a aucune zone plate accessible (dôme seul)."""
    if not flat_regions([(m, []) for m in models]):
        raise UserError("flat finishing: no flat horizontal area reachable from above on the part (nothing to do)")


def __getattr__(name):
    # ``operations.create_operation`` cherche le module d'interface (``Command.res``) pour le fournisseur de vue
    if name == "Command":
        from ..gui import flatpage

        return flatpage.command(KIND)
    raise AttributeError(name)
