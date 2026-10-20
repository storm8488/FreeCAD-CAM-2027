# SPDX-License-Identifier: LGPL-2.1-or-later
"""Chaîne complète : outil → préréglage → pièce → brut/montage → opération → parcours → export → sauvegarde/réouverture."""

import os
import tempfile
import unittest

import FreeCAD
import Part

from cam2027 import compat
from cam2027.tools.library import starter_library
from cam2027.tools import bridge
from cam2027.project.project import Project, ExportBlocked
from cam2027.project.machine import MachineProfile
from cam2027.project import export as exportmod


HOLE_CENTER = (72.0, 8.0)
HOLE_DIAMETER = 6.8  # avant-trou M8 x 1.25


def make_part(path):
    """Plaque 80x60x10 avec une poche rectangulaire, un îlot et un avant-trou débouchant, exportée en STEP."""
    plate = Part.makeBox(80, 60, 10)
    pocket = Part.makeBox(50, 30, 6, FreeCAD.Vector(15, 15, 4))
    island = Part.makeCylinder(6, 6, FreeCAD.Vector(40, 30, 4))
    hole = Part.makeCylinder(HOLE_DIAMETER / 2.0, 10, FreeCAD.Vector(HOLE_CENTER[0], HOLE_CENTER[1], 0))
    shape = plate.cut(pocket).fuse(island).cut(hole)
    shape.exportStep(path)
    return shape


def plate_top_face(clone):
    """Nom de la face supérieure de la plaque (z = 10, la plus grande)."""
    best = None
    for i, f in enumerate(clone.Shape.Faces, 1):
        if f.Surface.__class__.__name__ == "Plane" and abs(f.BoundBox.ZMax - 10.0) < 1e-6 and abs(f.BoundBox.ZMin - 10.0) < 1e-6:
            if best is None or f.Area > best[1]:
                best = ("Face%d" % i, f.Area)
    return best[0]


def plate_top_outer_edges(clone):
    """Arêtes du contour extérieur de la face supérieure (z = 10, sur le périmètre 80x60)."""
    names = []
    for i, e in enumerate(clone.Shape.Edges, 1):
        bb = e.BoundBox
        if abs(bb.ZMin - 10.0) > 1e-6 or abs(bb.ZMax - 10.0) > 1e-6:
            continue
        on_x = abs(bb.XMax - bb.XMin) < 1e-6 and (abs(bb.XMin) < 1e-6 or abs(bb.XMin - 80.0) < 1e-6)
        on_y = abs(bb.YMax - bb.YMin) < 1e-6 and (abs(bb.YMin) < 1e-6 or abs(bb.YMin - 60.0) < 1e-6)
        if on_x or on_y:
            names.append("Edge%d" % i)
    return names


def hole_face(clone):
    """Face cylindrique de l'avant-trou."""
    for i, f in enumerate(clone.Shape.Faces, 1):
        if f.Surface.__class__.__name__ == "Cylinder" and abs(f.BoundBox.XMin - (HOLE_CENTER[0] - HOLE_DIAMETER / 2.0)) < 1e-3:
            return "Face%d" % i
    return None


class TestPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="cam2027-")
        cls.step = os.path.join(cls.tmp, "plate.step")
        make_part(cls.step)
        FreeCAD.ConfigSet("SuppressRecomputeRequiredDialog", "True")

    def _machine(self, **kw):
        m = MachineProfile("test", controller="grbl", post_processor="grbl",
                           post_processor_args="--no-show-editor --precision=3", **kw)
        return m

    def _project_with_job(self, name):
        """Projet + plaque importée + brut à marges 2 mm ; retourne (projet, bibliothèque, clone du modèle)."""
        lib = starter_library()
        proj = Project.create(name, lib, self._machine())
        part = proj.import_model(self.step, label="Plate").objects[0]
        job = proj.create_job([part], stock={"kind": "box_margins", "xy": 2.0, "z_top": 1.0, "z_bottom": 0.0})
        return proj, lib, job.Model.Group[0]

    def _single_result(self, proj):
        results = proj.compute()
        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertTrue(r["valid"], r)
        self.assertGreater(r["commands"], 10, r)
        self.assertEqual(r["axes"], ["X", "Y", "Z"], r)
        return r

    def test_full_chain(self):
        lib = starter_library()
        proj = Project.create("Chain test", lib, self._machine())
        self.assertEqual(proj.library.summary()["tools"], lib.summary()["tools"])

        # pièce
        res = proj.import_model(self.step, label="Plate")
        self.assertEqual(res.kind, "solid")
        self.assertEqual(len(res.objects), 1)
        self.assertEqual(res.warnings, [])
        part = res.objects[0]

        # brut : marges XY 2 mm, +1 mm au-dessus ; montage G54
        job = proj.create_job([part], stock={"kind": "box_margins", "xy": 2.0, "z_top": 1.0, "z_bottom": 0.0})
        sb = proj.stock_bounds()
        self.assertAlmostEqual(sb["length"], 84.0, places=3)
        self.assertAlmostEqual(sb["zmax"], 11.0, places=3)
        self.assertEqual(job.Fixtures, ["G54"])
        clamp = proj.add_clamp("Clamp left", 10, 20, 15, (-12, 20, 0))
        self.assertEqual(clamp.Label, "Clamp left")

        # outil / préréglage
        endmill = lib.search("6 mm flat end mill")[0]
        asm = lib.assemblies_for_tool(endmill.id)[0]
        preset = endmill.presets[0]

        # face du fond de poche : chercher la face plane à z=4 dans le clone du modèle
        clone = job.Model.Group[0]
        bottom = None
        for i, f in enumerate(clone.Shape.Faces, 1):
            if f.Surface.__class__.__name__ == "Plane" and abs(f.BoundBox.ZMax - 4.0) < 1e-6 and abs(f.BoundBox.ZMin - 4.0) < 1e-6:
                bottom = "Face%d" % i
        self.assertIsNotNone(bottom)

        op, rec = proj.add_operation(
            "pocket", "Pocket roughing", asm.id, preset.id, base=[(clone, [bottom])],
            params={"StepDown": 2.0, "StepOver": 40, "FinalDepth": 4.0, "NotAProperty": 1},
        )
        self.assertEqual(rec["ignored_params"], ["NotAProperty"])
        self.assertAlmostEqual(rec["values"]["feed_mm_min"], 1800.0)
        tc = proj.doc.getObject(rec["tool_controller"])
        vals = bridge.tool_controller_values(tc)
        self.assertAlmostEqual(vals["feed_mm_min"], 1800.0)
        self.assertAlmostEqual(vals["spindle_rpm"], 18000.0)
        self.assertAlmostEqual(vals["diameter_mm"], 6.0)
        self.assertEqual(vals["tool_number"], asm.output.tool_number)

        # changer le préréglage après coup ne modifie pas l'opération
        preset.feed_mm_min = 10.0
        self.assertAlmostEqual(bridge.tool_controller_values(tc)["feed_mm_min"], 1800.0)

        op2, rec2 = proj.add_operation(
            "profile", "Outside contour", asm.id, preset.id, base=[(clone, [])],
            params={"StepDown": 5.0, "FinalDepth": 0.0, "Side": "Outside", "Direction": "CW"},
        )

        # calcul
        results = proj.compute()
        self.assertEqual(len(results), 2)
        for r in results:
            self.assertTrue(r["valid"], r)
            self.assertGreater(r["commands"], 10, r)
            self.assertGreater(r["length_mm"], 50.0, r)
            self.assertEqual(r["axes"], ["X", "Y", "Z"], r)
        pocket = results[0]
        self.assertAlmostEqual(pocket["zmin"], 4.0, places=3)
        self.assertIn(1800.0, pocket["feeds"])
        contour = results[1]
        self.assertAlmostEqual(contour["zmin"], 0.0, places=3)
        # le contour extérieur doit sortir de la pièce (80x60) d'au moins un rayon d'outil
        bb = contour["bbox"]
        self.assertLess(bb["X"][0], -2.9)
        self.assertGreater(bb["X"][1], 82.9)

        # export
        out = os.path.join(self.tmp, "chain.nc")
        result = proj.export_gcode(out)
        self.assertTrue(os.path.isfile(out))
        self.assertTrue(os.path.isfile(result["sheet"]))
        a = result["analysis"]
        self.assertEqual(a["units"], "mm")
        self.assertIn("G54", a["fixtures"])
        self.assertIn("G1", a["codes"])
        self.assertEqual(a["axes"], ["X", "Y", "Z"])
        self.assertAlmostEqual(a["bbox"]["Z"][0], 0.0, places=3)
        self.assertEqual(a["max_feed"], 1800.0)
        self.assertIn(18000.0, a["spindle_speeds"])
        levels = [lvl for lvl, _ in result["issues"]]
        self.assertNotIn("error", levels)
        self.assertIn("unverifiable", levels)  # courses inconnues : signalé, pas inventé
        self.assertIn("| 1 |", result["sheet_text"])
        self.assertIn("Machine data still to fill in", result["sheet_text"])

        # sauvegarde / réouverture
        fcstd = os.path.join(self.tmp, "chain.FCStd")
        proj.save(fcstd)
        name = proj.doc.Name
        op_names = {op.Name, op2.Name}
        proj.close()
        self.assertNotIn(name, FreeCAD.listDocuments())
        again = Project.open(fcstd)
        self.assertEqual(again.library.summary()["tools"], lib.summary()["tools"])
        self.assertEqual(again.machine.controller, "grbl")
        self.assertEqual(len(again.operations()), 2)
        self.assertEqual(set(again.registry), op_names)
        self.assertAlmostEqual(again.registry[sorted(op_names)[0]]["values"]["feed_mm_min"], 1800.0)
        results2 = again.compute()
        self.assertEqual([r["commands"] for r in results2], [r["commands"] for r in results])
        text, analysis2, issues2 = again.preview_gcode()
        self.assertEqual(analysis2["bbox"], a["bbox"])
        again.close()

    def test_export_blocked_on_travel(self):
        lib = starter_library()
        proj = Project.create("Travel test", lib, self._machine(travel_x_mm=20, travel_y_mm=20, travel_z_mm=50))
        part = proj.import_model(self.step).objects[0]
        proj.create_job([part])
        endmill = lib.search("6 mm flat end mill")[0]
        asm = lib.assemblies_for_tool(endmill.id)[0]
        clone = proj.job.Model.Group[0]
        proj.add_operation("profile", "Contour", asm.id, endmill.presets[0].id, base=[(clone, [])],
                           params={"FinalDepth": 0.0})
        proj.compute()
        with self.assertRaises(ExportBlocked) as ctx:
            proj.export_gcode(os.path.join(self.tmp, "blocked.nc"))
        msgs = " ".join(m for _l, m in ctx.exception.issues)
        self.assertIn("exceeds travel", msgs)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "blocked.nc")))
        proj.close()

    def test_rotary_words_rejected(self):
        machine = self._machine()
        analysis = exportmod.analyze_gcode("G21 G54\nG0 X1 Y2 Z3 A90\nG1 X2 F100 S1000 M3\n")
        self.assertEqual(analysis["axes"], ["A", "X", "Y", "Z"])
        issues = exportmod.verify(analysis, machine)
        self.assertTrue(any("rotary" in m for _l, m in issues))
        analysis = exportmod.analyze_gcode("G20\nG0 X1\nG99\n")
        issues = exportmod.verify(analysis, machine)
        self.assertTrue(any("inches" in m for _l, m in issues))
        self.assertTrue(any("G99" in m for _l, m in issues))

    def test_facing(self):
        """Surfaçage de la face supérieure : Z final = 10 - passe, outil dépassant les bords."""
        proj, lib, clone = self._project_with_job("Facing test")
        endmill = lib.search("6 mm flat end mill")[0]
        asm = lib.assemblies_for_tool(endmill.id)[0]
        op, rec = proj.add_operation(
            "millface", "Top facing", asm.id, endmill.presets[0].id, base=[(clone, [plate_top_face(clone)])],
            params={"StepDown": 1.0, "FinalDepth": 9.0, "StepOver": 50, "ClearEdges": True},
        )
        self.assertEqual(rec["ignored_params"], [])
        r = self._single_result(proj)
        self.assertAlmostEqual(r["zmin"], 9.0, places=3)
        self.assertIn("G1", r["gcodes"])
        # le centre de l'outil sort de la pièce (80x60) : la fraise déborde d'au moins un rayon
        bb = r["bbox"]
        radius = endmill.geometry.diameter / 2.0
        self.assertLess(bb["X"][0] - radius, -radius)
        self.assertGreater(bb["X"][1] + radius, 80.0 + radius)
        self.assertLess(bb["Y"][0] - radius, -radius)
        self.assertGreater(bb["Y"][1] + radius, 60.0 + radius)
        proj.close()

    def test_thread_milling(self):
        """Filet M8 x 1.25 dans l'avant-trou avec la fraise à fileter de la bibliothèque de démarrage."""
        from cam2027.project import operations as opsmod

        proj, lib, clone = self._project_with_job("Thread test")
        tm = lib.search("thread mill")[0]
        self.assertEqual(tm.tool_type, "threadmill")
        asm = lib.assemblies_for_tool(tm.id)[0]
        preset = tm.presets[0]
        face = hole_face(clone)
        self.assertIsNotNone(face)

        # pas hors de la plage de l'outil (M12 x 1.75 > 1.25) et outil inadapté : refusés avant création
        with self.assertRaises(ValueError):
            opsmod.resolve_params("threadmill", tm, {"ThreadName": "M12 x 1.75"})
        endmill = lib.search("6 mm flat end mill")[0]
        with self.assertRaises(ValueError):
            opsmod.resolve_params("threadmill", endmill, {"ThreadName": "M8 x 1.25"})
        with self.assertRaises(ValueError):
            opsmod.thread_spec("MetricInternal6H", "M8 x 9")
        # sans nom ni pas : le pas (maximal) de l'outil est repris
        self.assertAlmostEqual(opsmod.resolve_params("threadmill", tm, {})["Pitch"], 1.25)

        op, rec = proj.add_operation(
            "threadmill", "Thread M8", asm.id, preset.id, base=[(clone, [face])],
            params={"ThreadType": "MetricInternal6H", "ThreadName": "M8 x 1.25", "Passes": 2,
                    "StartDepth": 10.0, "FinalDepth": 0.0, "LeadInOut": True},
        )
        self.assertEqual(rec["ignored_params"], [])
        p = rec["params"]
        # table FreeCAD metric-internal-6H, ajustement 50 % : 8 + (8.34-8)/2 ; 6.647 + (6.912-6.647)/2
        self.assertAlmostEqual(p["MajorDiameter"], 8.17, places=3)
        self.assertAlmostEqual(p["MinorDiameter"], 6.7795, places=3)
        self.assertAlmostEqual(p["Pitch"], 1.25)
        self.assertEqual(p["TPI"], 0)
        self.assertAlmostEqual(float(op.Pitch.getValueAs("mm")), 1.25)
        self.assertAlmostEqual(float(op.MajorDiameter.getValueAs("mm")), 8.17, places=3)
        self.assertEqual(op.Passes, 2)

        r = self._single_result(proj)
        self.assertIn("G3", r["gcodes"])  # filet à droite intérieur, avalant : G3 de bas en haut
        self.assertAlmostEqual(r["zmin"], 0.0, places=3)
        self.assertIn(400.0, r["feeds"])
        # dernière passe : rayon du centre outil = D maj/2 + H/8 - D outil/2 autour du centre du trou
        bb = r["bbox"]
        h = (p["MajorDiameter"] - p["MinorDiameter"]) / 2.0 * 1.6
        last_pass = p["MajorDiameter"] / 2.0 + h / 8.0 - tm.geometry.diameter / 2.0
        self.assertAlmostEqual(bb["Y"][1], HOLE_CENTER[1] + last_pass, places=2)
        self.assertAlmostEqual(bb["Y"][0], HOLE_CENTER[1] - last_pass, places=2)
        self.assertLess(abs(bb["X"][0] - HOLE_CENTER[0]), last_pass + 1e-3)
        proj.close()

    def test_chamfer(self):
        """Chanfrein 1 mm des arêtes supérieures de la plaque avec le V-bit 90°."""
        proj, lib, clone = self._project_with_job("Chamfer test")
        vbit = [t for t in lib.search("V-bit") if t.geometry.tip_included_angle_deg == 90.0][0]
        asm = lib.assemblies_for_tool(vbit.id)[0]
        edges = plate_top_outer_edges(clone)
        self.assertEqual(len(edges), 4)
        op, rec = proj.add_operation(
            "chamfer", "Top chamfer", asm.id, vbit.presets[0].id, base=[(clone, edges)],
            params={"Width": 1.0, "ExtraDepth": 0.5, "Direction": "CW", "EntryPoint": 0},
        )
        self.assertEqual(rec["ignored_params"], [])
        r = self._single_result(proj)
        # V-bit 90° : profondeur = largeur / tan(45°) + surprofondeur = 1.5 ; décalage = pointe/2 + 0.5
        self.assertAlmostEqual(r["zmin"], 10.0 - 1.5, places=3)
        self.assertIn("G2", r["gcodes"])  # arcs de raccordement aux angles (sens horaire)
        bb = r["bbox"]
        offset = vbit.geometry.tip_diameter / 2.0 + 0.5
        self.assertAlmostEqual(bb["X"][0], -offset, places=2)
        self.assertAlmostEqual(bb["X"][1], 80.0 + offset, places=2)
        self.assertAlmostEqual(bb["Y"][0], -offset, places=2)
        self.assertAlmostEqual(bb["Y"][1], 60.0 + offset, places=2)
        proj.close()

    def test_strategy_translations(self):
        """Libellés et limites de chaque stratégie traduits ; aucune chaîne tr() manquante."""
        import json
        from cam2027 import i18n
        from cam2027.project.operations import STRATEGIES

        self.assertEqual(i18n.missing_translations("fr"), [])
        with open(os.path.join(os.path.dirname(i18n.__file__), "i18n", "fr.json"), "r", encoding="utf-8") as fp:
            catalog = json.load(fp)
        for kind, meta in STRATEGIES.items():
            self.assertIn(meta["label"], catalog, kind)
            if meta["limits"]:
                self.assertIn(meta["limits"], catalog, kind)

    def test_toolbit_shapes(self):
        """Chaque type d'outil produit un ToolBit FreeCAD (avec avertissement si approximé)."""
        lib = starter_library()
        doc = FreeCAD.newDocument("Bits")
        try:
            for tool in lib.tools.values():
                obj, warnings = bridge.create_toolbit(doc, tool)
                self.assertAlmostEqual(float(obj.Diameter.getValueAs("mm")), tool.geometry.diameter, places=3)
                if tool.tool_type == "vbit":
                    self.assertAlmostEqual(float(obj.CuttingEdgeAngle.getValueAs("deg")),
                                           tool.geometry.tip_included_angle_deg, places=3)
                if tool.tool_type == "drill":
                    self.assertAlmostEqual(float(obj.TipAngle.getValueAs("deg")), 118.0, places=3)
            from cam2027.tools.model import ToolDefinition
            tb = ToolDefinition("tb", "taperedball", dict(diameter=6, overall_length=50, flute_length=20,
                                                          taper_half_angle_deg=3, corner_radius=0.5))
            obj, warnings = bridge.create_toolbit(doc, tb)
            if compat.tool_api() == "legacy":
                self.assertTrue(any("ball end" in w for w in warnings))
        finally:
            FreeCAD.closeDocument(doc.Name)


if __name__ == "__main__":
    unittest.main()
