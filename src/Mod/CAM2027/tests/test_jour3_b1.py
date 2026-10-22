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

    def test_auto_floors_ignore_floor_under_another_body(self):
        """Le fond de la cavité du socle (Z 5) est sous le couvercle, un autre corps : la poche et l'adaptative
        le vidaient à travers le couvercle."""
        from cam2027.project import operations

        lib = starter_library()
        proj = Project.create("B1floors", lib)
        proj.import_model(self.step)
        proj.create_job(proj.model_candidates(), stock={"kind": "box_margins", "xy": 2.0, "z_top": 1.0, "z_bottom": 0.0})
        models = list(proj.job.Model.Group)
        for kind in ("pocket", "adaptive", "pocket2d"):
            chosen = operations.auto_geometry(kind, models)
            zs = [obj.Shape.getElement(sub).BoundBox.ZMin for obj, subs in chosen for sub in subs]
            self.assertNotIn(5.0, [round(z, 3) for z in zs], kind)


    def test_parallel_waterline_same_as_serial(self):
        """Niveaux du Z constant calculés dans des processus : même G-code que FreeCAD en série."""
        from cam2027.project import parallel_waterline

        params = {"LayerMode": "Multi-pass", "StepDown": 2.0, "SampleInterval": 0.5}
        computed = []
        original = parallel_waterline.compute

        def recording(*args):
            computed.append(original(*args))
            return computed[-1]

        parallel_waterline.compute = recording
        try:
            _proj, op = self._run("waterline", params)
        finally:
            parallel_waterline.compute = original
        self.assertTrue(computed and all(r is not None for r in computed))  # vraiment en parallèle
        parallel = op.Path.toGCode()
        os.environ[parallel_waterline.ENV_SWITCH] = "0"
        try:
            _proj, op = self._run("waterline", params)
        finally:
            del os.environ[parallel_waterline.ENV_SWITCH]
        self.assertGreater(op.Path.Size, 100)
        self.assertEqual(parallel, op.Path.toGCode())

    def test_combine_faces_same_region_as_freecad(self):
        """Réunion des fonds (poche 2D, adaptative) : une découpe au lieu des fusions une à une, mêmes faces."""
        import Path.Geom as geom
        from cam2027.project import operations

        operations.patch_combine_faces()
        self.assertTrue(getattr(geom.combineHorizontalFaces, "cam2027_patched", False))  # code FreeCAD reconnu

        def floors():
            out = []
            for i in range(6):  # alvéoles disjointes, dont une avec un îlot
                f = Part.makePlane(8, 8, FreeCAD.Vector(12 * i, 0, 3))
                if i == 2:
                    f = f.cut(Part.makePlane(2, 2, FreeCAD.Vector(12 * i + 3, 3, 3)))
                out.append(f)
            out.append(Part.makePlane(8, 8, FreeCAD.Vector(4, 4, 3)))  # recouvre la première
            out.append(Part.makePlane(8, 8, FreeCAD.Vector(80, 0, 3)))  # touche la suivante
            out.append(Part.makePlane(8, 8, FreeCAD.Vector(88, 0, 3)))
            return out

        def key(faces):
            return sorted((round(f.Area, 6), len(f.Wires), tuple(round(v, 6) for v in (
                f.BoundBox.XMin, f.BoundBox.YMin, f.BoundBox.XMax, f.BoundBox.YMax))) for f in faces)

        import importlib

        fresh = importlib.reload(geom)  # fonction d'origine de FreeCAD
        try:
            expected = key(fresh.combineHorizontalFaces(floors()))
            operations.patch_combine_faces()
            got = key(geom.combineHorizontalFaces(floors()))
        finally:
            operations.patch_combine_faces()
        self.assertGreater(len(expected), 4)
        self.assertEqual(got, expected)

class TestSurfaceSpeed(unittest.TestCase):
    """Accélérations de la finition 3D : mêmes points que FreeCAD."""

    def test_simplify_same_points_as_freecad(self):
        import math
        import random

        from cam2027.project import operations

        rnd = random.Random(3)
        for n in (3, 40, 63, 64, 65, 500, 6000):
            # ligne de balayage : relief lisse, plats, marches et bruit d'OpenCamLib
            line = []
            for i in range(n):
                x = -150.0 + 300.0 * i / max(n - 1, 1)
                z = 5.0 * math.sin(x / 7.0) if x < 0 else (10.0 if x < 60 else 3.0)
                line.append(FreeCAD.Vector(x, 20.0, z + rnd.uniform(-2e-4, 2e-4)))
            for tol in (1e-4, 1e-3, 0.01):
                expected = _freecad_simplify(line, tol)
                got = operations.simplify_3d_line(line, tol)
                self.assertEqual([(v.x, v.y, v.z) for v in got], [(v.x, v.y, v.z) for v in expected], (n, tol))


def _freecad_simplify(line, tolerance):
    """Copie de ``PathUtils.simplify3dLine`` de FreeCAD 1.1.4 (référence, non patchée)."""
    stack = [(0, len(line) - 1)]
    results = []
    while stack:
        start, end = stack.pop()
        if end - start < 2:
            results.extend(line[start:end])
            continue
        index, distance = 0, 0.0
        for i in range(start + 1, end):
            d = line[i].distanceToLineSegment(line[start], line[end]).Length
            if d > distance:
                index, distance = i, d
        if distance > tolerance:
            stack.append((index, end))
            stack.append((start, index))
        else:
            results.append(line[start])
    results.append(line[-1])
    return results


if __name__ == "__main__":
    unittest.main()
