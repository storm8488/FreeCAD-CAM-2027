# SPDX-License-Identifier: LGPL-2.1-or-later
"""Logique derrière l'interface (bugs trouvés par les scénarios utilisateur) : pièces détectées, maillages,
outils compatibles, géométrie automatique, fusion d'assemblage, contrôle mémorisé dans le document, messages."""

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
