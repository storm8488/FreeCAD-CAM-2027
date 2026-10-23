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


class TestPencilFilter(unittest.TestCase):
    def test_threads_equal_full_kernel(self):
        """Filtre de la boule réparti sur des fils, une passe pour deux lignes symétriques du noyau : identique au
        bit près au noyau 2D entier de scipy et à un seul fil (boule de 6 mm sur une carte à marches)."""
        import numpy as np
        from scipy import ndimage
        from cam2027.project import pencil

        rng = np.random.default_rng(7)
        H = np.cumsum(rng.normal(size=(160, 130)), axis=1) * 0.05 + np.where(rng.random((160, 130)) < 0.01, 4.0, 0.0)
        radius, res = 3.0, 0.1
        foot, prof = pencil.ball_kernel(radius, res)
        full_d = ndimage.grey_dilation(H, footprint=foot, structure=prof, mode="nearest")
        full_e = ndimage.grey_erosion(full_d, footprint=foot, structure=prof, mode="nearest")
        workers = pencil.FILTER_WORKERS
        try:
            for w in (1, 3, 8):
                pencil.FILTER_WORKERS = w
                self.assertTrue(np.array_equal(pencil.tip_heights(H, radius, res), full_d), w)
                self.assertTrue(np.array_equal(pencil.envelope(full_d, radius, res), full_e), w)
        finally:
            pencil.FILTER_WORKERS = workers


class TestPencilDrop(unittest.TestCase):
    def test_one_tree_for_all_passes(self):
        """Chute de la boule : le modèle OpenCamLib n'est indexé qu'une fois pour toutes les passes (``setSTL``
        reconstruisait l'arbre des triangles pour chacune : 68 des 76 s sur le chauffage Vz330, 178 passes) ;
        mêmes points qu'avec un ``PathDropCutter`` neuf par passe."""
        from cam2027.project import pencil

        ocl = pencil._ocl()
        calls = []

        class Counting(object):
            def __init__(self):
                self._pdc = ocl.PathDropCutter()

            def setSTL(self, stl):
                calls.append(1)
                return self._pdc.setSTL(stl)

            def __getattr__(self, name):
                return getattr(self._pdc, name)

        class Proxy(object):
            PathDropCutter = Counting

            def __getattr__(self, name):
                return getattr(ocl, name)

        shape = Part.makeBox(40, 30, 10).cut(Part.makeCylinder(8, 10, V(20, 15, 4)))
        lines = [[(2.0 + k, 2.0), (2.0 + k, 28.0), (20.0, 15.0 + 0.5 * k)] for k in range(12)]
        import numpy as np

        lines = [np.array(l) for l in lines]
        plain = pencil._ocl
        pencil._ocl = lambda: Proxy()
        try:
            got = pencil.drop_ball([shape], lines, 6.0, -1.0)
        finally:
            pencil._ocl = plain
        self.assertEqual(len(calls), 1)
        want = []
        stl = ocl.STLSurf()
        verts, tris = shape.copy(True, False).tessellate(0.01)
        for a, b, c in tris:
            va, vb, vc = verts[a], verts[b], verts[c]
            stl.addTriangle(ocl.Triangle(ocl.Point(va.x, va.y, va.z), ocl.Point(vb.x, vb.y, vb.z),
                                         ocl.Point(vc.x, vc.y, vc.z)))
        cutter = ocl.BallCutter(6.0, 50.0)
        for line in lines:
            pdc = ocl.PathDropCutter()
            pdc.setSTL(stl)
            pdc.setCutter(cutter)
            pdc.setZ(-1.0)
            pdc.setSampling(pencil.SAMPLING)
            path = ocl.Path()
            for a, b in zip(line[:-1], line[1:]):
                path.append(ocl.Line(ocl.Point(float(a[0]), float(a[1]), 0.0), ocl.Point(float(b[0]), float(b[1]), 0.0)))
            pdc.setPath(path)
            pdc.run()
            want.append(pencil._simplify([(p.x, p.y, p.z) for p in pdc.getCLPoints()]))
        self.assertEqual(got, want)


if __name__ == "__main__":
    unittest.main()
