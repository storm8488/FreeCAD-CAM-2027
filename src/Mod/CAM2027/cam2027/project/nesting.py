# SPDX-License-Identifier: LGPL-2.1-or-later
"""Imbrication de pièces 2D sur un panneau : par forme réelle (``shape_pack``, plus bas) ou par rectangles englobants.

Par rectangles (``skyline_pack``) : chaque dessin est représenté par son rectangle englobant, agrandi de
l'espacement demandé. Les rectangles sont placés du plus grand au plus petit, là où leur dessus reste le plus bas puis le plus
à gauche (ligne d'horizon), avec rotation de 90° si elle est permise et meilleure (les pièces ne
s'emboîtent pas dans les creux les unes des autres). Dans les deux cas, une pièce qui ne tient pas est rapportée, jamais posée hors du panneau.
"""

import FreeCAD


def skyline_pack(items, width, height, spacing=0.0, rotate=True):
    """Place ``items`` = ``[(clé, l, h)]`` dans ``width × height`` (origine 0, 0).

    Retourne ``(placements, non_placés)`` ; ``placements[clé] = (x, y, tourné)`` coin bas-gauche de la
    pièce (sans l'espacement). Deux pièces restent à ``spacing`` l'une de l'autre au moins.
    """
    # l'espacement est ajouté à droite et en haut de chaque pièce ; la zone utile en reçoit autant
    W, H = width + spacing, height + spacing
    skyline = [[0.0, W, 0.0]]  # segments [x, largeur, hauteur]
    order = sorted(items, key=lambda it: (max(it[1], it[2]), it[1] * it[2]), reverse=True)
    placed, unplaced = {}, []
    for key, w, h in order:
        best = None
        for rot in ((False, True) if rotate and abs(w - h) > 1e-9 else (False,)):
            pw, ph = ((h, w) if rot else (w, h))
            pw, ph = pw + spacing, ph + spacing
            xs = sorted({s[0] for s in skyline} | {s[0] + s[1] - pw for s in skyline if s[0] + s[1] - pw >= -1e-9})
            for x in xs:  # calé sur le début ou sur la fin de chaque segment de la ligne d'horizon
                x = max(0.0, x)
                if x + pw > W + 1e-9:
                    continue
                y = max(s[2] for s in skyline if s[0] < x + pw - 1e-9 and s[0] + s[1] > x + 1e-9)
                if y + ph > H + 1e-9:
                    continue
                cand = (y + ph, x, y, rot, pw, ph)  # dessus de la pièce le plus bas, puis le plus à gauche
                if best is None or cand[:2] < best[:2]:
                    best = cand
        if best is None:
            unplaced.append(key)
            continue
        _top, x, y, rot, pw, ph = best
        placed[key] = (x, y, rot)
        _raise_skyline(skyline, x, pw, y + ph)
    return placed, unplaced


def _raise_skyline(skyline, x, w, top):
    new = []
    for sx, sw, sh in skyline:
        ex = sx + sw
        if ex <= x + 1e-9 or sx >= x + w - 1e-9:
            new.append([sx, sw, sh])
            continue
        if sx < x:
            new.append([sx, x - sx, sh])
        if ex > x + w:
            new.append([x + w, ex - (x + w), sh])
    new.append([x, w, top])
    new.sort(key=lambda s: s[0])
    merged = []
    for s in new:
        if merged and abs(merged[-1][2] - s[2]) < 1e-9 and abs(merged[-1][0] + merged[-1][1] - s[0]) < 1e-9:
            merged[-1][1] += s[1]
        else:
            merged.append(s)
    skyline[:] = merged


def move_to(obj, x, y, rotated):
    """Tourne l'objet de 90° autour de Z si demandé puis pose le coin bas-gauche de son englobant en (x, y)."""
    if rotated:
        obj.Placement = FreeCAD.Placement(FreeCAD.Vector(), FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), 90)) \
            .multiply(obj.Placement)
    bb = obj.Shape.BoundBox
    obj.Placement = FreeCAD.Placement(FreeCAD.Vector(x - bb.XMin, y - bb.YMin, 0), FreeCAD.Rotation()) \
        .multiply(obj.Placement)


def outline_area(obj):
    """Surface des contours fermés du dessin (pour le taux d'utilisation)."""
    from . import sheet as sheetmod
    import Part

    wires = sheetmod.closed_wires(obj)
    if not wires:
        return 0.0
    try:
        return Part.makeFace(wires, "Part::FaceMakerBullseye").Area
    except Exception:
        return 0.0


# -- imbrication par forme réelle ----------------------------------------------------------------------------
#
# Chaque pièce est représentée par sa silhouette (contours extérieurs, trous bouchés) décalée de la moitié de
# l'espacement (``Part.makeOffset2D``), tournée de 0 à 360° par pas de ``angle_step``. Le panneau et les pièces
# sont rastérisés sur une grille de ``res`` mm de façon **prudente** : une cellule est occupée si son centre est
# dans la silhouette décalée de plus ``res·√2/2`` + la flèche de discrétisation, donc toute cellule touchée par
# la silhouette décalée l'est. Deux pièces dont les cellules ne se recouvrent pas sont à ``espacement`` au moins
# l'une de l'autre, et une pièce dont les cellules sont dans la grille (zone utile agrandie de la demi-espace) est
# dans la zone utile. Les positions
# libres de chaque rotation sont trouvées d'un coup par corrélation (FFT numpy) ; la pièce va là où son dessus est
# le plus bas, puis le plus à gauche (comme la ligne d'horizon). Une pièce qui ne tient sur aucun panneau ouvert
# en ouvre un autre (jusqu'à ``max_sheets``), sinon elle est rapportée.

#: flèche de discrétisation des contours (mm)
DEFLECTION = 0.05
#: cellules de la grille d'un panneau (finesse / temps : chaque bord de pièce perd au plus ``res·√2/2`` mm)
CELLS = 250000
#: écart entre deux panneaux posés côte à côte dans le document (mm)
SHEET_GAP = 50.0


def silhouette(shape):
    """Face des contours extérieurs d'un dessin (trous bouchés : une pièce ne se pose pas dans un trou)."""
    import Part

    wires = [w for w in shape.Wires if w.isClosed()]
    if not wires and shape.Edges:
        wires = [Part.Wire(e) for e in Part.sortEdges(shape.Edges)]
        wires = [w for w in wires if w.isClosed()]
    if not wires:
        raise ValueError("no closed outline")
    faces = [f for f in (Part.Face(w) for w in wires) if f.Area > 1e-9]
    faces.sort(key=lambda f: -f.Area)
    outer = []
    for f in faces:  # un contour contenu dans un plus grand est un trou ou un îlot : déjà couvert
        if not any(o.common(f).Area > f.Area * (1 - 1e-6) for o in outer):
            outer.append(f)
    face = outer[0]
    for f in outer[1:]:
        face = face.fuse(f)
    return face


def _points_in_polygons(px, py, polygons):
    """Pair-impair sur plusieurs polygones (tableaux (n, 2)) : masque booléen des points (px, py)."""
    import numpy as np

    inside = np.zeros(px.shape, dtype=bool)
    for poly in polygons:
        x0, y0 = poly[:, 0], poly[:, 1]
        x1, y1 = np.roll(x0, -1), np.roll(y0, -1)
        for a, b, c, d in zip(x0, y0, x1, y1):
            if b == d:
                continue
            cond = (b > py) != (d > py)
            xint = a + (py - b) * (c - a) / (d - b)
            inside ^= cond & (px < xint)
    return inside


def raster_mask(face, angle, res, grow):
    """Masque prudent de ``face`` tournée de ``angle`` degrés autour de l'origine et décalée de ``grow`` mm.

    Retourne ``(masque[nx, ny], x0, y0)`` : la cellule (i, j) couvre ``[x0 + i·res, x0 + (i+1)·res]`` en X (idem Y)."""
    import math
    import numpy as np

    f = face.copy()
    if angle:
        f.rotate(FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(0, 0, 1), float(angle))
    margin = grow + res * math.sqrt(2.0) / 2.0 + DEFLECTION
    big = f.makeOffset2D(margin, 0, False, False, False)
    polys = []
    for w in big.Wires:
        pts = w.discretize(Deflection=DEFLECTION)
        polys.append(np.array([[p.x, p.y] for p in pts]))
    bb = big.BoundBox
    x0 = math.floor(bb.XMin / res) * res
    y0 = math.floor(bb.YMin / res) * res
    nx = max(1, int(math.ceil((bb.XMax - x0) / res)))
    ny = max(1, int(math.ceil((bb.YMax - y0) / res)))
    xs = x0 + (np.arange(nx) + 0.5) * res
    ys = y0 + (np.arange(ny) + 0.5) * res
    X, Y = np.meshgrid(xs, ys, indexing="ij")
    return _points_in_polygons(X, Y, polys), x0, y0


def _fast_len(n):
    """Plus petite taille >= n dont les facteurs premiers sont 2, 3 et 5 (FFT rapide)."""
    while True:
        m = n
        for p in (2, 3, 5):
            while m % p == 0:
                m //= p
        if m == 1:
            return n
        n += 1


_WORKERS = {}


def _fft_module():
    """``scipy.fft`` sur tous les cœurs (grand panneau : une transformée inverse par rotation et par pièce), sinon
    ``numpy.fft``."""
    try:
        import scipy.fft as fft

        _WORKERS["workers"] = -1
        return fft
    except ImportError:
        import numpy as np

        _WORKERS.clear()
        return np.fft


class _Sheet(object):
    def __init__(self, nx, ny, fft_shape):
        import numpy as np

        self.occ = np.zeros((nx, ny), dtype=float)
        self.fft_shape = fft_shape
        self._fft = None

    def free_positions(self, mask, mask_fft):
        """Positions (i, j) où ``mask`` ne recouvre aucune cellule occupée et reste dans la grille (ou None)."""
        import numpy as np

        nx, ny = self.occ.shape
        mx, my = mask.shape
        if mx > nx or my > ny:
            return None
        fft = _fft_module()
        if self._fft is None:  # une transformée du panneau par pièce posée, pour toutes les rotations
            self._fft = fft.rfft2(self.occ, s=self.fft_shape, **_WORKERS)
        corr = fft.irfft2(self._fft * mask_fft, s=self.fft_shape, **_WORKERS)
        # convolution avec le masque retourné : le recouvrement en (i, j) se lit en (i + mx - 1, j + my - 1)
        return corr[mx - 1:nx, my - 1:ny] < 0.5

    def place(self, mask, i, j):
        mx, my = mask.shape
        self.occ[i:i + mx, j:j + my] += mask
        self._fft = None


def shape_pack(items, width, height, spacing=0.0, angle_step=15.0, max_sheets=1, res=None):
    """Imbrication par forme réelle de ``items`` = ``[(clé, face)]`` dans des panneaux ``width × height``.

    Retourne ``(placements, non_placées, res)`` ; ``placements[clé] = (panneau, angle, dx, dy)`` : la face tournée de
    ``angle`` autour de l'origine puis translatée de (dx, dy) est dans le panneau (origine 0, 0)."""
    import math
    import numpy as np

    if res is None:  # environ ``CELLS`` cellules par panneau, entre 0,5 et 2 mm
        res = min(2.0, max(0.5, math.sqrt(width * height / float(CELLS))))
    # grille = zone utile agrandie de la demi-espace : la silhouette décalée peut y toucher, la pièce reste dedans
    half = spacing / 2.0
    nx, ny = int(math.floor((width + spacing) / res + 1e-9)), int(math.floor((height + spacing) / res + 1e-9))
    angles = [a * float(angle_step) for a in range(int(round(360.0 / angle_step)))] if angle_step else [0.0]

    def geo_key(face):
        return (round(face.Area, 6), round(face.BoundBox.XLength, 6), round(face.BoundBox.YLength, 6),
                round(face.Length, 6))

    masks = {}  # (géométrie, angle) -> (masque, x0, y0) : les copies partagent leurs masques
    for _key, face in items:
        g = geo_key(face)
        for angle in angles:
            if (g, angle) not in masks:
                masks[(g, angle)] = raster_mask(face, angle, res, half)
    usable = [m for m, _x, _y in masks.values() if m.shape[0] <= nx and m.shape[1] <= ny]
    mx = max([m.shape[0] for m in usable] or [1])
    my = max([m.shape[1] for m in usable] or [1])
    fft_shape = (_fast_len(nx + mx), _fast_len(ny + my))
    mask_ffts = {}
    sheets = []
    order = sorted(items, key=lambda it: -it[1].Area)
    placed, unplaced = {}, []
    for key, face in order:
        g = geo_key(face)
        best = None
        candidates = list(enumerate(sheets))
        if len(sheets) < max_sheets:
            candidates.append((len(sheets), _Sheet(nx, ny, fft_shape)))  # panneau neuf si aucun ouvert ne convient
        for s_index, target in candidates:
            for angle in angles:
                mask, x0, y0 = masks[(g, angle)]
                if mask.shape[0] > nx or mask.shape[1] > ny:
                    continue
                mf = mask_ffts.get((g, angle))
                if mf is None:
                    mf = mask_ffts[(g, angle)] = _fft_module().rfft2(mask[::-1, ::-1].astype(float), s=fft_shape, **_WORKERS)
                free = target.free_positions(mask, mf)
                if free is None:
                    continue
                cols = free.any(axis=0)
                if not cols.any():
                    continue
                # dessus le plus bas (première colonne j libre, le dessus vaut j + hauteur du masque), puis le plus à
                # gauche (première ligne i libre de cette colonne) : le minimum de (j, i), sans trier les positions
                j = int(np.argmax(cols))
                i = int(np.argmax(free[:, j]))
                cand = (j + mask.shape[1], i)
                if best is None or cand < best[0]:
                    best = (cand, s_index, target, angle, i, j, mask, x0, y0)
            if best is not None:
                break  # premier panneau où la pièce tient
        if best is None:
            unplaced.append(key)
            continue
        _cand, s_index, target, angle, i, j, mask, x0, y0 = best
        if s_index == len(sheets):
            sheets.append(target)
        target.place(mask, i, j)
        placed[key] = (s_index, angle, i * res - x0 - half, j * res - y0 - half)
    return placed, unplaced, res


def place_shape(obj, angle, dx, dy):
    """Tourne l'objet de ``angle`` autour de l'origine puis le translate de (dx, dy) (après son placement actuel)."""
    obj.Placement = FreeCAD.Placement(FreeCAD.Vector(dx, dy, 0), FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), angle)) \
        .multiply(obj.Placement)
