# SPDX-License-Identifier: LGPL-2.1-or-later
"""Poche 2D par décalages (``offsetpocket``) : anneau percé et carré d'un dessin sur une plaque ; fraise
contenue, trou intact, fond atteint par pas axiaux, entrée en hélice ; zone trop étroite signalée."""

import math
import re
import unittest

import FreeCAD
import Part

from cam2027.project.project import Project
from cam2027.tools.library import starter_library
from cam2027.gui.commands import default_params
from tests.test_nuit_s5 import cut_points

V = FreeCAD.Vector


def drawing_faces(z):
    ring = Part.Face(Part.Wire(Part.makeCircle(20, V(30, 30, z)))).cut(Part.Face(Part.Wire(Part.makeCircle(8, V(30, 30, z)))))
    square = Part.makePolygon([V(65, 20, z), V(85, 20, z), V(85, 40, z), V(65, 40, z), V(65, 20, z)])
    return Part.Compound([ring, Part.Face(square)])


class TestOffsetPocket(unittest.TestCase):
    def setUp(self):
        self.lib = starter_library()
        self.proj = Project.create("OffsetPocket", self.lib)
        plate = self.proj.doc.addObject("Part::Feature", "Plate")
        plate.Shape = Part.makeBox(100, 60, 12)
        self.proj.doc.recompute()
        self.proj.create_job([plate], stock={"kind": "box_margins", "xy": 0.0, "z_top": 0.0, "z_bottom": 0.0})
        self.area = self.proj.doc.addObject("Part::Feature", "Area")
        self.area.Shape = drawing_faces(12.0)
        self.proj.doc.recompute()
        tool = [t for t in self.lib.search("3 mm flat end mill") if t.tool_type == "endmill"][0]
        self.tool = tool
        self.asm = self.lib.assemblies_for_tool(tool.id)[0]
        self.preset = tool.presets[0]

    def tearDown(self):
        for name in list(FreeCAD.listDocuments()):
            FreeCAD.closeDocument(name)

    def _add(self, base, **extra):
        params = default_params("offsetpocket", self.tool, self.preset.resolve(self.tool))
        params.update({"StartDepth": 12.0, "FinalDepth": 9.0, "StepDown": 1.0})
        params.update(extra)
        op, rec = self.proj.add_operation("offsetpocket", "Pocket", self.asm.id, self.preset.id, base=base, params=params)
        res = {r["name"]: r for r in self.proj.compute()}["Pocket"]
        self.assertTrue(res["valid"] and res["commands"] > 50, res)
        return op

    def test_ring_and_square(self):
        op = self._add([(self.area, ["Face1", "Face2"])])
        faces = self.area.Shape
        edges = Part.Compound(faces.Edges)
        pts = [p for p in cut_points(op) if p[2] < 12 - 1e-6]
        self.assertGreater(len(pts), 100)
        depths = {round(p[2], 3) for p in pts}
        self.assertTrue({9.0, 10.0, 11.0} <= depths, sorted(depths))  # pas axial de 1 mm jusqu'au fond
        self.assertEqual(min(depths), 9.0)  # les hélices descendent entre les niveaux, jamais sous le fond
        for x, y, z in pts:
            v = Part.Vertex(V(x, y, 12.0))
            self.assertLess(faces.distToShape(v)[0], 1e-3, (x, y))  # dans une des faces
            self.assertGreater(edges.distToShape(v)[0], 1.5 - 0.02, (x, y))  # fraise contenue
        self.assertFalse(any(math.hypot(x - 30, y - 30) < 8.0 for x, y, z in pts))  # trou intact
        # parois atteintes : des points à 1,5 mm (rayon) du contour extérieur de l'anneau et du carré
        self.assertTrue(any(abs(math.hypot(x - 30, y - 30) - 18.5) < 0.05 for x, y, z in pts))
        self.assertTrue(any(abs(x - 83.5) < 0.05 and 21.5 <= y <= 38.5 for x, y, z in pts))
        m = re.search(r"(\d+) helical entries, (\d+) straight plunges", op.Report)
        self.assertGreaterEqual(int(m.group(1)), 2 * 3)  # une hélice par zone et par niveau
        self.assertEqual(int(m.group(2)), 0)
        self.assertTrue(any(c.Name == "G2" for c in op.Path.Commands))

    def test_narrow_zone_reported(self):
        narrow = self.proj.doc.addObject("Part::Feature", "Narrow")
        narrow.Shape = Part.Face(Part.makePolygon([V(10, 50, 12), V(40, 50, 12), V(40, 52, 12), V(10, 52, 12), V(10, 50, 12)]))
        self.proj.doc.recompute()
        op = self._add([(self.area, ["Face2"]), (narrow, ["Face1"])])
        self.assertIn("1 zone(s) too narrow for the tool", op.Report)
        pts = [p for p in cut_points(op) if p[2] < 12 - 1e-6]
        self.assertFalse(any(y > 45 for x, y, z in pts))  # la zone étroite n'est pas usinée


if __name__ == "__main__":
    unittest.main()
