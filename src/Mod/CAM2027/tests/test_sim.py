# SPDX-License-Identifier: LGPL-2.1-or-later
"""Contrôle matière (Z-map) : cas analytiques, puis projets réels (surfaçage juste / trop profond, dôme)."""

import math
import os
import tempfile
import unittest

import FreeCAD
import Part

from cam2027.project import sim
from cam2027.project.project import Project
from cam2027.project.machine import MachineProfile
from cam2027.tools.library import starter_library
from tests.test_pipeline import make_part, plate_top_face


def _cell(zmap, x, y):
    i = int((x - zmap.x0) / zmap.res)
    j = int((y - zmap.y0) / zmap.res)
    return i, j, zmap.xs[i], zmap.ys[j]


class FakeCommand(object):
    def __init__(self, name, **params):
        self.Name = name
        self.Parameters = params


class TestZMap(unittest.TestCase):
    def test_flat_groove(self):
        z = sim.ZMap(0, 0, 50, 50, 0.0, 0.25)
        tool = sim.ToolProfile("flat", 6.0)
        self.assertTrue(z.sweep((10, 25, -2), (40, 25, -2), tool))
        expected = 2.0 * (30 * 6 + math.pi * 9)  # rainure + deux demi-disques, 2 mm de profondeur
        self.assertAlmostEqual(z.removed_volume(), expected, delta=0.02 * expected)
        i, j, _x, _y = _cell(z, 25, 27.6)
        self.assertAlmostEqual(z.top[i, j], -2.0)
        i, j, _x, _y = _cell(z, 25, 28.4)
        self.assertAlmostEqual(z.top[i, j], 0.0)

    def test_ball_and_vbit_profiles(self):
        for kind, kw, lift in (("ball", {}, lambda d: 3 - math.sqrt(9 - d * d)),
                               ("cone", {"included_angle_deg": 90.0}, lambda d: d)):
            z = sim.ZMap(0, 0, 50, 50, 0.0, 0.25)
            tool = sim.ToolProfile(kind, 6.0, **kw)
            z.sweep((10, 25, -2), (40, 25, -2), tool)
            for dy in (0.0, 1.0, 1.9):
                i, j, _x, y = _cell(z, 25, 25 + dy)
                d = abs(y - 25)
                self.assertAlmostEqual(z.top[i, j], min(0.0, -2 + lift(d)), places=6, msg=(kind, dy))

    def test_bull_profile(self):
        tool = sim.ToolProfile("bull", 6.0, corner_radius=1.0)
        import numpy
        lift = tool.lift(numpy.array([0.0, 2.0, 2.5, 3.0]))
        self.assertAlmostEqual(lift[0], 0.0)
        self.assertAlmostEqual(lift[1], 0.0)
        self.assertAlmostEqual(lift[2], 1 - math.sqrt(1 - 0.25))
        self.assertAlmostEqual(lift[3], 1.0)

    def test_arc_and_rapid(self):
        cmds = [FakeCommand("G0", X=30.0, Y=20.0, Z=5.0), FakeCommand("G1", Z=-1.0),
                FakeCommand("G2", X=20.0, Y=10.0, I=-10.0, J=0.0)]
        segs, end = sim.path_segments(cmds)
        self.assertEqual(end, [20.0, 10.0, -1.0])
        arc = [s for s in segs if not s[0]][1:]
        self.assertGreater(len(arc), 20)
        for _r, _p0, p1 in arc:  # quart de cercle horaire de rayon 10 autour de (20, 20)
            self.assertAlmostEqual(math.hypot(p1[0] - 20, p1[1] - 20), 10.0, places=6)
            self.assertLessEqual(p1[1], 20.0 + 1e-9)
        z = sim.ZMap(0, 0, 50, 50, 0.0, 0.5)
        tool = sim.ToolProfile("flat", 3.0)
        z.sweep((5, 5, 10), (5, 5, -1), tool, rapid=True)  # descente rapide dans la matière
        self.assertEqual(z.rapid_hits, 1)

    def test_model_heights(self):
        z = sim.ZMap(-5, -5, 25, 25, 20.0, 0.5)
        h = sim.model_heights(z, [Part.makeBox(10, 10, 5), Part.makeSphere(4, FreeCAD.Vector(18, 18, 0))])
        i, j, _x, _y = _cell(z, 5, 5)
        self.assertAlmostEqual(h[i, j], 5.0)
        i, j, x, y = _cell(z, 18, 18)
        self.assertAlmostEqual(h[i, j], math.sqrt(16 - (x - 18) ** 2 - (y - 18) ** 2), delta=0.05)
        i, j, _x, _y = _cell(z, 12, 3)
        self.assertEqual(h[i, j], -float("inf"))


class TestMaterialCheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="cam2027-sim-")
        cls.step = os.path.join(cls.tmp, "plate.step")
        make_part(cls.step)
        FreeCAD.ConfigSet("SuppressRecomputeRequiredDialog", "True")

    def _machine(self):
        return MachineProfile("test", controller="grbl", post_processor="grbl",
                              post_processor_args="--no-show-editor --precision=3")

    def test_facing_ok_then_too_deep(self):
        """Surfaçage au dessus de la plaque : aucune entaille ; à 1 mm sous le dessus : entaille de 1 mm."""
        lib = starter_library()
        proj = Project.create("Sim facing", lib, self._machine())
        part = proj.import_model(self.step, label="Plate").objects[0]
        proj.create_job([part], stock={"kind": "box_margins", "xy": 2.0, "z_top": 1.0, "z_bottom": 0.0})
        clone = proj.job.Model.Group[0]
        endmill = lib.search("6 mm flat end mill")[0]
        op, _rec = proj.add_operation("millface", "Top facing", lib.assemblies_for_tool(endmill.id)[0].id,
                                      endmill.presets[0].id, base=[(clone, [plate_top_face(clone)])],
                                      params={"StepDown": 1.0, "FinalDepth": 10.0, "StepOver": 50,
                                              "ClearEdges": True})
        rep = proj.material_check()
        self.assertEqual(rep["simulated"], ["Top facing"])
        self.assertEqual((rep["skipped"], rep["approximations"], rep["rapid_hits"]), ([], [], 0))
        self.assertLess(rep["gouge_max"], 0.03, rep)
        stock_top = 84.0 * 64.0 * 1.0  # 1 mm de brut au-dessus de la plaque, marges 2 mm
        self.assertAlmostEqual(rep["removed_volume"], stock_top, delta=0.03 * stock_top)
        # la poche (fond à Z 4) n'est pas usinée : 6 mm de reste, dans la poche
        self.assertAlmostEqual(rep["leftover_max"], 6.0, delta=0.05)
        x, y, _z = rep["leftover_at"]
        self.assertTrue(15 <= x <= 65 and 15 <= y <= 45, rep["leftover_at"])
        proj.update_operation(op, {"FinalDepth": 9.0})
        rep2 = proj.material_check()
        self.assertAlmostEqual(rep2["gouge_max"], 1.0, delta=0.03)
        self.assertGreater(rep2["gouge_cells"], 1000)
        proj.close()

    def test_dome_finishing(self):
        """Finition 3D boule sur un dôme : aucune entaille, crêtes limitées."""
        step = os.path.join(self.tmp, "dome.step")
        plate = Part.makeBox(60, 40, 5)
        dome = Part.makeSphere(25.0, FreeCAD.Vector(30, 20, -15)).common(Part.makeBox(60, 40, 30, FreeCAD.Vector(0, 0, 5)))
        plate.fuse(dome).removeSplitter().exportStep(step)
        lib = starter_library()
        proj = Project.create("Sim dome", lib, self._machine())
        part = proj.import_model(step, label="Dome").objects[0]
        proj.create_job([part], stock={"kind": "box_margins", "xy": 2.0, "z_top": 1.0, "z_bottom": 0.0})
        clone = proj.job.Model.Group[0]
        ball = lib.search("6 mm ball end mill")[0]
        proj.add_operation("surface3d", "Dome finishing", lib.assemblies_for_tool(ball.id)[0].id, ball.presets[0].id,
                           base=[(clone, [])], params={"CutPattern": "ZigZag", "StepOver": 20, "SampleInterval": 0.5,
                                                       "BoundBox": "BaseBoundBox", "FinalDepth": 5.0})
        rep = proj.material_check()
        self.assertEqual(rep["simulated"], ["Dome finishing"])
        self.assertLess(rep["gouge_max"], 0.05, rep)
        self.assertGreater(rep["removed_volume"], 1000.0)
        self.assertLess(rep["leftover_mean"], 0.3, rep)
        proj.close()


if __name__ == "__main__":
    unittest.main()
