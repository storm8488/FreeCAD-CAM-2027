# SPDX-License-Identifier: LGPL-2.1-or-later
"""Ébauche 2,5D sur le modèle de brut (``stockrough``) : pièce synthétique à deux fonds de poche et un second
corps plus haut ; aucune entaille, fonds atteints en une opération, entrées en hélice."""

import re
import unittest

import FreeCAD
import Part

from cam2027.project.project import Project
from cam2027.project import operations as opsmod
from cam2027.tools.library import starter_library
from cam2027.gui.commands import default_params

V = FreeCAD.Vector
LEAVE = 0.5


def two_pockets_and_tower():
    """Base 80 x 60 x 20 avec une poche de 5 mm (30 x 20) et une de 12 mm (20 x 20) ; tour 15 x 15 x 30 posée à
    côté, séparée (second corps)."""
    base = Part.makeBox(80, 60, 20)
    base = base.cut(Part.makeBox(30, 20, 5, V(5, 5, 15)))
    base = base.cut(Part.makeBox(20, 20, 12, V(50, 10, 8)))
    tower = Part.makeBox(15, 15, 30, V(30, 38, 0))
    return base, tower


class TestStockRough(unittest.TestCase):
    def setUp(self):
        self.lib = starter_library()
        self.proj = Project.create("StockRough", self.lib)
        base, tower = two_pockets_and_tower()
        a = self.proj.doc.addObject("Part::Feature", "Base")
        a.Shape = base
        b = self.proj.doc.addObject("Part::Feature", "Tower")
        b.Shape = tower
        self.proj.doc.recompute()
        self.proj.create_job([a, b], stock={"kind": "box_margins", "xy": 5.0, "z_top": 1.0, "z_bottom": 0.0})

    def tearDown(self):
        for name in list(FreeCAD.listDocuments()):
            FreeCAD.closeDocument(name)

    def _top_at(self, x, y):
        zmap = self.proj.last_zmap
        i = int((x - zmap.x0) / zmap.res)
        j = int((y - zmap.y0) / zmap.res)
        return float(zmap.top[i, j])

    def test_all_depths_one_operation_no_gouge(self):
        tool = [t for t in self.lib.search("6 mm flat end mill") if t.tool_type == "endmill"][0]
        asm = self.lib.assemblies_for_tool(tool.id)[0]
        preset = tool.presets[0]
        params = default_params("stockrough", tool, preset.resolve(tool))
        self.assertEqual(params["StockToLeave"], LEAVE)
        op, rec = self.proj.add_operation("stockrough", "Rough", asm.id, preset.id, params=params)
        results = {r["name"]: r for r in self.proj.compute()}
        self.assertTrue(results["Rough"]["valid"] and results["Rough"]["commands"] > 100, results["Rough"])
        report = self.proj.material_check()
        self.assertEqual(report["gouge_cells"], 0, report["gouge_at"])  # ni la tour ni les parois des poches
        # fonds atteints (surépaisseur près) en une seule opération, dessus de la base et de la tour dégagés
        self.assertAlmostEqual(self._top_at(20, 15), 15 + LEAVE, delta=0.05)  # poche de 5 mm
        self.assertAlmostEqual(self._top_at(60, 20), 8 + LEAVE, delta=0.05)  # poche de 12 mm
        self.assertAlmostEqual(self._top_at(15, 45), 20 + LEAVE, delta=0.05)  # dessus de la base
        self.assertAlmostEqual(self._top_at(37.5, 45.5), 30 + LEAVE, delta=0.05)  # dessus de la tour
        self.assertAlmostEqual(self._top_at(-3, -3), 0.0, delta=0.05)  # marge du brut dégagée jusqu'au fond
        # entrées en hélice dans la matière, aucune plongée droite (les poches sont assez larges)
        m = re.search(r"(\d+) helical entries, (\d+) straight plunges", op.Report)
        self.assertIsNotNone(m, op.Report)
        self.assertGreaterEqual(int(m.group(1)), 2)
        self.assertEqual(int(m.group(2)), 0)
        self.assertEqual(opsmod.compute_state(op, op, rec), "computed")

    def test_narrow_pocket_falls_back_to_plunge(self):
        """Poche de 7 mm de large : l'hélice de la fraise de 6 mm ne tient pas, plongée droite signalée."""
        narrow = Part.makeBox(40, 40, 10).cut(Part.makeBox(30, 7, 4, V(5, 5, 6)))
        obj = self.proj.doc.addObject("Part::Feature", "Narrow")
        obj.Shape = narrow
        for o in list(self.proj.job.Model.Group):
            self.proj.doc.removeObject(o.Name)
        self.proj.doc.recompute()
        proj = Project.create("Narrow", self.lib)
        o = proj.doc.addObject("Part::Feature", "Narrow")
        o.Shape = narrow
        proj.doc.recompute()
        proj.create_job([o], stock={"kind": "box_margins", "xy": 0.0, "z_top": 0.0, "z_bottom": 0.0})
        tool = [t for t in self.lib.search("6 mm flat end mill") if t.tool_type == "endmill"][0]
        asm = self.lib.assemblies_for_tool(tool.id)[0]
        preset = tool.presets[0]
        params = default_params("stockrough", tool, preset.resolve(tool))
        params["StockToLeave"] = 0.0
        op, _rec = proj.add_operation("stockrough", "Rough", asm.id, preset.id, params=params)
        proj.compute()
        report = proj.material_check()
        self.assertEqual(report["gouge_cells"], 0, report["gouge_at"])
        self.assertIn("straight plunges", op.Report)
        self.assertNotIn(" 0 straight plunges", op.Report)
        self.assertAlmostEqual(float(proj.last_zmap.top[int((20 - proj.last_zmap.x0) / proj.last_zmap.res),
                                                        int((8.5 - proj.last_zmap.y0) / proj.last_zmap.res)]), 6.0, delta=0.05)


if __name__ == "__main__":
    unittest.main()
