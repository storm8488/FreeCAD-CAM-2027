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

class TestDressups(unittest.TestCase):
    """Habillages sur la plaque des tests."""

    @classmethod
    def setUpClass(cls):
        from tests.test_pipeline import make_part

        cls.tmp = tempfile.mkdtemp(prefix="cam2027-b1d-")
        cls.step = os.path.join(cls.tmp, "plate.step")
        make_part(cls.step)
        FreeCAD.ConfigSet("SuppressRecomputeRequiredDialog", "True")

    def _profile(self, kind="profile", extra=None):
        from cam2027.gui.commands import default_params
        from cam2027.project import operations

        lib = starter_library()
        proj = Project.create("B1d", lib)
        proj.import_model(self.step)
        proj.create_job(proj.model_candidates(), stock={"kind": "box_margins", "xy": 2.0, "z_top": 1.0, "z_bottom": 0.0})
        tool = lib.search("6 mm flat end mill 2F")[0]
        asm = lib.assemblies_for_tool(tool.id)[0]
        preset = tool.presets[0]
        models = list(proj.job.Model.Group)
        base = operations.auto_geometry(kind, models)
        params = dict(default_params(kind, tool, preset.resolve(tool)), **(extra or {}))
        op, _rec = proj.add_operation(kind, kind, asm.id, preset.id,
                                      base=[(m, []) for m in models] if base is None else base, params=params)
        proj.compute()
        return proj, op

    def test_dogbones_on_pockets_in_both_cut_modes(self):
        """Poches au motif Décalage en opposition : FreeCAD réglait le côté des os pour un contour (« Right » sans
        Side ni Direction) et n'en mettait aucun ; le côté suit maintenant le sens de coupe. L'os dépasse des parois
        de r·(1 - 1/√2) = 0,88 mm au plus (coin à 90°, fraise de 6 mm) : c'est le but d'un dogbone, pas plus."""
        for kind in ("pocket", "pocket2d"):
            for mode in ("Climb", "Conventional"):
                proj, op = self._profile(kind, {"CutMode": mode, "OffsetPattern": "Offset", "ClearingPattern": "Offset"})
                bone, _ignored = proj.add_dressup(op, "dogbone")
                proj.compute()
                self.assertGreater(bone.Path.Size, op.Path.Size, (kind, mode))  # des os ont bien été ajoutés
                report = proj.material_check()
                self.assertLess(report["gouge_max"] or 0.0, 3.0 * (1.0 - 0.5 ** 0.5) + 0.05, (kind, mode))

    def test_dogbones_refused_on_zigzag_and_adaptive(self):
        """Zigzag (poche 3D par défaut) et adaptative : FreeCAD plante des os aux demi-tours des passes et aux
        coudes des trochoïdes, dans les parois quel que soit le côté (4 à 5 mm sur la plaque, 26 mm de haut sur le
        plateau à alvéoles) : refus expliqué."""
        from cam2027.i18n import UserError

        for kind, extra in (("pocket", {}), ("pocket2d", {"OffsetPattern": "ZigZag", "ClearingPattern": "ZigZag"}),
                            ("adaptive", {})):
            proj, op = self._profile(kind, extra)
            with self.assertRaises(UserError):
                proj.add_dressup(op, "dogbone")
            self.assertEqual(proj.dressups(op), [], kind)

    def test_tags_on_a_dressup_not_yet_computed(self):
        """Attaches ajoutées juste après une rampe (même validation de l'éditeur, sans recalcul entre les deux) :
        FreeCAD lisait le parcours vide de la rampe (« list index out of range »)."""
        proj, op = self._profile()
        proj.add_dressup(op, "ramp")
        tags, _ignored = proj.add_dressup(op, "tags")
        proj.compute()
        self.assertEqual(len(tags.Positions), 4)
        self.assertEqual(proj.operation_state(proj.job.Operations.Group[-1]), "computed")

    def test_clearing_pattern_editable(self):
        """FreeCAD 1.1 a renommé ``OffsetPattern`` des poches et du surfaçage en ``ClearingPattern`` : le motif de
        vidage n'était plus ni modifiable dans l'éditeur ni appliqué (paramètre ignoré)."""
        from cam2027.project import operations

        for kind in ("pocket", "pocket2d", "millface"):
            proj, op = self._profile(kind)
            names = [n for n in operations.STRATEGIES[kind]["params"] if n in op.PropertiesList]
            pattern = [n for n in names if n in ("OffsetPattern", "ClearingPattern")]
            self.assertEqual(len(pattern), 1, kind)
            self.assertEqual(operations.set_params(op, {pattern[0]: "Offset"}), [], kind)
            self.assertEqual(getattr(op, pattern[0]), "Offset", kind)

class TestParallelPocket2d(unittest.TestCase):
    """Poche 2D sur de nombreux fonds : niveaux découpés dans des processus, même G-code qu'en série."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="cam2027-b1p-")
        cls.step = os.path.join(cls.tmp, "tray.step")
        tray = Part.makeBox(70, 70, 12)
        for i in range(3):
            for j in range(3):
                tray = tray.cut(Part.makeBox(14, 14 + 2 * i, 9, FreeCAD.Vector(5 + 22 * i, 5 + 22 * j, 3)))
        tray.exportStep(cls.step)
        FreeCAD.ConfigSet("SuppressRecomputeRequiredDialog", "True")

    def _gcode(self):
        from cam2027.gui.commands import default_params
        from cam2027.project import operations

        lib = starter_library()
        proj = Project.create("B1p", lib)
        proj.import_model(self.step)
        proj.create_job(proj.model_candidates(), stock={"kind": "box_margins", "xy": 2.0, "z_top": 1.0, "z_bottom": 0.0})
        tool = lib.search("6 mm flat end mill 2F")[0]
        asm = lib.assemblies_for_tool(tool.id)[0]
        preset = tool.presets[0]
        base = operations.auto_geometry("pocket2d", list(proj.job.Model.Group))
        self.assertEqual(sum(len(subs) for _o, subs in base), 9)
        op, _rec = proj.add_operation("pocket2d", "pocket2d", asm.id, preset.id, base=base,
                                      params=default_params("pocket2d", tool, preset.resolve(tool)))
        proj.compute()
        return op.Path.toGCode()

    def test_same_gcode_as_serial(self):
        from cam2027.project import parallel_pocket

        used = []
        original = parallel_pocket.precompute_face_sections

        def recording(*args):
            cache = original(*args)
            used.append((len(cache), cache))
            return cache

        parallel_pocket.precompute_face_sections = recording
        try:
            parallel = self._gcode()
        finally:
            parallel_pocket.precompute_face_sections = original
        # 9 fonds préparés dans les processus, tous repris par FreeCAD (une entrée retirée par fond)
        self.assertEqual([(n, len(cache)) for n, cache in used], [(9, 0)])
        os.environ[parallel_pocket.ENV_SWITCH] = "0"
        try:
            serial = self._gcode()
        finally:
            del os.environ[parallel_pocket.ENV_SWITCH]
        self.assertGreater(len(serial), 1000)
        self.assertEqual(parallel, serial)

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
