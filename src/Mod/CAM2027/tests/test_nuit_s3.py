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


def make_two_pocket_part(path):
    """Plaque 80 x 60 x 10 avec deux poches rectangulaires (X 10..30 et 50..70, Y 15..45, profondeur 4)."""
    plate = Part.makeBox(80, 60, 10)
    for x in (10.0, 50.0):
        plate = plate.cut(Part.makeBox(20, 30, 4, FreeCAD.Vector(x, 15, 6)))
    plate.exportStep(path)
    return plate


def moves(path):
    """``[(nom, x, y, z)]`` des mouvements (positions modales)."""
    pos, out = {}, []
    for c in path.Commands:
        if c.Name in ("G0", "G1", "G2", "G3"):
            for k in "XYZ":
                if k in c.Parameters:
                    pos[k] = c.Parameters[k]
            out.append((c.Name,) + tuple(round(pos.get(k, float("nan")), 6) for k in "XYZ") + (
                tuple(round(c.Parameters.get(k, 0.0), 6) for k in "IJ") if c.Name in ("G2", "G3") else ()))
    return out


class TestKeepOut(unittest.TestCase):
    #: bride entre les deux poches, plus haute que le plan de dégagement
    CLAMP = (36.0, -10.0, 8.0, 80.0, 30.0)  # x, y, longueur, largeur, hauteur (posée sur la plaque à Z 10)

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="cam2027-s3k-")
        cls.step = os.path.join(cls.tmp, "two_pockets.step")
        make_two_pocket_part(cls.step)
        FreeCAD.ConfigSet("SuppressRecomputeRequiredDialog", "True")

    def _project(self, name):
        lib = starter_library()
        proj = Project.create(name, lib, machine())
        part = proj.import_model(self.step, label="Plate").objects[0]
        proj.create_job([part], stock={"kind": "box_margins", "xy": 2.0, "z_top": 0.0, "z_bottom": 0.0})
        clone = proj.job.Model.Group[0]
        floors = [n for n in (planar_face_at(clone, 6.0, 600.0),) if n]
        floors = ["Face%d" % i for i, f in enumerate(clone.Shape.Faces, 1)
                  if f.Surface.__class__.__name__ == "Plane" and abs(f.BoundBox.ZMax - 6.0) < 1e-6
                  and abs(f.BoundBox.ZMin - 6.0) < 1e-6]
        self.assertEqual(len(floors), 2)
        endmill = lib.search("6 mm flat end mill")[0]
        asm = lib.assemblies_for_tool(endmill.id)[0]
        op, _r = proj.add_operation("pocket", "Two pockets", asm.id, endmill.presets[0].id, base=[(clone, floors)],
                                    params={"StepDown": 2.0, "StepOver": 40})
        op2, _r = proj.add_operation("pocket", "Right pocket again", asm.id, endmill.presets[0].id,
                                     base=[(clone, [floors[0]])], params={"StepDown": 2.0, "StepOver": 40})
        proj.compute()
        return proj, lib, [op, op2]

    def _crossing_rapids(self, proj, boxes):
        from cam2027.project import sim, keepout

        hits = []
        pos = None
        for op in proj.operations():
            segs, pos = sim.path_segments(op.Path.Commands, pos)
            r = keepout._tool_radius(op)
            for rapid, p0, p1 in segs:
                if rapid and keepout.blocking_top(p0, p1, boxes, r, 0.0) is not None:
                    hits.append((op.Label, p0, p1))
        return hits

    def test_rapids_hop_over_clamp(self):
        """Bride entre deux poches : sans zone, des rapides la traversent ; zone active : plus aucun, le contrôle de
        collision des brides est OK et les mouvements de coupe sont identiques."""
        from cam2027.project import keepout

        proj, lib, ops = self._project("Keep-out clamp")
        x, y, l, w, h = self.CLAMP
        clamp = proj.add_clamp("Clamp middle", l, w, h, (x, y, 10.0))
        boxes = [(clamp.Label, clamp.Shape.BoundBox)]
        before = {op.Name: moves(op.Path) for op in ops}
        crossing = self._crossing_rapids(proj, boxes)
        self.assertTrue(crossing, "le cas d'essai doit avoir des rapides à travers la bride")
        rep = proj.material_check()
        self.assertEqual(rep["collisions"]["clamps"], "collision")
        t0 = time.time()
        keepout.configure(proj.doc, avoid_clamps=True)
        proj.compute()
        elapsed = time.time() - t0
        self.assertEqual(self._crossing_rapids(proj, boxes), [])
        for op in ops:
            cuts_before = [m for m in before[op.Name] if m[0] != "G0"]
            cuts_after = [m for m in moves(op.Path) if m[0] != "G0"]
            self.assertEqual(cuts_before, cuts_after, op.Label)
            self.assertEqual(list(getattr(op, keepout.VIOLATION_PROPERTY, [])), [])
        rep = proj.material_check()
        self.assertEqual(rep["collisions"]["clamps"], "ok", rep["collisions"]["events"])
        self.assertEqual(rep["gouge_max"], 0.0)
        self.assertEqual(rep["rapid_hits"], 0)
        top = max(c.Parameters.get("Z", 0) for op in ops for c in op.Path.Commands)
        self.assertGreaterEqual(top, 40.0 + keepout.DEFAULT_MARGIN - 1e-6)
        self.assertFalse([m for lvl, m in keepout.issues(proj) if lvl == "error"])
        print("keep-out: %d rapid(s) crossed the clamp before, recompute %.1f s" % (len(crossing), elapsed))
        proj.close()

    def test_drawn_zone_and_refused_cut(self):
        """Zone dessinée sur la poche de droite : la coupe qui y entre est refusée avec sa position, export bloqué ;
        zone retirée : plus d'erreur."""
        from cam2027.project import keepout
        from cam2027.project.project import ExportBlocked

        proj, lib, ops = self._project("Keep-out zone")
        zone = keepout.add_zone(proj.doc, 55.0, 25.0, 65.0, 35.0, 12.0, label="No-go")
        proj.compute()
        errs = keepout.issues(proj)
        self.assertTrue(errs)
        text = str(errs[0][1])
        self.assertIn("No-go", text)
        self.assertIn("Two pockets", text)
        with self.assertRaises(ExportBlocked):
            proj.export_gcode(os.path.join(self.tmp, "zone.nc"))
        keepout.remove_zone(proj.doc, zone)
        proj.compute()
        self.assertEqual(keepout.issues(proj), [])
        proj.close()

    def test_reroute_unit(self):
        """Rapide au ras d'une boîte : montée au dessus + marge, déplacement, descente ; départ inconnu relevé."""
        import Path
        from cam2027.project import keepout

        bb = FreeCAD.BoundBox(10, -5, 0, 20, 5, 20)
        cmds = [Path.Command("G0", {"Z": 5.0}), Path.Command("G0", {"X": 0.0, "Y": 0.0}),
                Path.Command("G1", {"Z": 1.0}), Path.Command("G0", {"Z": 5.0}),
                Path.Command("G0", {"X": 30.0, "Y": 0.0}), Path.Command("G1", {"Z": 1.0})]
        out, hits = keepout.reroute(cmds, [("box", bb)], 3.0, 2.0)
        self.assertEqual(hits, [])
        self.assertEqual(out[0].Parameters["Z"], 22.0)  # départ inconnu : au-dessus de toutes les zones
        names = [(c.Name, dict(c.Parameters)) for c in out]
        self.assertIn(("G0", {"X": 30.0, "Y": 0.0, "Z": 22.0}), names)
        self.assertEqual(out[-1].Name, "G1")
        # coupe à travers la boîte : signalée, jamais modifiée
        cmds = [Path.Command("G0", {"X": 0.0, "Y": 0.0, "Z": 5.0}), Path.Command("G1", {"X": 30.0, "Y": 0.0, "Z": 5.0})]
        out, hits = keepout.reroute(cmds, [("box", bb)], 3.0, 2.0)
        self.assertEqual(len(out), 2)
        self.assertEqual(hits[0][0], 2)
