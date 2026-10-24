# SPDX-License-Identifier: LGPL-2.1-or-later
"""Ébauche 2,5D sur un modèle de brut partagé : stratégie ``stockrough``.

Le brut est une **carte de hauteur** (``sim.ZMap``, la même que le contrôle matière) : dessus du brut du job
par colonne, mise à jour après chaque niveau avec les passes générées. La **pièce entière** (tous les corps du
job, pas seulement l'objet choisi) borne la descente : carte « plancher » = dessus de la pièce + surépaisseur,
dilatée du rayon de la fraise (``sim.disc_max``), donc la fraise entière reste au-dessus de la pièce : pas
d'entaille sur un second corps ni sous un surplomb, et les fonds à plusieurs profondeurs sont faits en une
seule opération.

À chaque niveau (pas axial depuis la profondeur de départ) : cellules où la fraise peut descendre et touche
encore de la matière, regroupées en régions connexes usinées une à une (balayage en serpentin, axe alterné d'un
niveau à l'autre, liaisons au niveau quand le trajet direct reste permis), puis passe le long des parois
(contour de la région) pour enlever les marches du balayage. Entrée en **hélice** dans la matière (angle et
diamètre limités), plongée droite seulement si l'hélice ne tient pas, descente directe quand il n'y a pas de
matière au-dessus.

Fraise plate seulement (le profil de la carte est un disque). Base ignorée : toute la pièce est protégée,
tout le brut accessible est dégagé.
"""

import math

import FreeCAD

from ..i18n import UserError
from . import sim

KIND = "stockrough"
#: matière de moins que ça au-dessus de la pointe : pas la peine de passer (comme Fusion « Ignore stock less than »)
IGNORE = 0.1
#: points par tour d'hélice, marge au-dessus de la matière pour le début de l'hélice (mm)
HELIX_STEPS = 24
ENTRY_MARGIN = 0.2


def _np():
    import numpy

    return numpy


def _runs(mask_1d):
    np = _np()
    idx = np.flatnonzero(mask_1d)
    if not len(idx):
        return []
    breaks = np.flatnonzero(np.diff(idx) > 1)
    starts = np.r_[idx[0], idx[breaks + 1]]
    ends = np.r_[idx[breaks], idx[-1]]
    return list(zip(starts, ends))


def _cell(zmap, p):
    i = min(max(int((p[0] - zmap.x0) / zmap.res), 0), zmap.nx - 1)
    j = min(max(int((p[1] - zmap.y0) / zmap.res), 0), zmap.ny - 1)
    return i, j


def _link_allowed(allowed, zmap, a, b):
    """La ligne droite a -> b (au niveau courant) reste-t-elle au-dessus du plancher ?"""
    np = _np()
    n = max(2, int(math.hypot(b[0] - a[0], b[1] - a[1]) / zmap.res) + 1)
    xs = np.linspace(a[0], b[0], n)
    ys = np.linspace(a[1], b[1], n)
    i = np.clip(((xs - zmap.x0) / zmap.res).astype(int), 0, zmap.nx - 1)
    j = np.clip(((ys - zmap.y0) / zmap.res).astype(int), 0, zmap.ny - 1)
    return bool(allowed[i, j].all())


def _raster(mask, zmap, i0, j0, row_step, along_x, allowed, pos):
    """Segments (a, b) en mm balayant ``mask`` (sous-grille d'origine i0, j0). Ordre glouton : depuis la
    position courante, le tronçon le plus proche des lignes voisines dont la liaison directe est permise
    (une zone en anneau autour d'un îlot se fait d'un côté puis de l'autre, sans remonter à chaque ligne),
    sinon le plus proche de tous."""
    runs = []
    rows = range(0, mask.shape[1] if along_x else mask.shape[0], row_step)
    for r_i, j in enumerate(rows):
        for s, e in _runs(mask[:, j] if along_x else mask[j, :]):
            if along_x:
                runs.append((r_i, (zmap.xs[i0 + s], zmap.ys[j0 + j]), (zmap.xs[i0 + e], zmap.ys[j0 + j])))
            else:
                runs.append((r_i, (zmap.xs[i0 + j], zmap.ys[j0 + s]), (zmap.xs[i0 + j], zmap.ys[j0 + e])))
    segs = []
    left = list(range(len(runs)))
    row = -1
    while left:
        best = None
        if pos is not None:
            near = sorted(left, key=lambda k: abs(runs[k][0] - row) + 0.001 * min(
                math.hypot(runs[k][1][0] - pos[0], runs[k][1][1] - pos[1]), math.hypot(runs[k][2][0] - pos[0], runs[k][2][1] - pos[1])))
            for k in near[:12]:
                if abs(runs[k][0] - row) > 2:
                    break
                r_i, a, b = runs[k]
                if math.hypot(b[0] - pos[0], b[1] - pos[1]) < math.hypot(a[0] - pos[0], a[1] - pos[1]):
                    a, b = b, a
                if _link_allowed(allowed, zmap, pos, a):
                    best = (k, a, b)
                    break
        if best is None:  # aucune liaison directe : le plus proche, avec remontée
            if pos is None:
                k = left[0]
            else:
                k = min(left, key=lambda k: min(math.hypot(runs[k][1][0] - pos[0], runs[k][1][1] - pos[1]),
                                                math.hypot(runs[k][2][0] - pos[0], runs[k][2][1] - pos[1])))
            r_i, a, b = runs[k]
            if pos is not None and math.hypot(b[0] - pos[0], b[1] - pos[1]) < math.hypot(a[0] - pos[0], a[1] - pos[1]):
                a, b = b, a
            best = (k, a, b)
        k, a, b = best
        left.remove(k)
        row = runs[k][0]
        segs.append((a, b))
        pos = b
    return segs


def _contours(mask, zmap, i0, j0):
    """Boucles fermées (points en mm) le long des parois de ``mask`` : contour du masque érodé d'une cellule
    (le contour à mi-chemin entre cellules passait une demi-cellule hors des cellules permises : entailles de
    0,2 à 0,5 mm sur les parois inclinées)."""
    np = _np()
    from scipy import ndimage

    from . import bitmap

    pad = np.zeros((mask.shape[0] + 2, mask.shape[1] + 2))
    pad[1:-1, 1:-1] = ndimage.binary_erosion(mask)
    loops = []
    for loop in bitmap._chain(bitmap._segments(pad, 0.5)):
        pts = [(zmap.x0 + (i0 + i - 0.5) * zmap.res, zmap.y0 + (j0 + j - 0.5) * zmap.res) for i, j in loop]
        if len(pts) >= 3:
            loops.append(pts)
    return loops


def _helix(a, h, z_from, z_to, angle_deg):
    """Hélice horaire de rayon ``h`` autour de ``a``, de ``z_from`` à ``z_to``, puis un tour plat au fond.
    Retourne ``(points fins pour le balayage du brut, arcs G2 par demi-tour (x, y, z, i, j))``."""
    pitch = 2.0 * math.pi * h * math.tan(math.radians(angle_deg))
    turns = max((z_from - z_to) / pitch, 1e-6)
    halves = max(1, int(math.ceil(turns * 2.0)))
    pts = [(a[0] + h, a[1], z_from)]
    arcs = []
    for k in range(1, halves + 3):  # + 2 demi-tours plats au fond
        z = z_from - (z_from - z_to) * min(k / (turns * 2.0), 1.0)
        for s in range(1, HELIX_STEPS // 2 + 1):
            ang = -math.pi * (k - 1 + 2.0 * s / HELIX_STEPS)  # horaire
            zz = pts[-1][2] + (z - pts[-1][2]) * (2.0 * s / HELIX_STEPS) if s < HELIX_STEPS // 2 else z
            pts.append((a[0] + h * math.cos(ang), a[1] + h * math.sin(ang), zz))
        end = (a[0] + h * math.cos(-math.pi * k), a[1] + h * math.sin(-math.pi * k), z)
        start = (a[0] + h * math.cos(-math.pi * (k - 1)), a[1] + h * math.sin(-math.pi * (k - 1)))
        arcs.append((end[0], end[1], z, a[0] - start[0], a[1] - start[1]))
    pts.append((a[0], a[1], z_to))
    return pts, arcs


def plan(stock_shape, part_shapes, radius, start, final, step_down, step_over, leave, resolution=0.5,
         helix_angle=3.0, helix_limit=0.0, walls=True, previous=None):
    """Mouvements de l'ébauche : ``(genre, x, y, z)`` avec genre ``link`` (remontée + rapide), ``plunge``
    (descente en avance verticale), ``cut`` (avance de coupe), ou ``("arc", x, y, z, i, j)`` (demi-tour
    d'hélice G2, avance verticale).
    Retourne ``(mouvements, statistiques)``."""
    np = _np()
    from scipy import ndimage

    bb = stock_shape.BoundBox
    if start - final <= 1e-6:
        raise UserError("stock roughing: start depth must be above the final depth")
    area = max(bb.XLength * bb.YLength, 1e-9)
    resolution = max(float(resolution), math.sqrt(area / (sim.MAX_CELLS * 0.9)))
    zmap = sim.ZMap(bb.XMin, bb.YMin, bb.XMax, bb.YMax, start, resolution)
    stock_top = sim.model_heights(zmap, [stock_shape])
    zmap.top = np.minimum(stock_top, start)  # -inf hors du brut : pas de matière
    if previous:  # reprise : brut tel que laissé par les opérations précédentes ``(commandes, profil)``
        sim.simulate_paths(zmap, previous)
    part = sim.model_heights(zmap, part_shapes)
    target = np.where(np.isfinite(part), part + leave, final)
    # plancher de la pointe : la fraise entière au-dessus de la pièce ; + 0,75 cellule : la pièce est vue aux centres
    # des cellules, son vrai bord peut être une demi-diagonale plus près (le coin d'un corps était effleuré)
    rc = radius / zmap.res + 0.75
    floor = np.maximum(sim.disc_max(target, rc), final)
    profile = sim.ToolProfile("flat", 2.0 * radius)
    h = min(radius, (helix_limit / 2.0) if helix_limit > 0 else 0.75 * radius)
    radii = [h, h / 2.0] if h / 2.0 >= zmap.res else [h]
    levels = []
    z = start
    while z - step_down > final + 1e-6:
        z -= step_down
        levels.append(z)
    levels.append(final)
    # zones plates (fonds de poche, dessus) : leur hauteur devient un niveau, sinon un fond entre deux pas
    # axiaux ne serait jamais atteint (Fusion « flat area detection ») ; les pentes n'ont pas de hauteur commune
    # (zone plate = au moins un disque de fraise de cellules de la pièce à la même hauteur, avant dilatation)
    flat_min_cells = int(math.pi * rc * rc)
    values, counts = np.unique(np.round(target[np.isfinite(part)], 3), return_counts=True)
    flats = set()
    for v, c in zip(values, counts):
        if c >= flat_min_cells and final + 1e-6 < v < start - 1e-6 and all(abs(v - lv) > 1e-3 for lv in levels):
            levels.append(float(v))
            flats.add(float(v))
    levels.sort(reverse=True)
    row_step = max(1, int(round(step_over * 2.0 * radius / zmap.res)))
    moves = []
    stats = {"levels": 0, "regions": 0, "helix": 0, "plunges": 0, "air": 0}
    pad = int(math.ceil(rc + h / zmap.res)) + 1
    for k, z in enumerate(levels):
        allowed = floor <= z + 1e-6
        cand = allowed
        if z in flats:  # niveau d'une zone plate : seulement cette zone (le reste attend le pas axial suivant)
            cand = allowed & (floor >= z - 1e-3)
        if not cand.any():
            continue
        # fenêtre autour des cellules candidates : les dilatations (matière touchée, place pour l'hélice, matière
        # autour de l'entrée) coûtent cher sur toute la grille, et un niveau de zone plate n'en couvre qu'un coin
        ii, jj = np.nonzero(cand)
        i0, i1 = max(0, int(ii.min()) - pad), min(zmap.nx, int(ii.max()) + pad + 1)
        j0, j1 = max(0, int(jj.min()) - pad), min(zmap.ny, int(jj.max()) + pad + 1)
        win = (slice(i0, i1), slice(j0, j1))
        top_w = zmap.top[win]
        material = top_w > z + IGNORE
        touch = sim.disc_max(np.where(material, 1.0, -np.inf), rc) > 0.5  # le disque de la fraise touche de la matière
        cut = cand[win] & touch
        if not cut.any():
            continue
        stats["levels"] += 1
        blocked = np.where(allowed[win], -np.inf, 1.0)
        helix_ok = [sim.disc_max(blocked, hr / zmap.res) < 0.5 for hr in radii]  # rien d'interdit à ``hr`` du centre
        top_near = sim.disc_max(top_w, (radius + h) / zmap.res)  # matière la plus haute autour de l'entrée
        labels, n = ndimage.label(cut)
        boxes = ndimage.find_objects(labels)
        # région plus petite que le disque de la fraise (miette laissée dans un coin par une fraise plus grosse) :
        # plongée droite (la fraise y est surtout en l'air) et pas de passe le long des parois (le balayage suffit)
        small_cells = math.pi * rc * rc
        pos = None  # (x, y) de la pointe au niveau courant, None = en l'air
        P0, P1 = [], []
        along_x = k % 2 == 0
        # coin (x, y) de chaque région : la région suivante est la plus proche de la position courante (recherche
        # vectorisée : 57 000 régions en reprise sur le chauffage, 22 s en Python pur)
        corners = np.array([(zmap.xs[i0 + b[0].start], zmap.ys[j0 + b[1].start]) for b in boxes], dtype=float)
        remaining = np.ones(n, dtype=bool)

        def helix_centre(a, sl, mask):
            """Centre d'hélice dans la région : cellule permise à ``hr`` à la ronde la plus proche de ``a``."""
            for hr, ok in zip(radii, helix_ok):
                cells = np.argwhere(ok[sl] & mask)
                if len(cells):
                    cx = zmap.xs[i0 + sl[0].start + cells[:, 0]]
                    cy = zmap.ys[j0 + sl[1].start + cells[:, 1]]
                    best = int(np.argmin((cx - a[0]) ** 2 + (cy - a[1]) ** 2))
                    return hr, (float(cx[best]), float(cy[best]))
            return None, None

        while remaining.any():
            if pos is None:
                c = int(np.argmax(remaining)) + 1
            else:  # région la plus proche
                d2 = (corners[:, 0] - pos[0]) ** 2 + (corners[:, 1] - pos[1]) ** 2
                c = int(np.argmin(np.where(remaining, d2, np.inf))) + 1
            remaining[c - 1] = False
            stats["regions"] += 1
            sl = boxes[c - 1]
            gi, gj = i0 + sl[0].start, j0 + sl[1].start  # origine de la région dans la grille entière
            mask = labels[sl] == c
            tiny = mask.sum() < small_cells
            segs = _raster(mask, zmap, gi, gj, row_step, along_x, allowed, pos)
            if walls and not tiny:
                for loop in _contours(mask, zmap, gi, gj):
                    segs.append((loop[0], loop[0]))
                    segs.extend(zip(loop, loop[1:] + loop[:1]))
            for a, b in segs:
                if pos is not None and (pos == a or _link_allowed(allowed, zmap, pos, a)):
                    if pos != a:
                        moves.append(("cut", a[0], a[1], z))
                        P0.append((pos[0], pos[1], z)); P1.append((a[0], a[1], z))
                else:
                    i, j = _cell(zmap, a)
                    z_from = min(start, float(top_near[i - i0, j - j0]) + ENTRY_MARGIN)
                    moves.append(("link", a[0], a[1], z))
                    if z_from <= z + IGNORE:  # pas de matière au-dessus : descente directe
                        moves.append(("plunge", a[0], a[1], z))
                        stats["air"] += 1
                    else:
                        hr, c = (None, None) if tiny else helix_centre(a, sl, mask)  # miette : plongée, la fraise est surtout en l'air
                        if hr is None or (c != a and not _link_allowed(allowed, zmap, c, a)):
                            moves.append(("plunge", a[0], a[1], z))
                            stats["plunges"] += 1
                            P0.append((a[0], a[1], z_from)); P1.append((a[0], a[1], z))
                        else:
                            ic, jc = _cell(zmap, c)
                            z_from = min(start, float(top_near[ic - i0, jc - j0]) + ENTRY_MARGIN)
                            pts, arcs = _helix(c, hr, z_from, z, helix_angle)
                            moves[-1] = ("link", pts[0][0], pts[0][1], z)
                            moves.append(("plunge", pts[0][0], pts[0][1], z_from))
                            for arc in arcs:
                                moves.append(("arc",) + arc)
                            moves.append(("plunge", c[0], c[1], z))
                            for prev, p in zip(pts[:-1], pts[1:]):
                                P0.append(prev); P1.append(p)
                            if c != a:
                                moves.append(("cut", a[0], a[1], z))
                                P0.append((c[0], c[1], z)); P1.append((a[0], a[1], z))
                            stats["helix"] += 1
                if b != a:
                    moves.append(("cut", b[0], b[1], z))
                    P0.append((a[0], a[1], z)); P1.append((b[0], b[1], z))
                pos = b
        if P0:
            zmap.sweep_arrays(np.array(P0, dtype=float), np.array(P1, dtype=float), profile)  # brut partagé mis à jour
    return moves, stats


def moves_to_commands(moves, clearance, safe, horiz_feed, vert_feed):
    """Commandes Path (avances en unités de Path) depuis ``plan``."""
    import Path

    cmds = []
    for move in moves:
        kind, x, y, z = move[:4]
        if kind == "link":
            cmds.append(Path.Command("G0", {"Z": clearance}))
            cmds.append(Path.Command("G0", {"X": x, "Y": y}))
            cmds.append(Path.Command("G0", {"Z": safe}))
        elif kind == "arc":
            cmds.append(Path.Command("G2", {"X": x, "Y": y, "Z": z, "I": move[4], "J": move[5], "F": vert_feed}))
        elif kind == "plunge":
            cmds.append(Path.Command("G1", {"X": x, "Y": y, "Z": z, "F": vert_feed}))
        else:
            cmds.append(Path.Command("G1", {"X": x, "Y": y, "Z": z, "F": horiz_feed}))
    return cmds


# -- opération FreeCAD -------------------------------------------------------------------------------------

import Path.Op.Base as PathOp  # noqa: E402  (FreeCAD CAM : chargé seulement dans FreeCAD)


class ObjectStockRough(PathOp.ObjectOp):
    """Opération ``stockrough`` (proxy enregistré dans le document : classe au niveau du module)."""

    def opFeatures(self, obj):
        return (PathOp.FeatureTool | PathOp.FeatureDepths | PathOp.FeatureStepDown | PathOp.FeatureHeights
                | PathOp.FeatureBaseFaces | PathOp.FeatureCoolant)

    def initOperation(self, obj):
        obj.addProperty("App::PropertyPercent", "StepOver", "StockRough", "Distance between passes, % of the tool diameter")
        obj.addProperty("App::PropertyDistance", "StockToLeave", "StockRough", "Stock left on the part for finishing")
        obj.addProperty("App::PropertyDistance", "Resolution", "StockRough", "Cell size of the stock model (mm)")
        obj.addProperty("App::PropertyAngle", "HelixAngle", "StockRough", "Ramp angle of the helical entry (deg)")
        obj.addProperty("App::PropertyDistance", "HelixDiameterLimit", "StockRough", "Maximum helix diameter (0 = automatic)")
        obj.addProperty("App::PropertyBool", "WallPass", "StockRough", "Follow the walls after the raster passes")
        obj.addProperty("App::PropertyBool", "RestMachining", "StockRough", "Start from the stock left by the previous operations")
        obj.addProperty("App::PropertyLinkList", "Previous", "StockRough", "Previous operations simulated for rest machining")
        obj.addProperty("App::PropertyString", "Report", "StockRough", "Last computation")
        obj.StepOver = 40
        obj.StockToLeave = 0.5
        obj.Resolution = 0.5
        obj.HelixAngle = 3.0
        obj.HelixDiameterLimit = 0.0
        obj.WallPass = True
        obj.RestMachining = False

    def opUpdateDepths(self, obj):
        # FreeCAD déduit les profondeurs de la géométrie de base (faces) : ici, le brut entier
        bb = self.stock.Shape.BoundBox if self.stock is not None and getattr(self.stock, "Shape", None) else None
        if bb is None:
            return
        obj.OpStartDepth = bb.ZMax
        obj.OpFinalDepth = bb.ZMin
        if obj.StartDepth.Value <= obj.FinalDepth.Value + 1e-6:  # valeurs de repli de FreeCAD (1 / 0)
            obj.StartDepth = bb.ZMax
            obj.FinalDepth = bb.ZMin

    def opExecute(self, obj):
        import Path

        if self.stock is None or getattr(self.stock, "Shape", None) is None:
            raise UserError("stock roughing: the job has no stock")
        shapes = [m.Shape for m in self.model if getattr(m, "Shape", None) is not None]
        previous = self._previous_paths(obj) if getattr(obj, "RestMachining", False) else []
        moves, stats = plan(self.stock.Shape, shapes, self.radius, float(obj.StartDepth.Value),
                            float(obj.FinalDepth.Value), float(obj.StepDown.Value),
                            max(1, min(100, int(obj.StepOver))) / 100.0, float(obj.StockToLeave.Value),
                            float(obj.Resolution.Value), float(obj.HelixAngle.Value),
                            float(obj.HelixDiameterLimit.Value), bool(obj.WallPass), previous)
        cmds = moves_to_commands(moves, obj.ClearanceHeight.Value, obj.SafeHeight.Value, self.horizFeed, self.vertFeed)
        if cmds:
            self.commandlist.append(Path.Command("G0", {"Z": obj.ClearanceHeight.Value}))
        self.commandlist.extend(cmds)
        obj.Report = "%d level(s), %d region(s), %d helical entries, %d straight plunges, %d entries in air" % (
            stats["levels"], stats["regions"], stats["helix"], stats["plunges"], stats["air"])
        if previous:
            obj.Report += ", after %d previous operation(s)" % len(previous)

    def _previous_paths(self, obj):
        """``[(commandes, profil de fraise)]`` des opérations précédentes (liste ``Previous``, tenue à jour par
        ``rest.sync``), comme le brut restant de la reprise de matière."""
        from .project import Project
        from . import dressups as dressupmod, holes as holesmod, rest

        project = Project.from_document(obj.Document)
        tops = [o for o in (obj.Previous or []) if o is not None] or rest.previous_tops(project, obj)
        items = []
        for o in tops:
            rec = project.registry.get(dressupmod.base_operation(o).Name) or {}
            if not rec.get("tool_id") or getattr(o, "Path", None) is None:
                continue
            _asm, tool, _holder = project.library.resolve_assembly(rec["assembly_id"])
            profile, _note = sim.ToolProfile.from_library_tool(tool)
            commands = o.Path.Commands
            if holesmod.has_cycles(commands):
                commands = holesmod.expand_cycles(commands)
            items.append((commands, profile))
        return items


def Create(name, obj=None, parentJob=None):
    """Comme les modules ``Path.Op.*`` : crée l'objet et son proxy dans le document actif."""
    if obj is None:
        obj = FreeCAD.ActiveDocument.addObject("Path::FeaturePython", name)
    obj.Proxy = ObjectStockRough(obj, name, parentJob)
    return obj


def __getattr__(name):
    # ``operations.create_operation`` cherche le module d'interface (``Command.res``) pour le fournisseur de vue
    if name == "Command":
        from ..gui import flatpage

        return flatpage.command(KIND)
    raise AttributeError(name)
