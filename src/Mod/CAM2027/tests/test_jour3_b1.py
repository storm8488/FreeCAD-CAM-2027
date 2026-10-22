# SPDX-License-Identifier: LGPL-2.1-or-later
"""Flux B1 du jour 3 : bugs et optimisations de la génération des parcours."""

import os
import tempfile
import unittest

import FreeCAD
import Part

from cam2027.project import sim
from cam2027.project.project import Project
from cam2027.tools.library import starter_library


def make_stacked(path):
    """Deux corps empilés comme le chauffage Vz330 : un socle de 40 x 40 x 20 creusé d'une cavité de 20 x 20
    sur 15 mm, fermée par un couvercle de 40 x 30 x 5 posé dessus (Z 20 à 25)."""
    base = Part.makeBox(40, 40, 20).cut(Part.makeBox(20, 20, 15, FreeCAD.Vector(10, 10, 5)))
    lid = Part.makeBox(40, 30, 5, FreeCAD.Vector(0, 0, 20))
    Part.makeCompound([base, lid]).exportStep(path)


class TestMultiBodySurface(unittest.TestCase):
    """Finition 3D d'une pièce à plusieurs corps : FreeCAD fait le « drop-cutter » corps par corps, chacun seul.
    Sur le socle, la boule descendait dans la cavité à travers le couvercle (entaille de 41 mm sur le
    chauffage Vz330 de l'utilisateur)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="cam2027-b1-")
        cls.step = os.path.join(cls.tmp, "stacked.step")
        make_stacked(cls.step)
        FreeCAD.ConfigSet("SuppressRecomputeRequiredDialog", "True")

    def _run(self, kind, params):
        lib = starter_library()
        proj = Project.create("B1" + kind, lib)
        proj.import_model(self.step)
        models = proj.model_candidates()
        self.assertEqual(len(models), 2)
        proj.create_job(models, stock={"kind": "box_margins", "xy": 2.0, "z_top": 1.0, "z_bottom": 0.0})
        ball = lib.search("6 mm ball end mill")[0]
        asm = lib.assemblies_for_tool(ball.id)[0]
        clones = list(proj.job.Model.Group)
        op, _rec = proj.add_operation(kind, kind, asm.id, ball.presets[0].id, base=[(m, []) for m in clones],
                                      params=params)
        proj.compute()
        return proj, op

    def test_surface_does_not_dive_under_the_lid(self):
        proj, op = self._run("surface3d", {"StepOver": 50, "CutPattern": "ZigZag", "SampleInterval": 1.0})
        segs, _pos = sim.path_segments(op.Path.Commands)
        cuts = [(p0, p1) for rapid, p0, p1 in segs if not rapid]
        self.assertTrue(cuts)
        # sous le couvercle (Y 3 à 27, X 3 à 37 : boule entière sous lui), rien ne descend sous son dessus
        low = [min(p0[2], p1[2]) for p0, p1 in cuts
               if all(3.0 < p[0] < 37.0 and 3.0 < p[1] < 27.0 for p in (p0, p1))]
        self.assertTrue(low)
        self.assertGreater(min(low), 25.0 - 0.05)
        report = proj.material_check()
        self.assertLess(report["gouge_max"] or 0.0, 0.05)
        # une seule zone : le couvercle n'est pas balayé une seconde fois pour lui-même
        self.assertNotIn("Transition to base", op.Path.toGCode())

    def test_waterline_does_not_dive_under_the_lid(self):
        proj, op = self._run("waterline", {"LayerMode": "Multi-pass", "StepDown": 5.0, "SampleInterval": 1.0})
        segs, _pos = sim.path_segments(op.Path.Commands)
        cuts = [(p0, p1) for rapid, p0, p1 in segs if not rapid]
        self.assertTrue(cuts)
        low = [min(p0[2], p1[2]) for p0, p1 in cuts
               if all(3.0 < p[0] < 37.0 and 3.0 < p[1] < 27.0 for p in (p0, p1))]
        self.assertFalse([z for z in low if z < 25.0 - 0.05])
        report = proj.material_check()
        self.assertLess(report["gouge_max"] or 0.0, 0.05)


if __name__ == "__main__":
    unittest.main()
