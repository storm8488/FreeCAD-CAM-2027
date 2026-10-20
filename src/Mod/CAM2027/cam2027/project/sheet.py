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
        if o.Name.endswith(("_Preview", "_FlatArea")):  # aperçu d'enroulement, zone de fond plat : pas des dessins
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


#: stratégies qui attendent une face (les autres prennent les arêtes du vecteur)
FACE_STRATEGIES = ("pocket2d", "vcarve", "pocket", "adaptive", "millface")


def expand_drawing_base(doc, kind, base):
    """Remplace un vecteur sélectionné « entier » par ce que la stratégie attend.

    ``base`` : liste ``(objet, sous-éléments)``. Un vecteur sans sous-élément devient sa face
    générée (``Face1``) pour une stratégie à faces, ou toutes ses arêtes sinon. Une face générée
    sélectionnée entière devient ``Face1``. Le reste est inchangé.
    """
    out = []
    for obj, subs in base or []:
        subs = list(subs)
        source = obj
        # clone du job -> objet source
        for attr in ("Objects", "Base"):
            inner = getattr(obj, attr, None)
            if isinstance(inner, list) and len(inner) == 1:
                inner = inner[0]
            if inner is not None and hasattr(inner, "Shape") and hasattr(inner, "Name"):
                source = inner
                break
        is_face_obj = source.Name.endswith(FACE_SUFFIX)
        is_vector = (not is_face_obj and source.TypeId == "Part::Feature" and source.Shape.Edges
                     and not source.Shape.Solids and not source.Shape.Faces)
        if subs or not (is_vector or is_face_obj):
            out.append((obj, subs))
            continue
        if kind in FACE_STRATEGIES:
            face = source if is_face_obj else doc.getObject(source.Name + FACE_SUFFIX)
            if face is None:
                raise ValueError("%s n'est pas un contour fermé : pas de face pour cette stratégie" % source.Label)
            out.append((face, ["Face1"]))
        elif is_face_obj:
            vector = doc.getObject(source.Name[: -len(FACE_SUFFIX)])
            out.append((vector or source, ["Edge%d" % (i + 1) for i in range(len((vector or source).Shape.Edges))]))
        else:
            out.append((source, ["Edge%d" % (i + 1) for i in range(len(source.Shape.Edges))]))
    return out


def make_sheet(doc, vectors, thickness, margin=10.0, rect=None):
    """Panneau rectangulaire sous le dessin : englobe les vecteurs + ``margin``, dessus à Z = 0.

    ``rect`` = ``(x, y, largeur, longueur)`` : panneau de taille imposée (imbrication)."""
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
    if rect is not None:
        x, y, w, h = (float(v) for v in rect)
        if bb.XMin < x - 1e-6 or bb.YMin < y - 1e-6 or bb.XMax > x + w + 1e-6 or bb.YMax > y + h + 1e-6:
            raise ValueError("the drawing does not fit in the %.0f x %.0f mm sheet" % (w, h))
        sheet.Shape = Part.makeBox(w, h, thickness, FreeCAD.Vector(x, y, -thickness))
    else:
        sheet.Shape = Part.makeBox(bb.XLength + 2 * margin, bb.YLength + 2 * margin, thickness,
                                   FreeCAD.Vector(bb.XMin - margin, bb.YMin - margin, -thickness))
    if FreeCAD.GuiUp and sheet.ViewObject is not None:
        # parcours sous Z 0 visibles à travers le panneau
        sheet.ViewObject.Transparency = 70
        sheet.ViewObject.ShapeColor = (0.80, 0.66, 0.45)
    return sheet
