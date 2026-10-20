# SPDX-License-Identifier: LGPL-2.1-or-later
"""Contrôle matière : simulation d'enlèvement de matière par carte de hauteur (Z-map, 3 axes).

Le brut est une grille de colonnes verticales (pas ``resolution`` mm) ; chaque colonne garde la
hauteur de matière restante. Chaque mouvement de coupe (G1, G2, G3, découpés) balaie la grille avec
le profil de la fraise (plate, boule, torique, conique) : la hauteur devient le minimum entre la
matière et le dessous de la fraise. Les rapides (G0) qui entrent dans la matière sont comptés.

Comparaison avec la pièce (hauteur du dessus de la pièce dans chaque colonne, par triangulation) :

- **entaille** : la matière restante est sous le dessus de la pièce (la fraise a mangé la pièce) ;
- **reste** : matière laissée au-dessus de la pièce (surépaisseur, crêtes, zones non usinées).

Limites : une colonne ne voit que le dessus (pas de contre-dépouille, parois verticales non
contrôlées) ; les opérations qui utilisent A (indexées hors A0, enroulées) ne sont pas simulées ;
précision de l'ordre du pas de grille dans le plan, exacte en Z au centre des colonnes.
"""

import math

import FreeCAD

DEFAULT_RESOLUTION = 0.5
MAX_CELLS = 2_000_000
_ARC_STEP_MM = 0.25
_SLOPE_STEP_MM = 0.5
_SLOPE_DZ_MM = 0.05


def _np():
    import numpy

    return numpy


# -- profil des fraises ------------------------------------------------------------------------------


class ToolProfile(object):
    """Hauteur du dessous de la fraise au-dessus de sa pointe, en fonction de la distance à l'axe."""

    def __init__(self, kind, diameter, corner_radius=0.0, tip_diameter=0.0, included_angle_deg=None):
        self.kind = kind
        self.radius = diameter / 2.0
        self.corner_radius = min(corner_radius or 0.0, self.radius)
        self.tip_radius = (tip_diameter or 0.0) / 2.0
        self.included_angle_deg = included_angle_deg

    @classmethod
    def from_library_tool(cls, tool):
        """Profil depuis un outil de la bibliothèque ; ``(profil, approximation ou None)``."""
        g = tool.geometry
        t = tool.tool_type
        if t in ("ballend",):
            return cls("ball", g.diameter), None
        if t in ("bullnose",) and g.corner_radius:
            return cls("bull", g.diameter, corner_radius=g.corner_radius), None
        if t in ("vbit", "chamfer", "engrave") and g.tip_included_angle_deg:
            return cls("cone", g.diameter, tip_diameter=g.tip_diameter, included_angle_deg=g.tip_included_angle_deg), None
        if t in ("drill",) and getattr(g, "tip_included_angle_deg", None):
            return cls("cone", g.diameter, included_angle_deg=g.tip_included_angle_deg), None
        if t in ("endmill", "facemill"):
            return cls("flat", g.diameter), None
        return cls("flat", g.diameter), "tool type %s simulated as a flat end mill" % t

    def lift(self, d):
        """Hauteur du dessous de la fraise à la distance ``d`` (tableau numpy, d <= rayon)."""
        np = _np()
        r = self.radius
        if self.kind == "ball":
            return r - np.sqrt(np.maximum(r * r - d * d, 0.0))
        if self.kind == "bull":
            rc = self.corner_radius
            flat = r - rc
            e = np.maximum(d - flat, 0.0)
            return rc - np.sqrt(np.maximum(rc * rc - e * e, 0.0))
        if self.kind == "cone":
            half = math.radians(self.included_angle_deg / 2.0)
            return np.maximum(d - self.tip_radius, 0.0) / math.tan(half)
        return np.zeros_like(d)


# -- carte de hauteur ---------------------------------------------------------------------------------


class ZMap(object):
    def __init__(self, xmin, ymin, xmax, ymax, ztop, resolution=DEFAULT_RESOLUTION):
        np = _np()
        nx = int(math.ceil((xmax - xmin) / resolution))
        ny = int(math.ceil((ymax - ymin) / resolution))
        if nx * ny > MAX_CELLS:
            raise ValueError("material check: %d x %d cells, increase the resolution (max %d cells)"
                             % (nx, ny, MAX_CELLS))
        self.res = float(resolution)
        self.x0, self.y0 = float(xmin), float(ymin)
        self.nx, self.ny = nx, ny
        self.xs = self.x0 + (np.arange(nx) + 0.5) * self.res  # centres des colonnes
        self.ys = self.y0 + (np.arange(ny) + 0.5) * self.res
        self.top = np.full((nx, ny), float(ztop))
        self.initial = self.top.copy()
        self.rapid_hits = 0
        self.rapid_hit_at = None

    @classmethod
    def from_bounds(cls, bounds, resolution=DEFAULT_RESOLUTION):
        return cls(bounds["xmin"], bounds["ymin"], bounds["xmax"], bounds["ymax"], bounds["zmax"], resolution)

    def _window(self, xlo, xhi, ylo, yhi):
        np = _np()
        i0 = max(0, int(math.floor((xlo - self.x0) / self.res)))
        i1 = min(self.nx, int(math.ceil((xhi - self.x0) / self.res)) + 1)
        j0 = max(0, int(math.floor((ylo - self.y0) / self.res)))
        j1 = min(self.ny, int(math.ceil((yhi - self.y0) / self.res)) + 1)
        if i0 >= i1 or j0 >= j1:
            return None
        return i0, i1, j0, j1, np.meshgrid(self.xs[i0:i1], self.ys[j0:j1], indexing="ij")

    def sweep(self, p0, p1, tool, rapid=False):
        """Balaye le segment p0 -> p1 (pointe de la fraise) ; retourne True si de la matière est touchée."""
        np = _np()
        length = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        dz = abs(p1[2] - p0[2])
        if length > 1e-9 and (length > _SLOPE_STEP_MM and dz > 1e-9 or dz > _SLOPE_DZ_MM):
            # pente : découpe en morceaux courts et peu inclinés (Z pris au point le plus proche)
            n = int(math.ceil(max(length / _SLOPE_STEP_MM, dz / _SLOPE_DZ_MM)))
            hit = False
            for k in range(n):
                a = [p0[c] + (p1[c] - p0[c]) * k / n for c in range(3)]
                b = [p0[c] + (p1[c] - p0[c]) * (k + 1) / n for c in range(3)]
                hit = self.sweep(a, b, tool, rapid) or hit
            return hit
        r = tool.radius
        win = self._window(min(p0[0], p1[0]) - r, max(p0[0], p1[0]) + r,
                           min(p0[1], p1[1]) - r, max(p0[1], p1[1]) + r)
        if win is None:
            return False
        i0, i1, j0, j1, (X, Y) = win
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        L2 = dx * dx + dy * dy
        if L2 < 1e-18:  # mouvement vertical : la pointe descend jusqu'au plus bas des deux points
            t = np.zeros_like(X)
            z_tip = min(p0[2], p1[2])
        else:
            t = np.clip(((X - p0[0]) * dx + (Y - p0[1]) * dy) / L2, 0.0, 1.0)
            z_tip = p0[2] + t * (p1[2] - p0[2])
        d = np.hypot(X - (p0[0] + t * dx), Y - (p0[1] + t * dy))
        inside = d <= r + 1e-9
        if not inside.any():
            return False
        z = z_tip + tool.lift(np.minimum(d, r))
        z = np.where(inside, z, np.inf)
        block = self.top[i0:i1, j0:j1]
        touched = z < block - 1e-6
        if rapid and touched.any():
            self.rapid_hits += 1
            if self.rapid_hit_at is None:
                self.rapid_hit_at = tuple(p1)
        np.minimum(block, z, out=block)
        return bool(touched.any())

    def removed_volume(self):
        return float((self.initial - self.top).sum() * self.res * self.res)


# -- collisions ---------------------------------------------------------------------------------------


class Envelope(object):
    """Volume de révolution de l'assemblage, par tronçons au-dessus de la pointe : ``(z_bas, z_haut, rayon, rôle)``.

    Rôles : ``cutter`` (partie taillée, longueur de coupe), ``shank`` (outil non taillé jusqu'à la
    sortie), ``holder`` (porte-outil au-dessus de la sortie). Tronçons coniques : rayon maximal
    (prudent : peut signaler un contact qui n'existe pas, jamais l'inverse).
    """

    def __init__(self, parts, has_holder):
        self.parts = parts
        self.has_holder = has_holder

    @classmethod
    def from_assembly(cls, asm, tool, holder):
        parts = []
        z = 0.0
        flute = tool.geometry.flute_length
        stickout = asm.stickout
        for seg in tool.silhouette():
            lo, hi = z, min(z + seg.length, stickout)
            if hi <= lo:
                break
            r = max(seg.lower_diameter, seg.upper_diameter) / 2.0
            if hi <= flute + 1e-9:
                parts.append((lo, hi, r, "cutter"))
            elif lo >= flute - 1e-9:
                parts.append((lo, hi, r, "shank"))
            else:
                parts.append((lo, flute, r, "cutter"))
                parts.append((flute, hi, r, "shank"))
            z = hi
        if z < stickout - 1e-6:  # queue au-delà de la silhouette connue
            parts.append((z, stickout, tool.geometry.shank_diameter / 2.0, "shank"))
        if holder is not None:
            z = stickout
            for seg in holder.segments:
                parts.append((z, z + seg.length, max(seg.lower_diameter, seg.upper_diameter) / 2.0, "holder"))
                z += seg.length
        return cls(parts, holder is not None)


def material_excess(zmap, p0, p1, radius, offset):
    """Plus grand dépassement de matière au-dessus de ``pointe + offset`` dans ``radius`` le long du segment.

    Retourne ``(dépassement, (x, y, z_pointe))`` ; dépassement <= 0 : pas de contact."""
    np = _np()
    win = zmap._window(min(p0[0], p1[0]) - radius, max(p0[0], p1[0]) + radius,
                       min(p0[1], p1[1]) - radius, max(p0[1], p1[1]) + radius)
    if win is None:
        return 0.0, None
    i0, i1, j0, j1, (X, Y) = win
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    L2 = dx * dx + dy * dy
    t = np.zeros_like(X) if L2 < 1e-18 else np.clip(((X - p0[0]) * dx + (Y - p0[1]) * dy) / L2, 0.0, 1.0)
    d = np.hypot(X - (p0[0] + t * dx), Y - (p0[1] + t * dy))
    z_tip = min(p0[2], p1[2]) if L2 < 1e-18 else p0[2] + t * (p1[2] - p0[2])
    excess = np.where(d <= radius + 1e-9, zmap.top[i0:i1, j0:j1] - (z_tip + offset), -np.inf)
    k = int(np.argmax(excess))
    worst = float(excess.flat[k])
    if not np.isfinite(worst) or worst <= 0:
        return worst if np.isfinite(worst) else 0.0, None
    tk = float(np.asarray(t).flat[k]) if L2 >= 1e-18 else 0.0
    at = (p0[0] + tk * dx, p0[1] + tk * dy, min(p0[2], p1[2]) if L2 < 1e-18 else p0[2] + tk * (p1[2] - p0[2]))
    return worst, at


def clamp_contacts(p0, p1, envelope, boxes, step=1.0):
    """Contacts entre l'assemblage (toutes ses parties) et des brides (``FreeCAD.BoundBox``) le long du segment.

    Retourne une liste ``(bride, rôle, pénétration, (x, y, z_pointe))`` (premier point de chaque bride)."""
    length = math.dist(p0, p1)
    n = max(1, int(math.ceil(length / step)))
    hits = {}
    for k in range(n + 1):
        q = [p0[c] + (p1[c] - p0[c]) * k / n for c in range(3)]
        for name, bb in boxes:
            if name in hits:
                continue
            ex = max(bb.XMin - q[0], 0.0, q[0] - bb.XMax)
            ey = max(bb.YMin - q[1], 0.0, q[1] - bb.YMax)
            dist = math.hypot(ex, ey)
            for lo, hi, r, role in envelope.parts:
                if q[2] + lo < bb.ZMax - 1e-6 and q[2] + hi > bb.ZMin + 1e-6 and dist < r - 1e-6:
                    hits[name] = (name, role, r - dist, tuple(q))
                    break
    return list(hits.values())


# -- parcours -----------------------------------------------------------------------------------------


def path_segments(commands, start=None, with_index=False):
    """``(rapid, p0, p1)`` en coordonnées machine depuis des commandes Path (arcs G17 découpés).

    ``start`` : position avant le premier mouvement ; inconnue (None) -> le premier mouvement fixe
    seulement la position (aucun balayage depuis une origine supposée)."""
    pos = list(start) if start is not None else None
    out = []
    for index, c in enumerate(commands, 1):
        name = c.Name.upper()
        p = c.Parameters
        if name not in ("G0", "G00", "G1", "G01", "G2", "G02", "G3", "G03"):
            continue
        if pos is None:
            pos = [p.get("X", 0.0), p.get("Y", 0.0), p.get("Z", 0.0)]
            continue
        end = [p.get("X", pos[0]), p.get("Y", pos[1]), p.get("Z", pos[2])]
        if name in ("G2", "G02", "G3", "G03"):
            cx, cy = pos[0] + p.get("I", 0.0), pos[1] + p.get("J", 0.0)
            a0 = math.atan2(pos[1] - cy, pos[0] - cx)
            a1 = math.atan2(end[1] - cy, end[0] - cx)
            radius = math.hypot(pos[0] - cx, pos[1] - cy)
            cw = name in ("G2", "G02")
            sweep = a1 - a0
            if cw and sweep >= -1e-12:
                sweep -= 2 * math.pi
            elif not cw and sweep <= 1e-12:
                sweep += 2 * math.pi
            n = max(2, int(math.ceil(abs(sweep) * radius / _ARC_STEP_MM)))
            prev = list(pos)
            for k in range(1, n + 1):
                a = a0 + sweep * k / n
                q = [cx + radius * math.cos(a), cy + radius * math.sin(a), pos[2] + (end[2] - pos[2]) * k / n]
                out.append((False, prev, q, index) if with_index else (False, prev, q))
                prev = q
        else:
            seg = (name in ("G0", "G00"), list(pos), end)
            out.append(seg + (index,) if with_index else seg)
        pos = end
    return out, pos


# -- dessus de la pièce ---------------------------------------------------------------------------------


def model_heights(zmap, shapes, deflection=0.05):
    """Hauteur du dessus des pièces au centre de chaque colonne (-inf hors pièce)."""
    np = _np()
    h = np.full((zmap.nx, zmap.ny), -np.inf)
    for shape in shapes:
        points, triangles = shape.tessellate(deflection)
        pts = np.array([[v.x, v.y, v.z] for v in points]) if points else np.zeros((0, 3))
        for tri in triangles:
            a, b, c = pts[tri[0]], pts[tri[1]], pts[tri[2]]
            det = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
            if abs(det) < 1e-12:
                continue  # face verticale vue de dessus
            win = zmap._window(min(a[0], b[0], c[0]), max(a[0], b[0], c[0]),
                               min(a[1], b[1], c[1]), max(a[1], b[1], c[1]))
            if win is None:
                continue
            i0, i1, j0, j1, (X, Y) = win
            l1 = ((b[1] - c[1]) * (X - c[0]) + (c[0] - b[0]) * (Y - c[1])) / det
            l2 = ((c[1] - a[1]) * (X - c[0]) + (a[0] - c[0]) * (Y - c[1])) / det
            l3 = 1.0 - l1 - l2
            eps = -1e-9
            inside = (l1 >= eps) & (l2 >= eps) & (l3 >= eps)
            if not inside.any():
                continue
            z = np.where(inside, l1 * a[2] + l2 * b[2] + l3 * c[2], -np.inf)
            block = h[i0:i1, j0:j1]
            np.maximum(block, z, out=block)
    return h


def surface_mesh(zmap, mask=None, lift=0.0):
    """Maillage du dessus du brut simulé (cellules de ``mask`` seulement si donné) : ``Mesh.Mesh``."""
    import Mesh

    np = _np()
    if mask is None:  # surface continue par les centres des colonnes : l'éclairage montre le relief
        X, Y = np.meshgrid(zmap.xs, zmap.ys, indexing="ij")
        P = np.stack([X, Y, zmap.top + lift], axis=2)
        a, b = P[:-1, :-1].reshape(-1, 3), P[1:, :-1].reshape(-1, 3)
        c, d = P[1:, 1:].reshape(-1, 3), P[:-1, 1:].reshape(-1, 3)
        tri = np.concatenate([np.stack([a, b, c], axis=1), np.stack([a, c, d], axis=1)]).reshape(-1, 3)
        return Mesh.Mesh([tuple(q) for q in tri.tolist()])
    keep = mask
    i, j = np.nonzero(keep)
    if not len(i):
        return Mesh.Mesh()
    x0 = zmap.x0 + i * zmap.res
    y0 = zmap.y0 + j * zmap.res
    x1, y1 = x0 + zmap.res, y0 + zmap.res
    z = zmap.top[i, j] + lift
    a = np.stack([x0, y0, z], axis=1)
    b = np.stack([x1, y0, z], axis=1)
    c = np.stack([x1, y1, z], axis=1)
    d = np.stack([x0, y1, z], axis=1)
    tri = np.concatenate([np.stack([a, b, c], axis=1), np.stack([a, c, d], axis=1)]).reshape(-1, 3)
    return Mesh.Mesh([tuple(p) for p in tri.tolist()])


def gouge_mask(zmap, heights, tolerance=0.02):
    np = _np()
    return np.isfinite(heights) & (zmap.top < heights - tolerance)


def compare(zmap, heights, tolerance=0.02):
    """Entailles et reste sur les colonnes de pièce : dict de mesures (mm, mm³)."""
    np = _np()
    on_part = np.isfinite(heights)
    report = {"part_cells": int(on_part.sum()), "gouge_max": 0.0, "gouge_cells": 0, "gouge_at": None,
              "leftover_max": 0.0, "leftover_mean": 0.0, "leftover_at": None}
    if not on_part.any():
        return report
    diff = np.where(on_part, zmap.top - heights, np.nan)  # > 0 : reste ; < 0 : entaille
    gouge = np.where(on_part, -diff, -np.inf)
    gmax = float(np.max(gouge))
    if gmax > tolerance:
        i, j = np.unravel_index(int(np.argmax(gouge)), gouge.shape)
        report.update(gouge_max=gmax, gouge_cells=int((gouge > tolerance).sum()),
                      gouge_at=(float(zmap.xs[i]), float(zmap.ys[j]), float(heights[i, j])))
    left = np.where(on_part, diff, -np.inf)
    lmax = float(np.max(left))
    i, j = np.unravel_index(int(np.argmax(left)), left.shape)
    report.update(leftover_max=max(0.0, lmax), leftover_mean=float(np.nanmean(np.maximum(diff, 0.0))),
                  leftover_at=(float(zmap.xs[i]), float(zmap.ys[j]), float(heights[i, j])))
    return report
