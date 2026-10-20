# SPDX-License-Identifier: LGPL-2.1-or-later
"""Import de fichiers : STEP, STL (maillage), SVG, DXF."""

import os
import tempfile
import unittest

import FreeCAD
import Part
import Mesh

from cam2027.project import importers

SVG = """<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="60mm" viewBox="0 0 100 60">
  <rect x="10" y="10" width="40" height="20" fill="none" stroke="black"/>
  <circle cx="75" cy="30" r="12" fill="none" stroke="black"/>
  <path d="M 10 50 L 60 50 L 35 58 Z" fill="none" stroke="black"/>
</svg>
"""

DXF = """0
SECTION
2
ENTITIES
0
LINE
8
0
10
0.0
20
0.0
30
0.0
11
50.0
21
0.0
31
0.0
0
CIRCLE
8
0
10
25.0
20
25.0
30
0.0
40
10.0
0
ENDSEC
0
EOF
"""


class TestImport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="cam2027-import-")

    def setUp(self):
        self.doc = FreeCAD.newDocument("ImportTest")

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)

    def test_step(self):
        path = os.path.join(self.tmp, "box.step")
        Part.makeBox(10, 20, 30).exportStep(path)
        res = importers.import_file(self.doc, path, label="Box")
        self.assertEqual(res.kind, "solid")
        self.assertEqual(len(res.objects), 1)
        self.assertEqual(res.objects[0].Label, "Box")
        self.assertAlmostEqual(res.objects[0].Shape.Volume, 6000.0, places=3)
        self.assertEqual(res.warnings, [])

    def test_stl_mesh_and_solid(self):
        path = os.path.join(self.tmp, "box.stl")
        m = Mesh.Mesh()
        shape = Part.makeBox(10, 10, 10)
        m.addFacets(shape.tessellate(0.1)[1] and [tuple(shape.tessellate(0.1)[0][i] for i in f) for f in shape.tessellate(0.1)[1]])
        m.write(path)
        res = importers.import_file(self.doc, path)
        # maillage fermé : converti en solide affiné à l'import (le maillage d'origine reste, masqué)
        self.assertEqual(res.kind, "solid")
        self.assertEqual(len(res.objects), 1)
        solid = res.objects[0]
        self.assertAlmostEqual(solid.Shape.Volume, 1000.0, places=1)
        self.assertEqual(len(solid.Shape.Faces), 6)  # triangles coplanaires fusionnés
        self.assertTrue(any(o.TypeId.startswith("Mesh::") for o in self.doc.Objects))
        # maillage ouvert : reste un maillage, avec un avertissement
        tris = [tuple(shape.tessellate(0.1)[0][i] for i in f) for f in shape.tessellate(0.1)[1]]
        open_path = os.path.join(self.tmp, "open.stl")
        Mesh.Mesh(tris[:-2]).write(open_path)
        res2 = importers.import_file(self.doc, open_path)
        self.assertTrue(any("open mesh" in str(w) for w in res2.warnings), res2.warnings)
        if res2.kind == "surface":  # FreeCAD 1.1 : surface 3D (faces non cousues), jamais un maillage dans le job
            surf = res2.objects[0]
            self.assertTrue(importers.is_mesh_surface(surf))
            self.assertEqual(len(surf.Shape.Faces), len(tris) - 2)
            self.assertFalse(surf.Shape.Solids)
        else:  # FreeCAD 1.0 : pas de conversion sans couture, le maillage reste (et ne peut pas etre usine)
            self.assertEqual(res2.kind, "mesh")

    def test_svg(self):
        path = os.path.join(self.tmp, "shapes.svg")
        with open(path, "w", encoding="utf-8") as fp:
            fp.write(SVG)
        res = importers.import_file(self.doc, path)
        self.assertEqual(res.kind, "vector")
        self.assertGreaterEqual(len(res.objects), 3)
        closed = [o for o in res.objects if getattr(o, "Shape", None) and o.Shape.isClosed()]
        self.assertGreaterEqual(len(closed), 3)

    def test_dxf(self):
        path = os.path.join(self.tmp, "shapes.dxf")
        with open(path, "w", encoding="utf-8") as fp:
            fp.write(DXF)
        res = importers.import_file(self.doc, path)
        self.assertEqual(res.kind, "vector")
        self.assertGreaterEqual(len(res.objects), 1)
        total_edges = sum(len(o.Shape.Edges) for o in res.objects if getattr(o, "Shape", None))
        self.assertGreaterEqual(total_edges, 2)

    def test_unknown_extension(self):
        path = os.path.join(self.tmp, "x.xyz")
        open(path, "w").close()
        with self.assertRaises(ValueError):
            importers.import_file(self.doc, path)
        with self.assertRaises(FileNotFoundError):
            importers.import_file(self.doc, os.path.join(self.tmp, "missing.step"))


if __name__ == "__main__":
    unittest.main()
