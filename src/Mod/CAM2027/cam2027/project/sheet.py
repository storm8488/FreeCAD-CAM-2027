# SPDX-License-Identifier: LGPL-2.1-or-later
"""Usinage d'un dessin 2D dans un panneau (flux « à la Aspire »).

Le dessin (SVG, DXF) est posé sur le dessus du panneau, à **Z = 0** ; le panneau
va de ``-épaisseur`` à 0 (zéro pièce sur le dessus de la matière, usage courant
en défonceuse bois). Pour chaque vecteur fermé, une face plane ``<nom>_Face`` est
ajoutée au modèle : les stratégies qui travaillent sur des faces (poche 2D,
V-carving) l'utilisent, celles qui travaillent sur des arêtes (contour,
gravure, chanfrein) utilisent le vecteur lui-même.
"""

import FreeCAD
import Part

SHEET_NAME = "CAM2027Sheet"
FACE_SUFFIX = "_Face"


def vector_objects(doc):
    """Objets du document portant des arêtes sans solide (vecteurs importés), hors faces générées."""
    out = []
    for o in doc.Objects:
        shape = getattr(o, "Shape", None)
        if shape is None or shape.isNull() or not shape.Edges or shape.Solids:
            continue
        if o.Name.endswith(FACE_SUFFIX) or o.Name.startswith("Clone") or o.TypeId != "Part::Feature":
            continue
        out.append(o)
    return out


def closed_wires(obj):
    shape = obj.Shape
    wires = list(shape.Wires)
    if not wires and shape.Edges:
        try:
            wires = [Part.Wire(e) for e in Part.sortEdges(shape.Edges)]
        except Part.OCCError:
            wires = []
    return [w for w in wires if w.isClosed()]


def make_faces(doc, vectors):
    """Crée une face plane par vecteur fermé (trous intérieurs respectés) ; retourne les objets créés."""
    faces = []
    for o in vectors:
        wires = closed_wires(o)
        if not wires:
            continue
        try:
            face = Part.makeFace(wires, "Part::FaceMakerBullseye")
        except Exception:
            face = Part.Face(wires[0])
        f = doc.addObject("Part::Feature", o.Name + FACE_SUFFIX)
        f.Label = o.Label + FACE_SUFFIX
        f.Shape = face
        if FreeCAD.GuiUp and f.ViewObject is not None:
            f.ViewObject.Visibility = False
        faces.append(f)
    return faces


def make_sheet(doc, vectors, thickness, margin=10.0):
    """Panneau rectangulaire sous le dessin : englobe les vecteurs + ``margin``, dessus à Z = 0."""
    if thickness <= 0:
        raise ValueError("épaisseur du panneau <= 0")
    bb = None
    for o in vectors:
        bb = o.Shape.BoundBox if bb is None else bb.united(o.Shape.BoundBox)
    if bb is None:
        raise ValueError("aucun vecteur à usiner")
    if abs(bb.ZMax - bb.ZMin) > 1e-6:
        raise ValueError("le dessin n'est pas plan (Z de %.3f à %.3f)" % (bb.ZMin, bb.ZMax))
    for o in vectors:
        if abs(bb.ZMin) > 1e-9:
            o.Placement.move(FreeCAD.Vector(0, 0, -bb.ZMin))
    sheet = doc.addObject("Part::Feature", SHEET_NAME)
    sheet.Label = "Sheet %.3g mm" % thickness
    sheet.Shape = Part.makeBox(bb.XLength + 2 * margin, bb.YLength + 2 * margin, thickness,
                               FreeCAD.Vector(bb.XMin - margin, bb.YMin - margin, -thickness))
    if FreeCAD.GuiUp and sheet.ViewObject is not None:
        # parcours sous Z 0 visibles à travers le panneau
        sheet.ViewObject.Transparency = 70
        sheet.ViewObject.ShapeColor = (0.80, 0.66, 0.45)
    return sheet
