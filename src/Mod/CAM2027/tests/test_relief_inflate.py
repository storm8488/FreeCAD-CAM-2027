# SPDX-License-Identifier: LGPL-2.1-or-later
"""Relief depuis une image, mode « formes gonflées » (dessins au trait, logos) : un dessin n'est pas une carte de
profondeur ; ses formes deviennent des dômes arrondis sur une largeur donnée, plats au-delà."""

import math
import os
import tempfile
import unittest

import FreeCAD

from cam2027.project import relief


def _image(path):
    """200 × 100 px blanc : carré noir de 60 px (x 20..80, y 20..80) et trait noir de 4 px (x 140..144)."""
    from PySide6 import QtGui

    img = QtGui.QImage(200, 100, QtGui.QImage.Format_RGB32)
    img.fill(QtGui.QColor(255, 255, 255))
    p = QtGui.QPainter(img)
    p.fillRect(20, 20, 60, 60, QtGui.QColor(0, 0, 0))
    p.fillRect(140, 10, 4, 80, QtGui.QColor(0, 0, 0))
    p.end()
    img.save(path)


class TestReliefInflate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = os.path.join(tempfile.mkdtemp(prefix="cam2027-inflate-"), "shapes.png")
        _image(cls.path)

    def tearDown(self):
        for name in list(FreeCAD.listDocuments()):
            FreeCAD.closeDocument(name)

    def grid(self, **kw):
        # 100 mm de large : 0,5 mm par pixel ; grille à la résolution de l'image (200 points)
        grid, size = relief.inflate_grid(self.path, 100.0, 5.0, cells=200, **kw)
        self.assertEqual(size, (200, 100))
        return lambda x_px, y_px: grid[x_px][99 - y_px]  # (colonne, ligne de l'image)

    def test_dark_shapes_become_rounded_domes(self):
        h = self.grid(rounding=5.0)
        self.assertAlmostEqual(h(50, 50), 1.0, places=2)   # centre du carré : pleine hauteur (plat)
        self.assertLess(h(20, 50), 0.35)                   # bord du carré : bas du dôme
        self.assertGreater(h(24, 50), h(21, 50))           # monte depuis le bord
        self.assertAlmostEqual(h(100, 50), 0.0, places=3)  # fond blanc : bas
        # trait de 4 px = 2 mm : à 1 mm du bord au plus, 1/5 de l'arrondi -> sqrt(1 - 0.8²) = 0.6
        self.assertAlmostEqual(max(h(x, 50) for x in range(138, 147)), math.sqrt(1 - 0.8 ** 2), delta=0.12)

    def test_raise_light_inverts(self):
        h = self.grid(rounding=5.0, raise_light=True)
        self.assertAlmostEqual(h(50, 50), 0.0, places=3)
        self.assertAlmostEqual(h(110, 50), 1.0, places=2)

    def test_relief_solid_from_inflated_shapes(self):
        doc = FreeCAD.newDocument("InflateRelief")
        obj, _w = relief.make_relief(doc, self.path, 100.0, 4.0, base=2.0, cells=100, source="inflate", rounding=3.0,
                                     smoothing=0)
        self.assertTrue(obj.Shape.isValid())
        bb = obj.Shape.BoundBox
        self.assertAlmostEqual(bb.XLength, 100.0, places=3)
        self.assertAlmostEqual(bb.YLength, 50.0, places=3)
        self.assertAlmostEqual(bb.ZMax, 6.0, delta=0.15)  # épaisseur 2 + relief 4 (centre du carré)
        self.assertEqual(obj.ReliefSource, "inflate")

    def test_threshold_without_shape_refused(self):
        with self.assertRaises(Exception):
            relief.inflate_grid(self.path, 100.0, 5.0, cells=100, threshold=0.0)



class TestReliefDepth(unittest.TestCase):
    """Profondeur estimée par l'IA (Depth Anything V2 Small, installée à la demande : test ignoré sans elle)."""

    @classmethod
    def setUpClass(cls):
        cls.path = os.path.join(tempfile.mkdtemp(prefix="cam2027-depth-"), "shapes.png")
        _image(cls.path)

    def tearDown(self):
        for name in list(FreeCAD.listDocuments()):
            FreeCAD.closeDocument(name)

    def test_not_available_in_an_empty_folder(self):
        old = os.environ.get("CAM2027_DEPTH_DIR")
        os.environ["CAM2027_DEPTH_DIR"] = tempfile.mkdtemp(prefix="cam2027-nodepth-")
        try:
            self.assertFalse(relief.depth_available())
            with self.assertRaises(Exception):
                relief.depth_grid(self.path, 50)
        finally:
            if old is None:
                del os.environ["CAM2027_DEPTH_DIR"]
            else:
                os.environ["CAM2027_DEPTH_DIR"] = old

    def test_depth_grid_and_relief(self):
        if not relief.depth_available():
            self.skipTest("AI depth model not installed")
        grid, size = relief.depth_grid(self.path, 60, grey_mix=0.25)
        self.assertEqual(size, (200, 100))
        self.assertEqual((len(grid), len(grid[0])), (60, 30))
        values = [v for col in grid for v in col]
        self.assertGreaterEqual(min(values), 0.0)
        self.assertLessEqual(max(values), 1.0)
        self.assertGreater(max(values) - min(values), 0.2)  # une vraie variation de profondeur
        doc = FreeCAD.newDocument("DepthRelief")
        obj, _w = relief.make_relief(doc, self.path, 100.0, 4.0, base=2.0, cells=60, source="depth", smoothing=0)
        self.assertTrue(obj.Shape.isValid())
        self.assertEqual(obj.ReliefSource, "depth")


if __name__ == "__main__":
    unittest.main()
