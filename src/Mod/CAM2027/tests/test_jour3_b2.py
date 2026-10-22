# SPDX-License-Identifier: LGPL-2.1-or-later
"""[B2] Contrôle matière, jour 3 : fausses entailles et entailles manquées, comparées à un calcul exact
(balayage échantillonné finement, surfaces analytiques, fraise boule tangente calculée à la main)."""

import math
import unittest

import FreeCAD
import Part

from cam2027.project import sim

V = FreeCAD.Vector


def reference_sweep(zmap, segments, tool, step=0.002):
    """Matière restante exacte (au pas ``step`` près le long des segments) : la fraise posée à chaque point."""
    import numpy as np

    top = zmap.top.copy()
    X, Y = np.meshgrid(zmap.xs, zmap.ys, indexing="ij")
    r = tool.radius
    for p0, p1 in segments:
        p0, p1 = np.array(p0, float), np.array(p1, float)
        n = max(1, int(math.ceil(np.linalg.norm(p1 - p0) / step)))
        for t in np.linspace(0.0, 1.0, n + 1):
            c = p0 + t * (p1 - p0)
            i0 = max(0, int((c[0] - r - zmap.x0) / zmap.res) - 1)
            i1 = min(zmap.nx, int((c[0] + r - zmap.x0) / zmap.res) + 2)
            j0 = max(0, int((c[1] - r - zmap.y0) / zmap.res) - 1)
            j1 = min(zmap.ny, int((c[1] + r - zmap.y0) / zmap.res) + 2)
            d = np.hypot(X[i0:i1, j0:j1] - c[0], Y[i0:i1, j0:j1] - c[1])
            z = np.where(d <= r + 1e-9, c[2] + tool.lift(np.minimum(d, r)), np.inf)
            np.minimum(top[i0:i1, j0:j1], z, out=top[i0:i1, j0:j1])
    return top


def bowl():
    """Bloc 60 x 60 x 20 creusé d'une calotte de sphère R25 (centre Z35) : fond à Z10, bord R20 à Z20."""
    return Part.makeBox(60, 60, 20).cut(Part.makeSphere(25, V(30, 30, 35)))


def bowl_z(X, Y):
    import numpy as np

    rho2 = (X - 30) ** 2 + (Y - 30) ** 2
    return np.where(rho2 < 400, 35 - np.sqrt(np.maximum(625 - rho2, 0)), 20.0)


def dome():
    """Bloc 60 x 60 x 20 surmonté d'une calotte de sphère R25 (centre Z0) : sommet Z25, bord R15 à Z20."""
    return Part.makeBox(60, 60, 20).fuse(
        Part.makeSphere(25, V(30, 30, 0)).common(Part.makeBox(60, 60, 25, V(0, 0, 20)))).removeSplitter()


def dome_z(X, Y):
    import numpy as np

    rho2 = (X - 30) ** 2 + (Y - 30) ** 2
    return np.maximum(np.sqrt(np.maximum(625 - rho2, 0)), 20.0)


def ball_tip_on_bowl(x, y, r=3.0):
    """Pointe d'une fraise boule tangente au bol (descente exacte) : sphère, arête du bord, dessus plat."""
    rho = math.hypot(x - 30, y - 30)
    zc = -math.inf
    if rho * 25.0 / (25.0 - r) <= 20.0:  # contact sur la calotte
        zc = 35 - math.sqrt((25.0 - r) ** 2 - rho * rho)
    if abs(rho - 20.0) <= r:  # arête du bord (cercle R20 à Z20)
        zc = max(zc, 20.0 + math.sqrt(r * r - (rho - 20.0) ** 2))
    if rho >= 20.0:
        zc = max(zc, 20.0 + r)
    return zc - r


def check(zmap, shapes, tolerance=0.02):
    """Même enchaînement que ``Project.material_check`` après le balayage."""
    heights, low = sim.model_heights(zmap, shapes, lateral=sim.WALL_TOLERANCE)
    low = sim.refine_gouges(zmap, shapes, low, tolerance)
    return sim.compare(zmap, heights, tolerance, gouge_heights=low)


class TestSlopes(unittest.TestCase):
    def test_bull_and_cone_on_slopes_match_exact_sweep(self):
        """Torique et conique sur des pentes : la carte = la fraise posée tous les 2 µm (avant : jusqu'à 0,05 mm
        de matière laissée en trop, entailles de 0,02 à 0,05 mm jamais vues)."""
        import numpy as np

        helix = []
        for k in range(30):
            a0, a1 = k * 0.3, (k + 1) * 0.3
            helix.append(((12 + 4 * math.cos(a0), 12 + 4 * math.sin(a0), 10 - 0.15 * k),
                          (12 + 4 * math.cos(a1), 12 + 4 * math.sin(a1), 10 - 0.15 * (k + 1))))
        cases = {"steep": [((5, 10, 10), (8, 10, 2))], "45": [((5, 10, 10), (13, 10, 2))],
                 "diagonal": [((4, 4, 10), (9, 7, 4))], "helix": helix}
        tools = {"bull": sim.ToolProfile("bull", 6, corner_radius=1.0),
                 "cone90": sim.ToolProfile("cone", 12.7, tip_diameter=0.1, included_angle_deg=90),
                 "cone60": sim.ToolProfile("cone", 12.7, tip_diameter=0.1, included_angle_deg=60)}
        for cname, segs in cases.items():
            for tname, tool in tools.items():
                z = sim.ZMap(-5, -5, 24, 24, 11.0, 0.25)
                z.sweep_arrays(np.array([s[0] for s in segs], float), np.array([s[1] for s in segs], float), tool)
                diff = z.top - reference_sweep(z, segs, tool)
                self.assertLess(float(np.abs(diff).max()), 0.005, (cname, tname, float(diff.max()), float(diff.min())))


class TestCurvedParts(unittest.TestCase):
    def test_part_top_follows_curved_faces(self):
        """Dessus de pièce triangulé = surface exacte à 0,012 mm près sur un bol (concave) et un dôme (convexe) ;
        avant : 0,045 mm au-dessus du bol (fausses entailles), 0,024 mm sous le dôme (entailles manquées)."""
        import numpy as np

        for shape, exact in ((bowl(), bowl_z), (dome(), dome_z)):
            z = sim.ZMap(0, 0, 60, 60, 30, 0.25)
            h = sim.model_heights(z, [shape])
            X, Y = np.meshgrid(z.xs, z.ys, indexing="ij")
            err = h - exact(X, Y)
            self.assertLess(float(np.abs(err).max()), 0.012, (float(err.max()), float(err.min())))

    def test_ball_tangent_in_bowl_is_not_a_gouge(self):
        """Fraise boule 6 mm exactement tangente à un bol : aucune entaille (garde-fou du dessus triangulé plus fin)."""
        import numpy as np

        ball = sim.ToolProfile("ball", 6.0)
        z = sim.ZMap(0, 0, 60, 60, 21.0, 0.25)
        P0, P1 = [], []
        for y in np.arange(4.0, 56.01, 0.5):
            prev = None
            for x in np.arange(4.0, 56.01, 0.1):
                p = (float(x), float(y), ball_tip_on_bowl(x, y))
                if prev is not None:
                    P0.append(prev)
                    P1.append(p)
                prev = p
        z.sweep_arrays(np.array(P0), np.array(P1), ball)
        rep = check(z, [bowl()])
        self.assertGreater(z.removed_volume(), 5000.0)
        self.assertLess(rep["gouge_max"], 0.02, rep)


if __name__ == "__main__":
    unittest.main()
