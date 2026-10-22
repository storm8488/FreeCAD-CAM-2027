# SPDX-License-Identifier: LGPL-2.1-or-later
"""Finition 3D à hauteur de crête constante (« Scallop » de Fusion) et pentu / peu incliné.

Calcul (comme la finition 3D de FreeCAD, hauteurs par OpenCamLib) :

1. grille des hauteurs de la pointe de la fraise (``BatchDropCutter`` sur la pièce triangulée), pas
   ``g`` <= pas de crête / 4 ;
2. pas entre passes ``s`` déduit de la crête maximale ``h`` et du rayon de la boule ``R`` :
   ``s = 2 sqrt(h (2R - h))`` (+ la partie plate d'une torique) ;
3. **distance géodésique** sur la surface décrite par le centre de l'outil depuis la limite de la zone
   (Dijkstra sur la grille, voisinage de 16, pas 3D) : les passes sont les courbes de niveau de cette
   distance à ``s/2``, ``3s/2``, ... (décalages successifs de la limite le long de la surface, pas 3D
   constant comme Fusion) ;
4. **couverture** : distance 3D de chaque point de la zone à la passe la plus proche ; là où elle dépasse
   ``s/2`` (crêtes de la distance, sommets), une passe est ajoutée le long de la ligne de crête ;
5. mode **pentu / peu incliné** : au-dessus de l'angle limite, passes à Z constant (courbes de niveau de la
   grille, pas vertical ``s sin(angle)``, soit un pas 3D <= ``s`` sur ces pentes) ; en dessous, passes à
   crête constante limitées à la zone peu inclinée ;
6. chaque point final est recalculé par OpenCamLib (aucune hauteur interpolée : pas d'entaille) ; les
   liaisons courtes suivent la surface, les autres passent par la hauteur de sécurité.

Fraises : boule et torique. La surépaisseur est un décalage normal (fraise de rayon R + e abaissée de e).
"""

import math

import Path.Op.Base as PathOp

from ..i18n import Msg, UserError

KIND = "scallop"
DEFAULT_SCALLOP = 0.02
DEFAULT_THRESHOLD_DEG = 45.0  # Fusion « Threshold angle » : 30-45° conseillés, défaut non documenté (45° d'après un tiers)
DEFAULT_SAMPLE = 0.1
#: rapport pas des passes / pas de la grille minimal
GRID_PER_STEP = 4.0
#: liaison le long de la surface si l'écart XY est au plus ce multiple du pas
STAY_DOWN_STEPS = 2.0
#: pente au-delà de laquelle la grille ne représente plus la surface (parois) : non contrôlée en couverture
WALL_DEG = 75.0
MAX_GRID_POINTS = 4000000
#: points du parcours au-delà desquels le calcul est refusé (chauffage Vz330 : 2,2 millions, < 6 Go ; plateau : 4,3 millions, 8,6 Go mesurés)
MAX_PATH_POINTS = 2500000
#: coupe remplacée par une marche : plus raide que cette pente (dz / dxy) et sous la surface de plus de REFINE_TOL
STEEP_SLOPE = 2.0
REFINE_TOL = 0.002
_NO_HEIGHT = -1.0e6


def _np():
    import numpy

    return numpy


def ocl_module():
    try:
        import ocl
    except ImportError:
        try:
            import opencamlib as ocl
        except ImportError:
            raise UserError("constant scallop finishing needs OpenCamLib (not found in this FreeCAD)")
    return ocl


def stepover(scallop, corner_radius, diameter):
    """Pas entre passes (mm) pour une crête ``scallop`` : boule ``corner_radius = D/2``, torique sinon."""
    if scallop <= 0:
        raise UserError("the maximum scallop height must be positive")
    r = float(corner_radius)
    if r <= 0:
        raise UserError("constant scallop finishing needs a ball or bull nose mill (corner radius > 0)")
    h = min(float(scallop), r)
    return max(float(diameter) - 2.0 * r, 0.0) + 2.0 * math.sqrt(h * (2.0 * r - h))


def scallop_of(step, corner_radius, diameter):
    """Crête théorique entre deux passes à plat espacées de ``step`` (inverse de ``stepover``)."""
    r = float(corner_radius)
    half = max(step - max(float(diameter) - 2.0 * r, 0.0), 0.0) / 2.0
    return r - math.sqrt(max(r * r - half * half, 0.0))


def make_stl(shapes, deflection):
    ocl = ocl_module()
    stl = ocl.STLSurf()
    for shape in shapes:
        verts, facets = shape.tessellate(deflection)
        for a, b, c in facets:
            stl.addTriangle(ocl.Triangle(ocl.Point(*verts[a]), ocl.Point(*verts[b]), ocl.Point(*verts[c])))
    return stl


def make_cutter(diameter, corner_radius, length, leave=0.0):
    """Fraise OpenCamLib ; ``leave`` : surépaisseur (fraise grossie, pointe à abaisser de ``leave``)."""
    ocl = ocl_module()
    d = float(diameter) + 2.0 * leave
    r = float(corner_radius) + leave
    if r >= d / 2.0 - 1e-9:
        return ocl.BallCutter(d, length)
    return ocl.BullCutter(d, r, length)


class Surface(object):
    """Pièce triangulée et fraise : hauteurs de pointe par OpenCamLib (surépaisseur comprise)."""

    def __init__(self, shapes, diameter, corner_radius, leave=0.0, deflection=0.005, length=None):
        self.stl = make_stl(shapes, deflection)
        self.leave = float(leave)
        self.cutter = make_cutter(diameter, corner_radius, length or 10.0 * diameter, leave)

    def drop(self, xs, ys):
        """Hauteur de pointe en chaque point (tableaux), NaN où aucune facette n'est sous la fraise."""
        np = _np()
        ocl = ocl_module()
        bdc = ocl.BatchDropCutter()
        bdc.setSTL(self.stl)
        bdc.setCutter(self.cutter)
        for x, y in zip(xs.tolist(), ys.tolist()):
            bdc.appendPoint(ocl.CLPoint(x, y, _NO_HEIGHT))
        bdc.run()
        z = np.array([p.z for p in bdc.getCLPoints()], dtype=float)
        z[z <= _NO_HEIGHT + 1.0] = np.nan
        return z - self.leave


# -- grille ---------------------------------------------------------------------------------------------


class Grid(object):
    """Hauteurs de pointe sur une grille régulière (centre de l'outil dans ``bounds`` XY)."""

    def __init__(self, surface, xmin, ymin, xmax, ymax, g, zmin=None):
        np = _np()
        nx = int(math.floor((xmax - xmin) / g)) + 1
        ny = int(math.floor((ymax - ymin) / g)) + 1
        if nx * ny > MAX_GRID_POINTS:
            raise UserError("constant scallop finishing: {n} surface samples, increase the sample interval", n=nx * ny)
        self.g = float(g)
        self.xs = xmin + np.arange(nx) * g
        self.ys = ymin + np.arange(ny) * g
        X, Y = np.meshgrid(self.xs, self.ys, indexing="ij")
        self.z = surface.drop(X.ravel(), Y.ravel()).reshape(nx, ny)
        if zmin is not None:
            self.z = np.where(np.isfinite(self.z), np.maximum(self.z, zmin), np.nan)
        self.valid = np.isfinite(self.z)
        zz = np.where(self.valid, self.z, np.nanmin(self.z) if self.valid.any() else 0.0)
        gx, gy = np.gradient(zz, g)
        self.slope = np.degrees(np.arctan(np.hypot(gx, gy)))

    def cell_of(self, pts):
        """Indices (i, j) des cellules des points XY (tableau (n, 2)), bornés à la grille."""
        np = _np()
        i = np.clip(np.rint((pts[:, 0] - self.xs[0]) / self.g).astype(int), 0, len(self.xs) - 1)
        j = np.clip(np.rint((pts[:, 1] - self.ys[0]) / self.g).astype(int), 0, len(self.ys) - 1)
        return i, j


_OFFSETS = ((1, 0), (0, 1), (1, 1), (1, -1), (2, 1), (1, 2), (2, -1), (1, -2))


def geodesic(grid, mask, sources):
    """Distance 3D le long de la surface (centre de l'outil) depuis ``sources`` dans ``mask`` (inf ailleurs)."""
    np = _np()
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import dijkstra

    nx, ny = mask.shape
    index = -np.ones(mask.shape, dtype=np.int64)
    n = int(mask.sum())
    out = np.full(mask.shape, np.inf)
    if n == 0 or not (sources & mask).any():
        return out
    index[mask] = np.arange(n)
    rows, cols, weights = [], [], []
    z = np.where(mask, grid.z, 0.0)
    for di, dj in _OFFSETS:
        a_i, b_i = slice(max(0, -di), nx - max(0, di)), slice(max(0, di), nx - max(0, -di))
        a_j, b_j = slice(max(0, -dj), ny - max(0, dj)), slice(max(0, dj), ny - max(0, -dj))
        both = mask[a_i, a_j] & mask[b_i, b_j]
        if not both.any():
            continue
        dz = (z[b_i, b_j] - z[a_i, a_j])[both]
        rows.append(index[a_i, a_j][both])
        cols.append(index[b_i, b_j][both])
        weights.append(np.sqrt((di * grid.g) ** 2 + (dj * grid.g) ** 2 + dz * dz) + 1e-12)
    graph = coo_matrix((np.concatenate(weights), (np.concatenate(rows), np.concatenate(cols))), shape=(n, n)).tocsr()
    src = index[sources & mask]
    dist = dijkstra(graph, directed=False, indices=src, min_only=True)
    out[mask] = dist
    return out


def _border(mask):
    """Cellules de ``mask`` voisines (4) d'une cellule hors masque ou du bord de la grille."""
    np = _np()
    pad = np.pad(mask, 1, constant_values=False)
    inner = pad[:-2, 1:-1] & pad[2:, 1:-1] & pad[1:-1, :-2] & pad[1:-1, 2:]
    return mask & ~inner


def iso_lines(grid, field, level, mask):
    """Courbes de niveau ``field = level`` dans ``mask`` : liste de tableaux XY ``(n, 2)``."""
    np = _np()
    import contourpy

    values = np.where(mask & np.isfinite(field), field, np.nan)
    gen = contourpy.contour_generator(grid.xs, grid.ys, np.ma.masked_invalid(values.T), line_type="Separate")
    return [np.asarray(line) for line in gen.lines(level) if len(line) >= 2]


def _split_by_mask(grid, line, keep):
    """Morceaux d'une polyligne XY dont les points tombent dans ``keep``."""
    np = _np()
    i, j = grid.cell_of(line)
    inside = keep[i, j]
    pieces, start = [], None
    for k, ok in enumerate(inside.tolist() + [False]):
        if ok and start is None:
            start = k
        elif not ok and start is not None:
            if k - start >= 2:
                pieces.append(line[start:k])
            start = None
    if len(pieces) >= 2 and inside[0] and inside[-1] and np.allclose(line[0], line[-1]):
        pieces[0] = np.vstack([pieces[-1], pieces[0]])  # boucle coupée à l'endroit du départ
        pieces.pop()
    return pieces


def _resample(line, step):
    """Polyligne XY rééchantillonnée (aucun segment plus long que ``step``)."""
    np = _np()
    out = [line[:1]]
    for a, b in zip(line[:-1], line[1:]):
        n = int(math.ceil(float(np.hypot(*(b - a))) / step))
        if n > 1:
            t = (np.arange(1, n + 1) / float(n))[:, None]
            out.append(a + (b - a) * t)
        else:
            out.append(b[None, :])
    return np.vstack(out)


def _ridge_lines(grid, field, todo):
    """Lignes de crête de ``field`` dans les cellules ``todo`` (points XY chaînés)."""
    np = _np()
    from scipy.spatial import cKDTree

    f = np.where(np.isfinite(field), field, -np.inf)
    ridge = np.zeros(f.shape, dtype=bool)
    for di, dj in ((1, 0), (0, 1), (1, 1), (1, -1)):
        a = np.roll(f, (di, dj), axis=(0, 1))
        b = np.roll(f, (-di, -dj), axis=(0, 1))
        ridge |= (f >= a) & (f >= b)
    cells = np.argwhere(ridge & todo)
    if not len(cells):
        cells = np.argwhere(todo)
    pts = np.column_stack([grid.xs[cells[:, 0]], grid.ys[cells[:, 1]]])
    if not len(pts):
        return []
    tree = cKDTree(pts)
    used = np.zeros(len(pts), dtype=bool)
    lines = []
    reach = 2.0 * grid.g * 1.5
    for start in range(len(pts)):
        if used[start]:
            continue
        chain = [start]
        used[start] = True
        for _direction in (0, 1):
            cur = chain[-1]
            while True:
                near = [k for k in tree.query_ball_point(pts[cur], reach) if not used[k]]
                if not near:
                    break
                nxt = min(near, key=lambda k: float(np.hypot(*(pts[k] - pts[cur]))))
                used[nxt] = True
                chain.append(nxt)
                cur = nxt
            chain.reverse()
        line = pts[chain]
        if len(line) == 1:
            line = np.vstack([line, line])  # un point isolé : la fraise y touche la surface
        lines.append(line)
    return lines


def _cover(grid, valid, passes):
    """Distance 3D (sur la surface) de chaque cellule à la passe la plus proche."""
    np = _np()
    src = np.zeros(valid.shape, dtype=bool)
    for line in passes:
        i, j = grid.cell_of(line)
        src[i, j] = True
    return geodesic(grid, valid, src & valid)


def compute_passes(surface, bounds, diameter, corner_radius, scallop, sample=DEFAULT_SAMPLE, steep_shallow=False,
                   threshold_deg=DEFAULT_THRESHOLD_DEG, zmin=None):
    """Passes de finition (polylignes XY, sans Z) et mesures.

    ``bounds`` : (xmin, ymin, xmax, ymax) du centre de l'outil. Retourne un dict : ``shallow`` et ``steep``
    (listes de polylignes XY), ``stepover``, ``grid``, ``uncovered`` (cellules restant à plus de s/2 d'une passe)."""
    np = _np()
    s = stepover(scallop, corner_radius, diameter)
    g = min(float(sample), s / GRID_PER_STEP)
    xmin, ymin, xmax, ymax = bounds
    # la grille ne porte que la distance le long de la surface (chaque point final est recalculé par
    # OpenCamLib) : sur une grande pièce elle peut grossir jusqu'à pas / 4
    cells = ((xmax - xmin) / g + 1) * ((ymax - ymin) / g + 1)
    if cells > MAX_GRID_POINTS:
        g = max(g, min(s / GRID_PER_STEP, math.sqrt((xmax - xmin) * (ymax - ymin) / (0.9 * MAX_GRID_POINTS))))
    grid = Grid(surface, xmin, ymin, xmax, ymax, g, zmin=zmin)
    valid = grid.valid
    if not valid.any():
        raise UserError("constant scallop finishing: the tool finds no surface inside the boundary")
    steep = np.zeros(valid.shape, dtype=bool)
    steep_lines = []
    warnings = []
    if steep_shallow:
        steep = valid & (grid.slope > threshold_deg)
        dz = s * math.sin(math.radians(max(threshold_deg, 1.0)))
        keep = _dilate(steep, 2)
        zs = grid.z[steep]
        if zs.size:
            level = float(zs.max()) - dz / 2.0
            while level > float(zs.min()) - dz / 2.0:
                for line in iso_lines(grid, grid.z, level, valid):
                    steep_lines.extend(_split_by_mask(grid, line, keep))
                level -= dz
    shallow = valid & ~steep
    dist = geodesic(grid, shallow, _border(shallow))
    finite = np.isfinite(dist)
    shallow_lines = []
    if finite.any():
        dmax = float(dist[finite].max())
        level = s / 2.0
        while level < dmax:
            shallow_lines.extend(iso_lines(grid, dist, level, shallow))
            level += s
    # couverture : ce qui reste à plus de s/2 de toute passe (crêtes de la distance, sommets)
    checked = valid & (grid.slope < WALL_DEG) & (shallow if steep_shallow else valid)
    extra = []
    for _round in range(3):
        cover = _cover(grid, valid, shallow_lines + steep_lines + extra)
        todo = checked & (cover > s / 2.0)
        if not todo.any():
            break
        extra.extend(_ridge_lines(grid, np.where(shallow, dist, cover), todo))
    else:
        cover = _cover(grid, valid, shallow_lines + steep_lines + extra)
        todo = checked & (cover > s / 2.0)
    if todo.any():
        warnings.append(Msg("{n} surface samples stay further than half a step from a pass (scallop may exceed the target there)",
                            n=int(todo.sum())))
    if (valid & (grid.slope >= WALL_DEG)).any() and not steep_shallow:
        warnings.append(Msg("walls steeper than {a:g}° are not checked by the scallop computation: use steep and shallow mode",
                            a=WALL_DEG))
    return {"shallow": shallow_lines + extra, "steep": steep_lines, "stepover": s, "grid": grid,
            "uncovered": int(todo.sum()), "warnings": warnings, "grid_step": g, "sample": min(float(sample), g)}


def _dilate(mask, n):
    from scipy.ndimage import binary_dilation

    return binary_dilation(mask, iterations=n) if n > 0 else mask


# -- passes en 3D et liaisons -------------------------------------------------------------------------------


def check_size(lines, sample, scallop):
    """Refus clair quand le parcours dépasserait ``MAX_PATH_POINTS`` points (un point par intervalle
    d'échantillonnage) : plateau 220 x 220 mm de l'utilisateur à 0,02 mm de crête, 4,3 millions de points, plus de
    10 Go de mémoire avant la fin du calcul."""
    np = _np()
    total = 0
    for l in lines:  # même compte que ``_resample`` : au moins un point par segment
        if len(l) >= 2:
            d = np.hypot(*np.diff(np.asarray(l)[:, :2], axis=0).T)
            total += 1 + int(np.maximum(np.ceil(d / sample), 1).sum())
    if total > MAX_PATH_POINTS:
        raise UserError("constant scallop finishing: about {n} million points for this area at a {h} mm scallop height: "
                        "increase the scallop height or the sample interval, or limit the area",
                        n="%.1f" % (total / 1e6), h="%g" % scallop)
    return total


def order_passes(lines):
    """Ordre des passes : plus proche voisin (boucles tournées, lignes ouvertes retournées au besoin).

    Même règle qu'une recherche de toutes les passes restantes à chaque pas (plus courte distance, puis la première
    passe de la liste ; départ d'une boucle à son sommet le plus proche, ligne ouverte par le bout le plus proche,
    son début à égalité), avec un arbre des points de départ possibles : 34 000 passes sur le plateau 220 x 220 mm
    au lieu de plusieurs centaines de millions de comparaisons."""
    np = _np()
    from scipy.spatial import cKDTree

    todo = [np.asarray(l) for l in lines if len(l) >= 2]
    if not todo:
        return []
    closed = [bool(np.allclose(l[0], l[-1])) for l in todo]
    pts, owner = [], []
    for k, (line, c) in enumerate(zip(todo, closed)):
        p = line[:-1] if c else line[[0, -1]]
        pts.append(p[:, :2])
        owner.append(np.full(len(p), k))
    pts, owner = np.vstack(pts), np.concatenate(owner)
    tree = cKDTree(pts)
    used = np.zeros(len(todo), dtype=bool)
    alive = len(pts)  # points dont la passe reste à faire

    def candidate(k, cur):
        line = todo[k]
        if closed[k]:
            dd = np.hypot(*(line[:-1] - cur).T)
            m = int(np.argmin(dd))
            return np.vstack([line[m:-1], line[:m + 1]]), float(dd[m])
        d0, d1 = float(np.hypot(*(line[0] - cur))), float(np.hypot(*(line[-1] - cur)))
        return (line, d0) if d0 <= d1 else (line[::-1], d1)

    out = [todo[0]]
    used[0] = True
    alive -= int((owner == 0).sum())
    cur = todo[0][-1]
    while alive > 0:
        if alive < len(pts) // 2:  # arbre refait sur les points restants (sinon les k plus proches sont déjà faits)
            keep = ~used[owner]
            pts, owner = pts[keep], owner[keep]
            tree = cKDTree(pts)
        k_query = 16
        while True:
            dist, idx = tree.query(cur[:2], k=min(k_query, len(pts)))
            dist, idx = np.atleast_1d(dist), np.atleast_1d(idx)
            ok = ~used[owner[idx]]
            if ok.any() or k_query >= len(pts):
                break
            k_query *= 4
        # toutes les passes à la plus courte distance (à l'arrondi près de l'arbre) : distance exacte, puis la
        # première de la liste
        near = dist[ok][0]
        within = np.asarray(tree.query_ball_point(cur[:2], near + 1e-6), dtype=int)
        within = within[~used[owner[within]]]
        best = None
        for k in sorted(set(owner[within].tolist())):
            cand, d = candidate(k, cur)
            if best is None or d < best[1]:
                best = (k, d, cand)
        k, _d, cand = best
        used[k] = True
        alive -= 2 if not closed[k] else len(todo[k]) - 1
        out.append(cand)
        cur = cand[-1]
    return out


def moves_for(surface, lines, step, safe_z, stay_down):
    """Mouvements ``(kind, x, y, z)`` (``rapid`` / ``plunge`` / ``cut``) : hauteurs recalculées par OpenCamLib.

    Liaison le long de la surface quand l'écart XY entre deux passes est au plus ``stay_down``."""
    np = _np()
    lines = [_resample(l, step) for l in lines]
    if not lines:
        return []
    allpts = np.vstack(lines)
    z = surface.drop(allpts[:, 0], allpts[:, 1])
    passes, k = [], 0
    for line in lines:
        zz = z[k:k + len(line)]
        k += len(line)
        keep = np.isfinite(zz)
        if keep.any():
            passes.append(np.column_stack([line[keep], zz[keep]]))
    # liaisons courtes : points intermédiaires recalculés en un seul lot (un arbre OpenCamLib par lot)
    links = [None]
    for a, b in zip(passes[:-1], passes[1:]):
        gap = float(np.hypot(*(b[0, :2] - a[-1, :2])))
        links.append(_resample(np.vstack([a[-1, :2], b[0, :2]]), step)[1:-1] if gap <= stay_down else None)
    flat = [l for l in links if l is not None and len(l)]
    if flat:
        lpts = np.vstack(flat)
        lz = surface.drop(lpts[:, 0], lpts[:, 1])
        k = 0
        for n, l in enumerate(links):
            if l is not None and len(l):
                links[n] = np.column_stack([l, lz[k:k + len(l)]])
                k += len(l)
    moves, prev = [], None
    for pts, link in zip(passes, links):
        if prev is not None and link is not None and np.isfinite(link).all():
            moves.extend(("cut", float(x), float(y), float(zv)) for x, y, zv in link.tolist())
        else:
            prev = None
        if prev is None:
            moves.append(("rapid", float(pts[0, 0]), float(pts[0, 1]), float(safe_z)))
            moves.append(("plunge", float(pts[0, 0]), float(pts[0, 1]), float(pts[0, 2])))
        moves.extend(("cut", float(x), float(y), float(zv)) for x, y, zv in pts.tolist())
        prev = pts[-1]
    if moves:
        last = moves[-1]
        moves.append(("rapid", last[1], last[2], float(safe_z)))
    return refine_steep(surface, moves)


def refine_steep(surface, moves, tol=REFINE_TOL):
    """Marches à la place des coupes raides qui passent sous la surface du centre de l'outil.

    Au bord d'une paroi verticale, deux points voisins d'une passe sont l'un sur l'arête (boule posée sur le bord),
    l'autre au pied de la paroi : la droite qui les relie entre dans l'arête (jusqu'à l'écart entre les points :
    0,053 mm mesurés sur l'ER16). Chaque coupe plus raide que ``STEEP_SLOPE`` dont le milieu est sous la hauteur
    OpenCamLib (+ ``tol``, un seul lot pour toutes) devient une marche : palier à la plus haute des deux hauteurs,
    puis montée ou descente verticale. Entre deux points voisins (au plus l'intervalle d'échantillonnage), la
    surface ne dépasse pas la plus haute des deux de plus que la flèche de la boule (< 0,001 mm à 0,1 mm). Les
    pentes douces ne sont pas touchées (flèche de corde < 0,002 mm au pas d'échantillonnage)."""
    np = _np()
    if len(moves) < 2:
        return moves
    kinds = np.array([m[0] for m in moves])
    pts = np.array([m[1:] for m in moves], dtype=float)
    a, b = pts[:-1], pts[1:]
    dxy = np.hypot(b[:, 0] - a[:, 0], b[:, 1] - a[:, 1])
    cand = np.nonzero((kinds[1:] == "cut") & (dxy > 1e-9) & (np.abs(b[:, 2] - a[:, 2]) > STEEP_SLOPE * dxy))[0]
    if not len(cand):
        return moves
    mid = 0.5 * (a[cand] + b[cand])
    z = surface.drop(mid[:, 0], mid[:, 1])
    bad = cand[np.isfinite(z) & (z > mid[:, 2] + tol)]
    if not len(bad):
        return moves
    a, b = pts[bad], pts[bad + 1]
    corner = np.where((a[:, 2] >= b[:, 2])[:, None], np.column_stack([b[:, :2], a[:, 2]]),
                      np.column_stack([a[:, :2], b[:, 2]]))
    pts = np.insert(pts, bad + 1, corner, axis=0)
    kinds = np.insert(kinds, bad + 1, "cut")
    return [(str(k), float(x), float(y), float(z)) for k, (x, y, z) in zip(kinds.tolist(), pts)]


def path_commands(moves, horiz_feed, vert_feed):
    """Commandes Path (avances dans l'unité interne de Path, mm/s)."""
    import Path

    cmds, cur = [], None
    for kind, x, y, z in moves:
        if kind == "rapid":
            if cur is not None and z > cur[2]:
                cmds.append(Path.Command("G0", {"Z": z}))
                cmds.append(Path.Command("G0", {"X": x, "Y": y}))
            else:
                cmds.append(Path.Command("G0", {"X": x, "Y": y}))
                cmds.append(Path.Command("G0", {"Z": z}))
        elif kind == "plunge":
            cmds.append(Path.Command("G1", {"X": x, "Y": y, "Z": z, "F": vert_feed}))
        else:
            cmds.append(Path.Command("G1", {"X": x, "Y": y, "Z": z, "F": horiz_feed}))
        cur = (x, y, z)
    return cmds


# -- opération FreeCAD ------------------------------------------------------------------------------------

#: propriétés propres à l'opération (nom, type, valeur par défaut, aide anglaise)
PROPERTIES = (
    ("ScallopHeight", "App::PropertyLength", DEFAULT_SCALLOP, "Maximum height of the ridge left between two passes."),
    ("SampleInterval", "App::PropertyLength", DEFAULT_SAMPLE, "Distance between surface samples (capped at a quarter of the step)."),
    ("SteepShallow", "App::PropertyBool", False, "Constant-Z passes above the threshold angle, constant scallop below."),
    ("ThresholdAngle", "App::PropertyAngle", DEFAULT_THRESHOLD_DEG, "Slope (deg) above which steep-and-shallow mode cuts at constant Z."),
    ("DepthOffset", "App::PropertyDistance", 0.0, "Material left on the surface (normal offset)."),
    ("LinearDeflection", "App::PropertyLength", 0.005, "Mesh tolerance used to sample the model (smaller = more precise)."),
    ("BoundBox", "App::PropertyEnumeration", ("BaseBoundBox", "Stock"), "Machine the model bounding box or the whole stock."),
    ("Stepover3D", "App::PropertyLength", 0.0, "Distance between passes along the surface, derived from the scallop height."),
)


def corner_radius_of(tool):
    """Rayon de bout d'un ToolBit FreeCAD (boule : D/2, torique : D/2 - rayon plat) ; ``None`` sinon."""
    shape = " ".join(str(getattr(tool, p, "")) for p in ("ShapeID", "ShapeType", "ShapeName", "BitShape")).lower()
    d = float(tool.Diameter)
    if "bull" in shape and hasattr(tool, "FlatRadius"):
        flat = float(getattr(tool.FlatRadius, "Value", tool.FlatRadius))
        return max(d / 2.0 - flat, 0.0) or None
    if "ball" in shape:
        return d / 2.0
    return None


class ObjectScallop(PathOp.ObjectOp):
    def opFeatures(self, obj):
        return (PathOp.FeatureTool | PathOp.FeatureDepths | PathOp.FeatureHeights | PathOp.FeatureBaseFaces
                | PathOp.FeatureCoolant)

    def initOperation(self, obj):
        for name, type_id, default, doc in PROPERTIES:
            if name not in obj.PropertiesList:
                obj.addProperty(type_id, name, "Scallop", doc)
                if type_id == "App::PropertyEnumeration":
                    setattr(obj, name, list(default))
                else:
                    setattr(obj, name, default)
        obj.setEditorMode("Stepover3D", 1)

    def opOnDocumentRestored(self, obj):
        self.initOperation(obj)

    def opUpdateDepths(self, obj):
        # profondeur finale par défaut = bas de la pièce (sans géométrie choisie, FreeCAD prend le haut du modèle)
        shapes = [base.Shape for base, _subs in (getattr(obj, "Base", None) or [])]
        shapes = shapes or [m.Shape for m in (getattr(self, "model", None) or []) if getattr(m, "Shape", None)]
        if shapes:
            obj.OpFinalDepth = min(s.BoundBox.ZMin for s in shapes)

    def opExecute(self, obj):
        from . import operations as opsmod

        radius = corner_radius_of(self.tool)
        if radius is None:
            raise UserError("constant scallop finishing needs a ball or bull nose mill")
        diameter = float(self.tool.Diameter)
        models = [base for base, _subs in (obj.Base or [])] or list(self.model)
        shapes = [m.Shape for m in models if getattr(m, "Shape", None) is not None and not m.Shape.isNull()]
        if not shapes:
            raise UserError("constant scallop finishing: no model to machine")
        if obj.BoundBox == "Stock" and self.stock is not None:
            bb = self.stock.Shape.BoundBox
        else:
            bb = shapes[0].BoundBox
            for s in shapes[1:]:
                bb.add(s.BoundBox)
        opsmod.keep_gui_alive()
        surface = Surface(shapes, diameter, radius, leave=float(obj.DepthOffset.Value),
                          deflection=max(float(obj.LinearDeflection.Value), 1e-4))
        res = compute_passes(surface, (bb.XMin, bb.YMin, bb.XMax, bb.YMax), diameter, radius,
                             float(obj.ScallopHeight.Value), sample=float(obj.SampleInterval.Value),
                             steep_shallow=bool(obj.SteepShallow), threshold_deg=float(obj.ThresholdAngle.Value),
                             zmin=float(obj.FinalDepth.Value))
        opsmod.keep_gui_alive()
        obj.Stepover3D = res["stepover"]
        check_size(res["steep"] + res["shallow"], res["sample"], float(obj.ScallopHeight.Value))
        lines = order_passes(res["steep"]) + order_passes(res["shallow"])
        moves = moves_for(surface, lines, res["sample"], float(obj.SafeHeight.Value),
                          STAY_DOWN_STEPS * res["stepover"])
        import FreeCAD
        import Path

        for w in res["warnings"]:
            FreeCAD.Console.PrintWarning("%s: %s\n" % (obj.Label, w))
        self.commandlist.append(Path.Command("G0", {"Z": float(obj.ClearanceHeight.Value)}))
        self.commandlist.extend(path_commands(moves, self.horizFeed, self.vertFeed))


def Create(name, obj=None, parentJob=None):
    import FreeCAD

    if obj is None:
        obj = FreeCAD.ActiveDocument.addObject("Path::FeaturePython", name)
    obj.Proxy = ObjectScallop(obj, name, parentJob)
    return obj


def gui_resources():
    """Ressources de la vue (icône de la finition 3D de FreeCAD, page sans réglages : l'éditeur CAM2027 les porte)."""
    import Path.Op.Gui.Base as PathOpGui

    class TaskPanelOpPage(PathOpGui.TaskPanelPage):
        def getForm(self):
            from ..gui.qt import QtWidgets

            return QtWidgets.QWidget()

        def getFields(self, obj):
            pass

        def setFields(self, obj):
            pass

        def getSignalsForUpdate(self, obj):
            return []

    TaskPanelOpPage.__module__ = __name__
    globals()["TaskPanelOpPage"] = TaskPanelOpPage
    return PathOpGui.CommandResources("Scallop", Create, TaskPanelOpPage, "CAM_3DSurface",
                                      "Constant scallop finishing", None, "Constant scallop 3D finishing")
