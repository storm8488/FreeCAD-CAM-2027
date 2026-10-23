# SPDX-License-Identifier: LGPL-2.1-or-later
"""Reprise des angles (Fusion « Pencil ») : stratégie ``pencil``, fraise boule.

Zones à reprendre = angles intérieurs (congés, raccords de parois, fonds arrondis) où une boule de référence
(« diamètre de l'outil de référence », celui de la finition précédente) ne descend pas, et où la boule de la
reprise descend plus bas. Calcul sur une carte de hauteur fine de la pièce (triangulation, ``sim.model_heights``) :

- hauteur de pointe d'une boule de rayon R au-dessus de chaque colonne (dilatation de la carte par le profil
  de la boule, ``scipy.ndimage.grey_dilation``) ; surface laissée par la boule de référence (érosion de cette
  hauteur par le même profil) ;
- matière laissée par la référence au-dessus de la pointe de la boule de reprise > « seuil » : zone utile
  (au-delà de la « pente maximale » de la pièce : écartée) ;
- passes = courbes de niveau de la distance au bord de la zone (``contourpy``), espacées du pas : elles longent
  l'angle des deux côtés et se resserrent sur lui ;
- hauteur exacte de chaque point par **OpenCamLib** (chute de la boule sur la pièce triangulée, comme la
  finition 3D) : aucune pénétration de la pièce, quelle que soit la grille.

Chaque passe est reliée à la suivante par une remontée à la hauteur de sécurité.
"""

import math
import os

import FreeCAD

from ..i18n import UserError

KIND = "pencil"
DEFAULT_RESOLUTION = 0.1
MAX_CELLS = 2_000_000
SAMPLING = 0.1  # pas de la chute de la boule (OpenCamLib), mm
MIN_CELLS = 4  # zone utile plus petite : ignorée (bruit de la grille)
FILTER_WORKERS = 8  # fils du filtre de la boule (chacun garde une carte : 16 Mo à 2 millions de cellules)


def _np():
    import numpy

    return numpy


def _ocl():
    try:
        import ocl
    except ImportError:
        import opencamlib as ocl
    return ocl


def ball_kernel(radius, res):
    """Disque (empreinte) et profil d'une boule (``sqrt(R² - d²) - R``, ≤ 0) sur la grille."""
    np = _np()
    n = int(math.floor(radius / res))
    k = np.arange(-n, n + 1) * res
    X, Y = np.meshgrid(k, k, indexing="ij")
    d2 = X * X + Y * Y
    foot = d2 <= radius * radius + 1e-12
    prof = np.where(foot, np.sqrt(np.maximum(radius * radius - d2, 0.0)) - radius, 0.0)
    return foot, prof


def _ball_filter(H, radius, res, dilate):
    """Dilatation (érosion) de ``H`` par le profil de la boule, une ligne du noyau à la fois : même résultat que
    ``grey_dilation`` avec le noyau 2D entier, qui monte à 6,5 Go pour une boule de référence de 18 mm sur une
    grille de 540 x 781 (disque WobbleRing ; 0,12 Go ici).

    Les lignes ``k`` et ``2n - k`` du noyau ont le même profil : une seule passe 1D sur la carte bordée sert aux
    deux, décalée. Les passes sont réparties sur ``FILTER_WORKERS`` fils (``scipy.ndimage`` rend le GIL), chacun
    gardant son maximum (minimum) ; le maximum ne dépend pas de l'ordre : résultat identique au bit près."""
    from concurrent.futures import ThreadPoolExecutor, wait
    from scipy import ndimage

    np = _np()
    foot, prof = ball_kernel(radius, res)
    n = foot.shape[0] // 2
    pad = np.pad(H, ((n, n), (0, 0)), mode="edge")
    rows = H.shape[0]
    pick = np.maximum if dilate else np.minimum
    flt = ndimage.grey_dilation if dilate else ndimage.grey_erosion
    ks = [k for k in range(n + 1) if foot[k].any()]

    def part(chunk):
        out = None
        for k in chunk:
            r = flt(pad, footprint=foot[k][None, :], structure=prof[k][None, :], mode="nearest")
            # dilatation : ligne k du noyau sur pad[k:k + rows] ; érosion : sur pad[2n - k:...] ; et la symétrique
            for a in {k, 2 * n - k}:
                s = r[a:a + rows]
                out = s.copy() if out is None else pick(out, s, out=out)
        return out

    workers = max(1, min(FILTER_WORKERS, (os.cpu_count() or 2) - 1, len(ks)))
    if workers == 1:
        return part(ks)
    from .operations import keep_gui_alive

    with ThreadPoolExecutor(workers) as pool:
        futures = [pool.submit(part, ks[w::workers]) for w in range(workers)]
        while wait(futures, timeout=0.2).not_done:
            keep_gui_alive()
        parts = [f.result() for f in futures]
    out = parts[0]
    for p in parts[1:]:
        pick(out, p, out=out)
    return out


def tip_heights(H, radius, res):
    """Hauteur de la pointe d'une boule posée sur la carte ``H`` au-dessus de chaque colonne."""
    return _ball_filter(H, radius, res, True)


def envelope(tips, radius, res):
    """Surface la plus basse atteinte par une boule dont la pointe suit ``tips`` (matière laissée)."""
    return _ball_filter(tips, radius, res, False)


def corner_zone(H, res, ref_radius, radius, threshold=0.02, max_slope_deg=90.0, inside=None, tips=None):
    """Zone utile (booléens) et matière reprise (mm) au centre de chaque colonne ; ``tips`` : hauteurs de pointe
    de la boule de reprise si déjà calculées."""
    from scipy import ndimage

    np = _np()
    left = envelope(tip_heights(H, ref_radius, res), ref_radius, res)
    if tips is None:
        tips = tip_heights(H, radius, res)
    gain = left - tips
    zone = gain > threshold
    if inside is not None:
        zone &= inside
    if max_slope_deg < 89.999:
        gx, gy = np.gradient(H, res)
        zone &= np.degrees(np.arctan(np.hypot(gx, gy))) <= max_slope_deg
    labels, n = ndimage.label(zone)
    if n:
        sizes = ndimage.sum(zone, labels, index=np.arange(1, n + 1))
        small = np.nonzero(sizes < MIN_CELLS)[0] + 1
        if len(small):
            zone &= ~np.isin(labels, small)
    return zone, gain


def pass_lines(zone, xs, ys, step, tips=None):
    """Courbes de niveau de la distance au bord de la zone : ``[tableau (n, 2)]`` en XY.

    Première passe sur le bord de la zone (la boule y touche le haut du congé, sa partie la plus raide), puis
    une tous les ``step`` **mesurés le long de la surface** : sur une pente, l'écart en XY est réduit du cosinus
    de la pente de la pointe (``tips``) relevée sur la passe (le plus raide décile), au moins une cellule. Une
    boule de reprise ne touche un congé qu'en un point : avec un écart constant en XY, la partie presque
    verticale d'un congé (près de la paroi) garderait des crêtes de plusieurs millimètres."""
    import contourpy
    from scipy import ndimage

    np = _np()
    if not zone.any():
        return []
    res = float(xs[1] - xs[0]) if len(xs) > 1 else 1.0
    dist = ndimage.distance_transform_edt(zone) * res
    top = float(dist.max())
    cosine = None
    if tips is not None:
        gx, gy = np.gradient(tips, res)
        cosine = np.cos(np.arctan(np.hypot(gx, gy)))
    levels = []
    lv = 0.5 * res
    while lv < top:
        levels.append(lv)
        c = 1.0
        if cosine is not None:
            near = zone & (np.abs(dist - lv) <= res)
            if near.any():
                c = float(np.percentile(cosine[near], 10))
        lv += max(res, step * c)
    gen = contourpy.contour_generator(x=xs, y=ys, z=dist.T)
    lines = []
    for lv in levels:
        for line in gen.lines(lv):
            arr = np.asarray(line, dtype=float)
            if len(arr) >= 2:
                lines.append(arr)
    return lines


def _resample(line, spacing):
    np = _np()
    out = [line[0]]
    for a, b in zip(line[:-1], line[1:]):
        n = max(1, int(math.ceil(float(np.hypot(*(b - a))) / spacing)))
        for k in range(1, n + 1):
            out.append(a + (b - a) * (k / float(n)))
    return np.array(out)


def drop_ball(shapes, lines, diameter, zmin, deflection=0.01, length=50.0):
    """Hauteurs exactes (OpenCamLib, pointe de la boule) le long des passes : ``[[(x, y, z)]]``."""
    ocl = _ocl()
    stl = ocl.STLSurf()
    for shape in shapes:
        try:
            fresh = shape.copy(True, False)
        except TypeError:
            fresh = shape
        verts, tris = fresh.tessellate(deflection)
        for a, b, c in tris:
            va, vb, vc = verts[a], verts[b], verts[c]
            stl.addTriangle(ocl.Triangle(ocl.Point(va.x, va.y, va.z), ocl.Point(vb.x, vb.y, vb.z),
                                         ocl.Point(vc.x, vc.y, vc.z)))
    cutter = ocl.BallCutter(diameter, length)
    out = []
    for line in lines:
        pdc = ocl.PathDropCutter()
        pdc.setSTL(stl)
        pdc.setCutter(cutter)
        pdc.setZ(zmin)
        pdc.setSampling(SAMPLING)
        path = ocl.Path()
        for a, b in zip(line[:-1], line[1:]):
            path.append(ocl.Line(ocl.Point(float(a[0]), float(a[1]), 0.0), ocl.Point(float(b[0]), float(b[1]), 0.0)))
        pdc.setPath(path)
        pdc.run()
        pts = [(p.x, p.y, p.z) for p in pdc.getCLPoints()]
        if len(pts) >= 2:
            out.append(_simplify(pts))
    return out


def _simplify(pts, tol=0.002):
    """Retire les points alignés (à ``tol`` près) : moins de commandes, même trajet."""
    if len(pts) < 3:
        return pts
    keep = [pts[0]]
    for i in range(1, len(pts) - 1):
        a, b, c = keep[-1], pts[i], pts[i + 1]
        ab = [b[k] - a[k] for k in range(3)]
        ac = [c[k] - a[k] for k in range(3)]
        lac = math.sqrt(sum(v * v for v in ac))
        if lac < 1e-9:
            continue
        cross = [ab[1] * ac[2] - ab[2] * ac[1], ab[2] * ac[0] - ab[0] * ac[2], ab[0] * ac[1] - ab[1] * ac[0]]
        if math.sqrt(sum(v * v for v in cross)) / lac > tol:
            keep.append(b)
    keep.append(pts[-1])
    return keep


def order_passes(passes):
    """Ordre glouton (plus proche voisin, passe retournée si besoin) pour raccourcir les liaisons."""
    left = list(passes)
    out = []
    pos = None
    while left:
        if pos is None:
            best, rev = 0, False
        else:
            best, rev, dmin = 0, False, float("inf")
            for i, p in enumerate(left):
                for r, q in ((False, p[0]), (True, p[-1])):
                    d = (q[0] - pos[0]) ** 2 + (q[1] - pos[1]) ** 2
                    if d < dmin:
                        best, rev, dmin = i, r, d
        p = left.pop(best)
        if rev:
            p = list(reversed(p))
        out.append(p)
        pos = p[-1]
    return out


def pencil_passes(shapes, diameter, ref_diameter, stepover, threshold=0.02, max_slope_deg=90.0,
                  resolution=DEFAULT_RESOLUTION):
    """Passes de reprise des angles ``[[(x, y, z)]]`` et un résumé ``{"cells", "gain_max"}``."""
    from . import sim

    np = _np()
    if ref_diameter <= diameter:
        raise UserError("pencil: the reference tool ({ref} mm) must be larger than the pencil tool ({d} mm)",
                        ref="%g" % ref_diameter, d="%g" % diameter)
    bb = None
    for s in shapes:
        bb = s.BoundBox if bb is None else bb.united(s.BoundBox)
    margin = ref_diameter / 2.0 + 1.0
    res = resolution
    while ((bb.XLength + 2 * margin) / res) * ((bb.YLength + 2 * margin) / res) > MAX_CELLS:
        res *= 1.25
    grid = sim.ZMap(bb.XMin - margin, bb.YMin - margin, bb.XMax + margin, bb.YMax + margin, bb.ZMax, res)
    H = sim.model_heights(grid, shapes)
    inside = np.isfinite(H)
    H = np.where(inside, H, bb.ZMin)
    tips = tip_heights(H, diameter / 2.0, res)
    zone, gain = corner_zone(H, res, ref_diameter / 2.0, diameter / 2.0, threshold, max_slope_deg, inside, tips)
    lines = [_resample(l, 0.5) for l in pass_lines(zone, grid.xs, grid.ys, stepover, tips)]
    passes = drop_ball(shapes, lines, diameter, bb.ZMin - 1.0) if lines else []
    info = {"cells": int(zone.sum()), "gain_max": float(gain[zone].max()) if zone.any() else 0.0,
            "resolution": res}
    return order_passes(passes), info


def passes_to_commands(passes, clearance, safe, horiz_feed, vert_feed):
    import Path

    cmds = []
    for p in passes:
        x, y, z = p[0]
        cmds.append(Path.Command("G0", {"Z": clearance}))
        cmds.append(Path.Command("G0", {"X": x, "Y": y}))
        cmds.append(Path.Command("G0", {"Z": max(safe, z)}))
        cmds.append(Path.Command("G1", {"X": x, "Y": y, "Z": z, "F": vert_feed}))
        for x, y, z in p[1:]:
            cmds.append(Path.Command("G1", {"X": x, "Y": y, "Z": z, "F": horiz_feed}))
    return cmds


# -- opération FreeCAD -------------------------------------------------------------------------------------

import Path.Op.Base as PathOp  # noqa: E402  (FreeCAD CAM : chargé seulement dans FreeCAD)


class ObjectPencil(PathOp.ObjectOp):
    """Opération ``pencil`` (proxy enregistré dans le document : classe au niveau du module)."""

    def opFeatures(self, obj):
        return (PathOp.FeatureTool | PathOp.FeatureDepths | PathOp.FeatureHeights | PathOp.FeatureBaseFaces
                | PathOp.FeatureCoolant)

    def initOperation(self, obj):
        obj.addProperty("App::PropertyLength", "ReferenceDiameter", "Pencil",
                        "Diameter of the ball used by the previous finishing (0 = 3 x this tool)")
        obj.addProperty("App::PropertyPercent", "StepOver", "Pencil", "Distance between passes, % of the tool diameter")
        obj.addProperty("App::PropertyDistance", "Threshold", "Pencil", "Ignore corners leaving less than this")
        obj.addProperty("App::PropertyAngle", "MaxSlope", "Pencil", "Ignore corners steeper than this angle")
        obj.addProperty("App::PropertyString", "Report", "Pencil", "Last computation")
        obj.ReferenceDiameter = 0.0
        obj.StepOver = 25
        obj.Threshold = 0.02
        obj.MaxSlope = 90.0

    def opExecute(self, obj):
        # objets choisis (Base) ou toute la pièce ; la reprise porte sur l'objet entier
        objs = [o for o, _subs in (obj.Base or [])] or list(self.model)
        shapes = [m.Shape for m in objs if getattr(m, "Shape", None) is not None]
        d = 2.0 * self.radius
        ref = float(obj.ReferenceDiameter.Value) or 3.0 * d
        step = d * max(1, min(100, int(obj.StepOver))) / 100.0
        passes, info = pencil_passes(shapes, d, ref, step, float(obj.Threshold.Value), float(obj.MaxSlope.Value))
        obj.Report = "%d pass(es), %d cells, up to %.2f mm taken, grid %.2f mm" % (
            len(passes), info["cells"], info["gain_max"], info["resolution"])
        if not passes:
            FreeCAD.Console.PrintWarning("CAM2027 %s: no inner corner left by the reference tool\n" % obj.Label)
            return
        self.commandlist.extend(passes_to_commands(passes, obj.ClearanceHeight.Value, obj.SafeHeight.Value,
                                                   self.horizFeed, self.vertFeed))


def Create(name, obj=None, parentJob=None):
    if obj is None:
        obj = FreeCAD.ActiveDocument.addObject("Path::FeaturePython", name)
    obj.Proxy = ObjectPencil(obj, name, parentJob)
    return obj


def __getattr__(name):
    if name == "Command":
        from ..gui import flatpage

        return flatpage.command(KIND)
    raise AttributeError(name)
