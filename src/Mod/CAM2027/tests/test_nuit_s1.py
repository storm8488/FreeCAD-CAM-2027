# SPDX-License-Identifier: LGPL-2.1-or-later
"""Nuit 2, flux S1 « Matière et fonds » : reprise de matière, finition des zones plates, reprise des angles,
découpe de parcours sans recalcul."""

import os
import tempfile
import time
import unittest

import FreeCAD
import Part

from cam2027.tools.library import starter_library
from cam2027.project.project import Project
from cam2027.project.machine import MachineProfile


def _machine():
    return MachineProfile("test", controller="grbl", post_processor="grbl",
                          post_processor_args="--no-show-editor --precision=3")


def add_tool(lib, name, tool_type, diameter, feed=900.0):
    """Ajoute un outil (un préréglage, un assemblage) à la bibliothèque ; retourne (outil, id d'assemblage)."""
    from cam2027.tools.model import ToolDefinition, CuttingPreset, ToolAssembly

    holder = next(iter(lib.holders.values()))
    tool = lib.add_tool(ToolDefinition(name, tool_type, dict(diameter=diameter, shank_diameter=max(3.0, diameter),
                                                             overall_length=50, flute_length=max(6.0, 3 * diameter)),
                                       flute_count=2))
    tool.add_preset(CuttingPreset("Test", usage="finishing", material="wood", spindle_rpm=18000, feed_mm_min=feed,
                                  plunge_feed_mm_min=feed / 3.0, axial_engagement_mm=diameter / 2.0,
                                  radial_engagement_mm=diameter * 0.3))
    number = 1 + max(a.output.tool_number for a in lib.assemblies.values())
    asm = lib.add_assembly(ToolAssembly("T%d %s" % (number, name), tool.id, holder.id, stickout=35.0,
                                        output={"tool_number": number, "manual_tool_change": True}))
    return tool, asm.id


def make_grooved_plate(path):
    """Plaque 60x40x10 : poche 30x20 de 4 mm (angles vifs) et rainure étroite 3,4 x 24 de 3 mm."""
    plate = Part.makeBox(60, 40, 10)
    pocket = Part.makeBox(30, 20, 4, FreeCAD.Vector(5, 10, 6))
    groove = Part.makeBox(3.4, 24, 3, FreeCAD.Vector(46, 8, 7))
    shape = plate.cut(pocket).cut(groove).removeSplitter()
    shape.exportStep(path)
    return shape


def cut_points(path):
    pos, pts = {}, []
    for c in path.Commands:
        for k in "XYZ":
            if k in c.Parameters:
                pos[k] = c.Parameters[k]
        if c.Name in ("G1", "G2", "G3") and len(pos) == 3:
            pts.append((pos["X"], pos["Y"], pos["Z"]))
    return pts


class TestRestMachining(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="cam2027-s1-")
        cls.step = os.path.join(cls.tmp, "grooved.step")
        make_grooved_plate(cls.step)
        FreeCAD.ConfigSet("SuppressRecomputeRequiredDialog", "True")

    def test_rest_after_roughing(self):
        """Ébauche adaptative Ø6 puis reprise Ø3 : seules la rainure et les angles de la poche sont usinés."""
        from cam2027.project import rest

        lib = starter_library()
        proj = Project.create("Rest test", lib, _machine())
        part = proj.import_model(self.step, label="Grooved").objects[0]
        proj.create_job([part], stock={"kind": "box_margins", "xy": 2.0, "z_top": 0.0, "z_bottom": 0.0})
        e6 = lib.search("6 mm flat end mill")[0]
        e3 = lib.search("3 mm flat end mill")[0]
        from cam2027.project import operations as opsmod

        clone = proj.job.Model.Group[0]
        groups = dict((round(z, 2), g) for z, g in opsmod.floor_groups(opsmod.auto_geometry("adaptive", [clone])))
        self.assertEqual(sorted(groups), [6.0, 7.0])
        params = {"StepDown": 2.0, "StepOver": 30}
        a6, a3 = lib.assemblies_for_tool(e6.id)[0].id, lib.assemblies_for_tool(e3.id)[0].id
        rough, _r = proj.add_operation("adaptive", "Roughing 6", a6, e6.presets[0].id, base=groups[6.0], params=params)
        rop, _r2 = proj.add_operation("adaptive", "Rest 3", a3, e3.presets[0].id, base=groups[6.0], params=params)
        gop, _r3 = proj.add_operation("adaptive", "Rest 3 groove", a3, e3.presets[0].id, base=groups[7.0], params=params)
        with self.assertRaises(Exception):
            rest.set_rest(proj, rough)  # aucune opération avant : refus
        proj.compute()
        full = cut_points(rop.Path)
        self.assertGreater(len(full), 100)
        rep_full = proj.material_check()
        dress = rest.set_rest(proj, rop, ignore_below=0.1)
        self.assertEqual([o.Name for o in dress.Previous], [rough.Name])
        gdress = rest.set_rest(proj, gop)
        t0 = time.time()
        proj.compute()
        elapsed = time.time() - t0
        self.assertEqual(len(cut_points(gdress.Path)), len(cut_points(gop.Path)))  # rainure intacte : tout est gardé
        kept = cut_points(dress.Path)
        self.assertGreater(len(kept), 10)
        self.assertLess(len(kept), len(full))
        # chaque point de coupe gardé est dans la rainure ou près d'un angle de la poche
        corners = [(5, 10), (35, 10), (5, 30), (35, 30)]
        for x, y, z in kept:
            in_groove = 46 - 0.01 <= x <= 49.4 + 0.01 and 8 - 0.01 <= y <= 32 + 0.01
            near_corner = any(abs(x - cx) < 4.5 and abs(y - cy) < 4.5 for cx, cy in corners)
            self.assertTrue(in_groove or near_corner, (x, y, z))
        rep = proj.material_check()
        self.assertLess(rep["gouge_max"], 0.03, rep)
        self.assertEqual(rep["rapid_hits"], 0, rep)
        # même matière finale qu'avec la reprise complète (à la tolérance près), pour bien moins de coupe
        removed_rest = rep["removed_volume"]
        self.assertAlmostEqual(removed_rest, rep_full["removed_volume"], delta=0.02 * rep_full["removed_volume"])
        self.assertLess(rep["leftover_max"], rep_full["leftover_max"] + 0.05)
        print("rest: %d of %d cut points kept, compute %.1f s, %s" % (len(kept), len(full), elapsed, dress.Report))
        proj.close()


def _even_odd(shape, P):
    """Points ``P`` (n, 2) dans ``shape`` (faces planes) : règle pair-impair sur tous les contours."""
    import numpy as np
    from cam2027.project import trim

    inside = np.zeros(len(P), dtype=bool)
    for w in shape.Wires:
        pts = [(v.x, v.y) for v in w.discretize(Deflection=0.01)]
        if len(pts) >= 3:
            inside ^= trim.polygon_keep(pts)(P)
    return inside


def floor_cells(zmap, face, radius):
    """Hauteurs des colonnes de ``face`` que la fraise atteint (disque de rayon ``radius`` moins une demi-cellule
    autour des centres permis : la face réduite du rayon) ; [] si la zone est plus étroite que la fraise."""
    import numpy as np
    from scipy import ndimage
    from cam2027.project import flatfinish

    reach = flatfinish.inset(face, radius)
    if reach is None:
        return []
    X, Y = np.meshgrid(zmap.xs, zmap.ys, indexing="ij")
    P = np.stack([X.ravel(), Y.ravel()], axis=1)
    centers = _even_odd(reach, P).reshape(X.shape)
    for w in reach.Wires:  # zone plus fine qu'une cellule : ses contours comptent
        for v in w.discretize(Distance=0.05):
            i, j = int((v.x - zmap.x0) // zmap.res), int((v.y - zmap.y0) // zmap.res)
            if 0 <= i < zmap.nx and 0 <= j < zmap.ny:
                centers[i, j] = True
    n = int((radius - zmap.res) // zmap.res)
    if n > 0:
        k = np.arange(-n, n + 1)
        disc = (k[:, None] ** 2 + k[None, :] ** 2) <= n * n
        covered = ndimage.binary_dilation(centers, structure=disc)
    else:
        covered = centers
    covered &= _even_odd(face, P).reshape(X.shape)
    return [float(v) for v in zmap.top[covered]]


class TestFlatFinishing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="cam2027-s1f-")
        cls.step = os.path.join(cls.tmp, "grooved.step")
        make_grooved_plate(cls.step)
        FreeCAD.ConfigSet("SuppressRecomputeRequiredDialog", "True")

    def test_flats_of_grooved_plate(self):
        """Dessus, fond de poche et fond de rainure finis chacun à sa hauteur exacte, fraise contenue, sans entaille."""
        from cam2027.project import operations as opsmod, flatfinish

        lib = starter_library()
        proj = Project.create("Flat test", lib, _machine())
        part = proj.import_model(self.step, label="Grooved").objects[0]
        proj.create_job([part], stock={"kind": "box_margins", "xy": 2.0, "z_top": 0.0, "z_bottom": 0.0})
        clone = proj.job.Model.Group[0]
        base = opsmod.auto_geometry("flat3d", [clone])
        regions = flatfinish.flat_regions(base)
        self.assertEqual([round(z, 3) for z, _f in regions], [10.0, 7.0, 6.0])
        e3 = lib.search("3 mm flat end mill")[0]
        op, rec = proj.add_operation("flat3d", "Flats", lib.assemblies_for_tool(e3.id)[0].id, e3.presets[0].id,
                                     base=base, params={"StepOver": 40})
        self.assertEqual(rec["ignored_params"], [])
        t0 = time.time()
        res = proj.compute()
        elapsed = time.time() - t0
        self.assertTrue(res[0]["valid"] and res[0]["commands"] > 50, res)
        self.assertEqual(proj.operation_state(op), "computed")
        pts = cut_points(op.Path)
        self.assertEqual(sorted(set(round(p[2], 4) for p in pts)), [6.0, 7.0, 10.0])
        # fraise contenue : chaque point de coupe est dans sa zone plate réduite du rayon
        faces = {round(z, 3): flatfinish._merged(f) for z, f in regions}
        allowed = {z: flatfinish.inset(f, 1.5 - 0.01) for z, f in faces.items()}
        for x, y, z in pts[::5]:
            self.assertTrue(allowed[round(z, 3)].isInside(FreeCAD.Vector(x, y, z), 1e-3, True), (x, y, z))
        rep = proj.material_check()
        self.assertLess(rep["gouge_max"], 0.03, rep)
        zmap = proj.last_zmap
        for z, face in faces.items():
            cells = floor_cells(zmap, face, 1.5)
            self.assertGreater(len(cells), 3, z)
            worst = max(abs(c - z) for c in cells)
            self.assertLess(worst, 0.02, (z, worst, len(cells)))
        print("flat: %d cut points, %d commands, compute %.1f s, %s" % (len(pts), res[0]["commands"], elapsed, op.Report))
        proj.close()

    def test_holed_floor_inset(self):
        """Fond percé (anneau) : la zone réduite reste dans la face et diminue (OpenCascade la grossissait)."""
        from cam2027.project import flatfinish

        ring = Part.Face(Part.Wire(Part.makePolygon([FreeCAD.Vector(x, y, 5) for x, y in
                                                     ((0, 0), (8, 0), (8, 8), (0, 8), (0, 0))])))
        ring = ring.cut(Part.Face(Part.Wire(Part.makeCircle(2.5, FreeCAD.Vector(4, 4, 5))))).Faces[0]
        for d in (0.3, 0.5, 0.7):
            inner = flatfinish.inset(ring, d)
            self.assertIsNotNone(inner, d)
            self.assertLess(inner.Area, ring.Area)
            for w in inner.Wires:
                for p in w.discretize(Deflection=0.05):
                    self.assertTrue(ring.isInside(p, 1e-3, True), (d, p))
        self.assertEqual(len(flatfinish.inset(ring, 1.0).Faces), 4)  # anneau de 1,5 mm : seuls les 4 coins restent
        self.assertIsNone(flatfinish.inset(ring, 1.6))

    def test_dome_has_no_flat(self):
        """Dôme seul (calotte sphérique) : aucune zone plate, refus clair."""
        from cam2027.project import operations as opsmod, flatfinish
        from cam2027.i18n import UserError

        step = os.path.join(self.tmp, "cap.step")
        Part.makeSphere(25, FreeCAD.Vector(0, 0, -15)).common(Part.makeBox(60, 60, 20, FreeCAD.Vector(-30, -30, 0))).exportStep(step)
        lib = starter_library()
        proj = Project.create("Flat dome", lib, _machine())
        part = proj.import_model(step, label="Cap").objects[0]
        proj.create_job([part], stock={"kind": "box_margins", "xy": 2.0, "z_top": 1.0, "z_bottom": 0.0})
        clone = proj.job.Model.Group[0]
        self.assertEqual(opsmod.auto_geometry("flat3d", [clone]), [])
        with self.assertRaises(UserError) as ctx:
            flatfinish.check_flats([clone])
        self.assertIn("no flat", str(ctx.exception))
        proj.close()


if __name__ == "__main__":
    unittest.main()
