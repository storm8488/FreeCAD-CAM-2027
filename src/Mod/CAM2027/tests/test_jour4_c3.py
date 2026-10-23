# SPDX-License-Identifier: LGPL-2.1-or-later
"""Flux C3 du jour 4 : mémoire et reprise des angles, chaque défaut reproduit par un test avant sa correction."""

import math
import time
import unittest

import FreeCAD
import Part

V = FreeCAD.Vector


def bump_heights(nx=80, ny=60, width=60.0, length=45.0, height=6.0, base=3.0):
    """Hauteurs d'une bosse gaussienne lue dans une image 8 bits (comme ``test_relief_from_image``)."""
    from cam2027.project import relief

    def bump(x, y):
        return math.exp(-((x - 30.0) ** 2 + (y - 22.5) ** 2) / (2 * 8.0 ** 2))

    grid = [[round(255 * bump(i * width / (nx - 1), j * length / (ny - 1))) / 255.0 for j in range(ny)]
            for i in range(nx)]
    return relief.relief_heights(grid, height, base, smoothing=0)


class TestReliefTiles(unittest.TestCase):
    width, length = 60.0, 45.0

    def test_tessellation_fast(self):
        """Relief de ``test_relief_from_image`` triangulé à l'écart de la finition 3D (tolérance du job / 4) :
        23 s et 3,1 Go d'un seul tenant avant (le test du relief culminait à 6,2 Go), moins d'une seconde
        en tuiles."""
        from cam2027.project import relief

        shape = relief.build_shape(bump_heights(), self.width, self.length)
        t = time.time()
        _verts, tris = shape.copy(True, False).tessellate(0.0025)
        self.assertLess(time.time() - t, 5.0)
        self.assertGreater(len(tris), 10000)

    def test_same_surface(self):
        """Les tuiles sont la même B-spline : mêmes hauteurs que la surface d'un seul tenant, solide valide,
        volume égal à celui du maillage."""
        import Mesh
        from cam2027.project import relief

        heights = bump_heights()
        nx, ny = len(heights), len(heights[0])
        shape = relief.build_shape(heights, self.width, self.length)
        self.assertTrue(shape.isValid() and shape.isClosed() and len(shape.Solids) == 1)
        self.assertGreater(len(shape.Faces), 50)
        whole = Part.BSplineSurface()
        whole.interpolate(heights, 0.0, self.width / (nx - 1.0), 0.0, self.length / (ny - 1.0))
        for x in (0.5, 7.3, 15.0, 22.2, 30.0, 37.9, 44.4, 52.6, 59.5):
            for y in (0.5, 9.1, 18.0, 22.5, 30.3, 40.0, 44.5):
                sec = shape.section(Part.makeLine(V(x, y, -1.0), V(x, y, 20.0)))
                top = max(v.Point.z for v in sec.Vertexes)
                p = V(x, y, top)
                u, v = whole.parameter(p)
                self.assertLess((whole.value(u, v) - p).Length, 1e-6, p)
        self.assertAlmostEqual(shape.Volume, Mesh.Mesh(shape.tessellate(0.01)).Volume, delta=1.0)
        bb = shape.BoundBox
        for got, want in ((bb.XMin, 0.0), (bb.XMax, self.width), (bb.YMin, 0.0), (bb.YMax, self.length),
                          (bb.ZMin, 0.0)):
            self.assertAlmostEqual(got, want, places=6)

    def test_small_grid_one_tile(self):
        """Grille plus petite qu'une tuile : une seule face du dessus, comme avant."""
        from cam2027.project import relief

        heights = [[1.0 + 0.1 * i + 0.05 * j for j in range(6)] for i in range(5)]
        shape = relief.build_shape(heights, 10.0, 12.0)
        self.assertTrue(shape.isValid() and shape.isClosed())
        self.assertEqual(len(shape.Faces), 6)


if __name__ == "__main__":
    unittest.main()
