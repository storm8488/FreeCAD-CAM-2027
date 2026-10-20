# SPDX-License-Identifier: LGPL-2.1-or-later
"""V-carving à fond plat (« flat depth » d'Aspire) et incrustations mâle / femelle.

Fond plat : un V-carving limité à une profondeur ``P`` laisse au milieu des zones larges une
surface à dégager. Le V-bit atteint ``P`` à la distance ``reach = rayon de pointe + P × tan(demi-angle)``
du bord ; tout ce qui est plus loin du bord que ``reach`` doit être à ``P``. La zone plate est la
face décalée vers l'intérieur de ``reach`` ; une poche 2D à ``P`` avec une fraise plate la vide
(avant le V-carving). Les angles rentrants de la zone plate gardent le rayon de la fraise plate.
"""

import math

import FreeCAD

from ..i18n import UserError

FLAT_SUFFIX = "_FlatArea"


def vbit_reach(tool, depth):
    """Distance horizontale du bord à laquelle le V-bit atteint la profondeur ``depth`` (> 0)."""
    g = tool.geometry
    if not g.tip_included_angle_deg:
        raise UserError("flat depth clearing needs a V-bit (tool {tool} has no included angle)", tool=tool.name)
    half = math.radians(g.tip_included_angle_deg / 2.0)
    return (g.tip_diameter or 0.0) / 2.0 + depth * math.tan(half)


def flat_area(faces, inset):
    """Faces décalées vers l'intérieur de ``inset`` (liste vide si la zone plate n'existe pas).

    Contour par contour : l'extérieur est réduit, chaque trou agrandi, puis les trous retirés
    (FreeCAD 1.0 décale le trou d'une face trouée dans le mauvais sens)."""
    import Part

    out = []
    for face in faces:
        try:
            outer = Part.Face(face.OuterWire).makeOffset2D(-inset, 0, False, False, False)
        except Exception:
            continue
        if not outer.Faces:
            continue
        area = outer
        for wire in face.Wires:
            if wire.isSame(face.OuterWire):
                continue
            hole = Part.Face(Part.Wire(wire.Edges)).makeOffset2D(inset, 0, False, False, False)
            area = area.cut(hole)
        out.extend(f for f in area.Faces if f.Area > 1e-6)
    return out


def operation_faces(op):
    faces = []
    for obj, subs in op.Base or []:
        shape = obj.Shape
        names = [s for s in subs if s.startswith("Face")] or ["Face%d" % (i + 1) for i in range(len(shape.Faces))]
        faces.extend(shape.getElement(n) for n in names)
    return faces


# -- incrustations mâle / femelle ---------------------------------------------------------------------------
#
# Profil perpendiculaire à un bord, k = 1 / tan(demi-angle du V-bit) :
#   femelle : fond de la cavité z = -min(Pf, k·u), u = distance au bord vers l'intérieur ;
#   mâle    : dessin miroir réduit de g = Ps / k, zone autour taillée en V jusqu'à Pm (fond plat) ;
#             surface h = -min(Pm, k·v), v = distance au bord réduit vers l'extérieur.
# Retourné et enfoncé de D, le dessous du bouchon est à -D + min(Pm, k·(g - u)) : les flancs se
# touchent pour D = Ps ; il reste Pf - Ps de colle au fond et Pm - Ps entre les planches.


def check_inlay_depths(female_depth, male_start_depth, male_flat_depth):
    if not 0 < male_start_depth < female_depth:
        raise UserError("inlay: the male start depth must be between 0 and the female depth")
    if male_flat_depth <= male_start_depth:
        raise UserError("inlay: the male flat depth must be deeper than the male start depth")
    return {"bottom_gap": female_depth - male_start_depth, "surface_gap": male_flat_depth - male_start_depth}


def male_outline(face, vbit, male_start_depth, margin):
    """Contours du mâle (dessin miroir) : rectangle extérieur + forme réduite de la profondeur de départ.

    Miroir autour de l'axe vertical passant par le centre du dessin (le bouchon est retourné)."""
    import Part

    half = math.radians(vbit.geometry.tip_included_angle_deg / 2.0)
    g = male_start_depth * math.tan(half)
    reduced = face.makeOffset2D(-g, 0, False, False, False) if g > 0 else face
    if not reduced.Faces:
        raise UserError("inlay: the shape disappears when reduced by the male start depth")
    bb = face.BoundBox
    V = FreeCAD.Vector
    rect = Part.makePolygon([V(bb.XMin - margin, bb.YMin - margin, 0), V(bb.XMax + margin, bb.YMin - margin, 0),
                             V(bb.XMax + margin, bb.YMax + margin, 0), V(bb.XMin - margin, bb.YMax + margin, 0),
                             V(bb.XMin - margin, bb.YMin - margin, 0)])
    wires = [rect] + [w for f in reduced.Faces for w in f.Wires]
    cx = (bb.XMin + bb.XMax) / 2.0
    return Part.Compound(wires).mirror(V(cx, 0, 0), V(1, 0, 0)), cx


# -- angles vifs du V-carving limité -------------------------------------------------------------------------
#
# Le V-carving de FreeCAD calcule la profondeur aux deux extrémités de chaque arête de l'axe médian puis
# la borne : la diagonale d'un angle (sommet -> jonction) qui dépasse la profondeur limite devient
# entièrement trop peu profonde et l'angle n'est pas vif. Correction : pour chaque angle saillant, le
# V-bit descend le long de la bissectrice, de 0 au bord jusqu'à -P au sommet de la zone plate.

CORNERS_PREFIX = "CAM2027VCorners"
CORNERS_KIND = "vcarve_corners"
CORNERS_LABEL = "V-carve sharp corners (limited depth)"


def corner_spurs(face, tool, depth):
    """Segments ``(départ, arrivée)`` (z 0 -> -depth) le long de la bissectrice de chaque angle saillant."""
    g = tool.geometry
    tip_r = (g.tip_diameter or 0.0) / 2.0
    reach = vbit_reach(tool, depth)
    spurs = []
    for wire in face.Wires:
        edges = wire.OrderedEdges
        n = len(edges)
        for i in range(n):
            e_in, e_out = edges[i - 1], edges[i]
            v = e_out.Vertexes[0].Point if e_out.Orientation == "Forward" else e_out.Vertexes[-1].Point
            t_in = _tangent(e_in, at_end=True)
            t_out = _tangent(e_out, at_end=False)
            a, b = -t_in, t_out  # directions qui partent du sommet le long des deux arêtes
            u = a + b
            if u.Length < 1e-9:
                continue  # arêtes alignées : pas d'angle
            u.normalize()
            sin_half = (u.cross(a)).Length  # sinus du demi-angle intérieur
            if sin_half < 1e-6 or not face.isInside(v + u * min(0.05, reach * 0.1), 1e-7, True):
                continue  # angle rentrant (le V-bit ne peut pas faire un angle rentrant vif)
            start = v + u * (tip_r / sin_half)
            end = v + u * (reach / sin_half)
            if not face.isInside(end, 1e-6, True):
                continue  # forme trop étroite à cet angle : l'axe médian du V-carving s'en charge
            spurs.append((start, end))
    return spurs


def _tangent(edge, at_end):
    """Tangente unitaire de l'arête dans le sens du fil, au début ou à la fin."""
    p0, p1 = edge.ParameterRange
    reverse = edge.Orientation == "Reversed"
    param = (p0 if reverse else p1) if at_end else (p1 if reverse else p0)
    t = edge.tangentAt(param)
    if reverse:
        t = -t
    t.normalize()
    return t


def spur_gcode(spurs, z_top, depth, safe_z, feed, plunge_feed):
    """G-code des angles vifs (avances en mm/s, unité de Path) : de ``z_top`` à ``z_top - depth`` le long de
    chaque bissectrice."""
    lines = []
    for start, end in spurs:
        lines += ["G0 Z%.4f" % safe_z, "G0 X%.4f Y%.4f" % (start.x, start.y),
                  "G1 Z%.4f F%.6f" % (z_top, plunge_feed / 60.0),
                  "G1 X%.4f Y%.4f Z%.4f F%.6f" % (end.x, end.y, z_top - depth, feed / 60.0),
                  "G0 Z%.4f" % safe_z]
    return lines
