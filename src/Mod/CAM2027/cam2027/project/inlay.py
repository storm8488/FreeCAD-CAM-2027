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

FLAT_SUFFIX = "_FlatArea"


def vbit_reach(tool, depth):
    """Distance horizontale du bord à laquelle le V-bit atteint la profondeur ``depth`` (> 0)."""
    g = tool.geometry
    if not g.tip_included_angle_deg:
        raise ValueError("flat depth clearing needs a V-bit (tool %s has no included angle)" % tool.name)
    half = math.radians(g.tip_included_angle_deg / 2.0)
    return (g.tip_diameter or 0.0) / 2.0 + depth * math.tan(half)


def flat_area(faces, inset):
    """Faces décalées vers l'intérieur de ``inset`` (liste vide si la zone plate n'existe pas)."""
    out = []
    for face in faces:
        try:
            off = face.makeOffset2D(-inset, 0, False, False, False)  # angles en arc, résultat fermé
        except Exception:
            continue
        out.extend(f for f in off.Faces if f.Area > 1e-6)
    return out


def operation_faces(op):
    faces = []
    for obj, subs in op.Base or []:
        shape = obj.Shape
        names = [s for s in subs if s.startswith("Face")] or ["Face%d" % (i + 1) for i in range(len(shape.Faces))]
        faces.extend(shape.getElement(n) for n in names)
    return faces
