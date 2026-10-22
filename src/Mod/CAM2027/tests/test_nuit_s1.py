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


if __name__ == "__main__":
    unittest.main()
