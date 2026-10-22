# SPDX-License-Identifier: LGPL-2.1-or-later
"""Flux S3 de la nuit 2 : recto-verso, zones interdites, imbrication par forme réelle, édition groupée."""

import os
import tempfile
import time
import unittest

import FreeCAD
import Part

from cam2027.tools.library import starter_library
from cam2027.project.project import Project
from cam2027.project.machine import MachineProfile
from cam2027.project import twosided


POCKET_A = (25.0, 30.0, 12.0, 3.0)  # centre x, y, rayon, profondeur depuis le dessus
POCKET_B = (57.0, 30.0, 10.0, 4.0)  # depuis le dessous


def make_two_sided_part(path):
    """Plaque 80 x 60 x 10 avec une poche ronde sur chaque face."""
    plate = Part.makeBox(80, 60, 10)
    xa, ya, ra, da = POCKET_A
    xb, yb, rb, db = POCKET_B
    shape = plate.cut(Part.makeCylinder(ra, da, FreeCAD.Vector(xa, ya, 10 - da))) \
        .cut(Part.makeCylinder(rb, db, FreeCAD.Vector(xb, yb, 0)))
    shape.exportStep(path)
    return shape


def planar_face_at(clone, z, area=None):
    for i, f in enumerate(clone.Shape.Faces, 1):
        if f.Surface.__class__.__name__ == "Plane" and abs(f.BoundBox.ZMin - z) < 1e-6 and abs(f.BoundBox.ZMax - z) < 1e-6:
            if area is None or abs(f.Area - area) < 1.0:
                return "Face%d" % i
    return None


def far_from_walls(h, cells=2):
    """Colonnes finies dont la hauteur est la même sur ``cells`` colonnes dans les 4 directions."""
    import numpy as np

    ok = np.isfinite(h)
    for k in range(1, cells + 1):
        for axis in (0, 1):
            for sign in (1, -1):
                shifted = np.roll(h, sign * k, axis=axis)
                ok &= np.isfinite(shifted) & (np.abs(shifted - h) < 1e-6)
    return ok


def machine():
    return MachineProfile("test", controller="grbl", post_processor="grbl",
                          post_processor_args="--no-show-editor --precision=3")


class TestTwoSided(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="cam2027-s3-")
        cls.step = os.path.join(cls.tmp, "twosided.step")
        make_two_sided_part(cls.step)
        FreeCAD.ConfigSet("SuppressRecomputeRequiredDialog", "True")

    def _project(self, name, axis="X"):
        lib = starter_library()
        proj = Project.create(name, lib, machine())
        part = proj.import_model(self.step, label="Plate").objects[0]
        proj.create_job([part], stock={"kind": "box_margins", "xy": 15.0, "z_top": 0.0, "z_bottom": 0.0})
        twosided.enable(proj, axis)
        return proj, lib

    def _pockets(self, proj, lib):
        import math

        endmill = lib.search("6 mm flat end mill")[0]
        asm = lib.assemblies_for_tool(endmill.id)[0]
        params = {"StepDown": 1.5, "StepOver": 40, "OffsetPattern": "Offset", "ClearingPattern": "Offset"}
        clone_a = twosided.jobs(proj)["A"].Model.Group[0]
        face_a = planar_face_at(clone_a, 10 - POCKET_A[3], math.pi * POCKET_A[2] ** 2)
        self.assertIsNotNone(face_a)
        op_a, _r = proj.add_operation("pocket", "Pocket A", asm.id, endmill.presets[0].id, base=[(clone_a, [face_a])],
                                      params=params)
        twosided.set_side(proj, "B")
        clone_b = proj.job.Model.Group[0]
        face_b = planar_face_at(clone_b, 10 - POCKET_B[3], math.pi * POCKET_B[2] ** 2)
        self.assertIsNotNone(face_b, "fond de la poche B vers le haut sur la pièce retournée")
        op_b, _r = proj.add_operation("pocket", "Pocket B", asm.id, endmill.presets[0].id, base=[(clone_b, [face_b])],
                                      params=params)
        return op_a, op_b, asm, endmill

    def test_flip_geometry(self):
        """La pièce de la face B est la pièce tournée de 180° autour de X par le centre du brut ; même brut."""
        proj, _lib = self._project("Two-sided flip")
        js = twosided.jobs(proj)
        self.assertEqual(twosided.current_side(proj), "A")
        a, b = js["A"].Stock.Shape.BoundBox, js["B"].Stock.Shape.BoundBox
        for k in ("XMin", "XMax", "YMin", "YMax", "ZMin", "ZMax"):
            self.assertAlmostEqual(getattr(a, k), getattr(b, k), places=6)
        pb = js["B"].Model.Group[0].Shape
        # la poche B (dessous, X 47..67) est en haut sur la face B, au même X, Y retourné (30 -> 30)
        top_b = pb.common(Part.makeBox(4, 4, 1, FreeCAD.Vector(55, 28, 9)))
        self.assertLess(top_b.Volume, 1e-6)  # vide : la poche B est ouverte vers le haut
        top_a = pb.common(Part.makeBox(4, 4, 1, FreeCAD.Vector(23, 28, 0)))
        self.assertLess(top_a.Volume, 1e-6)  # la poche A est maintenant en bas
        twosided.set_side(proj, "B")
        self.assertEqual(twosided.current_side(proj), "B")
        self.assertEqual(proj.job.Name, js["B"].Name)
        with self.assertRaises(Exception):
            twosided.enable(proj, "X")
        proj.close()
        proj, _lib = self._project("Two-sided flip Y", axis="Y")
        pb = twosided.jobs(proj)["B"].Model.Group[0].Shape.BoundBox
        sb = proj.stock_bounds()
        self.assertAlmostEqual(pb.XMin, sb["xmin"] + sb["xmax"] - 80.0, places=6)
        proj.close()

    def test_two_pockets_chained_check(self):
        """Une poche de chaque côté : les deux usinées, carte finale = pièce à 0,05 mm, aucune entaille, goujons
        sur l'axe, fiche avec les repères, un fichier par face."""
        from cam2027.project import sim

        np = sim._np()
        proj, lib = self._project("Two-sided pockets")
        op_a, op_b, asm, endmill = self._pockets(proj, lib)
        drill = lib.search("6 mm flat end mill")[0]
        dasm = lib.assemblies_for_tool(drill.id)[0]
        # goujons : hors de la pièce, sur l'axe, refus sinon
        with self.assertRaises(Exception):
            twosided.add_dowel_holes(proj, dasm.id, drill.presets[0].id, positions=[(-8.0, 20.0), (88.0, 20.0)])
        with self.assertRaises(Exception):
            twosided.add_dowel_holes(proj, dasm.id, drill.presets[0].id, positions=[(10.0, 30.0), (88.0, 30.0)])
        reg_op = twosided.add_dowel_holes(proj, dasm.id, drill.presets[0].id)
        positions = twosided.config(proj)["registration"]["positions"]
        self.assertEqual([round(p[1], 6) for p in positions], [30.0, 30.0])
        self.assertTrue(all(p[0] < 0 or p[0] > 80 for p in positions), positions)
        self.assertEqual(twosided.jobs(proj)["A"].Operations.Group[0].Name, reg_op.Name)
        self.assertEqual(twosided.current_side(proj), "B")  # l'ajout des goujons ne change pas de face
        t0 = time.time()
        rep = proj.material_check()
        elapsed = time.time() - t0
        ts = rep["two_sided"]
        self.assertEqual(ts["A"]["gouge_max"], 0.0, ts["A"])
        self.assertEqual(ts["B"]["gouge_max"], 0.0, ts["B"])
        self.assertIn("Pocket A", ts["A"]["simulated"])
        self.assertIn("Pocket B", ts["B"]["simulated"])
        self.assertEqual(ts["A"]["rapid_hits"], 0)
        self.assertEqual(ts["B"]["rapid_hits"], 0)
        import math

        vol_a = math.pi * POCKET_A[2] ** 2 * POCKET_A[3]
        vol_b = math.pi * POCKET_B[2] ** 2 * POCKET_B[3]
        self.assertGreater(ts["removed_volume_B"], 0.9 * vol_b)
        self.assertLess(ts["removed_volume_B"], 1.1 * vol_b)  # les trous de goujons déjà percés ne comptent pas
        top, bottom, part_top, part_bottom = twosided.final_part_maps(proj)
        zmap = proj.last_two_sided["zmap_A"]
        # colonnes de pièce à plus de 1 mm d'une paroi (dessus et dessous constants autour d'elles)
        inner = far_from_walls(part_top) & far_from_walls(part_bottom)
        self.assertGreater(int(inner.sum()), 10000)
        dtop = float(np.max(np.abs(top[inner] - part_top[inner])))
        dbot = float(np.max(np.abs(bottom[inner] - part_bottom[inner])))
        self.assertLess(dtop, 0.05, "dessus final")
        self.assertLess(dbot, 0.05, "dessous final")
        # les deux poches sont bien là : fond de A à 7, dessous de B à 4 (en repère A)
        i = int((POCKET_A[0] - zmap.x0) / zmap.res)
        j = int((POCKET_A[1] - zmap.y0) / zmap.res)
        self.assertAlmostEqual(float(top[i, j]), 7.0, places=2)
        i = int((POCKET_B[0] - zmap.x0) / zmap.res)
        self.assertAlmostEqual(float(bottom[i, j]), 4.0, places=2)
        # trous de goujons : débouchants, plus de matière dans leur colonne en face B
        px, py = positions[0]
        i, j = int((px - zmap.x0) / zmap.res), int((py - zmap.y0) / zmap.res)
        self.assertLess(float(zmap.top[i, j]), proj.stock_bounds()["zmin"])
        # export : un fichier par face, fiche avec les repères
        out = twosided.export(proj, os.path.join(self.tmp, "two.nc"))
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "two-A.nc")))
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "two-B.nc")))
        self.assertIn("dowel pins", out["B"]["sheet_text"])
        self.assertIn("Operations of side B: Pocket B", out["B"]["sheet_text"])
        self.assertNotIn("Pocket B", out["A"]["gcode"])
        self.assertIn("Pocket B", out["B"]["gcode"])
        self.assertFalse([m for lvl, m in out["A"]["issues"] + out["B"]["issues"] if lvl == "error"])
        self.assertEqual(twosided.current_side(proj), "B")
        print("two-sided check: %.1f s, removed A %.0f mm3, B %.0f mm3 (pockets %.0f / %.0f), final top %.3f bottom %.3f"
              % (elapsed, ts["A"]["removed_volume"], ts["removed_volume_B"], vol_a, vol_b, dtop, dbot))
        proj.close()

    def test_single_side_unchanged(self):
        """Un projet sans recto-verso garde le contrôle d'avant (pas de rapport ``two_sided``)."""
        lib = starter_library()
        proj = Project.create("One side", lib, machine())
        part = proj.import_model(self.step, label="Plate").objects[0]
        proj.create_job([part], stock={"kind": "box_margins", "xy": 2.0, "z_top": 0.0, "z_bottom": 0.0})
        self.assertFalse(twosided.is_two_sided(proj))
        self.assertEqual(twosided.all_operations(proj), [])
        proj.close()


if __name__ == "__main__":
    unittest.main()
