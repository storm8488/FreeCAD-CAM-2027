# SPDX-License-Identifier: LGPL-2.1-or-later
"""4e axe continu : contour et poche enroulés, finition 3D rotative (X, Z et A simultanés, G93).

Même repère déroulé que la gravure enroulée (``wrap.py``) : X le long de l'axe A, Y = longueur d'arc au
rayon ``R`` du brut rond (Y = 0 à A = 0), Z sous la surface du brut (0 = surface). Les mouvements produits
ici (``(kind, x, y, z)``) sont écrits par ``wrap.wrap_moves`` (temps inverse, avance réelle au rayon de
coupe) et tracés par ``wrap.preview_polylines``.

- **Contour / poche enroulés** : à la profondeur ``z`` la fraise (axe radial) coupe au rayon ``r = R + z`` ;
  un disque de rayon ``rt`` sur ce cylindre devient dans le repère déroulé une ellipse (X : ``rt``, Y :
  ``rt R / r``). Le décalage d'outil se fait donc dans le plan **réel** au rayon courant (Y multiplié par
  ``r / R``), puis le parcours est ramené au repère déroulé : la compensation suit le rayon de chaque
  niveau.
- **Finition 3D rotative** (« Rotary parallel » de Fusion) : lignes le long de l'axe, une par angle
  (pas angulaire = pas / rayon maximal de la pièce). Pour chaque angle θ la pièce est tournée de -θ
  autour de l'axe A (seules les facettes au-dessus de l'axe et à portée de la fraise sont gardées) et la
  hauteur de la pointe est calculée par OpenCamLib (``BatchDropCutter``) le long de X : hauteur exacte du
  modèle sous la fraise qui pointe vers l'axe. Niveaux d'ébauche optionnels (passe radiale) depuis le brut.
"""

import math

from ..i18n import UserError
from . import wrap as wrapmod

KINDS = {
    "wrap_contour": "Wrapped contour (continuous A axis)",
    "wrap_pocket": "Wrapped pocket (continuous A axis)",
    "rotary3d": "Rotary 3D finishing (continuous A axis)",
}
SIDES = ("outside", "inside", "on")
#: écart de discrétisation des contours déroulés (mm)
DEFLECTION = 0.01


def _np():
    import numpy

    return numpy


def levels(start, depth, step_down):
    """Profondeurs des passes de ``start`` (0 = surface) à ``depth`` (< start)."""
    if depth >= start - 1e-9:
        raise UserError("wrapped machining: the depth must be below the start (negative, under the surface)")
    if step_down <= 0:
        raise UserError("wrapped machining: the step down must be positive")
    out, z = [], start
    while z > depth + 1e-9:
        z = max(depth, z - step_down)
        out.append(z)
    return out


def _scaled(shape, ky):
    import FreeCAD

    m = FreeCAD.Matrix()
    m.scale(1.0, ky, 1.0)
    return shape.transformGeometry(m) if abs(ky - 1.0) > 1e-12 else shape.copy()


def _faces(wires):
    """Faces planes (îlots compris) des fils fermés du dessin."""
    import Part

    closed = [w for w in wires if w.isClosed()]
    if not closed:
        raise UserError("wrapped pocket: the drawing has no closed contour")
    try:
        face = Part.makeFace(closed, "Part::FaceMakerBullseye")
    except Exception:
        face = Part.Compound([Part.Face(w) for w in closed])
    return face


def _offset_wires(shape, distance):
    """Fils décalés de ``distance`` (positif = vers l'extérieur) ; [] si plus rien."""
    if abs(distance) < 1e-9:
        return list(shape.Wires) if shape.Faces else list(shape.Wires)
    try:
        off = shape.makeOffset2D(distance, 0, False, False, False)
    except Exception:
        return []
    if off.isNull():
        return []
    return list(off.Wires)


def _polyline(wire, ky_back):
    """Points (x, y déroulé) d'un fil du plan réel, ramené au repère déroulé (Y / ky)."""
    pts = wire.discretize(Deflection=DEFLECTION)
    return [(p.x, p.y * ky_back) for p in pts]


def _ring_moves(rings, z, safe_z, link_ok):
    moves, prev = [], None
    for pts in rings:
        if len(pts) < 2:
            continue
        x0, y0 = pts[0]
        if prev is None or not link_ok(prev, (x0, y0)):
            if prev is not None:
                moves.append(("rapid", prev[0], prev[1], safe_z))
            moves.append(("rapid", x0, y0, safe_z))
            moves.append(("plunge", x0, y0, z))
        else:
            moves.append(("cut", x0, y0, z))
        moves.extend(("cut", x, y, z) for x, y in pts[1:])
        prev = pts[-1]
    if prev is not None:
        moves.append(("rapid", prev[0], prev[1], safe_z))
    return moves


def contour_moves(wires, radius, tool_radius, side, depth, step_down, safe_z, start=0.0):
    """Contour enroulé : fil décalé du rayon d'outil au rayon de chaque niveau (côté extérieur / intérieur /
    sur le trait)."""
    if side not in SIDES:
        raise UserError("wrapped contour: unknown side {side}", side=side)
    import Part

    moves = []
    for z in levels(start, depth, step_down):
        k = (radius + z) / radius  # longueur d'arc réelle au rayon de coupe / longueur déroulée
        rings = []
        for wire in wires:
            real = _scaled(wire, k)
            if side == "on" or not wire.isClosed():
                rings.append(_polyline(real, 1.0 / k))
                continue
            offset = _offset_wires(Part.Face(real), tool_radius if side == "outside" else -tool_radius)
            if not offset:
                raise UserError("wrapped contour: the tool does not fit inside a contour of the drawing")
            rings.extend(_polyline(w, 1.0 / k) for w in offset)
        moves += _ring_moves(rings, z, safe_z, lambda a, b: False)
    return moves


def pocket_moves(wires, radius, tool_radius, stepover, depth, step_down, safe_z, start=0.0):
    """Poche enroulée : anneaux décalés vers l'intérieur (rayon d'outil puis pas), du centre vers les parois,
    à chaque niveau ; décalages calculés dans le plan réel au rayon du niveau."""
    if stepover <= 0 or stepover > 2.0 * tool_radius:
        raise UserError("wrapped pocket: the stepover must be between 0 and the tool diameter")
    import Part

    face0 = _faces(wires)
    moves = []
    for z in levels(start, depth, step_down):
        k = (radius + z) / radius
        face = _scaled(face0, k)
        rings, d = [], tool_radius
        limit = _offset_wires(face, -tool_radius)
        if not limit:
            raise UserError("wrapped pocket: the tool does not fit inside the pocket")
        while True:
            ws = _offset_wires(face, -d)
            if not ws:
                break
            rings.append([_polyline(w, 1.0 / k) for w in ws])
            d += stepover
        ordered = [ring for group in reversed(rings) for ring in group]  # du centre vers les parois
        zone = Part.Face(Part.Wire(limit[0])) if len(limit) == 1 else None

        def link_ok(a, b, zone=zone, k=k):
            # liaison à la profondeur seulement à l'intérieur de la zone du centre de l'outil (déjà vidée)
            if zone is None:
                return False
            import FreeCAD

            for t in (0.25, 0.5, 0.75):
                p = FreeCAD.Vector(a[0] + (b[0] - a[0]) * t, (a[1] + (b[1] - a[1]) * t) * k, 0)
                if not zone.isInside(p, 1e-6, True):
                    return False
            return math.hypot(b[0] - a[0], (b[1] - a[1]) * k) <= 2.0 * stepover
        moves += _ring_moves(ordered, z, safe_z, link_ok)
    return moves


# -- finition 3D rotative ---------------------------------------------------------------------------------------


class RotaryModel(object):
    """Pièce triangulée autour de l'axe A (droite parallèle à X passant par ``center``)."""

    def __init__(self, shapes, center, deflection=0.005):
        np = _np()
        verts, tris = [], []
        for shape in shapes:
            v, f = shape.tessellate(deflection)
            base = sum(len(a) for a in verts)
            verts.append(np.array([(p.x, p.y, p.z) for p in v], dtype=float))
            tris.append(np.array(f, dtype=np.int64) + base)
        self.v = np.vstack(verts)
        self.f = np.vstack(tris)
        cy, cz = center
        self.y = self.v[:, 1] - cy
        self.z = self.v[:, 2] - cz
        self.r = np.hypot(self.y, self.z)
        self.r_max = float(self.r.max())
        self.x_min, self.x_max = float(self.v[:, 0].min()), float(self.v[:, 0].max())

    def heights(self, theta, xs, cutter, reach):
        """Hauteur de la pointe au-dessus de l'axe (fraise radiale) le long de ``xs`` à l'angle ``theta`` (rad),
        NaN où la fraise ne trouve rien. ``reach`` : demi-largeur de la fraise (facettes gardées)."""
        np = _np()
        from .scallop import ocl_module

        ocl = ocl_module()
        c, s = math.cos(theta), math.sin(theta)
        # point de la pièce à l'angle θ (y = r sin θ, z = r cos θ) amené au sommet (+Z) : rotation de -θ
        yr = self.y * c - self.z * s
        zr = self.y * s + self.z * c
        ty, tz = yr[self.f], zr[self.f]
        keep = (ty.min(axis=1) <= reach) & (ty.max(axis=1) >= -reach) & (tz.max(axis=1) > 0.0)
        stl = ocl.STLSurf()
        X = self.v[:, 0]
        for a, b, d in self.f[keep].tolist():
            stl.addTriangle(ocl.Triangle(ocl.Point(X[a], yr[a], zr[a]), ocl.Point(X[b], yr[b], zr[b]),
                                         ocl.Point(X[d], yr[d], zr[d])))
        bdc = ocl.BatchDropCutter()
        bdc.setSTL(stl)
        bdc.setCutter(cutter)
        for x in xs.tolist():
            bdc.appendPoint(ocl.CLPoint(x, 0.0, -1.0e6))
        bdc.run()
        z = np.array([p.z for p in bdc.getCLPoints()], dtype=float)
        z[z <= -1.0e6 + 1.0] = np.nan
        return z


#: pente (dz / déplacement) au-delà de laquelle deux points voisins d'une passe sont reliés par une marche
STEEP_SLOPE = 2.0


def _stairs(run):
    """Points d'une passe ``[(x, y, z)]`` avec une marche entre deux voisins très écartés en hauteur.

    Au bord d'une paroi (poche, épaulement), un point est sur l'arête (fraise posée sur le bord) et le suivant au
    pied de la paroi : la droite qui les relie entre dans l'arête. La marche reste à la plus haute des deux
    hauteurs jusqu'au-dessus de l'autre point, puis descend (ou monte) seule : entre deux points voisins, la
    surface ne dépasse pas la plus haute des deux de plus que la flèche d'une boule sur l'écart (< 0,003 mm à
    0,25 mm)."""
    out = run[:1]
    for b in run[1:]:
        a = out[-1]
        if abs(b[2] - a[2]) > STEEP_SLOPE * math.hypot(b[0] - a[0], b[1] - a[1]) > 0.0:
            out.append((b[0], b[1], a[2]) if a[2] > b[2] else (a[0], a[1], b[2]))
        out.append(b)
    return out


def rotary_moves(model, stock_radius, cutter, tool_radius, stepover, sample, safe_z, step_down=0.0, leave=0.0,
                 x_range=None, spiral=False):
    """Lignes le long de l'axe (aller-retour), une par angle, en repère déroulé ; niveaux d'ébauche depuis le
    brut si ``step_down`` > 0 (pointe jamais sous ``max(modèle, niveau)``).

    ``spiral`` : une hélice continue (A tourne sans arrêt, X avance de ``stepover`` par tour ; un tour à X constant
    à chaque bout) au lieu des lignes : pas de remontée ni de rapide entre deux passes, A sur plusieurs tours."""
    np = _np()
    if stepover <= 0 or sample <= 0:
        raise UserError("rotary finishing: the stepover and the sample interval must be positive")
    x0, x1 = x_range or (model.x_min, model.x_max)
    reach = tool_radius + 0.5
    if spiral:
        # point i : u = i / n_a tours, angle 2 pi u, X = x0 + pas (u - 1) borné à [x0, x1]
        n_a = max(8, int(math.ceil(2.0 * math.pi * model.r_max / sample)))
        turns = int(math.ceil((x1 - x0) / stepover)) + 2
        u = np.arange(turns * n_a + 1) / float(n_a)
        xs = np.clip(x0 + stepover * (u - 1.0), x0, x1)
        ys = u * (2.0 * math.pi * stock_radius)
        heights = np.empty(len(u))
        for j in range(n_a):  # une triangulation tournée par angle, tous les tours à la fois
            heights[j::n_a] = model.heights(2.0 * math.pi * j / n_a, xs[j::n_a], cutter, reach)
        rows = [(xs, ys, heights + leave - stock_radius)]
        info = {"lines": 0, "turns": turns, "samples": len(u)}
    else:
        n_x = max(2, int(math.ceil((x1 - x0) / sample)) + 1)
        xs = np.linspace(x0, x1, n_x)
        n_a = max(4, int(math.ceil(2.0 * math.pi * model.r_max / stepover)))
        thetas = np.arange(n_a) * (2.0 * math.pi / n_a)
        # surépaisseur : pointe relevée de ``leave`` (radialement) ; repère déroulé : 0 = surface du brut
        rows = []
        for k, t in enumerate(thetas):
            z = model.heights(t, xs, cutter, reach) + leave - stock_radius
            order = slice(None) if k % 2 == 0 else slice(None, None, -1)
            rows.append((xs[order], np.full(n_x, t * stock_radius), z[order]))
        info = {"lines": n_a, "samples": n_x}
    floors = []
    if step_down > 0:
        z = 0.0
        finite = [r[2][np.isfinite(r[2])] for r in rows]
        low = min([float(f.min()) for f in finite if len(f)] or [-stock_radius])
        while z - step_down > low + 1e-9:
            z -= step_down
            floors.append(z)
    floors.append(None)  # finition : la surface
    moves, top = [], 0.0
    for level, floor in enumerate(floors):
        for xr, yr, grid in rows:
            zz = grid if floor is None else np.where(np.isfinite(grid), np.maximum(grid, floor), floor)
            if spiral and level % 2:  # hélice parcourue à l'envers un niveau sur deux : A ne revient pas en arrière
                xr, yr, zz = xr[::-1], yr[::-1], zz[::-1]
            run = []
            for i in list(range(len(zz))) + [None]:
                if i is not None and np.isfinite(zz[i]) and zz[i] < top + 1e-9 + (0 if floor is not None else 1e9):
                    run.append((float(xr[i]), float(yr[i]), float(zz[i])))
                    continue
                if len(run) >= 2:
                    xa, ya, za = run[0]
                    moves.append(("rapid", xa, ya, safe_z))
                    moves.append(("rapid", xa, ya, min(safe_z, max(za, top) + 1.0)))
                    moves.append(("plunge", xa, ya, za))
                    moves.extend(("cut", xv, yv, zv) for xv, yv, zv in _stairs(run)[1:])
                    moves.append(("rapid", run[-1][0], run[-1][1], safe_z))
                run = []
        if floor is not None:
            top = floor
    info.update(levels=len(floors), r_max=model.r_max)
    return moves, info


def make_cutter(tool):
    """Fraise OpenCamLib depuis un outil de la bibliothèque (plate, boule, torique) ; (fraise, rayon)."""
    from .scallop import make_cutter as ball_or_bull, ocl_module

    g = tool.geometry
    length = max(g.flute_length or 0.0, 4.0 * g.diameter)
    if tool.tool_type == "ballend":
        return ball_or_bull(g.diameter, g.diameter / 2.0, length), g.diameter / 2.0
    if tool.tool_type == "bullnose" and g.corner_radius:
        return ball_or_bull(g.diameter, g.corner_radius, length), g.diameter / 2.0
    if tool.tool_type in ("endmill",):
        return ocl_module().CylCutter(g.diameter, length), g.diameter / 2.0
    raise UserError("rotary finishing needs a flat, ball or bull nose end mill")


# -- carte de hauteur radiale (contrôle des tests) ---------------------------------------------------------------


class RadialMap(object):
    """Rayon de la matière restante sur une grille (X, angle) du repère pièce, pour vérifier un parcours
    enroulé : chaque position de la fraise (pointe au rayon ρ, angle θt) abaisse le rayon des rayons qu'elle
    couvre (fraise plate : plan du bout ; boule : sphère)."""

    def __init__(self, x0, x1, t0, t1, radius, res_x=0.1, res_t=None):
        np = _np()
        res_t = res_t or res_x / radius
        self.xs = np.arange(x0 + res_x / 2.0, x1, res_x)
        self.ts = np.arange(t0 + res_t / 2.0, t1, res_t)
        self.r = np.full((len(self.xs), len(self.ts)), float(radius))
        self.res_x, self.res_t = res_x, res_t

    def cut(self, x, theta, rho, kind, tool_radius):
        np = _np()
        rt = tool_radius
        i0, i1 = np.searchsorted(self.xs, [x - rt, x + rt])
        half = math.asin(min(1.0, rt / max(rho, rt))) + 1e-9
        j0, j1 = np.searchsorted(self.ts, [theta - half, theta + half])
        if i0 >= i1 or j0 >= j1:
            return
        dx = (self.xs[i0:i1] - x)[:, None]
        d = (self.ts[j0:j1] - theta)[None, :]
        if kind == "ball":
            cc = rho + rt
            b = cc * np.cos(d)
            disc = b * b - (cc * cc + dx * dx - rt * rt)
            r = np.where(disc >= 0, b - np.sqrt(np.maximum(disc, 0.0)), np.inf)
        else:
            w = np.sqrt(np.maximum(rt * rt - dx * dx, 0.0))
            r = np.where((np.abs(dx) <= rt) & (rho * np.abs(np.tan(d)) <= w), rho / np.cos(d), np.inf)
        sub = self.r[i0:i1, j0:j1]
        np.minimum(sub, r, out=sub)

    def sweep_moves(self, moves, radius, kind, tool_radius, step=None):
        """Balaye les mouvements de coupe déroulés (``(kind, x, y, z)``), interpolés comme la machine (X, A, Z
        linéaires). Les segments loin de la carte sont sautés ; les angles sont ramenés au tour de la carte."""
        step = step or min(self.res_x, self.res_t * radius) / 2.0
        xlo, xhi = self.xs[0] - tool_radius - self.res_x, self.xs[-1] + tool_radius + self.res_x
        tc = (self.ts[0] + self.ts[-1]) / 2.0
        span = (self.ts[-1] - self.ts[0]) / 2.0 + math.asin(min(1.0, tool_radius / (radius / 2.0))) + self.res_t

        def wrapped(theta):
            return tc + (theta - tc + math.pi) % (2.0 * math.pi) - math.pi

        prev = None
        for mk, x, y, z in moves:
            if mk == "rapid":
                prev = (x, y, z)
                continue
            if prev is not None:
                px, py, pz = prev
                t0, t1 = py / radius, y / radius
                w0 = wrapped(t0)
                far_x = max(x, px) < xlo or min(x, px) > xhi
                far_t = abs(w0 - tc) > span + abs(t1 - t0) and abs(wrapped(t1) - tc) > span + abs(t1 - t0)
                if not (far_x or far_t):
                    n = max(1, int(math.ceil(max(abs(x - px), abs(y - py), abs(z - pz)) / step)))
                    for k in range(1, n + 1):
                        t = float(k) / n
                        qx, qz = px + (x - px) * t, pz + (z - pz) * t
                        self.cut(qx, w0 + (t1 - t0) * t, radius + qz, kind, tool_radius)
            prev = (x, y, z)


# -- opérations du projet -------------------------------------------------------------------------------------------


def defaults(kind):
    base = {"start": 0.0, "depth": -1.0, "step_down": 0.5, "safe_margin": 5.0}
    if kind == "wrap_contour":
        base["side"] = "outside"
    elif kind == "wrap_pocket":
        base["stepover"] = 0.4  # fraction du diamètre
    elif kind == "rotary3d":
        base = {"stepover": 0.5, "sample": 0.25, "step_down": 0.0, "leave": 0.0, "safe_margin": 5.0, "spiral": False}
    return base


def generate(project, op):
    """(Re)calcule une opération rotative du projet : G-code G93 dans l'opération « Custom », aperçu 3D."""
    from .indexing import check_machine

    reg = project.registry
    rec = reg[op.Name]
    kind = rec["kind"]
    p = dict(defaults(kind), **rec["params"])
    cy, cz, sign = check_machine(project.machine)
    radius = wrapmod.radius_of_stock(project.job)
    wrapmod.check_stock_axis(project.job, (cy, cz))
    tool = project.library.tool(rec["tool_id"])
    tool_r = tool.geometry.diameter / 2.0
    safe = p["safe_margin"]
    warnings = []
    if kind in ("wrap_contour", "wrap_pocket"):
        base = []
        for name, subs in rec["wrap_base"]:
            obj = project.doc.getObject(name)
            if obj is None:
                raise UserError("wrapped machining {op}: drawing object {name} not found", op=op.Label, name=name)
            base.append((obj, subs))
        wires = wrapmod.drawing_wires(base)
        warnings += wrapmod.check_layout(wires, radius)
        if kind == "wrap_contour":
            moves = contour_moves(wires, radius, tool_r, p["side"], p["depth"], p["step_down"], safe, p["start"])
        else:
            moves = pocket_moves(wires, radius, tool_r, p["stepover"] * tool.geometry.diameter, p["depth"],
                                 p["step_down"], safe, p["start"])
    elif kind == "rotary3d":
        shapes = [o.Shape for o in project.job.Model.Group if getattr(o, "Shape", None) is not None]
        model = RotaryModel(shapes, (cy, cz))
        if model.r_max > radius + 1e-6:
            raise UserError("rotary finishing: the part (radius {r:.2f} mm) is larger than the round stock ({s:.2f} mm)",
                            r=model.r_max, s=radius)
        cutter, tool_r = make_cutter(tool)
        if p.get("spiral"):
            rot = project.machine.rotary
            turns = math.ceil((model.x_max - model.x_min) / p["stepover"]) + 2
            limit = rot.max_deg if sign > 0 else (None if rot.min_deg is None else -rot.min_deg)
            if limit is not None and 360.0 * turns > limit + 1e-6:  # A va de 0 à ± 360° x tours
                raise UserError("rotary finishing: the spiral turns the A axis {t:.0f} times ({d:.0f}°), more than its travel ({a:g}° to {b:g}° in the machine profile): use lines along the axis",  # noqa: E501
                                t=turns, d=360.0 * turns, a=rot.min_deg, b=rot.max_deg)
        moves, info = rotary_moves(model, radius, cutter, tool_r, p["stepover"], p["sample"], safe,
                                   step_down=p["step_down"], leave=p["leave"], spiral=bool(p.get("spiral")))
        rec["info"] = info
    else:
        raise UserError("unknown rotary operation {kind}", kind=kind)
    if not moves:
        raise UserError("{op}: no toolpath (nothing to cut)", op=op.Label)
    values = rec["values"]
    lines = wrapmod.wrap_moves(moves, radius, (cy, cz), sign, values["feed_mm_min"], values["plunge_feed_mm_min"])
    op.Gcode = wrapmod.path_gcode(lines)
    project._wrap_preview(op, wrapmod.preview_polylines(moves, radius, (cy, cz)))
    rec["warnings"] = [w for w in rec.get("warnings", []) if not w.startswith("drawing Y")] + warnings
    project._save_registry(reg)
    project.doc.recompute()
    return lines, moves


def add_operation(project, kind, name, assembly_id, preset_id, base=None, params=None):
    """Crée une opération rotative continue (``KINDS``) ; ``base`` : dessin déroulé (contour, poche).

    Retourne ``(op, record)``. Même enregistrement que la gravure enroulée (préfixe ``CAM2027Wrap`` : contrôle
    matière 3 axes sauté, opération sur A)."""
    import FreeCAD
    import Path.Op.Custom as Custom

    from ..tools import bridge
    from .indexing import check_machine, sync

    if kind not in KINDS:
        raise UserError("unknown rotary operation {kind}", kind=kind)
    check_machine(project.machine)
    if kind != "rotary3d" and not base:
        raise UserError("wrapped machining: select the unrolled drawing")
    job = project.job
    asm, tool, holder = project.library.resolve_assembly(assembly_id)
    if kind == "rotary3d":
        make_cutter(tool)
    elif tool.tool_type not in ("endmill", "ballend", "bullnose"):
        raise UserError("wrapped contour and pocket need an end mill (flat, ball or bull nose)")
    preset = tool.preset(preset_id)
    values = preset.resolve(tool)
    toolbit, bit_warnings = bridge.create_toolbit(project.doc, tool, label="%s (T%d)" % (tool.name, asm.output.tool_number))
    tc, _ = bridge.create_tool_controller(project.doc, asm, tool, values, toolbit=toolbit, label="TC: %s" % name)
    job.Proxy.addToolController(tc)
    previous = FreeCAD.ActiveDocument
    FreeCAD.setActiveDocument(project.doc.Name)
    try:
        op = Custom.Create(wrapmod.WRAP_PREFIX, parentJob=job)
    finally:
        if previous is not None and previous.Name != project.doc.Name:
            FreeCAD.setActiveDocument(previous.Name)
    op.Label = name
    op.ToolController = tc
    op.Source = "Text"
    if FreeCAD.GuiUp and op.ViewObject is not None:
        op.ViewObject.Visibility = False  # la vue des parcours ignore A : l'aperçu « (preview) » le remplace
    reg = project.registry
    reg[op.Name] = {
        "kind": kind, "label": name, "order": len(reg), "assembly_id": asm.id, "tool_id": tool.id,
        "holder_id": holder.id if holder else None, "preset_id": preset.id, "values": values,
        "tool_controller": tc.Name, "toolbit": toolbit.Name,
        "params": dict(defaults(kind), **{k: v for k, v in (params or {}).items()}),
        "wrap_base": [[obj.Name, list(subs)] for obj, subs in (base or [])],
        "ignored_params": [], "warnings": bit_warnings, "index_deg": None,
    }
    project._save_registry(reg)
    try:
        generate(project, op)
    except Exception:
        project.remove_operation(op)
        raise
    sync(project)
    project._renumber()
    return op, project.registry[op.Name]


def update_operation(project, op, **params):
    reg = project.registry
    reg[op.Name]["params"].update({k: v for k, v in params.items() if v is not None})
    project._save_registry(reg)
    return generate(project, op)
