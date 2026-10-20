# SPDX-License-Identifier: LGPL-2.1-or-later
"""Logique derrière l'interface (bugs trouvés par les scénarios utilisateur) : pièces détectées, maillages,
outils compatibles, géométrie automatique, fusion d'assemblage, contrôle mémorisé dans le document, messages."""

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
        self.assertFalse(opsmod.tool_fits("drilling", by_type["endmill"]))
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
        """Réglages initiaux tirés de la matrice stratégies × pièces : finition 3D échantillonnée à 0,1 mm
        (0,5 mm : 1,45 mm d'entaille sur la plaque), Z constant à 0,5 mm (0,1 mm : plus de 400 s sur le
        chauffage), liaisons de l'adaptative remontées d'une passe (G0 à travers 3 mm de matière sinon)."""
        from cam2027.gui.commands import default_params

        lib = starter_library()
        ball = lib.search("6 mm ball end mill")[0]
        flat = lib.search("6 mm flat end mill")[0]
        self.assertEqual(default_params("surface3d", ball, ball.presets[0].resolve(ball))["SampleInterval"], 0.1)
        self.assertEqual(default_params("waterline", ball, ball.presets[0].resolve(ball))["SampleInterval"], 0.5)
        for kind in ("adaptive", "rough3d"):
            p = default_params(kind, flat, flat.presets[0].resolve(flat))
            self.assertEqual(p["LiftDistance"], p["StepDown"])
            self.assertGreater(p["LiftDistance"], 0)

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
