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


def make_part(path):
    """Plaque 80x60x10 avec une poche rectangulaire et un îlot, exportée en STEP."""
    plate = Part.makeBox(80, 60, 10)
    pocket = Part.makeBox(50, 30, 6, FreeCAD.Vector(15, 15, 4))
    island = Part.makeCylinder(6, 6, FreeCAD.Vector(40, 30, 4))
    shape = plate.cut(pocket).fuse(island)
    shape.exportStep(path)
    return shape


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
