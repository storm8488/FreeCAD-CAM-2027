# SPDX-License-Identifier: LGPL-2.1-or-later
"""Dessin vectoriel dans l'atelier (Aspire « Drawing ») : texte, texte sur courbe, décalage, union /
soustraction / intersection, miroir, copies circulaires.

Géométrie Part de FreeCAD (``Part.makeWireString`` est le moteur de ``Draft.ShapeString``,
``makeOffset2D`` celui de ``Draft.make_offset``, booléens Part) ; chaque résultat est un vecteur du dessin
(``Part::Feature`` de fils fermés à Z 0), usinable comme un SVG importé. Si le job du panneau existe déjà,
sa face et ses clones sont ajoutés au modèle du job.
"""

import math
import os

import FreeCAD
import Part

from ..i18n import UserError
from . import sheet as sheetmod

V = FreeCAD.Vector

#: polices proposées (Windows) en plus de celle livrée avec FreeCAD
SYSTEM_FONTS = (("Arial", "arial.ttf"), ("Arial Black", "ariblk.ttf"), ("Times New Roman", "times.ttf"),
                ("Courier New", "cour.ttf"), ("Verdana", "verdana.ttf"), ("Georgia", "georgia.ttf"),
                ("Impact", "impact.ttf"), ("Comic Sans MS", "comic.ttf"), ("Segoe UI", "segoeui.ttf"))


def fonts():
    """``[(nom, chemin)]`` des polices disponibles ; la première est celle livrée avec FreeCAD (osifont)."""
    out = []
    bundled = os.path.join(FreeCAD.getResourceDir(), "Mod", "TechDraw", "Resources", "fonts", "osifont-lgpl3fe.ttf")
    if os.path.isfile(bundled):
        out.append(("osifont", bundled))
    windir = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    for name, fname in SYSTEM_FONTS:
        path = os.path.join(windir, fname)
        if os.path.isfile(path):
            out.append((name, path))
    return out


def default_font():
    found = fonts()
    if not found:
        raise UserError("no TrueType font found: choose a .ttf file")
    return found[0][1]


# -- texte -------------------------------------------------------------------------------------------------


def _glyphs(text, font, size, tracking=0.0):
    """Fils de chaque caractère (liste par caractère, vide pour une espace), ligne de base Y 0."""
    if not text.strip():
        raise UserError("the text is empty")
    if size <= 0:
        raise UserError("the text size must be above 0")
    font = font or default_font()
    if not os.path.isfile(font):
        raise UserError("font file not found: {file}", file=font)
    # contours de police en B-splines : polygones à 0,01 mm (décalages et fusions OCC fiables, G1 en sortie)
    return [[_polygon_wire(w) for w in chars] for chars in Part.makeWireString(text, font, float(size), float(tracking))]


def _polygon_wire(wire, deflection=None):
    pts = wire.discretize(Deflection=deflection or POLYGON_DEFLECTION)
    if (pts[0] - pts[-1]).Length > 1e-9:
        pts.append(pts[0])
    return Part.makePolygon([V(p.x, p.y, 0.0) for p in pts])


def text_shape(text, font=None, size=10.0, tracking=0.0, origin=(0.0, 0.0)):
    """Texte en lignes droites ; ``origin`` = début de la ligne de base."""
    wires = [w for chars in _glyphs(text, font, size, tracking) for w in chars]
    comp = Part.Compound(wires)
    comp.translate(V(origin[0], origin[1], 0))
    return comp


def arc_rail(center, radius, span_deg=180.0, top=True):
    """Arc de lecture pour un texte : de gauche à droite, centré en haut (``top``) ou en bas du cercle."""
    cx, cy = center
    half = math.radians(span_deg) / 2.0
    mid = math.pi / 2 if top else -math.pi / 2
    a0, a1 = (mid + half, mid - half) if top else (mid - half, mid + half)
    pts = [V(cx + radius * math.cos(a), cy + radius * math.sin(a), 0) for a in (a0, mid, a1)]
    return Part.Edge(Part.Arc(*pts))


def _rail_edge(rail):
    if isinstance(rail, Part.Edge):
        return rail
    edges = rail.Edges
    if len(edges) == 1:
        return edges[0]
    wire = Part.Wire(Part.__sortEdges__(edges)) if hasattr(Part, "__sortEdges__") else Part.Wire(edges)
    return Part.Edge(wire.approximate(1e-4, 1e-3, 50, 25))


def text_on_curve(text, rail, font=None, size=10.0, tracking=0.0, offset=0.0, align="center", below=False):
    """Texte posé sur une courbe (arête ou fil) : chaque caractère tourné sur la tangente au point de la
    courbe à son abscisse, ligne de base sur la courbe (``below`` : texte sous la courbe, ligne de base
    décalée de la hauteur du texte). ``align`` : « left » (début de courbe + ``offset``) ou « center »."""
    edge = _rail_edge(rail)
    glyphs = _glyphs(text, font, size, tracking)
    boxes = [Part.Compound(chars).BoundBox if chars else None for chars in glyphs]
    xs = [b.XMax for b in boxes if b is not None]
    width = max(xs) if xs else 0.0
    length = edge.Length
    if width > length + 1e-6:
        raise UserError("the text ({w:.1f} mm) is longer than the curve ({l:.1f} mm)", w=width, l=length)
    start = offset if align == "left" else (length - width) / 2.0 + offset
    out = []
    for chars, bb in zip(glyphs, boxes):
        if not chars:
            continue
        xc = (bb.XMin + bb.XMax) / 2.0
        s = min(max(start + xc, 0.0), length)
        u = edge.getParameterByLength(s)
        p = edge.valueAt(u)
        t = edge.tangentAt(u)
        angle = math.degrees(math.atan2(t.y, t.x))
        for w in chars:
            w = w.copy()
            w.translate(V(-xc, -size if below else 0.0, 0))
            w.rotate(V(0, 0, 0), V(0, 0, 1), angle)
            w.translate(V(p.x, p.y, 0))
            out.append(w)
    return Part.Compound(out)


# -- opérations sur les vecteurs ------------------------------------------------------------------------


def closed_wires_of(shape):
    wires = [w for w in shape.Wires if w.isClosed()]
    if not wires and shape.Edges:
        try:
            wires = [Part.Wire(e) for e in Part.sortEdges(shape.Edges)]
        except Part.OCCError:
            wires = []
        wires = [w for w in wires if w.isClosed()]
    return wires


def faces_of(shape):
    """Faces planes des fils fermés (trous respectés), fusionnées."""
    wires = closed_wires_of(shape)
    if not wires:
        raise UserError("the drawing has no closed vector")
    face = Part.makeFace(wires, "Part::FaceMakerBullseye")
    return face


#: écart maximal entre une courbe et son contour polygonal de repli (décalage)
POLYGON_DEFLECTION = 0.01


def _polygonal(face, deflection=POLYGON_DEFLECTION):
    """Même face, fils remplacés par des polygones à ``deflection`` mm au plus de la courbe."""
    return Part.makeFace([_polygon_wire(w, deflection) for w in face.Wires], "Part::FaceMakerBullseye")


def _outline(faces):
    """Fils des faces (contours extérieurs et trous), à Z 0."""
    faces = faces.Faces if hasattr(faces, "Faces") else faces
    wires = [w for f in faces for w in f.Wires]
    if not wires:
        raise UserError("the result is empty")
    return Part.Compound(wires)


def _bottom_faces(solid):
    """Faces à Z 0 d'un solide extrudé de Z 0 à Z 1 : le résultat 2D d'un booléen."""
    try:
        solid = solid.removeSplitter()
    except Exception:
        pass
    return [f for f in solid.Faces if f.BoundBox.ZMax < 1e-6 and f.Area > 1e-9]


def _prism(faces):
    """Solides extrudés de 1 mm : les booléens de faces planes d'OCC découpent sans réunir (removeSplitter
    sans effet sur des faces), ceux de solides réunissent (lettres qui se touchent après décalage)."""
    faces = faces.Faces if hasattr(faces, "Faces") else faces
    return [f.extrude(V(0, 0, 1)) for f in faces if f.Area > 1e-9]


def _fused(face_list):
    solids = _prism(face_list)
    if not solids:
        raise UserError("the result is empty")
    out = solids[0].fuse(solids[1:]) if len(solids) > 1 else solids[0]
    return _bottom_faces(out)


def offset(shape, distance, corners="round"):
    """Décalage des vecteurs fermés de ``distance`` mm (> 0 vers l'extérieur, < 0 vers l'intérieur) ; les
    formes qui se recouvrent après décalage sont réunies (lettres d'un texte)."""
    if abs(distance) < 1e-9:
        raise UserError("the offset distance is 0")
    face = faces_of(shape)
    join = {"round": 0, "sharp": 2}.get(corners, 0)
    result = []
    for f in face.Faces:
        try:
            off = f.makeOffset2D(float(distance), join, False, False, False)
        except Exception:  # B-splines de police : OCC rend un décalage nul ; contour polygonal à 0,01 mm
            try:
                off = _polygonal(f).makeOffset2D(float(distance), join, False, False, False)
            except Exception:
                continue
        result.extend(off.Faces)
    if not result:
        raise UserError("the offset of {d} mm leaves nothing", d="%g" % distance)
    return _outline(_fused(result))


def boolean(a, b, mode):
    """« union », « subtract » (a moins b) ou « intersect » des surfaces fermées de deux vecteurs."""
    sa, sb = _prism(faces_of(a)), _prism(faces_of(b))
    A = sa[0].fuse(sa[1:]) if len(sa) > 1 else sa[0]
    B = sb[0].fuse(sb[1:]) if len(sb) > 1 else sb[0]
    if mode == "union":
        res = A.fuse(B)
    elif mode == "subtract":
        res = A.cut(B)
    elif mode == "intersect":
        res = A.common(B)
    else:
        raise ValueError(mode)
    faces = _bottom_faces(res)
    if not faces:
        raise UserError("the result is empty")
    return _outline(faces)


def mirror(shape, axis="x", center=None):
    """Miroir autour d'une droite verticale (``axis`` « x » : gauche-droite) ou horizontale (« y »)
    passant par ``center`` (défaut : centre de la boîte du dessin)."""
    bb = shape.BoundBox
    c = V(center[0], center[1], 0) if center is not None else V(bb.Center.x, bb.Center.y, 0)
    normal = V(1, 0, 0) if axis == "x" else V(0, 1, 0)
    return shape.mirror(c, normal)


def circular_copies(shape, count, center=(0.0, 0.0), total_deg=360.0, include_original=True):
    """``count`` exemplaires tournés autour de ``center`` sur ``total_deg`` (360 : répartis sur le tour)."""
    count = int(count)
    if count < 2:
        raise UserError("at least 2 copies")
    step = total_deg / count if abs(total_deg - 360.0) < 1e-9 else total_deg / (count - 1)
    out = []
    for i in range(0 if include_original else 1, count):
        s = shape.copy()
        s.rotate(V(center[0], center[1], 0), V(0, 0, 1), step * i)
        out.append(s)
    return Part.Compound(out)


# -- vecteurs du document ----------------------------------------------------------------------------------


def add_vector(proj, shape, label, layer=""):
    """Nouveau vecteur du dessin ; avec un job : sa face (vecteur fermé) et leurs clones dans le modèle."""
    doc = proj.doc
    bb = shape.BoundBox
    if abs(bb.ZMin) > 1e-6 or abs(bb.ZMax) > 1e-6:
        shape = shape.copy()
        shape.translate(V(0, 0, -bb.ZMin))
    obj = doc.addObject("Part::Feature", "Vector")
    obj.Label = label
    obj.Shape = shape
    if layer:
        from . import templates

        templates.set_layer(obj, layer)
    if FreeCAD.GuiUp and obj.ViewObject is not None:
        obj.ViewObject.LineColor = (0.10, 0.10, 0.10)
        obj.ViewObject.LineWidth = 2.0
    if proj.has_job:
        import Path.Main.Job as PathJob

        job = proj.job
        faces = sheetmod.make_faces(doc, [obj])
        for o in [obj] + faces:
            job.Model.addObject(PathJob.createModelResourceClone(job, o))
    doc.recompute()
    return obj


# -- formes de base et vecteurs paramétriques [C4] ----------------------------------------------------------------
#
# Un vecteur dessiné dans l'atelier est un objet ``Part::FeaturePython`` (``ParametricVector``) qui garde ses
# réglages (texte, police, rectangle, cercle, polygone, nœuds d'une polyligne) et recalcule sa forme ; sa face
# (``VectorFace``, même nom + ``_Face``) suit la source, les clones du job aussi (``Draft.clone``). Modifier le
# vecteur puis recalculer met à jour les opérations qui l'usinent (``refresh_operations`` : sous-éléments repris
# quand le nombre de faces change, un texte qui gagne une lettre par exemple).

KINDS = ("text", "rectangle", "circle", "polygon", "polyline")
LAYOUTS = ("line", "arc", "curve")

#: réglages de chaque genre : (propriété, type FreeCAD, valeur par défaut)
PROPERTIES = {
    "text": (("Text", "App::PropertyString", "CAM2027"), ("Font", "App::PropertyString", ""),
             ("Size", "App::PropertyFloat", 10.0), ("Tracking", "App::PropertyFloat", 0.0),
             ("Layout", "App::PropertyString", "line"), ("X", "App::PropertyFloat", 0.0),
             ("Y", "App::PropertyFloat", 0.0), ("ArcRadius", "App::PropertyFloat", 40.0),
             ("ArcSpan", "App::PropertyFloat", 180.0), ("Below", "App::PropertyBool", False),
             ("Rail", "App::PropertyLink", None)),
    "rectangle": (("X", "App::PropertyFloat", 0.0), ("Y", "App::PropertyFloat", 0.0),
                  ("Width", "App::PropertyFloat", 50.0), ("Height", "App::PropertyFloat", 30.0),
                  ("CornerRadius", "App::PropertyFloat", 0.0), ("Angle", "App::PropertyFloat", 0.0)),
    "circle": (("X", "App::PropertyFloat", 0.0), ("Y", "App::PropertyFloat", 0.0),
               ("Radius", "App::PropertyFloat", 20.0)),
    "polygon": (("X", "App::PropertyFloat", 0.0), ("Y", "App::PropertyFloat", 0.0),
                ("Radius", "App::PropertyFloat", 20.0), ("Sides", "App::PropertyInteger", 6),
                ("Angle", "App::PropertyFloat", 0.0)),
    "polyline": (("Points", "App::PropertyVectorList", None), ("Closed", "App::PropertyBool", True)),
}


def rectangle_shape(x, y, width, height, corner=0.0, angle=0.0):
    """Rectangle centré en (x, y), angles arrondis de ``corner`` mm, tourné de ``angle`` degrés."""
    if width <= 0 or height <= 0:
        raise UserError("the rectangle width and height must be above 0")
    if corner < 0 or (corner > 0 and corner >= min(width, height) / 2.0 - 1e-9):
        raise UserError("the corner radius must be less than half the smaller side ({m} mm)",
                        m="%g" % (min(width, height) / 2.0))
    w, h = width / 2.0 - corner, height / 2.0 - corner
    wire = Part.makePolygon([V(x - w, y - h, 0), V(x + w, y - h, 0), V(x + w, y + h, 0), V(x - w, y + h, 0),
                             V(x - w, y - h, 0)])
    if corner > 0:  # côtés exacts, coins en arcs de cercle
        wire = Part.Face(wire).makeOffset2D(corner, 0, False, False, False).Wires[0]
    if angle:
        wire.rotate(V(x, y, 0), V(0, 0, 1), angle)
    return Part.Compound([wire])


def circle_shape(x, y, radius):
    if radius <= 0:
        raise UserError("the circle radius must be above 0")
    return Part.Compound([Part.Wire(Part.makeCircle(radius, V(x, y, 0)))])


def polygon_shape(x, y, radius, sides, angle=0.0):
    """Polygone régulier inscrit dans le cercle de ``radius`` mm, premier sommet en haut (tourné de ``angle``)."""
    sides = int(sides)
    if sides < 3:
        raise UserError("a polygon needs at least 3 sides")
    if radius <= 0:
        raise UserError("the polygon radius must be above 0")
    a0 = math.pi / 2 + math.radians(angle)
    pts = [V(x + radius * math.cos(a0 + 2 * math.pi * i / sides), y + radius * math.sin(a0 + 2 * math.pi * i / sides), 0)
           for i in range(sides)]
    return Part.Compound([Part.makePolygon(pts + pts[:1])])


def polyline_shape(points, closed=True):
    """Polyligne de nœuds ``[(x, y)]`` (fermée : le dernier nœud rejoint le premier)."""
    pts = []
    for p in points:
        q = V(float(p[0]), float(p[1]), 0)
        if not pts or (q - pts[-1]).Length > 1e-6:
            pts.append(q)
    if closed and len(pts) > 1 and (pts[0] - pts[-1]).Length <= 1e-6:
        pts.pop()
    if len(pts) < (3 if closed else 2):
        raise UserError("the shape needs at least {n} distinct nodes", n=3 if closed else 2)
    wire = Part.makePolygon(pts + (pts[:1] if closed else []))
    if closed and Part.Face(wire).Area < 1e-9:
        raise UserError("the closed shape has no area (nodes in line)")
    return Part.Compound([wire])


def build_shape(kind, p):
    """Forme d'un vecteur paramétrique depuis ses réglages ``p`` (dict ; ``Rail`` : forme du rail), placement
    appliqué à la géométrie (un placement de forme deviendrait celui de l'objet et s'ajouterait au suivant)."""
    shape = _build_shape(kind, p).copy()
    if not shape.Placement.isIdentity():
        m = shape.Placement.toMatrix()
        shape.Placement = FreeCAD.Placement()
        shape.transformShape(m, True)  # copie de la géométrie : placement neutre, arcs et droites gardés
    return shape


def _build_shape(kind, p):
    if kind == "text":
        layout = p.get("Layout", "line")
        args = (p["Text"], p.get("Font") or None, p["Size"], p.get("Tracking", 0.0))
        if layout == "line":
            return text_shape(*args, origin=(p["X"], p["Y"]))
        if layout == "arc":
            rail = arc_rail((p["X"], p["Y"]), p["ArcRadius"], p["ArcSpan"], top=not p.get("Below"))
            return text_on_curve(args[0], rail, *args[1:], below=bool(p.get("Below")))
        if layout == "curve":
            if p.get("Rail") is None:
                raise UserError("the text has no curve to follow")
            return text_on_curve(args[0], p["Rail"], *args[1:])
        raise UserError("unknown text layout {layout}", layout=layout)
    if kind == "rectangle":
        return rectangle_shape(p["X"], p["Y"], p["Width"], p["Height"], p.get("CornerRadius", 0.0), p.get("Angle", 0.0))
    if kind == "circle":
        return circle_shape(p["X"], p["Y"], p["Radius"])
    if kind == "polygon":
        return polygon_shape(p["X"], p["Y"], p["Radius"], p["Sides"], p.get("Angle", 0.0))
    if kind == "polyline":
        return polyline_shape([(q[0], q[1]) for q in p["Points"]], p.get("Closed", True))
    raise UserError("unknown vector kind {kind}", kind=kind)


def is_parametric(obj):
    return obj is not None and isinstance(getattr(obj, "Proxy", None), ParametricVector)


def params_of(obj):
    """Réglages d'un vecteur paramétrique (dict) ; ``Rail`` donné en forme, ``Points`` en ``(x, y)``."""
    p = {}
    for name, _type, _default in PROPERTIES[obj.VectorKind]:
        value = getattr(obj, name)
        if name == "Rail":
            value = value.Shape if value is not None else None
        elif name == "Points":
            value = [(v.x, v.y) for v in value]
        p[name] = value
    return p


class ParametricVector(object):
    """Proxy d'un vecteur dessiné : forme recalculée depuis ses réglages."""

    def __init__(self, obj, kind):
        obj.Proxy = self
        obj.addProperty("App::PropertyString", "VectorKind", "CAM2027 vector", "Kind of drawing vector")
        obj.VectorKind = kind
        obj.setEditorMode("VectorKind", 1)
        self.add_properties(obj)

    @staticmethod
    def add_properties(obj):
        for name, typ, default in PROPERTIES[obj.VectorKind]:
            if name not in obj.PropertiesList:
                obj.addProperty(typ, name, "CAM2027 vector", name)
                if default is not None:
                    setattr(obj, name, default)

    def execute(self, obj):
        # forme sans placement : FreeCAD lui applique celui de l'objet (vecteur déplacé par l'imbrication)
        obj.Shape = build_shape(obj.VectorKind, params_of(obj))

    def onDocumentRestored(self, obj):
        self.add_properties(obj)

    def dumps(self):
        return None

    def loads(self, state):
        return None


class VectorFace(object):
    """Proxy de la face d'un vecteur fermé : suit la source (``Source``)."""

    def __init__(self, obj, source):
        obj.Proxy = self
        obj.addProperty("App::PropertyLink", "Source", "CAM2027 vector", "Drawing vector of this face")
        obj.Source = source

    def execute(self, obj):
        src = obj.Source
        if src is None:
            return
        wires = closed_wires_of(src.Shape)
        if not wires:
            raise UserError("{name}: no closed contour left, the face cannot follow", name=src.Label)
        obj.Shape = Part.makeFace(wires, "Part::FaceMakerBullseye")

    def dumps(self):
        return None

    def loads(self, state):
        return None


def add_parametric(proj, kind, label, layer="", **params):
    """Nouveau vecteur paramétrique ``kind`` ; réglages vérifiés avant la création (``UserError`` sinon).
    Avec un job : sa face (si fermé) et leurs clones dans le modèle, comme ``add_vector``."""
    if kind not in KINDS:
        raise UserError("unknown vector kind {kind}", kind=kind)
    p = dict(((n, d) for n, _t, d in PROPERTIES[kind]), **params)
    check = dict(p)
    if check.get("Rail") is not None:
        check["Rail"] = check["Rail"].Shape
    shape = build_shape(kind, check)
    doc = proj.doc
    obj = doc.addObject("Part::FeaturePython", "Vector")
    ParametricVector(obj, kind)
    obj.Label = label
    for name, value in p.items():
        if value is None:
            continue
        if name == "Points":
            value = [V(q[0], q[1], 0) for q in value]
        setattr(obj, name, value)
    obj.Shape = shape
    if layer:
        from . import templates

        templates.set_layer(obj, layer)
    _attach_view(obj)
    doc.recompute()
    if proj.has_job:  # comme add_vector : la face (si fermé) et les clones avec le job seulement
        import Path.Main.Job as PathJob

        job = proj.job
        for o in [obj] + sheetmod.make_faces(doc, [obj]):
            job.Model.addObject(PathJob.createModelResourceClone(job, o))
    doc.recompute()
    return obj


def make_face(doc, obj):
    """Face paramétrique d'un vecteur dessiné (``sheet.make_faces``) : suit le vecteur ; None s'il n'est pas fermé."""
    if not closed_wires_of(obj.Shape):
        return None
    face = doc.addObject("Part::FeaturePython", obj.Name + sheetmod.FACE_SUFFIX)
    VectorFace(face, obj)
    face.Label = obj.Label + sheetmod.FACE_SUFFIX
    if FreeCAD.GuiUp and face.ViewObject is not None:
        face.ViewObject.Proxy = 0
        face.ViewObject.Visibility = False
    face.recompute()
    return face


def _attach_view(obj):
    if not FreeCAD.GuiUp or obj.ViewObject is None:
        return
    try:
        from ..gui.vectors import ViewProviderVector

        ViewProviderVector(obj.ViewObject)
    except Exception:
        obj.ViewObject.Proxy = 0
    obj.ViewObject.LineColor = (0.10, 0.10, 0.10)
    obj.ViewObject.LineWidth = 2.0


def update_parametric(proj, obj, **params):
    """Change les réglages d'un vecteur paramétrique (vérifiés d'abord), recalcule le dessin et les opérations
    qui l'usinent. Retourne les opérations touchées."""
    if not is_parametric(obj):
        raise UserError("{name} is not a vector drawn in CAM2027 (imported vectors cannot be edited)", name=obj.Label)
    p = dict(params_of(obj))
    for name, value in params.items():
        p[name] = value.Shape if name == "Rail" and value is not None else value
    shape = build_shape(obj.VectorKind, p)
    if proj.doc.getObject(obj.Name + sheetmod.FACE_SUFFIX) is not None and not closed_wires_of(shape):
        raise UserError("{name} is machined as a closed shape: it must stay closed", name=obj.Label)
    for name, value in params.items():
        if name == "Points":
            value = [V(q[0], q[1], 0) for q in value]
        setattr(obj, name, value)
    return refresh_operations(proj, obj)


def nodes(obj):
    """Nœuds ``[(x, y)]`` d'un vecteur paramétrique à côtés droits (polyligne, rectangle sans arrondi,
    polygone) ; ``UserError`` sinon."""
    if not is_parametric(obj):
        raise UserError("{name} is not a vector drawn in CAM2027 (imported vectors cannot be edited)", name=obj.Label)
    if obj.VectorKind == "polyline":
        return [(v.x, v.y) for v in obj.Points]
    if obj.VectorKind not in ("rectangle", "polygon") or (obj.VectorKind == "rectangle" and obj.CornerRadius > 0):
        raise UserError("only straight-sided shapes (rectangle without rounded corners, polygon, line) have nodes")
    return [(v.Point.x, v.Point.y) for v in obj.Shape.Wires[0].OrderedVertexes]


def set_nodes(proj, obj, points, closed=None):
    """Remplace les nœuds (déplacés, supprimés) ; un rectangle ou un polygone devient une polyligne (même
    forme tant qu'aucun nœud ne bouge). Opérations recalculées comme ``update_parametric``."""
    nodes(obj)  # vérifie que le vecteur a des nœuds
    closed = obj.Closed if obj.VectorKind == "polyline" and closed is None else (True if closed is None else closed)
    polyline_shape(points, closed)  # vérifié avant de toucher l'objet
    if obj.VectorKind != "polyline":
        for name, _t, _d in PROPERTIES[obj.VectorKind]:
            obj.removeProperty(name)
        obj.VectorKind = "polyline"
        ParametricVector.add_properties(obj)
    return update_parametric(proj, obj, Points=list(points), Closed=closed)


def move_node(proj, obj, index, x, y):
    pts = nodes(obj)
    if not 0 <= index < len(pts):
        raise UserError("no node {n}", n=index + 1)
    pts[index] = (x, y)
    return set_nodes(proj, obj, pts)


def delete_node(proj, obj, index):
    pts = nodes(obj)
    if not 0 <= index < len(pts):
        raise UserError("no node {n}", n=index + 1)
    del pts[index]
    return set_nodes(proj, obj, pts)


def _clone_source(obj):
    for attr in ("Objects", "Base"):
        inner = getattr(obj, attr, None)
        if isinstance(inner, list) and len(inner) == 1:
            inner = inner[0]
        if inner is not None and hasattr(inner, "Shape") and hasattr(inner, "Name"):
            return inner
    return obj


def refresh_operations(proj, vector):
    """Opérations dont la géométrie vient de ``vector`` (ou de sa face, ou de leurs clones) : sous-éléments
    « toutes les faces » / « toutes les arêtes » repris sur la nouvelle forme (le nombre de lettres d'un texte
    peut changer), puis recalcul du document. Retourne les opérations touchées."""
    names = {vector.Name, vector.Name + sheetmod.FACE_SUFFIX}
    # 1. opérations ramenées au premier élément (toujours présent) : FreeCAD ne cherche pas à suivre « Face2 »
    #    quand le clone change de forme (élément disparu « ?Face2 », message d'erreur)
    plans = []
    for op in (proj.operations() if proj.has_job else []):
        base = getattr(op, "Base", None)
        if not isinstance(base, list) or not base:
            continue
        entries, changed = [], False
        for o, subs in base:
            subs = tuple(s.lstrip("?") for s in subs)
            kind = None
            if _clone_source(o).Name in names and subs:
                kind = "Face" if all(s.startswith("Face") for s in subs) else (
                    "Edge" if all(s.startswith("Edge") for s in subs) else None)
            changed = changed or _clone_source(o).Name in names
            entries.append((o, subs, kind))
        if changed:
            op.Base = [(o, (kind + "1",) if kind else subs) for o, subs, kind in entries]
            plans.append((op, entries))
    # 2. le dessin, sa face et leurs clones
    for o in [vector, proj.doc.getObject(vector.Name + sheetmod.FACE_SUFFIX)] + [
            c for c in proj.doc.Objects if c.Name.startswith("Clone") and _clone_source(c).Name in names]:
        if o is not None:
            o.touch()
            o.recompute()
    # 3. tous les éléments de la nouvelle forme, puis recalcul des opérations
    for op, entries in plans:
        new = []
        for o, subs, kind in entries:
            if kind:
                count = len(o.Shape.Faces) if kind == "Face" else len(o.Shape.Edges)
                subs = tuple("%s%d" % (kind, i + 1) for i in range(count))
            new.append((o, subs))
        op.Base = new
        op.touch()
    proj.doc.recompute()
    return [op for op, _e in plans]
