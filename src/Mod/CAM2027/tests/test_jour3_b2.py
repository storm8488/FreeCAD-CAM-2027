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


class TestOverhang(unittest.TestCase):
    def test_tool_under_an_overhang_is_a_gouge(self):
        """Fraise verticale sous un surplomb : son corps traverse le surplomb, c'est une entaille (avant : rien,
        le point coupé étant hors de la pièce ; et au-delà de 4 000 colonnes la hauteur verticale restait)."""
        part = Part.makeBox(50, 20, 2).fuse(Part.makeBox(10, 20, 2, V(30, 0, 4)))  # dalle 4..6 sur x 30..40
        z = sim.ZMap(0, 0, 50, 20, 8.0, 0.5)
        flat = sim.ToolProfile("flat", 6.0)
        z.sweep((10, 2, 2.0), (10, 18, 2.0), flat)  # sur le dessus du socle, loin du surplomb : rien
        self.assertLess(check(z, [part])["gouge_max"], 0.02)
        z.sweep((35, 2, 3.0), (35, 18, 3.0), flat)  # sous la dalle
        rep = check(z, [part])
        self.assertGreater(rep["gouge_max"], 0.9, rep)  # au moins la demi-épaisseur de la dalle
        x, _y, _z = rep["gouge_at"]
        self.assertTrue(31.5 < x < 38.5, rep["gouge_at"])


class TestHolderOnRamps(unittest.TestCase):
    def test_shank_beside_a_ramp_touches_material(self):
        """Queue (Ø6, 18 mm au-dessus de la pointe) le long d'une rampe à 26,6° : un bloc de matière à 2,5 mm du
        trajet, au milieu de la rampe, est touché plus bas sur la rampe (pointe à Z 16,67, queue à 34,67 sous un
        bloc à Z 35). Avant : pointe prise au point le plus proche (Z 17,5), dépassement -0,5, collision manquée."""
        import numpy as np

        z = sim.ZMap(-5, 0, 20, 20, 0.0, 0.5)
        i, j = int((5.0 - z.x0) / z.res), int((12.5 - z.y0) / z.res)
        self.assertAlmostEqual(float(z.xs[i]), 5.25)
        z.top[i, j] = 35.0  # colonne (5,25 ; 12,75)
        p0, p1 = (0.0, 10.0, 20.0), (10.0, 10.0, 15.0)
        # pointe au plus bas sous le disque de la queue (rayon 3) au-dessus de cette colonne
        x, y = float(z.xs[i]), float(z.ys[j])
        t = (x + math.sqrt(9.0 - (y - 10.0) ** 2)) / 10.0
        expected = 35.0 - (20.0 - 5.0 * t + 18.0)
        self.assertGreater(expected, 0.2)
        excess, at = sim.material_excess(z, p0, p1, 3.0, 18.0)
        self.assertAlmostEqual(excess, expected, places=6)
        self.assertIsNotNone(at)
        many = sim.material_excess_many(z, np.array([p0]), np.array([p1]), 3.0, 18.0)
        self.assertAlmostEqual(float(many[0]), expected, places=6)
        self.assertTrue(z.excess_any(np.array([p0]), np.array([p1]), 3.0, 18.0, 0.05, True))
        # montée sur la même rampe : même colonne touchée au même point bas
        self.assertAlmostEqual(sim.material_excess(z, p1, p0, 3.0, 18.0)[0], expected, places=6)


class TestReport(unittest.TestCase):
    def test_nothing_simulated_is_not_reported_as_no_gouge(self):
        """Toutes les opérations sautées (axe A) : le rapport ne dit pas « aucune entaille trouvée »."""
        from cam2027.gui.commands import material_report_text
        from cam2027.i18n import Msg

        rep = {"resolution": 0.5, "removed_volume": 0.0, "gouge_max": 0.0, "tolerance": 0.02, "gouge_at": None,
               "part_cells": 0, "rapid_hits": 0, "simulated": [], "approximations": [],
               "skipped": [("Wrap", Msg("uses the A axis (wrapped)"))]}
        text = material_report_text(rep)
        self.assertNotIn("No gouge found", text)
        self.assertIn("No operation simulated: gouges not checked", text)
        self.assertIn("Not simulated: Wrap", text)
        rep["simulated"] = ["Facing"]
        self.assertIn("No gouge found", material_report_text(rep))


class TestRestStock(unittest.TestCase):
    def test_drilling_cycles_remove_stock_for_rest_machining(self):
        """Reprise de matière après un perçage en cycles (G81) : les trous sont enlevés du brut restant, comme au
        contrôle matière (avant : cycles ignorés, brut intact au droit des trous)."""
        import Path as P
        from cam2027.project import rest
        from cam2027.tools.library import starter_library

        lib = starter_library()
        drill = lib.search("3 mm drill")[0]

        class Obj(object):
            Name = "Drill"
            Path = P.Path([P.Command("G0", {"X": 10.0, "Y": 10.0, "Z": 15.0}), P.Command("G99"),
                           P.Command("G81", {"X": 10.0, "Y": 10.0, "Z": -5.0, "R": 12.0, "F": 300.0}),
                           P.Command("G81", {"X": 30.0, "Y": 20.0}), P.Command("G0", {"Z": 15.0})])

        class BoxStock(object):
            pass

        class Job(object):
            Stock = BoxStock()

        class Lib(object):
            def resolve_assembly(self, _aid):
                return None, drill, None

        class Proj(object):
            job = Job()
            library = Lib()
            registry = {"Drill": {"assembly_id": "a"}}

            def stock_bounds(self):
                return {"xmin": 0.0, "ymin": 0.0, "xmax": 40.0, "ymax": 30.0, "zmax": 11.0}

        zmap = rest.remaining_stock(Proj(), [Obj()], resolution=0.25)
        for x, y in ((10.0, 10.0), (30.0, 20.0)):
            i, j = int((x - zmap.x0) / zmap.res), int((y - zmap.y0) / zmap.res)
            self.assertLess(float(zmap.top[i, j]), -4.0, (x, y))
        self.assertAlmostEqual(float(zmap.top.max()), 11.0)


if __name__ == "__main__":
    unittest.main()
