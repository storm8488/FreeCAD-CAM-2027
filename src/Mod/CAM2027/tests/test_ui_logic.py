# SPDX-License-Identifier: LGPL-2.1-or-later
"""Logique derrière l'interface (bugs trouvés par les scénarios utilisateur) : pièces détectées, maillages,
outils compatibles, géométrie automatique, fusion d'assemblage, contrôle mémorisé dans le document, messages."""

import json
import math
import os
import tempfile
import unittest

import FreeCAD
import Part

from cam2027 import i18n
from cam2027.project import operations as opsmod
from cam2027.project.project import Project
from cam2027.project.machine import MachineProfile
from cam2027.tools.library import starter_library
from tests.test_pipeline import make_part


class TestUiLogic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="cam2027-ui-")
        cls.step = os.path.join(cls.tmp, "plate.step")
        make_part(cls.step)
        FreeCAD.ConfigSet("SuppressRecomputeRequiredDialog", "True")

    def _project(self, name):
        return Project.create(name, starter_library(), MachineProfile(
            "test", controller="grbl", post_processor="grbl", post_processor_args="--no-show-editor --precision=3"))

    def test_tool_fits_strategy(self):
        lib = starter_library()
        by_type = {t.tool_type: t for t in lib.tools.values()}
        self.assertFalse(opsmod.tool_fits("vcarve", by_type["endmill"]))  # le bug : V-carving avec une fraise plate
        self.assertTrue(opsmod.tool_fits("vcarve", by_type["vbit"]))
        self.assertTrue(opsmod.tool_fits("drilling", by_type["endmill"]))  # perçage par plongée (Fusion)
        self.assertFalse(opsmod.tool_fits("drilling", by_type["ballend"]))
        self.assertTrue(opsmod.tool_fits("profile", by_type["endmill"]))
        self.assertFalse(opsmod.tool_fits("threadmill", by_type["endmill"]))
        self.assertLess(opsmod.tool_rank("surface3d", by_type["ballend"]), opsmod.tool_rank("surface3d", by_type["endmill"]))
        for kind in opsmod.STRATEGIES:  # chaque stratégie a au moins un outil de démarrage compatible
            self.assertTrue(any(opsmod.tool_fits(kind, t) for t in lib.tools.values()), kind)

    def test_auto_geometry(self):
        proj = self._project("Auto")
        part = proj.import_model(self.step).objects[0]
        proj.create_job([part])
        clone = proj.job.Model.Group[0]
        floors = opsmod.pocket_floor_faces(clone)  # plaque 80×60×10, poche au fond à Z 4
        self.assertTrue(floors)
        for name in floors:
            self.assertAlmostEqual(clone.Shape.getElement(name).BoundBox.ZMin, 4.0, places=6)
        tops = opsmod.top_faces(clone)
        self.assertTrue(tops)
        for name in tops:
            self.assertAlmostEqual(clone.Shape.getElement(name).BoundBox.ZMax, 10.0, places=6)
        self.assertEqual(opsmod.auto_geometry("adaptive", [clone]), [(clone, floors)])
        self.assertIsNone(opsmod.auto_geometry("profile", [clone]))  # toute la pièce
        box = proj.doc.addObject("Part::Feature", "Flat")
        box.Shape = Part.makeBox(10, 10, 10)
        self.assertEqual(opsmod.auto_geometry("pocket", [box]), [])  # rien de pertinent : l'interface le dit
        # fond sous un surplomb (rainure en T) : inaccessible par le dessus, la poche usinerait le surplomb
        V = FreeCAD.Vector
        tslot = Part.makeBox(40, 20, 20).cut(Part.makeBox(30, 20, 5, V(5, 0, 5))).cut(Part.makeBox(10, 20, 10, V(15, 0, 10)))
        tee = proj.doc.addObject("Part::Feature", "TSlot")
        tee.Shape = tslot
        self.assertEqual(opsmod.pocket_floor_faces(tee), [])
        proj.close()

    def test_pocket_floor_faces_fast_same_list(self):
        """Fonds de poche : le tri rapide (faces voisines) rend exactement la liste de l'intersection complète
        avec la pièce, sur un plateau avec surplomb, rampe, gradin et alvéoles rondes."""
        V = FreeCAD.Vector
        tray = Part.makeBox(120, 80, 20)
        for k in range(4):  # alvéoles carrées dégagées, à profondeurs variées
            tray = tray.cut(Part.makeBox(15, 15, 6 + 2 * k, V(5 + 20 * k, 5, 20 - 6 - 2 * k)))
        for k in range(3):  # alvéoles rondes (fond plan, paroi cylindrique)
            tray = tray.cut(Part.makeCylinder(6, 8, V(15 + 25 * k, 40, 12)))
        tray = tray.cut(Part.makeBox(20, 20, 10, V(90, 5, 10)))  # gradin : deux fonds étagés
        tray = tray.cut(Part.makeBox(10, 20, 5, V(90, 5, 5)))
        # rainure en T : fond sous surplomb (exclu), goulotte au-dessus (fond dégagé partiel exclu aussi)
        tray = tray.cut(Part.makeBox(30, 15, 4, V(5, 58, 6))).cut(Part.makeBox(10, 15, 10, V(15, 58, 10)))
        # fond partiellement couvert par une rampe inclinée (face non verticale au-dessus d'une partie du fond)
        tray = tray.cut(Part.makeBox(20, 15, 8, V(50, 58, 8)))
        ramp = Part.Face(Part.makePolygon([V(50, 58, 20), V(50, 58, 12), V(60, 58, 20), V(50, 58, 20)]))
        tray = tray.fuse(ramp.extrude(V(0, 15, 0))).removeSplitter()
        obj = type("Obj", (), {})()
        obj.Shape = tray

        def reference(o):  # algorithme d'origine : intersection complète de la colonne avec la pièce
            shape, out = o.Shape, []
            bb = shape.BoundBox
            for i, f in opsmod._horizontal_planes(shape):
                if not bb.ZMin + 1e-3 < f.BoundBox.ZMin < bb.ZMax - 1e-3:
                    continue
                above = f.copy()
                above.translate(V(0, 0, 1e-3))
                if above.extrude(V(0, 0, bb.ZMax - f.BoundBox.ZMin + 1.0)).common(shape).Volume > 1e-3:
                    continue
                out.append("Face%d" % i)
            return out

        expected = reference(obj)
        self.assertEqual(opsmod.pocket_floor_faces(obj), expected)
        zs = sorted(round(tray.getElement(n).BoundBox.ZMin, 3) for n in expected)
        self.assertEqual(zs, [5.0, 8.0, 10.0, 10.0, 12.0, 12.0, 12.0, 12.0, 14.0])  # ni le fond en T ni sous la rampe

    def test_model_candidates_and_mesh(self):
        import Mesh

        proj = self._project("Cand")
        stl = os.path.join(self.tmp, "box.stl")
        shape = Part.makeBox(30, 20, 10)
        pts, tris = shape.tessellate(0.1)
        Mesh.Mesh([[pts[a], pts[b], pts[c]] for a, b, c in tris]).write(stl)
        res = proj.import_model(stl, label="Box")
        self.assertEqual(res.kind, "solid")  # le bug : un STL fermé n'était pas usinable
        cands = proj.model_candidates()
        self.assertEqual([o.Label for o in cands], ["Box"])  # le solide, pas le maillage d'origine en double
        self.assertTrue(any(o.TypeId.startswith("Mesh::") and o.Label.startswith("Box") for o in proj.doc.Objects))
        proj.create_job(cands, stock={"kind": "box_margins", "xy": 2.0, "z_top": 1.0, "z_bottom": 0.0})
        proj.add_clamp("Clamp", 5, 5, 5, (40, 0, 0))
        self.assertEqual([o.Label for o in proj.model_candidates()], ["Box"])  # ni le brut, ni le clone, ni la bride
        proj.close()

    def test_merge_stacked_bodies(self):
        """Assemblage empilé : contourné corps par corps, chaque contour descend à travers l'autre corps."""
        proj = self._project("Merge")
        base = proj.doc.addObject("Part::Feature", "Base")
        base.Shape = Part.makeBox(80, 60, 10)
        top = proj.doc.addObject("Part::Feature", "Top")
        top.Shape = Part.makeBox(40, 30, 5, FreeCAD.Vector(10, 10, 10))
        proj.doc.recompute()
        merged = proj.merge_models([base, top], "Stack")
        self.assertEqual(len(merged.Shape.Solids), 1)
        self.assertAlmostEqual(merged.Shape.Volume, 80 * 60 * 10 + 40 * 30 * 5, places=3)
        proj.create_job([merged], stock={"kind": "box_margins", "xy": 2.0, "z_top": 0.0, "z_bottom": 0.0})
        lib = proj.library
        e = lib.search("6 mm flat end mill")[0]
        proj.add_operation("profile", "Outline", lib.assemblies_for_tool(e.id)[0].id, e.presets[0].id,
                           base=[(proj.job.Model.Group[0], [])], params={"StepDown": 5.0})
        rep = proj.material_check()
        self.assertLess(rep["gouge_max"], 0.05, rep)
        proj.close()

    def test_duplicate_import_does_not_crash_the_stock(self):
        """Le plantage du 2026-10-20 : fichier importé deux fois -> fusion des doublons = forme vide ->
        Stock.execute de FreeCAD bouclait jusqu'au débordement de pile."""
        from cam2027.i18n import UserError

        proj = self._project("Dup")
        step = os.path.join(self.tmp, "stack.step")
        Part.makeCompound([Part.makeBox(80, 60, 10), Part.makeBox(40, 30, 5, FreeCAD.Vector(10, 10, 10))]).exportStep(step)
        proj.import_model(step)
        res2 = proj.import_model(step)
        self.assertTrue(any("already imported" in str(w) for w in res2.warnings), res2.warnings)
        cands = proj.model_candidates()
        unique = proj.unique_bodies(cands)
        self.assertLess(len(unique), len(cands))  # les doublons sont reconnus
        twice = proj.merge_models(cands[:1] * 2)  # doublon exact : jamais de forme vide en retour
        self.assertTrue(twice is None or (twice.Shape.Solids and twice.Shape.BoundBox.isValid()))
        merged = proj.merge_models(unique)
        if merged is not None:
            self.assertTrue(merged.Shape.Solids and merged.Shape.BoundBox.isValid())
        empty = proj.doc.addObject("Part::Feature", "Empty")
        empty.Shape = Part.Shape()
        with self.assertRaises(UserError):  # refus explicite au lieu de la récursion du brut
            proj.create_job([empty])
        proj.create_job([merged] if merged is not None else unique,
                        stock={"kind": "box_margins", "xy": 2.0, "z_top": 0.0, "z_bottom": 0.0})
        self.assertTrue(proj.stock_bounds()["height"] > 0)
        proj.close()

    def test_mesh_model_does_not_crash_the_stock(self):
        """Les plantages du 2026-10-20 au soir : un STL resté maillage (ouvert, ou trop gros pour la conversion)
        passait au job ; le clone FreeCAD d'un maillage n'a pas de forme, le brut bouclait jusqu'au
        débordement de pile. Refus explicite, et le brut de FreeCAD ne boucle plus sur une boîte invalide."""
        import Mesh

        from cam2027.i18n import UserError
        from cam2027.project import stock as stockmod

        proj = self._project("Mesh")
        m = Mesh.createBox(40, 30, 10)
        m.removeFacets([0, 1])  # maillage ouvert : reste un maillage à l'import
        path = os.path.join(self.tmp, "open_box.stl")
        m.write(path)
        res = proj.import_model(path)
        meshes = [o for o in res.objects if o.TypeId.startswith("Mesh::")]
        if meshes:  # (après la correction de l'import, un maillage ouvert devient une surface : plus de maillage)
            with self.assertRaises(UserError):
                proj.create_job(meshes)
        self.assertFalse(proj.has_job)
        # garde de récursion : clone sans forme après la création du job (boîte invalide) = pas de plantage
        self.assertTrue(stockmod.PathStock.StockFromBase.execute.cam2027_guarded)
        part = proj.import_model(self.step).objects[0]
        proj.create_job([part], stock={"kind": "box_margins", "xy": 2.0, "z_top": 0.0, "z_bottom": 0.0})
        clone = proj.job.Model.Group[0]
        saved = clone.Shape
        clone.Shape = Part.Shape()
        proj.job.Stock.touch()
        proj.doc.recompute()  # avant la garde : débordement de pile ici
        clone.Shape = saved
        proj.job.Stock.touch()
        proj.doc.recompute()
        self.assertGreater(proj.stock_bounds()["height"], 0)
        proj.close()

    @unittest.skipUnless(os.path.isfile(os.path.join(os.path.expanduser("~"), "Downloads",
                                                     "Not So XL Male Nutcracker 26 (1).stl")),
                         "fichier de l'utilisateur absent")
    def test_user_big_stl_becomes_a_surface(self):
        """Le cas reel du 2026-10-20 au soir : STL ferme de 215 552 triangles (au-dela de la conversion en
        solide), garde en maillage -> brut en boucle -> plantage. Il devient une surface 3D (14 s), le brut
        se cree, et seules les finitions 3D sont acceptees."""
        from cam2027.i18n import UserError
        from cam2027.project import importers

        proj = self._project("Nut")
        res = proj.import_model(os.path.join(os.path.expanduser("~"), "Downloads", "Not So XL Male Nutcracker 26 (1).stl"))
        if res.kind == "mesh":
            self.skipTest("FreeCAD sans conversion de maillage sans couture")
        self.assertEqual(res.kind, "surface")
        self.assertTrue(any("triangles" in str(w) for w in res.warnings), res.warnings)
        cands = proj.model_candidates()
        self.assertEqual([importers.is_mesh_surface(c) for c in cands], [True])
        proj.create_job(cands, stock={"kind": "box_margins", "xy": 2.0, "z_top": 0.0, "z_bottom": 0.0})
        self.assertAlmostEqual(proj.stock_bounds()["height"], 12.12, delta=0.05)
        self.assertEqual(len(proj.surface_models()), 1)
        lib = proj.library
        flat = lib.search("6 mm flat end mill")[0]
        with self.assertRaises(UserError):
            proj.add_operation("profile", "Contour", lib.assemblies_for_tool(flat.id)[0].id, flat.presets[0].id,
                               base=[(proj.job.Model.Group[0], [])])
        proj.close()

    @unittest.skipUnless(os.path.isfile(os.path.join(os.path.expanduser("~"), "Downloads",
                                                     "Vz330 Concept Chamber Heater v1 (1).step")),
                         "fichier de l'utilisateur absent")
    def test_user_heater_imported_twice(self):
        """Le cas réel : ce STEP importé deux fois, fusionné tel quel, donnait 0 solide (boîte invalide)."""
        proj = self._project("Heater")
        path = os.path.join(os.path.expanduser("~"), "Downloads", "Vz330 Concept Chamber Heater v1 (1).step")
        proj.import_model(path)
        proj.import_model(path)
        cands = proj.model_candidates()
        self.assertEqual(len(cands), 4)
        self.assertIsNone(proj.merge_models(cands))  # la fusion brute est refusée au lieu de rendre une forme vide
        unique = proj.unique_bodies(cands)
        self.assertEqual(len(unique), 2)
        merged = proj.merge_models(unique)
        self.assertIsNotNone(merged)
        proj.create_job([merged], stock={"kind": "box_margins", "xy": 2.0, "z_top": 0.0, "z_bottom": 0.0})
        self.assertAlmostEqual(proj.stock_bounds()["height"], 47.0, places=3)
        proj.close()

    def test_rough3d_on_a_tray_does_not_freeze(self):
        """Le gel signalé : ébauche 3D d'un plateau à alvéoles (plus de 1000 faces en relief) = plus de 15 min.
        Pièce entière -> mode « modèle » de l'adaptative (1.1) : rapide, alvéoles vidées ; 1.0 : refus clair."""
        import time
        from tests.test_pipeline import cutting_points
        from cam2027.i18n import UserError

        tray = Part.makeBox(120, 120, 10)
        for i in range(10):
            for j in range(10):
                tray = tray.cut(Part.makeBox(9, 9, 6, FreeCAD.Vector(2 + i * 11.8, 2 + j * 11.8, 4)))
        proj = self._project("Tray")
        obj = proj.doc.addObject("Part::Feature", "Tray")
        obj.Shape = tray.removeSplitter()
        proj.doc.recompute()
        proj.create_job([obj], stock={"kind": "box_margins", "xy": 3.0, "z_top": 1.0, "z_bottom": 0.0})
        clone = proj.job.Model.Group[0]
        self.assertGreater(len(opsmod.raised_faces(clone)), opsmod.MAX_CLASSIC_ROUGH_FACES)
        lib = proj.library
        e = lib.search("3 mm flat end mill")[0]
        asm = lib.assemblies_for_tool(e.id)[0]
        try:
            op, _rec = proj.add_operation("rough3d", "Rough", asm.id, e.presets[0].id, base=[(clone, [])],
                                          params={"StepDown": 2.0, "StepOver": 40, "StockToLeave": 0.5})
        except UserError as exc:  # FreeCAD 1.0 : pas de mode « modèle » -> refus au lieu d'un calcul interminable
            self.assertIn("select the faces", str(exc))
            proj.close()
            return
        self.assertTrue(op.ModelAwareExperiment)
        t0 = time.time()
        proj.compute()
        self.assertLess(time.time() - t0, 120.0)
        levels = sorted(set(round(p["Z"], 2) for p in cutting_points(op.Path)))
        self.assertTrue(any(4.0 < z < 6.0 for z in levels), levels)  # fond des alvéoles (Z 4) + surépaisseur
        rep = proj.material_check()
        self.assertLess(rep["gouge_max"], 0.05, rep)
        proj.close()

    def test_default_params(self):
        """Réglages initiaux tirés de la matrice stratégies × pièces : finition 3D échantillonnée à 0,05 mm
        (0,5 mm : entaille sur la plaque ; 0,1 mm : 0,07 mm sur le casse-noix), Z constant à 0,5 mm (0,1 mm : plus de 400 s sur le
        chauffage), liaisons de l'adaptative remontées d'une passe (G0 à travers 3 mm de matière sinon)."""
        from cam2027.gui.commands import default_params

        lib = starter_library()
        ball = lib.search("6 mm ball end mill")[0]
        flat = lib.search("6 mm flat end mill")[0]
        self.assertEqual(default_params("surface3d", ball, ball.presets[0].resolve(ball))["SampleInterval"], 0.05)
        self.assertEqual(default_params("waterline", ball, ball.presets[0].resolve(ball))["SampleInterval"], 0.5)
        for kind in ("adaptive", "rough3d"):
            p = default_params(kind, flat, flat.presets[0].resolve(flat))
            self.assertEqual(p["LiftDistance"], p["StepDown"])
            self.assertGreater(p["LiftDistance"], 0)
            self.assertAlmostEqual(p["HelixDiameterLimit"], 5.7)  # fraise de 6 : 0,95 x D, réduite au besoin

    def test_parallel_roughing_matches_serial(self):
        """Ébauche 3D : régions des niveaux préparées dans des processus = régions calculées ici (aires et
        différences nulles), et adaptatives calculées dans des processus = mêmes trajets qu'ici."""
        import Path.Op.Adaptive as adaptive

        from cam2027.project import parallel_adaptive, parallel_levels

        if not hasattr(adaptive, "_getSolidProjection") or parallel_levels._python() is None:
            self.skipTest("FreeCAD sans mode modèle ou sans python.exe")
        opsmod.patch_adaptive_slicing(adaptive)
        V = FreeCAD.Vector
        part = Part.makeBox(60, 40, 12).cut(Part.makeBox(20, 20, 8, V(5, 5, 4))).cut(Part.makeCylinder(6, 6, V(45, 20, 6)))
        stock = Part.makeBox(64, 44, 13, V(-2, -2, 0))
        zs = [11.5, 8.5, 5.5, 3.5, 1.5]
        par = parallel_levels.compute(part, stock, zs)
        self.assertIsNotNone(par)
        import TechDraw

        outline = [Part.makeFace(TechDraw.findShapeOutline(s, 1, V(0, 0, 1))) for s in part.Solids]
        for z, got in zip(zs, par):
            ref = parallel_levels.level_regions(adaptive, part, stock, outline, z)
            for a, b in zip(ref, got):
                if a is None or a.isNull() or not a.Faces:
                    self.assertTrue(b is None or b.isNull() or not b.Faces, z)
                    continue
                self.assertAlmostEqual(a.Area, b.Area, places=6)
                self.assertLess(a.cut(b).Area + b.cut(a).Area, 1e-6)
        # adaptatives : 3 régions en processus = en série
        import area

        def job(square):
            return {"params": {"stepOverFactor": 0.4, "toolDiameter": 6.0, "helixRampDiameter": 5.0,
                               "keepToolDownDistRatio": 3.0, "stockToLeave": 0.5, "tolerance": 0.1,
                               "forceInsideOut": False, "finishingProfile": True},
                    "opType": int(area.AdaptiveOperationType.ClearingInside),
                    "stock": [[(-10, -10), (90, -10), (90, 60), (-10, 60)]], "path": [square]}

        jobs = [job([(0, 0), (40 + 5 * k, 0), (40 + 5 * k, 30), (0, 30)]) for k in range(3)]
        serial = [parallel_adaptive._run_job(area, j) for j in jobs]
        par = parallel_adaptive._run_parallel(jobs, None)
        # l'adaptative de FreeCAD n'est pas déterministe (deux calculs de suite dans le même processus ne
        # donnent pas les mêmes points) : même structure, même longueur de coupe à 5 %, rien hors du contour

        def cut_length(results):
            total = 0.0
            for r in results:
                for motion, pts in r["AdaptivePaths"]:
                    if motion == int(area.AdaptiveMotionType.Cutting):
                        total += sum(math.dist(p, q) for p, q in zip(pts, pts[1:]))
            return total

        for k, (a, b) in enumerate(zip(serial, par)):
            self.assertIsNotNone(b, k)
            self.assertEqual(len(a), len(b))
            self.assertAlmostEqual(cut_length(b), cut_length(a), delta=0.05 * cut_length(a))
            w = 40 + 5 * k
            for r in b:
                for motion, pts in r["AdaptivePaths"]:
                    if motion == int(area.AdaptiveMotionType.Cutting):
                        for x, y in pts:
                            self.assertTrue(3 - 1e-6 <= x <= w - 3 + 1e-6 and 3 - 1e-6 <= y <= 27 + 1e-6, (x, y))

    def test_parallel_pocket_matches_serial(self):
        """Poche 3D sur des fonds d'alvéoles (collectivement) : découpe, intersections et niveaux calculés dans
        des processus = calcul de FreeCAD en série (même volume à enlever, même parcours, même contrôle)."""
        from cam2027.project import parallel_pocket

        if parallel_pocket._python() is None:
            self.skipTest("FreeCAD sans python.exe")
        V = FreeCAD.Vector
        tray = Part.makeBox(100, 80, 20)
        for i in range(4):
            for j in range(3):
                tray = tray.cut(Part.makeCylinder(6, 8, V(14 + 24 * i, 16 + 24 * j, 12)) if (i + j) % 2 else
                                Part.makeBox(14, 14, 8, V(5 + 24 * i, 9 + 24 * j, 12)))
        proj = self._project("PocketPar")
        obj = proj.doc.addObject("Part::Feature", "Tray")
        obj.Shape = tray.removeSplitter()
        proj.doc.recompute()
        proj.create_job([obj], stock={"kind": "box_margins", "xy": 3.0, "z_top": 1.0, "z_bottom": 0.0})
        clone = proj.job.Model.Group[0]
        base = opsmod.auto_geometry("pocket", [clone])
        self.assertEqual(len(base[0][1]), 12)
        lib = proj.library
        e = lib.search("3 mm flat end mill")[0]
        op, _rec = proj.add_operation("pocket", "Pocket", lib.assemblies_for_tool(e.id)[0].id, e.presets[0].id,
                                      base=base, params={"StepDown": 2.0, "StepOver": 40})
        import Path.Op.Pocket as pocket

        self.assertTrue(getattr(pocket.ObjectPocket.areaOpShapes, "cam2027_patched", False))  # 1.0.2 et 1.1.4
        saved = (parallel_pocket.MIN_SOLIDS, parallel_pocket.MIN_HEIGHTS, parallel_pocket._run)
        runs = []

        def counting(tasks, files):
            runs.append(tasks[0]["kind"])
            return saved[2](tasks, files)

        results = {}
        try:
            parallel_pocket.MIN_SOLIDS = parallel_pocket.MIN_HEIGHTS = 1
            parallel_pocket._run = counting
            for switch in ("0", "1"):
                os.environ[parallel_pocket.ENV_SWITCH] = switch
                op.touch()
                proj.compute()
                rep = proj.material_check()
                results[switch] = (op.removalshape.Volume, len(op.removalshape.Solids), op.Path.Commands, rep)
        finally:
            parallel_pocket.MIN_SOLIDS, parallel_pocket.MIN_HEIGHTS, parallel_pocket._run = saved
            os.environ.pop(parallel_pocket.ENV_SWITCH, None)
        self.assertEqual(sorted(set(runs)), ["removal", "sections"])
        (vol0, n0, cmds0, rep0), (vol1, n1, cmds1, rep1) = results["0"], results["1"]
        self.assertEqual(n0, 12)
        self.assertEqual(n1, n0)
        self.assertAlmostEqual(vol1, vol0, delta=1e-6 * vol0)
        self.assertEqual([c.Name for c in cmds1], [c.Name for c in cmds0])
        for a, b in zip(cmds0, cmds1):
            self.assertEqual(sorted(a.Parameters), sorted(b.Parameters))
            for k, v in a.Parameters.items():
                self.assertAlmostEqual(b.Parameters[k], v, delta=1e-5)
        self.assertGreater(rep0["removed_volume"], 0.0)
        self.assertAlmostEqual(rep1["removed_volume"], rep0["removed_volume"], delta=1e-6 * rep0["removed_volume"])
        self.assertLess(rep1["gouge_max"], 0.05, rep1)
        self.assertLess(rep0["gouge_max"], 0.05, rep0)
        proj.close()

    def test_move_operation_to(self):
        """Ordre d'usinage : une opération placée à un rang donné (glisser-déposer du panneau Projet)."""
        proj = self._project("Order")
        part = proj.import_model(self.step).objects[0]
        proj.create_job([part])
        clone = proj.job.Model.Group[0]
        lib = proj.library
        e = lib.search("6 mm flat end mill")[0]
        asm = lib.assemblies_for_tool(e.id)[0]
        ops = [proj.add_operation("profile", "Op %d" % k, asm.id, e.presets[0].id, base=[(clone, [])])[0] for k in range(3)]
        names = lambda: [o.Label for o in proj.operations()]  # noqa: E731
        self.assertEqual(names(), ["Op 0", "Op 1", "Op 2"])
        self.assertEqual(proj.move_operation_to(ops[2], 0), 0)
        self.assertEqual(names(), ["Op 2", "Op 0", "Op 1"])
        proj.move_operation_to(ops[2], 2)
        self.assertEqual(names(), ["Op 0", "Op 1", "Op 2"])
        proj.move_operation_to(ops[0], 99)  # au-delà : dernière
        self.assertEqual(names(), ["Op 1", "Op 2", "Op 0"])
        proj.close()

    def test_new_tool_offered_to_an_existing_project(self):
        """Fraise créée dans la bibliothèque après le projet : rendue utilisable (préréglage, assemblage) et
        ajoutée à l'instantané du projet, sans toucher aux outils déjà présents ; proposée au surfaçage."""
        from cam2027.tools.model import ToolDefinition

        from cam2027.tools.library import ToolLibrary

        proj = self._project("NewTool")
        part = proj.import_model(self.step).objects[0]
        proj.create_job([part])
        user = ToolLibrary.from_dict(proj.library.snapshot())  # la bibliothèque dont le projet a été copié
        self.assertEqual(proj.merge_library(starter_library()), 0)  # mêmes outils, autres identifiants : rien
        before = {k: v.to_dict() for k, v in proj.library.tools.items()}
        face = ToolDefinition("Fraise a surfacer 50", "facemill",
                              dict(diameter=50, shank_diameter=6.35, overall_length=40, flute_length=7,
                                   taper_half_angle_deg=0.0))
        user.add_tool(face)
        self.assertFalse(user.assemblies_for_tool(face.id))
        self.assertTrue(user.ensure_usable(face.id, "Nouveau"))
        self.assertEqual(len(face.presets), 1)
        self.assertEqual(len(user.assemblies_for_tool(face.id)), 1)
        self.assertFalse(user.ensure_usable(face.id, "Nouveau"))  # déjà utilisable : rien
        self.assertEqual(proj.merge_library(user), 1)
        lib = proj.library
        self.assertIn(face.id, lib.tools)
        self.assertEqual({k: lib.tools[k].to_dict() for k in before}, before)  # outils déjà là : inchangés
        offered = [a for a in lib.assemblies.values() if opsmod.tool_fits("millface", lib.tool(a.tool_id))]
        self.assertIn(face.id, [a.tool_id for a in offered])
        self.assertEqual(proj.merge_library(user), 0)  # rien de nouveau la deuxième fois
        asm = lib.assemblies_for_tool(face.id)[0]
        from tests.test_pipeline import plate_top_face
        clone = proj.job.Model.Group[0]
        op, _rec = proj.add_operation("millface", "Surfacage", asm.id, face.presets[0].id,
                                      base=[(clone, [plate_top_face(clone)])])
        proj.compute()
        self.assertIn(proj.operation_state(op), ("computed", "warning"))
        proj.close()

    def test_facing_a_mesh_surface(self):
        """Surfaçage d'une pièce en surface 3D (STL ouvert) : refusé auparavant (« seules les finitions 3D »).
        Comme Fusion, le dessus du brut est surfacé jusqu'au haut de la pièce, sur tout le brut."""
        import Mesh

        from cam2027.gui.commands import default_params

        proj = self._project("FaceSurf")
        m = Mesh.createBox(40, 30, 10)
        m.removeFacets([0, 1])
        path = os.path.join(self.tmp, "open_face.stl")
        m.write(path)
        res = proj.import_model(path)
        if res.kind != "surface":
            self.skipTest("FreeCAD sans conversion de maillage sans couture")
        proj.create_job(proj.model_candidates(), stock={"kind": "box_margins", "xy": 2.0, "z_top": 1.0, "z_bottom": 0.0})
        clone = proj.job.Model.Group[0]
        self.assertEqual(opsmod.auto_geometry("millface", [clone]), [])  # aucune face plane : surface 3D
        lib = proj.library
        e = lib.search("6 mm flat end mill")[0]
        params = default_params("millface", e, e.presets[0].resolve(e))
        params.update({"BoundaryShape": "Stock", "FinalDepth": clone.Shape.BoundBox.ZMax})
        op, _rec = proj.add_operation("millface", "Surfacage", lib.assemblies_for_tool(e.id)[0].id, e.presets[0].id,
                                      base=[(proj.job.Stock, [opsmod.stock_top_face(proj.job.Stock)])], params=params)
        proj.compute()
        self.assertIn(proj.operation_state(op), ("computed", "warning"))
        s = opsmod.toolpath_summary(op)
        self.assertAlmostEqual(s["zmin"], clone.Shape.BoundBox.ZMax, places=3)  # jusqu'au haut de la pièce
        rep = proj.material_check()
        self.assertLess(rep["gouge_max"], 0.03)
        stock_area = 44.0 * 34.0
        self.assertAlmostEqual(rep["removed_volume"], stock_area * 1.0, delta=0.05 * stock_area)  # 1 mm sur tout le brut
        proj.close()

    def test_tool_types_per_strategy(self):
        """Correspondance fraise -> stratégies (usage Fusion) : fraise à surfacer pour le surfaçage, pas pour les
        poches ni l'adaptative (elle ne coupe pas au centre) ; queue d'aronde / rainurer en contour ; boule en
        ébauche 3D ; fraise deux tailles en perçage par plongée."""
        self.assertIn("facemill", opsmod.TOOLS_FOR["millface"])
        self.assertEqual(opsmod.TOOLS_FOR["millface"][0], "facemill")  # présélectionnée pour le surfaçage
        for kind in ("pocket", "adaptive", "rough3d", "helix", "drilling"):
            self.assertNotIn("facemill", opsmod.TOOLS_FOR[kind], kind)
        for t in ("dovetail", "slot", "lollipop"):
            self.assertIn(t, opsmod.TOOLS_FOR["profile"])
        self.assertIn("ballend", opsmod.TOOLS_FOR["rough3d"])
        self.assertIn("endmill", opsmod.TOOLS_FOR["drilling"])

    def test_adaptive_projection_fallback(self):
        """Mode « modèle » : quand la réunion des projections (DraftGeomUtils.concatenate) échoue, la réunion
        des projections face par face est gardée (sinon l'ébauche 3D entière échoue sans parcours)."""
        import Path.Op.Adaptive as adaptive

        if not hasattr(adaptive, "projectFacesToXY"):
            self.skipTest("FreeCAD sans mode modèle")
        opsmod.patch_adaptive_slicing(adaptive)
        self.assertTrue(adaptive.projectFacesToXY.cam2027_patched)
        V = FreeCAD.Vector
        faces = Part.makeBox(10, 10, 5).Faces + Part.makeBox(10, 10, 5, V(20, 0, 0)).Faces
        import DraftGeomUtils

        saved = DraftGeomUtils.concatenate
        calls = []

        def failing(shape):
            calls.append(len(shape.Faces))
            if len(shape.Faces) > 1:
                raise RuntimeError("Wire is not closed.")
            return saved(shape)

        DraftGeomUtils.concatenate = failing
        try:
            proj = adaptive.projectFacesToXY(faces)
        finally:
            DraftGeomUtils.concatenate = saved
        self.assertTrue(calls)
        self.assertAlmostEqual(proj.Area, 200.0, places=3)
        self.assertAlmostEqual(proj.BoundBox.ZMax, 0.0, places=6)

    def test_check_survives_reloading_the_project(self):
        """Le bug : le contrôle était gardé dans l'objet Python, perdu quand l'export relit le projet."""
        proj = self._project("Persist")
        part = proj.import_model(self.step).objects[0]
        proj.create_job([part], stock={"kind": "box_margins", "xy": 2.0, "z_top": 1.0, "z_bottom": 0.0})
        lib = proj.library
        e = lib.search("6 mm flat end mill")[0]
        clone = proj.job.Model.Group[0]
        op, _r = proj.add_operation("millface", "Too deep", lib.assemblies_for_tool(e.id)[0].id, e.presets[0].id,
                                    base=[(clone, opsmod.top_faces(clone))],
                                    params={"StepDown": 1.0, "FinalDepth": 9.0, "StepOver": 50, "ClearEdges": True})
        proj.material_check()
        again = Project.from_document(proj.doc)  # comme une nouvelle commande de l'interface
        errors = [str(m) for lvl, m in again.collision_issues() if lvl == "error"]
        self.assertTrue(any("cuts 1.00 mm into the part" in m for m in errors), errors)
        fcstd = os.path.join(self.tmp, "persist.FCStd")
        proj.save(fcstd)
        proj.close()
        reopened = Project.open(fcstd)  # et même après la réouverture du fichier
        self.assertIsNotNone(reopened.last_check())
        reopened.close()

    def test_messages_translated(self):
        i18n.set_language("fr")
        try:
            msg = i18n.Msg("{name}: invalid shape", name="Plaque")
            self.assertEqual(str(msg), "Plaque: invalid shape")  # anglais pour le code et les journaux
            self.assertEqual(i18n.tr_msg(msg), "Plaque : forme invalide")
            err = i18n.UserError("unsupported format: {ext}", ext=".xyz")
            self.assertEqual(i18n.tr_msg(err), "format non pris en charge : .xyz")
            nested = i18n.Msg("female: {why}", why=i18n.UserError("relief solid is not valid"))
            self.assertEqual(i18n.tr_msg(nested), "femelle : le solide du relief n'est pas valide")
            self.assertEqual(i18n.tr_msg("texte libre"), "texte libre")
        finally:
            i18n.set_language("en")


if __name__ == "__main__":
    unittest.main()
