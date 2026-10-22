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

from ..i18n import Msg, UserError

DEFAULT_RESOLUTION = 0.5
MAX_CELLS = 2_000_000
_ARC_STEP_MM = 0.25
_SLOPE_STEP_MM = 0.5
_SLOPE_DZ_MM = 0.05
_GOLDEN_STEPS = 14  # section dorée des profils torique / conique sur pente : plage réduite à 0,1 %


#: profondeur à partir de laquelle un rapide (G0) compte comme entrant dans la matière (mm)
RAPID_TOLERANCE = 0.01


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
        return cls("flat", g.diameter), Msg("tool type {t} simulated as a flat end mill", t=t)

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
            raise UserError("material check: {nx} x {ny} cells, increase the resolution (max {m} cells)",
                            nx=nx, ny=ny, m=MAX_CELLS)
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

    def _window(self, xlo, xhi, ylo, yhi, grid=True):
        np = _np()
        i0 = max(0, int(math.floor((xlo - self.x0) / self.res)))
        i1 = min(self.nx, int(math.ceil((xhi - self.x0) / self.res)) + 1)
        j0 = max(0, int(math.floor((ylo - self.y0) / self.res)))
        j1 = min(self.ny, int(math.ceil((yhi - self.y0) / self.res)) + 1)
        if i0 >= i1 or j0 >= j1:
            return None
        return i0, i1, j0, j1, np.meshgrid(self.xs[i0:i1], self.ys[j0:j1], indexing="ij") if grid else None

    def sweep(self, p0, p1, tool, rapid=False):
        """Balaye le segment p0 -> p1 (pointe de la fraise) ; retourne True si de la matière est touchée."""
        np = _np()
        P0, P1 = split_segments(np.array([p0], dtype=float), np.array([p1], dtype=float), tool)
        return self._sweep_chunk(P0, P1, tool, rapid)

    def sweep_many(self, segments, tool):
        """Balaye des segments de coupe ``(p0, p1)`` : même résultat que ``sweep`` sur chacun dans l'ordre."""
        np = _np()
        self.sweep_arrays(np.array([q[0] for q in segments], dtype=float),
                          np.array([q[1] for q in segments], dtype=float), tool)

    def sweep_arrays(self, P0, P1, tool):
        """Balayage de ``n`` segments (tableaux ``(n, 3)``) : même résultat que ``sweep`` sur chacun dans
        l'ordre (le minimum ne dépend pas de l'ordre), bien plus vite sur les parcours de dizaines de
        milliers de commandes.

        Fraise plate : les segments horizontaux (et les verticaux, disque au point bas) sont regroupés par
        hauteur, quel que soit leur ordre, et chaque groupe est rempli par colonnes (``_sweep_flat_level``) ;
        les segments inclinés, et tout pour les autres profils, passent par fenêtres communes
        (``_sweep_chunk``)."""
        np = _np()
        P0, P1 = split_segments(P0, P1, tool)
        if tool.kind == "flat" and len(P0):
            P0, P1, rest0, rest1 = flat_groups_ready(P0, P1)
            for z in np.unique(P0[:, 2]):
                sel = P0[:, 2] == z
                self._sweep_flat_level(P0[sel], P1[sel], float(z), tool.radius)
            P0, P1 = rest0, rest1
        for start, stop in chunk_bounds(P0, P1, self.res, tool.radius):
            self._sweep_chunk(P0[start:stop], P1[start:stop], tool)

    def excess_any(self, P0, P1, radius, offset, threshold, flat):
        """Vrai si, sur l'état courant, de la matière dépasse ``pointe + offset`` de plus de ``threshold`` dans
        ``radius`` autour d'un des segments (queue, porte-outil). ``flat`` : fraise plate (les segments
        horizontaux sont regroupés par hauteur et remplis par colonnes, comme le balayage)."""
        np = _np()
        if flat and len(P0):
            P0, P1, rest0, rest1 = flat_groups_ready(P0, P1)
            for z in np.unique(P0[:, 2]):
                sel = P0[:, 2] == z
                cov = self._flat_cover(P0[sel], P1[sel], radius)
                if cov is None:
                    continue
                i0, i1, j0, j1, covered = cov
                if (self.top[i0:i1, j0:j1][covered] > float(z) + offset + threshold).any():
                    return True
            P0, P1 = rest0, rest1
        for start, stop in chunk_bounds(P0, P1, self.res, radius):
            if (material_excess_many(self, P0[start:stop], P1[start:stop], radius, offset) > threshold).any():
                return True
        return False

    def _sweep_flat_level(self, P0, P1, zlev, r):
        """Fraise plate, segments horizontaux à la hauteur ``zlev`` : les cellules couvertes descendent à
        ``zlev`` (voir ``_flat_cover``)."""
        np = _np()
        cov = self._flat_cover(P0, P1, r)
        if cov is None:
            return
        i0, i1, j0, j1, covered = cov
        block = self.top[i0:i1, j0:j1]
        np.minimum(block, np.where(covered, zlev, np.inf), out=block)

    def _flat_cover(self, P0, P1, r):
        """Cellules couvertes par des segments horizontaux élargis de ``r`` : dans chaque colonne de cellules,
        la capsule couvre un intervalle de Y, union de ses trois morceaux (disque de départ, disque d'arrivée,
        bande entre les perpendiculaires aux extrémités) ; les intervalles sont cumulés par colonne
        (``add.at`` puis somme cumulée) : une cellule est couverte si son centre est dans l'un d'eux,
        exactement comme ``d <= r`` dans ``_bottom``. Retourne ``(i0, i1, j0, j1, masque)`` ou None."""
        np = _np()
        win = self._window(min(P0[:, 0].min(), P1[:, 0].min()) - r, max(P0[:, 0].max(), P1[:, 0].max()) + r,
                           min(P0[:, 1].min(), P1[:, 1].min()) - r, max(P0[:, 1].max(), P1[:, 1].max()) + r,
                           grid=False)
        if win is None:
            return None
        i0, i1, j0, j1, _grid = win
        rr = r + 1e-9
        res = self.res
        xA, yA, xB, yB = P0[:, 0], P0[:, 1], P1[:, 0], P1[:, 1]
        cmin = np.clip(np.floor((np.minimum(xA, xB) - rr - self.x0) / res).astype(int), i0, i1 - 1)
        cmax = np.clip(np.ceil((np.maximum(xA, xB) + rr - self.x0) / res).astype(int), i0, i1 - 1)
        # paires (segment, colonne) à plat : un long segment ne fait plus calculer sa largeur à tous les autres
        seg, rank = _ragged(cmax - cmin + 1)
        cols = cmin[seg] + rank
        valid = True
        xc = self.xs[cols]
        xA, yA, xB, yB = xA[seg], yA[seg], xB[seg], yB[seg]
        inf = np.inf
        # disques aux extrémités
        hA = rr * rr - (xc - xA) ** 2
        hB = rr * rr - (xc - xB) ** 2
        sA = np.sqrt(np.maximum(hA, 0.0))
        sB = np.sqrt(np.maximum(hB, 0.0))
        loA = np.where(hA >= 0, yA - sA, inf)
        hiA = np.where(hA >= 0, yA + sA, -inf)
        loB = np.where(hB >= 0, yB - sB, inf)
        hiB = np.where(hB >= 0, yB + sB, -inf)
        # bande entre les perpendiculaires : 0 <= t <= 1 et |perp| <= r, deux contraintes linéaires en y
        dx, dy = xB - xA, yB - yA
        L2 = dx * dx + dy * dy
        L = np.sqrt(L2)
        u = xc - xA
        eps = 1e-12
        with np.errstate(divide="ignore", invalid="ignore"):
            t_a = yA + (0.0 - u * dx) / dy
            t_b = yA + (L2 - u * dx) / dy
            p_a = yA + (u * dy - rr * L) / dx
            p_b = yA + (u * dy + rr * L) / dx
        dy_ok = np.abs(dy) > eps
        dx_ok = np.abs(dx) > eps
        t_lo = np.where(dy_ok, np.minimum(t_a, t_b), np.where((u * dx >= 0) & (u * dx <= L2), -inf, inf))
        t_hi = np.where(dy_ok, np.maximum(t_a, t_b), np.where((u * dx >= 0) & (u * dx <= L2), inf, -inf))
        p_lo = np.where(dx_ok, np.minimum(p_a, p_b), np.where(np.abs(u * dy) <= rr * L, -inf, inf))
        p_hi = np.where(dx_ok, np.maximum(p_a, p_b), np.where(np.abs(u * dy) <= rr * L, inf, -inf))
        loS = np.maximum(t_lo, p_lo)
        hiS = np.minimum(t_hi, p_hi)
        degenerate = L2 < eps
        loS = np.where(degenerate | (loS > hiS), inf, loS)
        hiS = np.where(degenerate | (loS > hiS), -inf, hiS)
        lo = np.minimum(np.minimum(loA, loB), loS)
        hi = np.maximum(np.maximum(hiA, hiB), hiS)
        ok = valid & np.isfinite(lo) & np.isfinite(hi) & (lo <= hi)
        # cellules dont le centre y0 + (j + 0.5) res est dans [lo, hi]
        jlo = np.ceil((lo - self.y0) / res - 0.5)
        jhi = np.floor((hi - self.y0) / res - 0.5)
        jlo = np.clip(np.where(ok, jlo, 0), j0, j1).astype(int)
        jhi = np.clip(np.where(ok, jhi, -1), j0 - 1, j1 - 1).astype(int)
        ok &= jlo <= jhi
        if not ok.any():
            return None
        ci = (cols - i0)[ok]
        D = np.zeros((i1 - i0, j1 - j0 + 1), dtype=np.int32)
        np.add.at(D, (ci, jlo[ok] - j0), 1)
        np.add.at(D, (ci, jhi[ok] - j0 + 1), -1)
        return i0, i1, j0, j1, np.cumsum(D, axis=1)[:, :-1] > 0

    def _bottom(self, P0, P1, tool):
        """Fenêtre commune et hauteur du dessous de la fraise ``(n, w, h)`` pour chaque segment (inf hors de sa
        couverture).

        Sur une pente, la fraise plate est au plus bas à l'extrémité basse de la plage de paramètres où son
        disque couvre la colonne ; la boule, sphère balayée le long du segment 3D (capsule), au paramètre
        ``t* - dz/L * sqrt((r² - d⊥²) / (L² + dz²))`` borné à cette plage (fonction convexe). Les autres
        profils sont découpés avant (``split_segments``) et pris au point le plus proche."""
        np = _np()
        r = tool.radius
        win = self._window(min(P0[:, 0].min(), P1[:, 0].min()) - r, max(P0[:, 0].max(), P1[:, 0].max()) + r,
                           min(P0[:, 1].min(), P1[:, 1].min()) - r, max(P0[:, 1].max(), P1[:, 1].max()) + r,
                           grid=False)
        if win is None:
            return None
        i0, i1, j0, j1, _grid = win
        X = self.xs[i0:i1][None, :, None]
        Y = self.ys[j0:j1][None, None, :]
        x0, y0, z0 = (P0[:, k][:, None, None] for k in range(3))
        x1, y1, z1 = (P1[:, k][:, None, None] for k in range(3))
        dx, dy, dz = x1 - x0, y1 - y0, z1 - z0
        L2 = dx * dx + dy * dy
        vertical = L2 < 1e-18
        L2s = np.where(vertical, 1.0, L2)
        t_foot = ((X - x0) * dx + (Y - y0) * dy) / L2s  # paramètre du pied de la colonne sur la droite
        t = np.where(vertical, 0.0, np.clip(t_foot, 0.0, 1.0))
        d = np.hypot(X - (x0 + t * dx), Y - (y0 + t * dy))  # distance au segment (couverture)
        inside = d <= r + 1e-9
        if tool.kind == "flat" and not (dz != 0).any():  # fraise plate à plat : le dessous est au Z du segment
            z = z0 + np.zeros_like(d)
        elif tool.kind == "ball" and not (dz != 0).any():
            # boule à plat (Z constant) : le point le plus bas de la plage est le point le plus proche, même
            # résultat que la formule de la pente avec dz = 0, sans ses tableaux intermédiaires
            z = z0 + tool.lift(np.minimum(d, r))
        elif tool.kind in ("flat", "ball"):
            d_perp = np.hypot(X - (x0 + t_foot * dx), Y - (y0 + t_foot * dy))
            reach = np.sqrt(np.maximum(r * r - d_perp * d_perp, 0.0))
            half = reach / np.sqrt(L2s)  # demi-plage de couverture
            lo = np.maximum(t_foot - half, 0.0)
            hi = np.minimum(t_foot + half, 1.0)
            if tool.kind == "flat":
                t_low = np.where(dz < 0, hi, lo)  # extrémité basse de la plage
            else:
                t_low = np.clip(t_foot - dz / np.sqrt(L2s) * reach / np.sqrt(L2s + dz * dz), lo, hi)
            t_low = np.where(vertical, 0.0, t_low)
            d_low = np.where(vertical, d, np.hypot(X - (x0 + t_low * dx), Y - (y0 + t_low * dy)))
            z_tip = np.where(vertical, np.minimum(z0, z1), z0 + t_low * dz)
            z = z_tip + tool.lift(np.minimum(d_low, r))
        else:
            z_tip = np.where(vertical, np.minimum(z0, z1), z0 + t * dz)
            z = z_tip + tool.lift(np.minimum(d, r))
            if (dz != 0).any():
                z = np.minimum(z, self._slope_bottom(X, Y, x0, y0, z0, dx, dy, dz, L2s, vertical, t_foot, tool))
        return i0, i1, j0, j1, np.where(inside, z, np.inf), vertical[:, 0, 0]

    @staticmethod
    def _slope_bottom(X, Y, x0, y0, z0, dx, dy, dz, L2s, vertical, t_foot, tool):
        """Torique et conique sur une pente : plus bas dessous de la fraise sur la plage de paramètres où son
        disque couvre la colonne. ``z(t) + lift(distance(t))`` est convexe (profil croissant et convexe de la
        distance, elle-même convexe) : section dorée sur la plage, bornes comprises. Le point le plus proche
        laissait jusqu'au dénivelé d'un morceau (0,05 mm) de matière en trop."""
        np = _np()
        r = tool.radius
        d_perp = np.hypot(X - (x0 + t_foot * dx), Y - (y0 + t_foot * dy))
        half = np.sqrt(np.maximum(r * r - d_perp * d_perp, 0.0)) / np.sqrt(L2s)
        a = np.where(vertical, 0.0, np.maximum(t_foot - half, 0.0))
        b = np.where(vertical, 1.0, np.minimum(t_foot + half, 1.0))
        b = np.maximum(a, b)

        def f(tt):
            dd = np.hypot(X - (x0 + tt * dx), Y - (y0 + tt * dy))
            return z0 + tt * dz + tool.lift(np.minimum(dd, r))

        best = np.minimum(f(a), f(b))
        g = (math.sqrt(5.0) - 1.0) / 2.0
        c, e = b - g * (b - a), a + g * (b - a)
        fc, fe = f(c), f(e)
        for _k in range(_GOLDEN_STEPS):
            left = fc < fe  # minimum dans [a, e]
            b = np.where(left, e, b)
            a = np.where(left, a, c)
            new = np.where(left, b - g * (b - a), a + g * (b - a))
            fn = f(new)
            c, e, fc, fe = (np.where(left, new, e), np.where(left, c, new),
                            np.where(left, fn, fe), np.where(left, fc, fn))
        return np.minimum(best, np.minimum(fc, fe))

    def _sweep_chunk(self, P0, P1, tool, rapid=False):
        np = _np()
        res = self._bottom(P0, P1, tool)
        if res is None:
            return False
        i0, i1, j0, j1, z, vertical = res
        block = self.top[i0:i1, j0:j1]
        zmin = z.min(axis=0)
        touched = zmin < block - 1e-6
        if rapid and not (vertical.all() and (P1[:, 2] > P0[:, 2]).all()) and (zmin < block - RAPID_TOLERANCE).any():
            # rapide : dégagement vertical vers le haut jamais compté ; ailleurs au-delà de RAPID_TOLERANCE
            self.rapid_hits += 1
            if self.rapid_hit_at is None:
                self.rapid_hit_at = tuple(P1[-1])
        np.minimum(block, zmin, out=block)
        return bool(touched.any())

    def rapid_hits_many(self, P0, P1, tool):
        """Pour chaque rapide, True s'il entrerait dans la matière sur l'état courant (sans la modifier)."""
        np = _np()
        res = self._bottom(P0, P1, tool)
        if res is None:
            return np.zeros(len(P0), dtype=bool)
        i0, i1, j0, j1, z, vertical = res
        up = vertical & (P1[:, 2] > P0[:, 2])
        return (z < self.top[i0:i1, j0:j1][None, :, :] - RAPID_TOLERANCE).any(axis=(1, 2)) & ~up

    def removed_volume(self):
        return float((self.initial - self.top).sum() * self.res * self.res)


#: paquets vectorisés : segments × cellules de la fenêtre commune au plus (~100 Mo de tableaux temporaires)
CHUNK_CELLS = 1_500_000
CHUNK_SEGMENTS = 512
#: suites de segments plats au même Z traitées par colonnes : au moins / au plus tant de segments d'un coup
FLAT_RUN_MIN = 4
FLAT_RUN_MAX = 20000
#: la fenêtre commune ne doit pas dépasser ce multiple de la somme des fenêtres propres (sinon les segments
#: alignés d'une longue ligne font calculer, pour chacun, les cellules de toute la ligne)
CHUNK_WASTE = 3.0


def chunk_bounds(P0, P1, res, radius):
    """Bornes ``(début, fin)`` de paquets de segments consécutifs (tableaux ``(n, 3)``) dont la fenêtre commune
    (boîte des segments élargie de ``radius``) reste petite : ``n × largeur × hauteur <= CHUNK_CELLS`` et au
    plus ``CHUNK_WASTE`` fois la somme des fenêtres propres des segments."""
    out = []
    start = 0
    total = len(P0)
    xs0, ys0, xs1, ys1 = P0[:, 0].tolist(), P0[:, 1].tolist(), P1[:, 0].tolist(), P1[:, 1].tolist()
    pad = 2 * radius

    def own(k):
        return ((abs(xs1[k] - xs0[k]) + pad) / res + 2) * ((abs(ys1[k] - ys0[k]) + pad) / res + 2)

    while start < total:
        xlo, xhi = min(xs0[start], xs1[start]), max(xs0[start], xs1[start])
        ylo, yhi = min(ys0[start], ys1[start]), max(ys0[start], ys1[start])
        n = 1
        own_sum = own(start)
        while start + n < total and n < CHUNK_SEGMENTS:
            k = start + n
            nxlo, nxhi = min(xlo, xs0[k], xs1[k]), max(xhi, xs0[k], xs1[k])
            nylo, nyhi = min(ylo, ys0[k], ys1[k]), max(yhi, ys0[k], ys1[k])
            cells = ((nxhi - nxlo + pad) / res + 2) * ((nyhi - nylo + pad) / res + 2)
            total_cells = (n + 1) * cells
            if total_cells > CHUNK_CELLS or total_cells > CHUNK_WASTE * (own_sum + own(k)):
                break
            xlo, xhi, ylo, yhi = nxlo, nxhi, nylo, nyhi
            own_sum += own(k)
            n += 1
        out.append((start, start + n))
        start += n
    return out


def flat_groups_ready(P0, P1):
    """Sépare les segments d'une fraise plate : ``(H0, H1, R0, R1)`` avec les horizontaux (et les verticaux,
    ramenés à un point à leur Z le plus bas : même disque, même hauteur que dans ``_bottom``) prêts pour le
    remplissage par colonnes, et le reste (pentes) pour les fenêtres communes."""
    np = _np()
    horizontal = P0[:, 2] == P1[:, 2]
    vertical = (P0[:, 0] == P1[:, 0]) & (P0[:, 1] == P1[:, 1]) & ~horizontal
    H0 = P0[horizontal | vertical].copy()
    H1 = P1[horizontal | vertical].copy()
    v = vertical[horizontal | vertical]
    if v.any():
        zmin = np.minimum(H0[v, 2], H1[v, 2])
        H0[v, 2] = zmin
        H1[v] = H0[v]
    rest = ~(horizontal | vertical)
    return H0, H1, P0[rest], P1[rest]


def split_segments(P0, P1, tool):
    """Profils sans formule exacte sur une pente (torique, conique) : découpe des segments inclinés en morceaux
    courts et peu inclinés ; fraise plate et boule : inchangés."""
    np = _np()
    if tool.kind in ("flat", "ball") or not len(P0):
        return P0, P1
    length = np.hypot(P1[:, 0] - P0[:, 0], P1[:, 1] - P0[:, 1])
    dz = np.abs(P1[:, 2] - P0[:, 2])
    needs = (length > 1e-9) & ((length > _SLOPE_STEP_MM) & (dz > 1e-9) | (dz > _SLOPE_DZ_MM))
    if not needs.any():
        return P0, P1
    outs0, outs1 = [], []
    for k in range(len(P0)):
        if not needs[k]:
            outs0.append(P0[k])
            outs1.append(P1[k])
            continue
        n = int(math.ceil(max(length[k] / _SLOPE_STEP_MM, dz[k] / _SLOPE_DZ_MM)))
        steps = np.arange(n + 1)[:, None] / n
        pts = P0[k][None, :] + (P1[k] - P0[k])[None, :] * steps
        outs0.extend(pts[:-1])
        outs1.extend(pts[1:])
    return np.array(outs0, dtype=float), np.array(outs1, dtype=float)


def material_excess(zmap, p0, p1, radius, offset):
    """Plus grand dépassement de matière au-dessus de ``pointe + offset`` dans ``radius`` le long du segment.

    La pointe est prise au plus bas de la plage où le disque de rayon ``radius`` couvre la colonne (dessous d'un
    cylindre balayé, ``_bottom`` d'une fraise plate) : au point le plus proche, une queue ou un porte-outil le
    long d'une rampe touchait la matière plus bas sur la rampe sans que le contrôle le voie.

    Retourne ``(dépassement, (x, y, z_pointe))`` ; dépassement <= 0 : pas de contact."""
    np = _np()
    P0, P1 = np.array([p0], dtype=float), np.array([p1], dtype=float)
    res = zmap._bottom(P0, P1, ToolProfile("flat", 2.0 * radius))
    if res is None:
        return 0.0, None
    i0, i1, j0, j1, z_low, _vertical = res
    excess = np.where(np.isfinite(z_low[0]), zmap.top[i0:i1, j0:j1] - (z_low[0] + offset), -np.inf)
    k = int(np.argmax(excess))
    worst = float(excess.flat[k])
    if not np.isfinite(worst) or worst <= 0:
        return worst if np.isfinite(worst) else 0.0, None
    i, j = np.unravel_index(k, excess.shape)
    x, y = float(zmap.xs[i0 + i]), float(zmap.ys[j0 + j])
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    L2 = dx * dx + dy * dy
    tk = 0.0 if L2 < 1e-18 else min(max(((x - p0[0]) * dx + (y - p0[1]) * dy) / L2, 0.0), 1.0)
    return worst, (p0[0] + tk * dx, p0[1] + tk * dy, float(z_low[0][i, j]))


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


def material_excess_many(zmap, P0, P1, radius, offset):
    """``material_excess`` vectorisé : plus grand dépassement par segment (tableau ``(n,)``), sur l'état courant
    de la carte. Les positions ne sont pas retournées : sert de pré-contrôle d'un paquet (aucun dépassement =
    aucun événement, car la matière ne fait que baisser)."""
    np = _np()
    res = zmap._bottom(P0, P1, ToolProfile("flat", 2.0 * radius))
    if res is None:
        return np.zeros(len(P0))
    i0, i1, j0, j1, z_low, _vertical = res
    excess = np.where(np.isfinite(z_low), zmap.top[i0:i1, j0:j1][None, :, :] - (z_low + offset), -np.inf)
    worst = excess.max(axis=(1, 2))
    return np.where(np.isfinite(worst), worst, 0.0)


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


#: tolérance latérale du contrôle d'entaille au droit des parois verticales (mm)
WALL_TOLERANCE = 0.05
#: flèche de la triangulation de la pièce (mm) : les facettes passent jusqu'à cette distance au-dessus d'une
#: surface concave (fausses entailles) ou au-dessous d'une convexe (entailles manquées) ; à 0,05 mm, 0,045 mm
#: d'écart sur un bol, plus que la tolérance d'entaille (0,02 mm)
MODEL_DEFLECTION = 0.01


#: triangles rastérisés d'un coup (tableaux de quelques Mo)
_RASTER_TRIANGLES = 20000


def _ragged(counts):
    """``(propriétaire, rang)`` de chaque élément d'une liste à plat de ``counts[k]`` éléments par propriétaire."""
    np = _np()
    owner = np.repeat(np.arange(len(counts)), counts)
    start = np.cumsum(counts) - counts
    return owner, np.arange(int(counts.sum())) - start[owner]


def _raster_max(zmap, a, b, c, det, ox, oy, flat):
    """Hauteur des triangles ``(a, b, c)`` (non verticaux, ``det`` : double aire signée en XY) aux centres des
    colonnes décalés de ``(ox, oy)``, gardée au maximum dans ``flat`` (``zmap.top`` à plat).

    Pour chaque colonne de cellules de la fenêtre d'un triangle, les coordonnées barycentriques sont linéaires
    en Y : l'intervalle de Y où elles sont toutes >= -1e-9 donne les cellules à évaluer (une de marge de chaque
    côté), puis le test et la hauteur (linéaire en Y aussi) cellule par cellule. Travail proportionnel à la
    surface des triangles et non à leur boîte (les triangles longs des faces planes coûtaient des milliers de
    cellules chacun)."""
    np = _np()
    eps = -1e-9
    xmin = np.minimum(np.minimum(a[:, 0], b[:, 0]), c[:, 0])
    xmax = np.maximum(np.maximum(a[:, 0], b[:, 0]), c[:, 0])
    ymin = np.minimum(np.minimum(a[:, 1], b[:, 1]), c[:, 1])
    ymax = np.maximum(np.maximum(a[:, 1], b[:, 1]), c[:, 1])
    # colonne (i, j) décalée de (ox, oy) : même fenêtre que ``_window`` sur le triangle décalé de -o
    i0 = np.clip(np.floor((xmin - ox - zmap.x0) / zmap.res).astype(int), 0, zmap.nx)
    i1 = np.clip(np.ceil((xmax - ox - zmap.x0) / zmap.res).astype(int) + 1, 0, zmap.nx)
    j0 = np.clip(np.floor((ymin - oy - zmap.y0) / zmap.res).astype(int), 0, zmap.ny)
    j1 = np.clip(np.ceil((ymax - oy - zmap.y0) / zmap.res).astype(int) + 1, 0, zmap.ny)
    t, r = _ragged(np.where(j1 > j0, np.maximum(i1 - i0, 0), 0))  # (triangle, colonne)
    col = i0[t] + r
    X = zmap.xs[col] + ox
    at, bt, ct, dt = a[t], b[t], c[t], det[t]
    # l1 = A1 Y + B1, l2 = A2 Y + B2, l3 = 1 - l1 - l2
    A1 = (ct[:, 0] - bt[:, 0]) / dt
    B1 = ((bt[:, 1] - ct[:, 1]) * (X - ct[:, 0]) - (ct[:, 0] - bt[:, 0]) * ct[:, 1]) / dt
    A2 = (at[:, 0] - ct[:, 0]) / dt
    B2 = ((ct[:, 1] - at[:, 1]) * (X - ct[:, 0]) - (at[:, 0] - ct[:, 0]) * ct[:, 1]) / dt
    lo = np.full(len(t), -np.inf)
    hi = np.full(len(t), np.inf)
    with np.errstate(divide="ignore", invalid="ignore"):
        for A, B in ((A1, B1), (A2, B2), (-A1 - A2, 1.0 - B1 - B2)):
            y = (eps - B) / A
            lo = np.where(A > 0, np.maximum(lo, y), lo)
            hi = np.where(A < 0, np.minimum(hi, y), hi)
            lo = np.where((A == 0) & (B < eps), np.inf, lo)
    jl = np.maximum(np.floor(np.clip((lo - oy - zmap.y0) / zmap.res - 0.5, -1, zmap.ny + 1)).astype(int), j0[t])
    jh = np.minimum(np.ceil(np.clip((hi - oy - zmap.y0) / zmap.res - 0.5, -2, zmap.ny + 1)).astype(int), j1[t] - 1)
    A3, B3 = -A1 - A2, 1.0 - B1 - B2
    Az = A1 * at[:, 2] + A2 * bt[:, 2] + A3 * ct[:, 2]  # hauteur sur la colonne : Az Y + Bz
    Bz = B1 * at[:, 2] + B2 * bt[:, 2] + B3 * ct[:, 2]
    p, q = _ragged(np.maximum(jh - jl + 1, 0))  # (triangle-colonne, cellule)
    jj = jl[p] + q
    Yc = zmap.ys[jj] + oy
    inside = (A1[p] * Yc + B1[p] >= eps) & (A2[p] * Yc + B2[p] >= eps) & (A3[p] * Yc + B3[p] >= eps)
    if not inside.any():
        return
    p, Yc = p[inside], Yc[inside]
    z = Az[p] * Yc + Bz[p]
    np.maximum.at(flat, col[p] * zmap.ny + jj[inside], z)


def model_heights(zmap, shapes, deflection=MODEL_DEFLECTION, lateral=0.0):
    """Hauteur du dessus des pièces au centre de chaque colonne (-inf hors pièce).

    ``lateral`` > 0 : retourne ``(hauteurs au centre, hauteurs basses)``, les basses étant la plus basse des
    hauteurs au centre et à ``lateral`` mm de lui (4 directions ; -inf si l'un de ces points est hors pièce). Sert au contrôle d'entaille : une colonne
    dont le centre tombe pile sur une paroi verticale (grille alignée sur les cotes de la pièce) prendrait
    le haut de la paroi alors que la fraise passe tangente à côté.

    Triangles rastérisés par colonnes (``_raster_max``)."""
    np = _np()
    offsets = [(0.0, 0.0)]
    if lateral > 0:
        offsets += [(lateral, 0.0), (-lateral, 0.0), (0.0, lateral), (0.0, -lateral)]
    hs = [np.full((zmap.nx, zmap.ny), -np.inf) for _o in offsets]
    for shape in shapes:
        # copie sans triangulation : OCC garde la triangulation la plus fine demandée (une finition 3D à
        # 0,0025 mm en laisse une dix fois plus dense, 8 s de rastérisation au lieu de 1,5)
        try:
            fresh = shape.copy(True, False)
        except TypeError:
            fresh = shape
        points, triangles = fresh.tessellate(deflection)
        if not triangles:
            continue
        pts = np.array([[v.x, v.y, v.z] for v in points])
        tri = np.asarray(triangles, dtype=int)
        a, b, c = pts[tri[:, 0]], pts[tri[:, 1]], pts[tri[:, 2]]
        det = (b[:, 1] - c[:, 1]) * (a[:, 0] - c[:, 0]) + (c[:, 0] - b[:, 0]) * (a[:, 1] - c[:, 1])
        keep = np.abs(det) >= 1e-12  # faces verticales vues de dessus
        a, b, c, det = a[keep], b[keep], c[keep], det[keep]
        if not len(det):
            continue
        for (ox, oy), h in zip(offsets, hs):
            for s0 in range(0, len(det), _RASTER_TRIANGLES):
                k = slice(s0, s0 + _RASTER_TRIANGLES)
                _raster_max(zmap, a[k], b[k], c[k], det[k], ox, oy, h.reshape(-1))
    if len(hs) == 1:
        return hs[0]
    low = hs[0].copy()
    for h in hs[1:]:
        # hors pièce à ``lateral`` mm (-inf) : colonne sur le bord de la silhouette, pas contrôlée non plus
        # (une colonne pile sur le bord d'un surplomb comptait toute sa hauteur comme entaillée)
        low = np.minimum(low, h)
    return hs[0], low


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


#: entailles vérifiées en 3D (distance exacte à la pièce) : les plus profondes d'abord, au plus tant de colonnes
REFINE_MAX_CELLS = 4000
#: portée de la recherche de la surface autour d'une colonne entaillée (mm) ; au-delà, l'entaille verticale
#: est gardée
REFINE_REACH = 10.0
_BUCKET_MM = 2.0


def _triangles(shapes, deflection):
    """Triangles ``(A, B, C)`` (tableaux ``(n, 3)``) des formes, triangulées sur une copie."""
    np = _np()
    As, Bs, Cs = [], [], []
    for shape in shapes:
        try:
            fresh = shape.copy(True, False)
        except TypeError:
            fresh = shape
        points, triangles = fresh.tessellate(deflection)
        if not triangles:
            continue
        pts = np.array([[v.x, v.y, v.z] for v in points])
        tri = np.asarray(triangles, dtype=int)
        As.append(pts[tri[:, 0]]); Bs.append(pts[tri[:, 1]]); Cs.append(pts[tri[:, 2]])
    if not As:
        z = np.zeros((0, 3))
        return z, z, z
    return np.concatenate(As), np.concatenate(Bs), np.concatenate(Cs)


def _point_triangle_distance(p, A, B, C):
    """Distance du point ``p`` à chaque triangle (vectorisé) : projection sur le plan si elle tombe dans le
    triangle, sinon distance aux trois arêtes."""
    np = _np()

    def seg(P0, P1):
        d = P1 - P0
        L2 = (d * d).sum(1)
        t = np.clip(((p - P0) * d).sum(1) / np.where(L2 > 0, L2, 1.0), 0.0, 1.0)
        return np.linalg.norm(p - (P0 + d * t[:, None]), axis=1)

    ab, ac = B - A, C - A
    n = np.cross(ab, ac)
    nn = np.linalg.norm(n, axis=1)
    ok = nn > 1e-15
    nu = n / np.where(ok, nn, 1.0)[:, None]
    dist_plane = ((p - A) * nu).sum(1)
    q = p - nu * dist_plane[:, None]
    # q dans le triangle : mêmes signes des trois produits mixtes
    c1 = (np.cross(B - A, q - A) * n).sum(1)
    c2 = (np.cross(C - B, q - B) * n).sum(1)
    c3 = (np.cross(A - C, q - C) * n).sum(1)
    inside = ok & (c1 >= 0) & (c2 >= 0) & (c3 >= 0)
    face = np.where(inside, np.abs(dist_plane), np.inf)
    return np.minimum.reduce([face, seg(A, B), seg(B, C), seg(C, A)])


def refine_gouges(zmap, shapes, gouge_heights, tolerance=0.02, deflection=MODEL_DEFLECTION):
    """Vérifie en 3D les colonnes que la carte de hauteur dit entaillées et remplace leur entaille verticale
    par la vraie pénétration : distance du point coupé ``(x, y, matière restante)`` à la surface de la pièce ;
    si ce point est hors de la pièce (dessous d'un surplomb), la fraise verticale traverse le surplomb : distance
    du milieu de la première traversée de la pièce au-dessus du point.

    Près d'une paroi raide, une fraise qui entre de 0,05 mm sur le côté abaisse la colonne de toute la hauteur
    de la paroi (1,85 mm signalés sur le casse-noix de l'utilisateur pour 0,05 mm réels). Retourne les
    hauteurs d'entaille corrigées (copie)."""
    np = _np()
    gh = np.array(gouge_heights, dtype=float, copy=True)
    vertical = np.where(np.isfinite(gh), gh - zmap.top, -np.inf)
    cand = np.argwhere(vertical > tolerance)
    if not len(cand):
        return gh
    order = np.argsort(-vertical[cand[:, 0], cand[:, 1]])[:REFINE_MAX_CELLS]
    cand = cand[order]
    A, B, C = _triangles(shapes, deflection)
    if not len(A):
        return gh
    lo = np.minimum(np.minimum(A, B), C)
    hi = np.maximum(np.maximum(A, B), C)
    # casiers de 2 mm sur XY : triangle -> casiers couverts par sa boîte
    bx0 = np.floor((lo[:, 0] - zmap.x0) / _BUCKET_MM).astype(int)
    bx1 = np.floor((hi[:, 0] - zmap.x0) / _BUCKET_MM).astype(int)
    by0 = np.floor((lo[:, 1] - zmap.y0) / _BUCKET_MM).astype(int)
    by1 = np.floor((hi[:, 1] - zmap.y0) / _BUCKET_MM).astype(int)
    buckets = {}
    for k in range(len(A)):
        for bx in range(bx0[k], bx1[k] + 1):
            for by in range(by0[k], by1[k] + 1):
                buckets.setdefault((bx, by), []).append(k)

    def near(x, y, reach):
        out = set()
        for bx in range(int(math.floor((x - reach - zmap.x0) / _BUCKET_MM)), int(math.floor((x + reach - zmap.x0) / _BUCKET_MM)) + 1):
            for by in range(int(math.floor((y - reach - zmap.y0) / _BUCKET_MM)), int(math.floor((y + reach - zmap.y0) / _BUCKET_MM)) + 1):
                out.update(buckets.get((bx, by), ()))
        return np.fromiter(out, dtype=int) if out else np.zeros(0, dtype=int)

    for i, j in cand:
        x, y, z = float(zmap.xs[i]), float(zmap.ys[j]), float(zmap.top[i, j])
        v = float(vertical[i, j])
        reach = min(v, REFINE_REACH) + 0.05
        idx = near(x, y, reach)
        if not len(idx):
            continue
        a, b, c = A[idx], B[idx], C[idx]
        # dedans / dehors : parité des traversées de la verticale au-dessus du point (légèrement décalée pour
        # ne pas tomber sur une arête)
        px, py = x + 1.3e-5, y + 0.7e-5
        det = (b[:, 1] - c[:, 1]) * (a[:, 0] - c[:, 0]) + (c[:, 0] - b[:, 0]) * (a[:, 1] - c[:, 1])
        okd = np.abs(det) > 1e-15
        dets = np.where(okd, det, 1.0)
        l1 = ((b[:, 1] - c[:, 1]) * (px - c[:, 0]) + (c[:, 0] - b[:, 0]) * (py - c[:, 1])) / dets
        l2 = ((c[:, 1] - a[:, 1]) * (px - c[:, 0]) + (a[:, 0] - c[:, 0]) * (py - c[:, 1])) / dets
        l3 = 1.0 - l1 - l2
        crosses = okd & (l1 >= 0) & (l2 >= 0) & (l3 >= 0)
        zc = l1 * a[:, 2] + l2 * b[:, 2] + l3 * c[:, 2]
        over = np.sort(zc[crosses & (zc > z)])
        probe = z
        if len(over) % 2 == 0:
            # point coupé hors de la pièce, pièce au-dessus (surplomb) : le corps de la fraise, vertical au-dessus
            # de sa pointe, traverse la pièce. Pénétration prise au milieu de la première traversée.
            if not len(over):
                gh[i, j] = z
                continue
            probe = 0.5 * (over[0] + (over[1] if len(over) > 1 else over[0]))
        d = float(_point_triangle_distance(np.array([x, y, probe]), a, b, c).min())
        if d < reach:
            gh[i, j] = z + min(d, v)
    return gh


def gouge_mask(zmap, heights, tolerance=0.02):
    np = _np()
    return np.isfinite(heights) & (zmap.top < heights - tolerance)


def compare(zmap, heights, tolerance=0.02, gouge_heights=None):
    """Entailles et reste sur les colonnes de pièce : dict de mesures (mm, mm³).

    ``gouge_heights`` : hauteurs pour l'entaille seulement (tolérance latérale aux parois, voir
    ``model_heights``) ; le reste se mesure toujours au centre des colonnes."""
    np = _np()
    on_part = np.isfinite(heights)
    report = {"part_cells": int(on_part.sum()), "gouge_max": 0.0, "gouge_cells": 0, "gouge_at": None,
              "leftover_max": 0.0, "leftover_mean": 0.0, "leftover_at": None}
    if not on_part.any():
        return report
    diff = np.where(on_part, zmap.top - heights, np.nan)  # > 0 : reste ; < 0 : entaille
    gh = heights if gouge_heights is None else gouge_heights
    gouge = np.where(on_part, gh - zmap.top, -np.inf)
    gmax = float(np.max(gouge))
    if gmax > tolerance:
        i, j = np.unravel_index(int(np.argmax(gouge)), gouge.shape)
        report.update(gouge_max=gmax, gouge_cells=int((gouge > tolerance).sum()),
                      gouge_at=(float(zmap.xs[i]), float(zmap.ys[j]), float(gh[i, j])))
    left = np.where(on_part, diff, -np.inf)
    lmax = float(np.max(left))
    i, j = np.unravel_index(int(np.argmax(left)), left.shape)
    report.update(leftover_max=max(0.0, lmax), leftover_mean=float(np.nanmean(np.maximum(diff, 0.0))),
                  leftover_at=(float(zmap.xs[i]), float(zmap.ys[j]), float(heights[i, j])))
    return report


# -- brut restant (reprise de matière, finitions) ------------------------------------------------------------


def simulate_paths(zmap, items, start=None):
    """Enlève de ``zmap`` la matière de parcours ``[(commandes Path, ToolProfile)]`` dans l'ordre, sans contrôle
    (ni entaille ni collision) ; rapides compris. Retourne la dernière position connue."""
    np = _np()
    pos = start
    for commands, profile in items:
        segments, pos = path_segments(commands, pos)
        if not segments:
            continue
        P0 = np.array([s[1] for s in segments], dtype=float)
        P1 = np.array([s[2] for s in segments], dtype=float)
        zmap.sweep_arrays(P0, P1, profile)
    return pos


def disc_max(grid, radius_cells):
    """Maximum de ``grid`` sur un disque de ``radius_cells`` cellules autour de chaque cellule (-inf au-delà)."""
    np = _np()
    rc = int(math.floor(radius_cells))
    nx, ny = grid.shape
    out = grid.copy()
    pad = np.full((nx + 2 * rc, ny + 2 * rc), -np.inf)
    pad[rc:rc + nx, rc:rc + ny] = grid
    for di in range(-rc, rc + 1):
        for dj in range(-rc, rc + 1):
            if (di or dj) and di * di + dj * dj <= radius_cells * radius_cells:
                np.maximum(out, pad[rc + di:rc + di + nx, rc + dj:rc + dj + ny], out=out)
    return out
