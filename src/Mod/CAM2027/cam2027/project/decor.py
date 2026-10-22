# SPDX-License-Identifier: LGPL-2.1-or-later
"""Parcours décoratifs (Aspire « Moulding Toolpath » et « Fluting Toolpath »).

**Moulure** : un profil ouvert (section) est extrudé le long d'un rail (vecteur ouvert ou fermé du dessin).
La section est donnée dans le repère du rail : ``u`` = distance latérale à gauche du rail (mm), ``z`` =
hauteur sous le dessus du brut (≤ 0). La fraise boule balaie des passes parallèles au rail, de ``u`` min à
``u`` max au pas latéral demandé ; la hauteur de chaque passe est calculée en 2D comme une fraise qui
descend sur la section (*drop cutter*) : la boule touche la section sans jamais passer dessous. Ébauche
éventuelle par paliers (profondeur de passe), comme Aspire.

**Cannelures** : chaque vecteur ouvert est suivi à profondeur variable : rampe de 0 à la profondeur sur une
longueur de départ, palier, rampe de retour à 0 sur une longueur de fin (V-bit ou boule : la largeur suit).
"""

import math

import FreeCAD

from ..i18n import UserError

DECOR_PREFIX = "CAM2027Decor"
MOULDING_KIND = "moulding"
FLUTING_KIND = "fluting"

#: sections prédéfinies : nom -> fonction(largeur, profondeur) -> points (u, z)
PROFILES = ("quarter_round", "cove", "chamfer", "ogee")


def profile_points(kind, width, depth, n=60):
    """Section ``[(u, z)]`` de largeur ``width`` (u de 0, bord extérieur, à ``width``, intérieur) et de
    profondeur ``depth`` : au bord ``z = -depth``, à l'intérieur ``z = 0`` (le dessus est gardé)."""
    if width <= 0 or depth <= 0:
        raise UserError("moulding: profile width and depth must be above 0")
    pts = []
    for k in range(n + 1):
        t = k / float(n)  # 0 au bord, 1 à l'intérieur
        if kind == "quarter_round":  # quart de rond convexe : ellipse de centre (width, -depth)
            z = -depth + depth * math.sqrt(max(0.0, 1.0 - (1.0 - t) ** 2))
        elif kind == "cove":  # gorge concave : ellipse de centre (0, 0)
            z = -depth * math.sqrt(max(0.0, 1.0 - t * t))
        elif kind == "chamfer":
            z = -depth * (1.0 - t)
        elif kind == "ogee":  # doucine : gorge puis quart de rond
            z = -depth * (0.5 * (1.0 + math.cos(math.pi * t)))
        else:
            raise UserError("moulding: unknown profile {name}", name=kind)
        pts.append((t * width, z))
    return pts


def _section_z(section, u):
    """Hauteur de la section en ``u`` (interpolation linéaire, constante au-delà des extrémités)."""
    if u <= section[0][0]:
        return section[0][1]
    if u >= section[-1][0]:
        return section[-1][1]
    lo, hi = 0, len(section) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if section[mid][0] <= u:
            lo = mid
        else:
            hi = mid
    (u0, z0), (u1, z1) = section[lo], section[hi]
    return z0 + (z1 - z0) * (u - u0) / (u1 - u0) if u1 > u0 else max(z0, z1)


def ball_tip_z(section, u, radius, sample=0.02):
    """Pointe d'une boule de rayon ``radius`` centrée latéralement en ``u``, posée sur la section (2D) :
    ``max(z(s) + sqrt(r² − (s − u)²) − r)`` sur ``|s − u| ≤ r``, sommets de la section compris."""
    best = -float("inf")
    n = max(2, int(math.ceil(2 * radius / sample)))
    candidates = [u - radius + 2 * radius * k / n for k in range(n + 1)]
    candidates += [s for s, _z in section if abs(s - u) <= radius]
    for s in candidates:
        dz = math.sqrt(max(0.0, radius * radius - (s - u) ** 2))
        best = max(best, _section_z(section, s) + dz - radius)
    return best


def _rail_points(rail, step):
    """Points (x, y) et normales gauches unitaires le long du rail (fil ou arête), tous les ``step`` mm au plus."""
    import Part

    edges = rail.Edges
    wire = rail if isinstance(rail, Part.Wire) else Part.Wire(Part.__sortEdges__(edges)) if len(edges) > 1 else Part.Wire(edges)
    pts = wire.discretize(Distance=step) if wire.Length > step else [wire.Vertexes[0].Point, wire.Vertexes[-1].Point]
    out = []
    for k, p in enumerate(pts):
        a = pts[max(0, k - 1)]
        b = pts[min(len(pts) - 1, k + 1)]
        tx, ty = b.x - a.x, b.y - a.y
        n = math.hypot(tx, ty)
        out.append((p.x, p.y, -ty / n, tx / n))
    return out, wire.isClosed()


def moulding_passes(rail, section, radius, stepover, z_top=0.0, step=0.5, step_down=None):
    """Polylignes ``[[(x, y, z)]]`` des passes de la moulure. Finition : une passe tous les ``stepover`` mm
    de ``u`` min − r à ``u`` max, aller-retour (section prolongée à plat au-delà de ses extrémités : la boule
    déborde du profil de son rayon côté bord, comme Aspire, pour finir un flanc raide).
    ``step_down`` : paliers d'ébauche au-dessus de la finition (z = max(finition, palier))."""
    if stepover <= 0:
        raise UserError("moulding: the stepover must be above 0")
    rail_pts, closed = _rail_points(rail, step)
    u_lo, u_hi = section[0][0], section[-1][0]
    us = []
    u = u_lo - radius  # boule au-delà du bord : le flanc raide de la section se finit par le côté
    while u < u_hi - 1e-9:
        us.append(u)
        u += stepover
    us.append(u_hi)
    finish = [(u, ball_tip_z(section, u, radius)) for u in us]
    finish = [(u, z) for u, z in finish if z < -1e-4]  # rien à enlever : passe sautée
    levels = []
    if step_down:
        deepest = min(z for _u, z in finish) if finish else 0.0
        k = 1
        while -k * step_down > deepest + 1e-9:
            levels.append(-k * step_down)
            k += 1
    levels.append(None)  # finition
    passes = []
    for level in levels:
        for i, (u, z) in enumerate(finish):
            if level is not None and z >= level:
                continue  # finition au-dessus du palier : faite par la passe de finition
            zz = z if level is None else level
            line = [(x + u * nx, y + u * ny, z_top + zz) for x, y, nx, ny in rail_pts]
            if closed:
                line.append(line[0])
            if i % 2 and not closed:
                line.reverse()
            passes.append(line)
    return passes


def flute_lines(rails, depth, ramp_start, ramp_end, z_top=0.0, step=0.25):
    """Polylignes des cannelures : chaque rail suivi avec ``z = z_top − depth · rampe(s)``."""
    if depth <= 0:
        raise UserError("fluting: the depth must be above 0")
    out = []
    for rail in rails:
        pts, _closed = _rail_points(rail, step)
        total = 0.0
        dist = [0.0]
        for k in range(1, len(pts)):
            total += math.hypot(pts[k][0] - pts[k - 1][0], pts[k][1] - pts[k - 1][1])
            dist.append(total)
        if ramp_start + ramp_end > total + 1e-9:
            raise UserError("fluting: the ramps ({r:.1f} mm) are longer than the vector ({l:.1f} mm)",
                            r=ramp_start + ramp_end, l=total)
        line = []
        for (x, y, _nx, _ny), s in zip(pts, dist):
            f = 1.0
            if ramp_start > 0 and s < ramp_start:
                f = s / ramp_start
            if ramp_end > 0 and total - s < ramp_end:
                f = min(f, (total - s) / ramp_end)
            line.append((x, y, z_top - depth * f))
        out.append(line)
    return out


def gcode(lines, safe_z, feed, plunge_feed):
    """G-code des polylignes (approche G0, plongée, coupe, remontée), avances en mm/min."""
    out = ["G0 Z%.4f" % safe_z]
    for line in lines:
        x, y, z = line[0]
        out.append("G0 X%.4f Y%.4f" % (x, y))
        out.append("G1 Z%.4f F%.1f" % (z, plunge_feed))
        out.extend("G1 X%.4f Y%.4f Z%.4f F%.1f" % (p[0], p[1], p[2], feed) for p in line[1:])
        out.append("G0 Z%.4f" % safe_z)
    return out


def add_decor_operation(proj, kind, name, assembly_id, preset_id, lines_fn, params, safe_margin=3.0):
    """Opération ``Path.Op.Custom`` (moulure ou cannelures) ; ``lines_fn(outil, z_top)`` donne les polylignes."""
    import Path.Op.Custom as Custom
    from ..tools import bridge
    from . import project as projmod
    from . import wrap as wrapmod

    asm, tool, holder = proj.library.resolve_assembly(assembly_id)
    preset = tool.preset(preset_id)
    values = preset.resolve(tool)
    z_top = proj.stock_bounds()["zmax"]
    lines = lines_fn(tool, z_top)
    if not lines:
        raise UserError("{op}: nothing to cut", op=name)
    toolbit, bit_warnings = bridge.create_toolbit(proj.doc, tool, label="%s (T%d)" % (tool.name, asm.output.tool_number))
    tc, _ = bridge.create_tool_controller(proj.doc, asm, tool, values, toolbit=toolbit, label="TC: %s" % name)
    proj.job.Proxy.addToolController(tc)
    previous = FreeCAD.ActiveDocument
    FreeCAD.setActiveDocument(proj.doc.Name)
    try:
        op = Custom.Create(DECOR_PREFIX, parentJob=proj.job)
    finally:
        if previous is not None and previous.Name != proj.doc.Name:
            FreeCAD.setActiveDocument(previous.Name)
    op.Label = name
    op.ToolController = tc
    op.Source = "Text"
    op.Gcode = wrapmod.path_gcode(gcode(lines, z_top + safe_margin, values["feed_mm_min"], values["plunge_feed_mm_min"]))
    reg = proj.registry
    reg[op.Name] = {
        "kind": kind, "label": name, "order": len(reg), "assembly_id": asm.id, "tool_id": tool.id,
        "holder_id": holder.id if holder else None, "preset_id": preset.id, "values": values,
        "tool_controller": tc.Name, "toolbit": toolbit.Name, "params": projmod._jsonable(params),
        "ignored_params": [], "warnings": list(bit_warnings), "index_deg": None,
    }
    proj._save_registry(reg)
    proj.doc.recompute()
    return op, reg[op.Name]


def add_moulding(proj, name, assembly_id, preset_id, rail_obj, profile="quarter_round", width=10.0, depth=10.0,
                 stepover=0.3, step_down=None, flip=False):
    """Moulure le long de ``rail_obj`` (vecteur du dessin), section ``profile`` à gauche du rail
    (``flip`` : à droite). Fraise boule. Retourne ``(op, record)``."""
    section = profile_points(profile, width, depth)
    if flip:
        section = [(-u, z) for u, z in reversed(section)]

    def lines(tool, z_top):
        if tool.tool_type != "ballend":
            raise UserError("moulding needs a ball end mill")
        return moulding_passes(rail_obj.Shape, section, tool.geometry.diameter / 2.0, stepover, z_top, step_down=step_down)

    params = {"rail": rail_obj.Name, "profile": profile, "width": width, "depth": depth, "stepover": stepover,
              "step_down": step_down, "flip": flip}
    return add_decor_operation(proj, MOULDING_KIND, name, assembly_id, preset_id, lines, params)


def add_fluting(proj, name, assembly_id, preset_id, rail_objs, depth, ramp_start=10.0, ramp_end=10.0):
    """Cannelures le long des vecteurs ``rail_objs`` (boule ou V-bit). Retourne ``(op, record)``."""
    def lines(tool, z_top):
        if tool.tool_type not in ("ballend", "vbit", "engrave"):
            raise UserError("fluting needs a ball end mill or a V-bit")
        return flute_lines([o.Shape for o in rail_objs], depth, ramp_start, ramp_end, z_top)

    params = {"rails": [o.Name for o in rail_objs], "depth": depth, "ramp_start": ramp_start, "ramp_end": ramp_end}
    return add_decor_operation(proj, FLUTING_KIND, name, assembly_id, preset_id, lines, params)
