# SPDX-License-Identifier: LGPL-2.1-or-later
"""4e axe continu : enroulement d'un parcours 2D sur un cylindre (X, Z et A simultanés).

Repère du dessin **déroulé** : X = le long de l'axe A (identique au X machine), Y = longueur d'arc
sur la surface du brut rond (Y = 0 à A = 0, Y = 2πR pour un tour), Z = profondeur sous la surface
(0 = surface, négatif dans la matière).

Transformation d'un point (x, y, z) : X = x, A = signe × y / R (en degrés), Z = cz + R + z, la
fraise restant au-dessus de l'axe (Y machine = cy). Les segments de coupe sont découpés (longueur
et angle maximaux) puis écrits en **temps inverse G93** : F = avance / longueur réelle du segment
(1/min), la longueur étant mesurée au rayon de coupe. Le programme revient en G94 à la fin.

Seule stratégie enroulée pour l'instant : la **gravure** de contours (la fraise suit les traits du
dessin à profondeur constante, en plusieurs passes). Les poches et contours décalés enroulés ne
sont pas faits.
"""

import math

import FreeCAD

from ..i18n import Msg, UserError

WRAP_PREFIX = "CAM2027Wrap"
KIND = "wrap_engrave"
LABEL = "Wrapped engraving (continuous A axis)"
MAX_SEGMENT_MM = 0.5
MAX_SEGMENT_DEG = 2.0
#: Path stocke les avances en mm/s : le postprocesseur multiplie F par 60 à la sortie
_PATH_FEED_SCALE = 1.0 / 60.0


def is_wrap_op(obj):
    return obj.Name.startswith(WRAP_PREFIX)


def check_stock_axis(job, center, tol=1e-3):
    """Le brut rond doit être centré sur l'axe A du profil machine (sinon l'enroulement serait faux)."""
    base = job.Stock.Placement.Base
    if abs(base.y - center[0]) > tol or abs(base.z - center[1]) > tol:
        raise UserError("the round stock axis (Y {y:.3f}, Z {z:.3f}) is not the A axis of the machine profile (Y {cy:.3f}, Z {cz:.3f})",
                        y=base.y, z=base.z, cy=center[0], cz=center[1])


def radius_of_stock(job):
    """Rayon du brut rond d'axe X du job (ValueError sinon)."""
    stock = getattr(job, "Stock", None)
    radius = getattr(stock, "Radius", None)
    if radius is None:
        raise UserError("wrapping needs a round stock along X (Stock and fixture > round bar on the A axis)")
    return float(radius.getValueAs("mm")) if hasattr(radius, "getValueAs") else float(radius)


def flat_engrave_moves(wires, depth, step_down, safe_z, deflection=0.01):
    """Gravure à plat (repère déroulé) : liste de ``(kind, x, y, z)`` avec kind ``rapid`` / ``plunge`` / ``cut``.

    Chaque fil est suivi à chaque passe ; ``depth`` < 0 ; ``safe_z`` > 0 au-dessus de la surface.
    """
    if depth >= 0:
        raise UserError("wrapped engraving: the depth must be below the surface (negative)")
    if step_down <= 0:
        raise UserError("wrapped engraving: the step down must be positive")
    levels = []
    z = 0.0
    while z > depth + 1e-9:
        z = max(depth, z - step_down)
        levels.append(z)
    moves = []
    for wire in wires:
        pts = wire.discretize(Deflection=deflection)
        if len(pts) < 2:
            continue
        for level in levels:
            p0 = pts[0]
            moves.append(("rapid", p0.x, p0.y, safe_z))
            moves.append(("plunge", p0.x, p0.y, level))
            for p in pts[1:]:
                moves.append(("cut", p.x, p.y, level))
            moves.append(("rapid", pts[-1].x, pts[-1].y, safe_z))
    return moves


def to_machine(x, y, z, radius, center, sign):
    """Point déroulé -> (X, A en degrés, Z) machine."""
    cy, cz = center
    return x, sign * math.degrees(y / radius), cz + radius + z


def wrap_moves(moves, radius, center, sign, feed, plunge_feed):
    """Lignes G-code enroulées (avances réelles en mm/min). Les mouvements de coupe sont en G93."""
    if radius <= 0:
        raise UserError("wrapping radius must be positive")
    cy, _cz = center
    lines = ["G94"]
    prev = None  # (x, y, z) déroulés
    inverse = False
    for kind, x, y, z in moves:
        if prev is None:
            # entrée : monter au plan de sécurité avant de tourner, puis se placer au-dessus de l'axe
            X, A, Z = to_machine(x, y, max(z, 0.0), radius, center, sign)
            lines += ["G0 Z%.4f" % Z, "G0 Y%.4f" % cy, "G0 X%.4f A%.4f" % (X, A)]
            if z < 0:
                lines.append("G0 Z%.4f" % to_machine(x, y, z, radius, center, sign)[2])
            prev = (x, y, z)
            continue
        if kind == "rapid":
            if inverse:
                lines.append("G94")
                inverse = False
            X, A, Z = to_machine(x, y, z, radius, center, sign)
            if prev is not None and z > prev[2]:
                lines.append("G0 Z%.4f" % Z)  # remonter d'abord, puis tourner / translater
                lines.append("G0 X%.4f A%.4f" % (X, A))
            else:
                lines.append("G0 X%.4f A%.4f" % (X, A))
                lines.append("G0 Z%.4f" % Z)
            prev = (x, y, z)
            continue
        if feed <= 0 or plunge_feed <= 0:
            raise UserError("wrapping needs positive feeds")
        rate = plunge_feed if kind == "plunge" else feed
        if not inverse:
            lines.append("G93")
            inverse = True
        px, py, pz = prev
        r_mid = radius + (z + pz) / 2.0
        arc = abs(y - py) * r_mid / radius  # longueur d'arc au rayon de coupe
        n = max(1, int(math.ceil(max(math.hypot(x - px, arc) / MAX_SEGMENT_MM,
                                     math.degrees(abs(y - py) / radius) / MAX_SEGMENT_DEG, 1e-9))))
        for k in range(1, n + 1):
            t = float(k) / n
            qx, qy, qz = px + (x - px) * t, py + (y - py) * t, pz + (z - pz) * t
            length = math.sqrt(((x - px) / n) ** 2 + (arc / n) ** 2 + ((z - pz) / n) ** 2)
            if length < 1e-9:
                continue
            X, A, Z = to_machine(qx, qy, qz, radius, center, sign)
            lines.append("G1 X%.4f A%.4f Z%.4f F%.4f" % (X, A, Z, rate / length))
        prev = (x, y, z)
    if inverse:
        lines.append("G94")
    return lines


def preview_polylines(moves, radius, center):
    """Trajet de la pointe de la fraise **sur la pièce** (repère pièce, A = 0) pour l'aperçu 3D.

    La vue des parcours de FreeCAD ignore A ; ici chaque point déroulé (x, y, z) est reporté à
    l'angle y / R autour de l'axe : (x, cy + r sin θ, cz + r cos θ) avec r = R + z.
    """
    cy, cz = center

    def on_part(x, y, z):
        theta, r = y / radius, radius + z
        return FreeCAD.Vector(x, cy + r * math.sin(theta), cz + r * math.cos(theta))

    out, current, prev = [], [], None
    for kind, x, y, z in moves:
        if kind == "rapid" or prev is None:
            if len(current) > 1:
                out.append(current)
            current = [on_part(x, y, z)]
        else:
            px, py, pz = prev
            n = max(1, int(math.ceil(math.degrees(abs(y - py) / radius) / MAX_SEGMENT_DEG)))
            for k in range(1, n + 1):  # un segment déroulé devient une hélice sur la pièce
                t = float(k) / n
                current.append(on_part(px + (x - px) * t, py + (y - py) * t, pz + (z - pz) * t))
        prev = (x, y, z)
    if len(current) > 1:
        out.append(current)
    return out


def path_gcode(lines):
    """Lignes pour une opération « Custom » FreeCAD : F converti dans l'unité interne de Path (mm/s)."""
    out = []
    for line in lines:
        words = line.split()
        out.append(" ".join("F%.6f" % (float(w[1:]) * _PATH_FEED_SCALE) if w.startswith("F") else w for w in words))
    return out


def drawing_wires(base):
    """Fils (contours) des objets / sous-éléments du dessin déroulé."""
    import Part

    wires = []
    for obj, subs in base:
        shape = obj.Shape
        if subs:
            edges = [shape.getElement(s) for s in subs if s.startswith("Edge")]
            for face in [shape.getElement(s) for s in subs if s.startswith("Face")]:
                wires.extend(face.Wires)
            if edges:
                wires.extend(Part.Wire(group) for group in Part.sortEdges(edges))
        else:
            wires.extend(shape.Wires)
            loose = [e for e in shape.Edges if not any(e.isSame(we) for w in shape.Wires for we in w.Edges)]
            if loose:
                wires.extend(Part.Wire(group) for group in Part.sortEdges(loose))
    return wires


def check_layout(wires, radius):
    """Avertissements : dessin hors de la circonférence déroulée (recouvrement)."""
    warnings = []
    if not wires:
        raise UserError("wrapped engraving: no contour in the selected drawing")
    ymin = min(w.BoundBox.YMin for w in wires)
    ymax = max(w.BoundBox.YMax for w in wires)
    circ = 2 * math.pi * radius
    if ymin < -1e-6 or ymax > circ + 1e-6:
        warnings.append(Msg("drawing Y {lo:.2f}..{hi:.2f} mm is outside the unrolled circumference 0..{c:.2f} mm: it overlaps itself once wrapped",
                            lo=ymin, hi=ymax, c=circ))
    return warnings
