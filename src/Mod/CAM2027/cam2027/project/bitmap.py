# SPDX-License-Identifier: LGPL-2.1-or-later
"""Images vers parcours (Aspire « Trace Bitmap » et « Photo V-Carving »).

**Vectorisation** : l'image en niveaux de gris (``relief.load_heightmap``) est seuillée par *marching
squares* (sous-pixel : les bords sont interpolés à la valeur du seuil), les segments sont chaînés en
contours fermés (bord de l'image compris : l'image est entourée de fond), simplifiés (Douglas-Peucker) et
les taches plus petites que ``min_area`` sont écartées. Pas de ``potrace`` (absent de FreeCAD) : contours
polygonaux, pas de courbes de Bézier. Le résultat est un vecteur du dessin (trous respectés), usinable par
la poche 2D, le contour ou le V-carving.

**Photo V-Carve** : lignes parallèles gravées au V-bit, profondeur proportionnelle au sombre de l'image
(blanc = rien, noir = profondeur maximale) : la largeur du trait rend le gris. Les zones plus claires que la
profondeur minimale sont sautées (remontée au-dessus de la matière).
"""

import math

import FreeCAD

from ..i18n import Msg, UserError

#: Photo V-Carve : nom des opérations générées (Path.Op.Custom) et genre dans le registre
PHOTO_PREFIX = "CAM2027PhotoVCarve"
PHOTO_KIND = "photo_vcarve"
#: libellés (anglais, traduits par l'interface) des opérations générées du flux S5, pour la liste des opérations
KIND_LABELS = {PHOTO_KIND: "Photo V-carve", "moulding": "Moulding", "fluting": "Fluting", "texture": "Texture"}


def _grid(path, cells):
    from . import relief
    import numpy as np

    grid, size = relief.load_heightmap(path, cells)
    return np.array(grid, dtype=float), size  # g[i, j] : i colonnes (gauche -> droite), j lignes (bas -> haut)


# -- vectorisation --------------------------------------------------------------------------------------


def _segments(field, level):
    """Segments d'iso-valeur ``level`` d'un champ ``field[i, j]`` (marching squares) ; extrémités = clés
    d'arêtes de la grille pour un chaînage exact."""
    nx, ny = field.shape
    segs = []
    fl = field.tolist()  # accès Python : dix fois plus rapide que l'indexation numpy cellule par cellule

    def point(a, b):
        (i0, j0), (i1, j1) = a, b
        v0, v1 = fl[i0][j0], fl[i1][j1]
        t = 0.5 if v1 == v0 else (level - v0) / (v1 - v0)
        return (i0 + t * (i1 - i0), j0 + t * (j1 - j0))

    inside = (field > level).tolist()
    for i in range(nx - 1):
        for j in range(ny - 1):
            c = (inside[i][j], inside[i + 1][j], inside[i + 1][j + 1], inside[i][j + 1])
            code = int(c[0]) | (int(c[1]) << 1) | (int(c[2]) << 2) | (int(c[3]) << 3)
            if code in (0, 15):
                continue
            corners = ((i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1))
            # arêtes : 0 bas, 1 droite, 2 haut, 3 gauche
            edges = [(corners[0], corners[1]), (corners[1], corners[2]), (corners[3], corners[2]), (corners[0], corners[3])]
            crossing = [k for k in range(4) if c[[0, 1, 3, 0][k]] != c[[1, 2, 2, 3][k]]]
            if len(crossing) == 4:  # selle : tranchée par la moyenne des quatre coins
                centre_inside = sum(fl[a][b] for a, b in corners) / 4.0 > level
                pairs = ((0, 1), (2, 3)) if (code == 5) == centre_inside else ((0, 3), (1, 2))
            else:
                pairs = (tuple(crossing),)
            for a, b in pairs:
                ka, kb = edges[a], edges[b]
                segs.append((ka, kb, point(*ka), point(*kb)))
    return segs


def _chain(segs):
    """Contours fermés à partir des segments (chaque arête de grille est partagée par deux segments)."""
    links = {}
    for ka, kb, pa, pb in segs:
        links.setdefault(ka, []).append((kb, pa, pb))
        links.setdefault(kb, []).append((ka, pb, pa))
    loops, used = [], set()
    for start in list(links):
        if start in used:
            continue
        loop, key = [], start
        while key not in used:
            used.add(key)
            nxt = [n for n in links[key] if n[0] not in used]
            if not nxt:
                break
            other, p_here, _p_there = nxt[0]
            loop.append(p_here)
            key = other
        if len(loop) >= 3:
            loops.append(loop)
    return loops


def _area(pts):
    return 0.5 * sum(pts[k][0] * pts[k - 1][1] - pts[k - 1][0] * pts[k][1] for k in range(len(pts)))


def _douglas_peucker(pts, tol):
    if len(pts) < 3:
        return pts
    (x0, y0), (x1, y1) = pts[0], pts[-1]
    dx, dy = x1 - x0, y1 - y0
    norm = math.hypot(dx, dy)
    best, idx = -1.0, 0
    for k in range(1, len(pts) - 1):
        px, py = pts[k]
        d = abs(dy * (px - x0) - dx * (py - y0)) / norm if norm > 1e-12 else math.hypot(px - x0, py - y0)
        if d > best:
            best, idx = d, k
    if best <= tol:
        return [pts[0], pts[-1]]
    return _douglas_peucker(pts[: idx + 1], tol)[:-1] + _douglas_peucker(pts[idx:], tol)


def _simplify_loop(loop, tol):
    # point de départ le plus éloigné du premier : les deux moitiés se simplifient sans perdre le contour
    far = max(range(len(loop)), key=lambda k: (loop[k][0] - loop[0][0]) ** 2 + (loop[k][1] - loop[0][1]) ** 2)
    a = _douglas_peucker(loop[: far + 1], tol)
    b = _douglas_peucker(loop[far:] + [loop[0]], tol)
    return a[:-1] + b[:-1]


def trace(path, width, threshold=0.5, invert=False, cells=400, tolerance=0.05, min_area=1.0, origin=(0.0, 0.0)):
    """Contours fermés (listes de points en mm, X à droite, Y en haut) des zones **sombres** de l'image
    (``invert`` : zones claires), largeur de l'image = ``width`` mm, coin bas gauche = ``origin``.

    ``threshold`` : gris de séparation (0 noir, 1 blanc) ; ``tolerance`` : écart maximal (mm) de la
    simplification ; ``min_area`` : taches plus petites ignorées (mm²)."""
    import numpy as np

    if width <= 0:
        raise UserError("the image width must be above 0")
    if not 0.0 < threshold < 1.0:
        raise UserError("the threshold must be between 0 and 1")
    g, (w_px, h_px) = _grid(path, cells)
    field = g if invert else 1.0 - g  # « dedans » = valeur au-dessus du niveau
    level = threshold if invert else 1.0 - threshold
    nx, ny = field.shape
    pad = np.zeros((nx + 2, ny + 2))
    pad[1:-1, 1:-1] = field
    scale = float(width) / (nx - 1) if nx > 1 else 1.0
    loops = []
    for loop in _chain(_segments(pad, level)):
        pts = [((i - 1) * scale + origin[0], (j - 1) * scale + origin[1]) for i, j in loop]
        pts = [(min(max(x, origin[0]), origin[0] + width), min(max(y, origin[1]), origin[1] + (ny - 1) * scale)) for x, y in pts]
        if abs(_area(pts)) < min_area:
            continue
        pts = _simplify_loop(pts, tolerance)
        if len(pts) >= 3 and abs(_area(pts)) >= min_area:
            loops.append(pts)
    if not loops:
        raise UserError("nothing traced: no area darker than the threshold (try another threshold or invert)")
    return loops


def loops_shape(loops):
    import Part

    V = FreeCAD.Vector
    return Part.Compound([Part.makePolygon([V(x, y, 0) for x, y in pts] + [V(pts[0][0], pts[0][1], 0)]) for pts in loops])


def trace_to_vector(proj, path, width, label=None, **options):
    """Vectorise l'image dans un nouveau vecteur du dessin ; retourne ``(objet, nombre de contours)``."""
    import os
    from . import vectors

    loops = trace(path, width, **options)
    obj = vectors.add_vector(proj, loops_shape(loops), label or os.path.splitext(os.path.basename(path))[0])
    return obj, len(loops)


# -- Photo V-Carve -------------------------------------------------------------------------------------


def _bilinear(g, u, v):
    """Valeur de la grille aux coordonnées continues (u, v) en cellules."""
    nx, ny = g.shape
    u = min(max(u, 0.0), nx - 1.0)
    v = min(max(v, 0.0), ny - 1.0)
    i, j = min(int(u), nx - 2), min(int(v), ny - 2)
    fu, fv = u - i, v - j
    return ((1 - fu) * (1 - fv) * g[i, j] + fu * (1 - fv) * g[i + 1, j] + (1 - fu) * fv * g[i, j + 1] + fu * fv * g[i + 1, j + 1])


def photo_lines(path, width, max_depth, spacing, sample=0.2, min_depth=0.05, invert=False, origin=(0.0, 0.0),
                z_top=0.0, cells=400, gamma=1.0):
    """Polylignes de coupe ``[[(x, y, z), ...], ...]`` : une ligne horizontale tous les ``spacing`` mm,
    points tous les ``sample`` mm, ``z = z_top - max_depth * sombre ** gamma`` ; coupées là où la
    profondeur est sous ``min_depth``. Lignes alternées (aller-retour)."""
    if max_depth <= 0 or spacing <= 0 or sample <= 0 or width <= 0:
        raise UserError("photo V-carve: width, depth, line spacing and sampling must be above 0")
    g, _size = _grid(path, cells)
    nx, ny = g.shape
    height = float(width) * (ny - 1) / (nx - 1)
    cx, cy = (nx - 1) / float(width), (ny - 1) / height
    n_lines = int(math.floor(height / spacing + 1e-9))
    n_pts = int(math.floor(width / sample + 1e-9))
    lines = []
    for k in range(n_lines + 1):
        y = spacing / 2.0 + k * spacing
        if y > height + 1e-9:
            break
        xs = [p * sample for p in range(n_pts + 1)]
        if k % 2:
            xs.reverse()
        current = []
        for x in xs:
            grey = _bilinear(g, x * cx, y * cy)
            dark = grey if invert else 1.0 - grey
            depth = max_depth * max(0.0, min(1.0, dark)) ** gamma
            if depth < min_depth:
                if len(current) >= 2:
                    lines.append(current)
                current = []
                continue
            current.append((x + origin[0], y + origin[1], z_top - depth))
        if len(current) >= 2:
            lines.append(current)
    return lines


def _reduce(points, tol=0.005):
    """Points alignés retirés (écart < ``tol`` mm à la corde) : moins de commandes, même trajet."""
    if len(points) < 3:
        return points
    out = [points[0]]
    for k in range(1, len(points) - 1):
        a, b, c = out[-1], points[k], points[k + 1]
        ab = [b[i] - a[i] for i in range(3)]
        ac = [c[i] - a[i] for i in range(3)]
        lac = math.sqrt(sum(v * v for v in ac))
        if lac < 1e-12:
            continue
        cross = (ab[1] * ac[2] - ab[2] * ac[1], ab[2] * ac[0] - ab[0] * ac[2], ab[0] * ac[1] - ab[1] * ac[0])
        if math.sqrt(sum(v * v for v in cross)) / lac > tol:
            out.append(b)
    out.append(points[-1])
    return out


def photo_gcode(lines, safe_z, feed, plunge_feed):
    """G-code (liste de lignes) des polylignes : approche en G0 à ``safe_z``, plongée, coupe, remontée."""
    out = ["G0 Z%.4f" % safe_z]
    for line in lines:
        pts = _reduce(line)
        x, y, z = pts[0]
        out.append("G0 X%.4f Y%.4f" % (x, y))
        out.append("G1 Z%.4f F%.1f" % (z, plunge_feed))
        out.extend("G1 X%.4f Y%.4f Z%.4f F%.1f" % (p[0], p[1], p[2], feed) for p in pts[1:])
        out.append("G0 Z%.4f" % safe_z)
    return out


def add_photo_vcarve(proj, name, assembly_id, preset_id, path, width, max_depth, spacing=None, origin=(0.0, 0.0),
                     sample=0.2, min_depth=0.05, invert=False, gamma=1.0, safe_margin=3.0):
    """Opération Photo V-Carve (``Path.Op.Custom``) sur le dessus du brut. ``spacing`` par défaut : largeur
    du V-bit à la profondeur maximale (les traits les plus sombres se touchent). Retourne ``(op, record)``."""
    import Path.Op.Custom as Custom
    from ..tools import bridge
    from . import project as projmod

    asm, tool, holder = proj.library.resolve_assembly(assembly_id)
    angle = tool.geometry.tip_included_angle_deg
    if tool.tool_type not in ("vbit", "engrave", "chamfer") or not angle:
        raise UserError("photo V-carve needs a V-bit (tool with a tip angle)")
    half = math.radians(float(angle)) / 2.0
    tip = float(getattr(tool.geometry, "tip_diameter", 0.0) or 0.0)
    full_width = tip + 2.0 * max_depth * math.tan(half)
    if full_width > tool.geometry.diameter + 1e-9:
        raise UserError("photo V-carve: {d} mm deep is wider than the V-bit ({w:.2f} > {dia:.2f} mm)",
                        d="%g" % max_depth, w=full_width, dia=tool.geometry.diameter)
    spacing = float(spacing or full_width)
    preset = tool.preset(preset_id)
    values = preset.resolve(tool)
    job = proj.job
    z_top = proj.stock_bounds()["zmax"]
    lines = photo_lines(path, width, max_depth, spacing, sample, min_depth, invert, origin, z_top, gamma=gamma)
    if not lines:
        raise UserError("photo V-carve: the image is lighter than the minimum depth everywhere: nothing to cut")
    toolbit, bit_warnings = bridge.create_toolbit(proj.doc, tool, label="%s (T%d)" % (tool.name, asm.output.tool_number))
    tc, _ = bridge.create_tool_controller(proj.doc, asm, tool, values, toolbit=toolbit, label="TC: %s" % name)
    job.Proxy.addToolController(tc)
    previous = FreeCAD.ActiveDocument
    FreeCAD.setActiveDocument(proj.doc.Name)
    try:
        op = Custom.Create(PHOTO_PREFIX, parentJob=job)
    finally:
        if previous is not None and previous.Name != proj.doc.Name:
            FreeCAD.setActiveDocument(previous.Name)
    op.Label = name
    op.ToolController = tc
    op.Source = "Text"
    from . import wrap as wrapmod

    # F en mm/min dans le texte, converti dans l'unité interne de Path (mm/s) comme la gravure enroulée
    op.Gcode = wrapmod.path_gcode(photo_gcode(lines, z_top + safe_margin, values["feed_mm_min"], values["plunge_feed_mm_min"]))
    reg = proj.registry
    record = {
        "kind": PHOTO_KIND, "label": name, "order": len(reg), "assembly_id": asm.id, "tool_id": tool.id,
        "holder_id": holder.id if holder else None, "preset_id": preset.id, "values": values,
        "tool_controller": tc.Name, "toolbit": toolbit.Name,
        "params": projmod._jsonable({"image": path, "width": width, "max_depth": max_depth, "spacing": spacing,
                                      "origin": list(origin), "sample": sample, "min_depth": min_depth,
                                      "invert": invert, "gamma": gamma}),
        "ignored_params": [], "warnings": list(bit_warnings), "index_deg": None,
    }
    reg[op.Name] = record
    proj._save_registry(reg)
    proj.doc.recompute()
    return op, record
