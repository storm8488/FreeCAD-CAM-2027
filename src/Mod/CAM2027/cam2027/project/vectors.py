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
