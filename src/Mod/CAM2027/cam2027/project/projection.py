# SPDX-License-Identifier: LGPL-2.1-or-later
"""Projection d'un parcours 2D sur la pièce 3D (« Project » de Fusion) : gravure, contour, V-carving.

L'opération de base est calculée à plat (FreeCAD) ; sa profondeur de départ ``StartDepth`` sert de plan de
référence ``Zref``. L'habillage « projeté » remplace chaque point de coupe ``(x, y, z)`` par
``(x, y, S(x, y) - (Zref - z))`` où ``S`` est la hauteur de la surface de la pièce sous l'axe de l'outil,
calculée par OpenCamLib (``BatchDropCutter`` avec une fraise cylindrique de 0,01 mm) : la profondeur demandée
est gardée sous la surface, V-carving compris (profondeur variable). Les segments sont rééchantillonnés
(intervalle d'échantillonnage) puis recoupés là où la surface s'écarte de la corde de plus de la tolérance :
le pas diminue sur les pentes et les courbures. Les rapides passent au-dessus du point le plus haut de la
pièce (même écart au plan de référence qu'à plat) ; un point hors de la pièce est relevé à ce niveau.

Comme les habillages FreeCAD, l'objet porte « Dressup » dans son nom et remplace l'opération dans le groupe
« Operations » du job (``dressups.base_operation`` le traverse).
"""

import math

from ..i18n import UserError

SUFFIX = "_DressupProject"
LABEL = "Projected on the part"
KINDS = ("engrave", "profile", "vcarve", "pocket2d", "slot", "chamfer")
DEFAULT_SAMPLE = 0.2
DEFAULT_TOLERANCE = 0.005
#: diamètre de la « fraise » OpenCamLib qui lit la surface sous l'axe
PROBE_DIAMETER = 0.01


def _np():
    import numpy

    return numpy


def is_projection(obj):
    return SUFFIX in obj.Name and hasattr(obj, "Base")


class SurfaceHeights(object):
    """Hauteur de la surface de la pièce sous un point XY (OpenCamLib), NaN hors de la pièce."""

    def __init__(self, shapes, deflection=0.005):
        from .scallop import make_stl, ocl_module

        self.stl = make_stl(shapes, deflection)
        self.cutter = ocl_module().CylCutter(PROBE_DIAMETER, 100.0)
        self.top = max(s.BoundBox.ZMax for s in shapes)

    def __call__(self, xs, ys):
        np = _np()
        from .scallop import ocl_module

        ocl = ocl_module()
        bdc = ocl.BatchDropCutter()
        bdc.setSTL(self.stl)
        bdc.setCutter(self.cutter)
        for x, y in zip(np.asarray(xs).tolist(), np.asarray(ys).tolist()):
            bdc.appendPoint(ocl.CLPoint(x, y, -1.0e6))
        bdc.run()
        z = np.array([p.z for p in bdc.getCLPoints()], dtype=float)
        z[z <= -1.0e6 + 1.0] = np.nan
        return z


def project_segments(segments, heights, zref, sample=DEFAULT_SAMPLE, tolerance=DEFAULT_TOLERANCE, max_depth=6):
    """Segments ``(rapid, p0, p1)`` à plat -> liste de mouvements ``(rapid, (x, y, z))`` projetés.

    Coupes (sous ``zref``) : ``z' = S(x, y) - (zref - z)`` ; au-dessus de ``zref`` (approches, retraits) :
    ``z' = S + (z - zref)`` pour une coupe, ``top + (z - zref)`` pour un rapide (au-dessus de toute la pièce)."""
    np = _np()
    top = heights.top
    plan = []
    for rapid, p0, p1 in segments:
        if rapid:
            plan.append(("rapid", [tuple(p1)]))
            continue
        n = max(1, int(math.ceil(math.hypot(p1[0] - p0[0], p1[1] - p0[1]) / sample)))
        t = np.arange(1, n + 1) / float(n)
        seg = [(p0[0] + (p1[0] - p0[0]) * u, p0[1] + (p1[1] - p0[1]) * u, p0[2] + (p1[2] - p0[2]) * u) for u in t]
        plan.append(("cut", [tuple(p0)] + seg))
    # hauteurs de toutes les extrémités en un lot, puis subdivisions là où la corde s'écarte de la surface
    cache = {}

    def lookup(points):
        todo = [p for p in points if (round(p[0], 6), round(p[1], 6)) not in cache]
        if todo:
            z = heights(np.array([p[0] for p in todo]), np.array([p[1] for p in todo]))
            for p, zv in zip(todo, z.tolist()):
                cache[(round(p[0], 6), round(p[1], 6))] = zv
        return [cache[(round(p[0], 6), round(p[1], 6))] for p in points]

    lookup([p for _k, ps in plan if _k == "cut" for p in ps])

    def mapped(p, s, rapid=False):
        x, y, z = p
        if rapid or s is None or not math.isfinite(s):
            return (x, y, top + (z - zref)) if z > zref - 1e-9 or rapid else (x, y, top)
        return (x, y, s + (z - zref))

    out = []
    for kind, ps in plan:
        if kind == "rapid":
            out.append((True, mapped(ps[0], None, rapid=True)))
            continue
        chain = list(ps)
        for _round in range(max_depth):
            s = lookup(chain)
            mids, idx = [], []
            for i in range(len(chain) - 1):
                a, b = chain[i], chain[i + 1]
                if math.hypot(b[0] - a[0], b[1] - a[1]) < 1e-4:
                    continue
                mids.append(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2))
                idx.append(i)
            if not mids:
                break
            sm = lookup(mids)
            refine = [k for k, (i, zm) in enumerate(zip(idx, sm))
                      if math.isfinite(zm) and math.isfinite(s[i]) and math.isfinite(s[i + 1])
                      and abs(zm - (s[i] + s[i + 1]) / 2.0) > tolerance]
            if not refine:
                break
            for k in reversed(refine):
                chain.insert(idx[k] + 1, mids[k])
        s = lookup(chain)
        for p, zs in zip(chain[1:], s[1:]):
            out.append((False, mapped(p, zs)))
    return out


def projected_commands(path_commands, heights, zref, horiz_feed=None, sample=DEFAULT_SAMPLE, tolerance=DEFAULT_TOLERANCE):
    """Commandes Path projetées (G0 / G1 ; arcs découpés) depuis les commandes à plat."""
    import Path

    from . import sim

    segments, _pos = sim.path_segments(path_commands)
    feeds = [c.Parameters["F"] for c in path_commands if "F" in c.Parameters and c.Name in ("G1", "G2", "G3", "G01")]
    feed = horiz_feed if horiz_feed is not None else (feeds[0] if feeds else None)
    out = []
    if segments:  # position de départ (le premier mouvement ne fait que la fixer) : au-dessus de toute la pièce
        x, y, z = segments[0][1]
        out.append(Path.Command("G0", {"Z": heights.top + max(z - zref, 0.0)}))
        out.append(Path.Command("G0", {"X": x, "Y": y}))
    for rapid, (x, y, z) in project_segments(segments, heights, zref, sample, tolerance):
        if rapid:
            out.append(Path.Command("G0", {"X": x, "Y": y, "Z": z}))
        else:
            params = {"X": x, "Y": y, "Z": z}
            if feed is not None:
                params["F"] = feed
            out.append(Path.Command("G1", params))
    return out


class ObjectProjection(object):
    """Habillage « Projeté sur la pièce » : ``Base`` = l'opération (ou l'habillage) calculée à plat."""

    def __init__(self, obj, base):
        obj.addProperty("App::PropertyLink", "Base", "Path", "The operation projected on the part")
        obj.addProperty("App::PropertyLength", "SampleInterval", "Projection", "Distance between surface samples along a pass")
        obj.addProperty("App::PropertyLength", "Tolerance", "Projection", "Maximum gap between a segment and the surface (finer steps on slopes)")
        obj.addProperty("App::PropertyDistance", "ReferenceZ", "Projection", "Flat level standing for the part surface (the start depth of the operation)")
        obj.addProperty("App::PropertyBool", "UseStartDepth", "Projection", "Take the start depth of the operation as reference level")
        obj.Base = base
        obj.SampleInterval = DEFAULT_SAMPLE
        obj.Tolerance = DEFAULT_TOLERANCE
        obj.UseStartDepth = True
        obj.Proxy = self

    def dumps(self):
        return None

    def loads(self, state):
        return None

    def onDocumentRestored(self, obj):
        pass

    def execute(self, obj):
        import Path

        from .dressups import base_operation

        base = obj.Base
        if base is None or not hasattr(base, "Path"):
            obj.Path = Path.Path()
            return
        op = base_operation(base)
        from PathScripts import PathUtils

        job = PathUtils.findParentJob(op)
        shapes = [m.Shape for m in job.Model.Group if getattr(m, "Shape", None) is not None and not m.Shape.isNull()]
        if not shapes:
            raise UserError("projection: the job has no part to project on")
        zref = float(op.StartDepth.Value) if obj.UseStartDepth and hasattr(op, "StartDepth") else float(obj.ReferenceZ.Value)
        if obj.UseStartDepth:
            obj.ReferenceZ = zref
        heights = SurfaceHeights(shapes)
        cmds = projected_commands(base.Path.Commands, heights, zref, sample=max(float(obj.SampleInterval.Value), 0.01),
                                  tolerance=max(float(obj.Tolerance.Value), 1e-4))
        if hasattr(op, "ClearanceHeight"):
            cmds = [Path.Command("G0", {"Z": heights.top + float(op.ClearanceHeight.Value) - zref})] + cmds \
                + [Path.Command("G0", {"Z": heights.top + float(op.ClearanceHeight.Value) - zref})]
        obj.Path = Path.Path(cmds)


def add_projection(project, op, sample=DEFAULT_SAMPLE, tolerance=DEFAULT_TOLERANCE):
    """Projette ``op`` (gravure, contour, V-carving...) sur la pièce du job ; retourne l'habillage."""
    import FreeCAD

    from . import dressups

    base_op = dressups.base_operation(op)
    rec = project.registry.get(base_op.Name) or {}
    if rec.get("kind") not in KINDS:
        raise UserError("projection on the part: only engraving, contour, V-carving, 2D pocket, slot and chamfer can be projected")
    if rec.get("index_deg") not in (None, 0, 0.0):
        raise UserError("projection on the part: not available on an indexed operation")
    job = project.job
    current = dressups.top_of(job, base_op)
    if any(is_projection(d) for d in [current] + dressups.dressup_chain(current)):
        raise UserError("{op} is already projected on the part", op=base_op.Label)
    doc = project.doc
    obj = doc.addObject("Path::FeaturePython", base_op.Name + SUFFIX)
    ObjectProjection(obj, current)
    obj.SampleInterval = float(sample)
    obj.Tolerance = float(tolerance)
    job.Proxy.addOperation(obj, current)
    obj.Label = "%s + %s" % (base_op.Label, "projected")
    job.Operations.Group = [o for o in job.Operations.Group if o.Name != current.Name]
    if FreeCAD.GuiUp and obj.ViewObject is not None:
        try:
            import Path.Dressup.Gui.RampEntry as Ramp

            obj.ViewObject.Proxy = Ramp.ViewProviderDressup(obj.ViewObject)
            current.ViewObject.Visibility = False
            obj.ViewObject.Visibility = True
        except Exception as exc:  # fournisseur de vue absent : l'habillage reste calculable
            FreeCAD.Console.PrintWarning("CAM2027: projection view provider: %s\n" % exc)
    doc.recompute()
    return obj


def remove_projection(project, op):
    """Retire la projection de ``op`` (l'opération revient à plat)."""
    from . import dressups

    base_op = dressups.base_operation(op)
    top = dressups.top_of(project.job, base_op)
    for d in [top] + dressups.dressup_chain(top):
        if is_projection(d):
            return dressups.remove_dressup(project.job, d)
    raise UserError("{op} is not projected on the part", op=base_op.Label)
