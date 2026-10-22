# SPDX-License-Identifier: LGPL-2.1-or-later
"""Flux B4 du jour 3 : défauts des fonctions de la nuit 2, chacun reproduit par un test avant sa correction."""

import math
import unittest

import FreeCAD
import Part

from cam2027.project.machine import MachineProfile
from cam2027.project.project import Project
from cam2027.tools.library import starter_library

V = FreeCAD.Vector


def machine(**kw):
    return MachineProfile("test", controller="grbl", post_processor="grbl",
                          post_processor_args="--no-show-editor --precision=3", **kw)


class _Ops(object):
    """Projet minimal pour ``timing.estimate`` : des objets Path et un profil machine."""

    def __init__(self, ops, profile):
        self._ops, self.machine = ops, profile

    def operations(self):
        return self._ops


class TestTiming(unittest.TestCase):
    def tearDown(self):
        for name in list(FreeCAD.listDocuments()):
            FreeCAD.closeDocument(name)

    def test_inverse_time_moves(self):
        """G93 (rotatif continu, gravure enroulée) : F = 1 / durée en minutes. Avant : avance lue comme une vitesse
        en mm/s sur la seule longueur X Y Z, rotation pure comptée 0 s."""
        import Path
        from cam2027.project import timing, wrap

        doc = FreeCAD.newDocument("B4Timing")
        op = doc.addObject("Path::Feature", "Rotary")
        # 2 s de rotation pure (F 30 / min), puis 1 s pour 10 mm le long de X avec rotation (F 60 / min)
        lines = ["G0 X0 Y0 Z5 A0", "G93", "G1 X0 A90 Z5 F30", "G1 X10 A180 Z5 F60", "G94",
                 "G1 X20 F600"]  # retour en G94 : 10 mm à 600 mm/min (1 s + accélération)
        path = Path.Path()
        path.setFromGCode("\n".join(wrap.path_gcode(lines)))
        op.Path = path
        est = timing.estimate(_Ops([op], machine()))
        accel = est["acceleration"]
        v = 10.0
        self.assertAlmostEqual(est["total"], 2.0 + 1.0 + 10.0 / v + v / accel, places=3)
        self.assertAlmostEqual(est["without_accel"], 2.0 + 1.0 + 1.0, places=3)


class TestKeepOutPattern(unittest.TestCase):
    def tearDown(self):
        for name in list(FreeCAD.listDocuments()):
            FreeCAD.closeDocument(name)

    def test_pattern_copies_hop_over_zone(self):
        """Poche sur deux fonds (rapide de l'un à l'autre), copiée 60 mm plus loin : le rapide de la copie traverse une
        zone interdite que celui de l'original ne touche pas. Il doit passer au-dessus comme ceux des opérations.
        Avant : le motif recopiait le parcours de l'original sans la correction des rapides."""
        import os
        import tempfile
        from cam2027.project import keepout, patterns, sim

        path = os.path.join(tempfile.mkdtemp(prefix="cam2027-b4k-"), "plate.step")
        plate = Part.makeBox(170, 40, 10).cut(Part.makeBox(20, 14, 4, V(10, 12, 6)))
        plate.cut(Part.makeBox(20, 14, 4, V(80, 12, 6))).exportStep(path)
        lib = starter_library()
        proj = Project.create("B4 keep-out pattern", lib, machine())
        part = proj.import_model(path, label="Plate").objects[0]
        proj.create_job([part], stock={"kind": "box_margins", "xy": 2.0, "z_top": 0.0, "z_bottom": 0.0})
        clone = proj.job.Model.Group[0]
        floor = ["Face%d" % i for i, f in enumerate(clone.Shape.Faces, 1)
                 if f.Surface.__class__.__name__ == "Plane" and abs(f.BoundBox.ZMax - 6.0) < 1e-6
                 and abs(f.BoundBox.ZMin - 6.0) < 1e-6]
        t = lib.search("6 mm flat end mill")[0]
        op, _r = proj.add_operation("pocket", "Pocket", lib.assemblies_for_tool(t.id)[0].id, t.presets[0].id,
                                    base=[(clone, floor)], params={"StepDown": 2.0})
        self.assertEqual(len(floor), 2)
        zone = keepout.add_zone(proj.doc, 110.0, -20.0, 114.0, 60.0, 30.0, 10.0, label="Zone")
        patterns.add_pattern(proj, [op], {"Kind": "Grid", "Columns": 2, "Rows": 1, "StepX": 60.0, "StepY": 0.0})
        proj.compute()
        boxes = [(zone.Label, zone.Shape.BoundBox)]
        crossing = []
        pos = None
        for obj in proj.operations():
            segs, pos = sim.path_segments(obj.Path.Commands, pos)
            crossing += [(p0, p1) for rapid, p0, p1 in segs
                         if rapid and keepout.blocking_top(p0, p1, boxes, 3.0, 0.0) is not None]
        self.assertEqual(crossing, [])
        self.assertEqual(keepout.issues(proj), [])
        # mouvements de coupe inchangés : 2 fois ceux de l'original
        cuts = [c for c in proj.operations()[0].Path.Commands if c.Name in ("G1", "G2", "G3")]
        self.assertEqual(len(cuts), 2 * len([c for c in op.Path.Commands if c.Name in ("G1", "G2", "G3")]))


    def test_trimmed_links_hop_over_zone(self):
        """Contour limité à « dehors » d'un coin : la liaison recalculée d'un bout gardé à l'autre (hauteur de
        dégagement) passait à travers une zone interdite posée sur le coin retiré. Elle passe au-dessus maintenant."""
        import os
        import tempfile
        from cam2027.project import keepout, sim, trim

        path = os.path.join(tempfile.mkdtemp(prefix="cam2027-b4t-"), "plate.step")
        Part.makeBox(100, 40, 10).exportStep(path)
        lib = starter_library()
        proj = Project.create("B4 keep-out trim", lib, machine())
        part = proj.import_model(path, label="Plate").objects[0]
        proj.create_job([part], stock={"kind": "box_margins", "xy": 4.0, "z_top": 1.0, "z_bottom": 0.0})
        clone = proj.job.Model.Group[0]
        t = lib.search("6 mm flat end mill")[0]
        op, _r = proj.add_operation("profile", "Contour", lib.assemblies_for_tool(t.id)[0].id, t.presets[0].id,
                                    base=[(clone, [])], params={"FinalDepth": 5.0, "StepDown": 5.0, "Side": "Outside"})
        # coin avant gauche retiré : liaison en diagonale de (30, -3) à (-3, 10), au-dessus d'une zone posée sur le coin
        # de la pièce, hors de portée des coupes (fraise à X -3 / Y -3, zone élargie du rayon : X, Y >= -1)
        zone = keepout.add_zone(proj.doc, 2.0, 2.0, 15.0, 6.0, 30.0, 0.0, label="Zone")
        dress = trim.set_limit(proj, op, trim.rectangle(-50, -50, 30, 10), inside=False, source="rectangle")
        proj.compute()
        boxes = [(zone.Label, zone.Shape.BoundBox)]
        segs, _pos = sim.path_segments(dress.Path.Commands)
        self.assertTrue(any(not rapid for rapid, _a, _b in segs))
        crossing = [(p0, p1) for rapid, p0, p1 in segs if rapid and keepout.blocking_top(p0, p1, boxes, 3.0, 0.0) is not None]
        self.assertEqual(crossing, [])
        self.assertEqual(keepout.issues(proj), [])


class TestHolesBodies(unittest.TestCase):
    def tearDown(self):
        for name in list(FreeCAD.listDocuments()):
            FreeCAD.closeDocument(name)

    def test_holes_of_every_body(self):
        """Pièce en deux corps (le chauffage de l'utilisateur en a deux), un trou Ø3 débouchant dans chacun : le
        perçage intelligent les trouve et les perce tous les deux. Avant : seul le premier corps du job était lu."""
        from cam2027.project import holes

        lib = starter_library()
        proj = Project.create("B4 holes bodies", lib, machine())
        objs = []
        for k, x in enumerate((0.0, 40.0)):
            o = proj.doc.addObject("Part::Feature", "Body%d" % k)
            o.Shape = Part.makeBox(30, 30, 10, V(x, 0, 0)).cut(Part.makeCylinder(1.5, 10, V(x + 15, 15, 0)))
            objs.append(o)
        proj.doc.recompute()
        proj.create_job(objs, stock={"kind": "box_margins", "xy": 2.0, "z_top": 0.0, "z_bottom": 0.0})
        found = holes.find_job_holes(proj)
        self.assertEqual(sorted((round(h.x, 3), round(h.y, 3)) for h in found), [(15.0, 15.0), (55.0, 15.0)])
        steps, notes = holes.plan(lib, found)
        self.assertEqual(len(holes.groups(found)), 1)
        ops = holes.apply_plan(proj, proj.job.Model.Group[0], steps)
        res = {r["name"]: r for r in proj.compute()}
        self.assertTrue(all(r["valid"] for r in res.values()), res)
        rep = proj.material_check(resolution=0.25)
        self.assertEqual(rep["gouge_max"], 0.0, rep)
        self.assertEqual(rep["rapid_hits"], 0, rep)
        z = proj.last_zmap
        for x in (15.0, 55.0):
            top = float(z.top[int(round((x - z.xs[0]) / z.res)), int(round((15.0 - z.ys[0]) / z.res))])
            self.assertLess(top, 0.0, x)  # percé jusqu'en dessous du fond


class TestStackedBodies(unittest.TestCase):
    """Pièce en deux corps, l'un posé sur l'autre (chauffage Vz330 de l'utilisateur) : la face du dessous n'est
    accessible par le dessus qu'en dehors de l'empreinte du corps du dessus."""

    def tearDown(self):
        for name in list(FreeCAD.listDocuments()):
            FreeCAD.closeDocument(name)

    def _project(self, name, plate, block):
        lib = starter_library()
        proj = Project.create(name, lib, machine())
        objs = []
        for label, shape in (("Plate", plate), ("Block", block)):
            o = proj.doc.addObject("Part::Feature", label)
            o.Shape = shape
            objs.append(o)
        proj.doc.recompute()
        proj.create_job(objs, stock={"kind": "box_margins", "xy": 2.0, "z_top": 0.0, "z_bottom": 0.0})
        return proj, lib

    def test_flat_finish_skips_the_block_footprint(self):
        """Finition des plats : le dessus de la plaque (Z 10) est fini autour du bloc posé dessus, pas sous lui ; le
        dessus du bloc (Z 20) aussi. Avant : la passe traversait le bloc (entaille de 10 mm ; 5 mm sur le chauffage)."""
        from cam2027.gui.commands import default_params

        proj, lib = self._project("B4 stacked flat", Part.makeBox(60, 40, 10), Part.makeBox(20, 20, 10, V(20, 10, 10)))
        mill = lib.search("6 mm flat end mill")[0]
        op, _rec = proj.add_operation("flat3d", "Flats", lib.assemblies_for_tool(mill.id)[0].id, mill.presets[0].id,
                                      base=[(m, []) for m in proj.job.Model.Group],
                                      params=default_params("flat3d", mill, mill.presets[0].resolve(mill)))
        res = {r["name"]: r for r in proj.compute()}
        self.assertTrue(res["Flats"]["valid"], res)
        rep = proj.material_check(resolution=0.25)
        self.assertEqual(rep["gouge_max"], 0.0, rep)
        cuts = [c.Parameters for c in op.Path.Commands if c.Name == "G1" and "X" in c.Parameters]
        self.assertTrue(any(abs(p["Z"] - 10.0) < 1e-6 for p in cuts))  # plaque finie autour du bloc
        self.assertTrue(any(abs(p["Z"] - 20.0) < 1e-6 for p in cuts))  # dessus du bloc fini
        near = [(p["X"], p["Y"]) for p in cuts if abs(p["Z"] - 10.0) < 1e-6
                and math.hypot(max(20.0 - p["X"], 0.0, p["X"] - 40.0), max(10.0 - p["Y"], 0.0, p["Y"] - 30.0)) < 3.0 - 0.02]
        self.assertEqual(near, [])  # centre de la fraise jamais à moins d'un rayon du bloc

    def test_holes_under_a_body_left_out(self):
        """Trou débouchant de la plaque sous le bloc : écarté (le foret traversait le bloc) ; l'autre trou est percé."""
        from cam2027.project import holes

        plate = Part.makeBox(60, 40, 10).cut(Part.makeCylinder(1.5, 10, V(30, 20, 0))).cut(Part.makeCylinder(1.5, 10, V(8, 8, 0)))
        proj, lib = self._project("B4 stacked holes", plate, Part.makeBox(20, 20, 10, V(20, 10, 10)))
        covered = []
        found = holes.find_job_holes(proj, covered)
        self.assertEqual([(round(h.x, 3), round(h.y, 3)) for h in found], [(8.0, 8.0)])
        self.assertEqual([(round(h.x, 3), round(h.y, 3)) for h in covered], [(30.0, 20.0)])
        steps, _notes = holes.plan(lib, found)
        holes.apply_plan(proj, proj.job.Model.Group[0], steps)
        proj.compute()
        rep = proj.material_check(resolution=0.25)
        self.assertEqual(rep["gouge_max"], 0.0, rep)  # bloc intact (le brut boîte monte au dessus du bloc : les
        # rapides du perçage traversent le brut au-dessus de la plaque, sans rapport avec ce correctif)


def ball_penetration(commands, boxes, radius, step=0.01):
    """Pénétration maximale (mm, distance normale) d'une boule de rayon ``radius`` (pointe = point du parcours) dans
    une union de boîtes ``(xmin, ymin, zmin, xmax, ymax, zmax)`` le long des mouvements de coupe (calcul exact)."""
    import numpy as np
    from cam2027.project import sim

    segs, _pos = sim.path_segments(commands)
    P0 = np.array([s[1] for s in segs if not s[0]])
    P1 = np.array([s[2] for s in segs if not s[0]])
    worst, at = 0.0, None
    n = np.maximum(1, np.ceil(np.linalg.norm(P1 - P0, axis=1) / step).astype(int))
    idx = np.repeat(np.arange(len(P0)), n + 1)
    t = np.concatenate([np.linspace(0, 1, k + 1) for k in n])
    pts = P0[idx] + (P1[idx] - P0[idx]) * t[:, None]
    centre = pts + np.array([0.0, 0.0, radius])
    dist = np.full(len(pts), np.inf)
    for b in boxes:
        lo, hi = np.array(b[:3]), np.array(b[3:])
        d = np.linalg.norm(np.maximum(np.maximum(lo - centre, 0.0), centre - hi), axis=1)
        inside = np.all((centre > lo) & (centre < hi), axis=1)
        dist = np.minimum(dist, np.where(inside, 0.0, d))
    pen = radius - dist
    k = int(np.argmax(pen))
    return float(pen[k]), tuple(np.round(pts[k], 3))


class TestScallopWalls(unittest.TestCase):
    def tearDown(self):
        for name in list(FreeCAD.listDocuments()):
            FreeCAD.closeDocument(name)

    def test_no_gouge_at_vertical_wall(self):
        """Marche de 10 mm à paroi verticale : deux points voisins d'une passe (0,1 mm en XY) sont l'un sur l'arête
        (boule posée sur le bord), l'autre au pied de la paroi ; la droite qui les relie entrait dans l'arête
        (0,05 mm sur l'ER16 de l'utilisateur). Pénétration exacte de la boule dans la pièce <= 0,005 mm."""
        import os
        import tempfile
        from cam2027.gui.commands import default_params

        boxes = [(0.0, 0.0, 0.0, 40.0, 30.0, 5.0), (20.0, 0.0, 5.0, 40.0, 30.0, 15.0)]
        path = os.path.join(tempfile.mkdtemp(prefix="cam2027-b4s-"), "step.step")
        Part.makeBox(40, 30, 5).fuse(Part.makeBox(20, 30, 10, V(20, 0, 5))).removeSplitter().exportStep(path)
        lib = starter_library()
        proj = Project.create("B4 scallop wall", lib, machine())
        part = proj.import_model(path, label="Step").objects[0]
        proj.create_job([part], stock={"kind": "box_margins", "xy": 2.0, "z_top": 1.0, "z_bottom": 0.0})
        ball = lib.search("6 mm ball end mill")[0]
        op, _rec = proj.add_operation("scallop", "Scallop", lib.assemblies_for_tool(ball.id)[0].id, ball.presets[0].id,
                                      base=[(proj.job.Model.Group[0], [])],
                                      params=default_params("scallop", ball, ball.presets[0].resolve(ball)))
        res = {r["name"]: r for r in proj.compute()}
        self.assertTrue(res["Scallop"]["valid"], res)
        pen, at = ball_penetration(op.Path.Commands, boxes, 3.0)
        self.assertLess(pen, 0.005, (pen, at))


    def test_large_part_coarser_grid(self):
        """Grande pièce : la grille de distance dépasse la limite de points. Avant : refus (« augmentez l'intervalle
        d'échantillonnage » sur le plateau 220 x 220 de l'utilisateur) ; maintenant la grille, qui ne porte que la
        distance le long de la surface, grossit jusqu'à pas / 4, et les points des passes restent à l'intervalle
        demandé (hauteurs OpenCamLib). Limite abaissée pour le test : mêmes rapports sur une petite pièce."""
        from cam2027.project import scallop

        shape = Part.makeBox(40, 30, 5).fuse(Part.makeBox(20, 30, 10, V(20, 0, 5))).removeSplitter()
        surface = scallop.Surface([shape], 6.0, 3.0)
        saved = scallop.MAX_GRID_POINTS
        scallop.MAX_GRID_POINTS = 60000  # 40 x 30 mm à 0,1 mm : 121 000 points
        try:
            res = scallop.compute_passes(surface, (0.0, 0.0, 40.0, 30.0), 6.0, 3.0, 0.02, sample=0.1)
        finally:
            scallop.MAX_GRID_POINTS = saved
        self.assertGreater(res["grid"].g, 0.1)
        self.assertLessEqual(res["grid"].g, res["stepover"] / scallop.GRID_PER_STEP + 1e-9)
        self.assertLessEqual(res["grid"].z.size, 60000)
        self.assertAlmostEqual(res["sample"], 0.1)
        self.assertGreater(len(res["shallow"]), 10)
        self.assertEqual(res["uncovered"], 0)


def order_passes_reference(lines):
    """Ordre des passes de ``scallop`` avant l'optimisation (recherche dans toutes les passes restantes)."""
    import numpy as np

    todo = [np.asarray(l) for l in lines if len(l) >= 2]
    out, cur = [], None
    while todo:
        best, best_d, best_line = 0, None, None
        for k, line in enumerate(todo):
            if cur is None:
                cand, d = line, 0.0
            elif np.allclose(line[0], line[-1]):
                dd = np.hypot(*(line[:-1] - cur).T)
                m = int(np.argmin(dd))
                cand, d = np.vstack([line[m:-1], line[:m + 1]]), float(dd[m])
            else:
                d0, d1 = float(np.hypot(*(line[0] - cur))), float(np.hypot(*(line[-1] - cur)))
                cand, d = (line, d0) if d0 <= d1 else (line[::-1], d1)
            if best_d is None or d < best_d:
                best, best_d, best_line = k, d, cand
            if cur is None:
                break
        todo.pop(best)
        out.append(best_line)
        cur = best_line[-1]
    return out


class TestScallopOrder(unittest.TestCase):
    def test_same_order_as_reference(self):
        """Ordre des passes par arbre = ordre de la recherche exhaustive d'avant, égalités comprises (points sur une
        grille entière : beaucoup de distances égales), boucles, lignes ouvertes, points isolés doublés."""
        import random
        import numpy as np
        from cam2027.project import scallop

        rnd = random.Random(7)
        for _case in range(4):
            lines = []
            for _k in range(300):
                x, y = rnd.randint(0, 40), rnd.randint(0, 40)
                kind = rnd.random()
                if kind < 0.3:  # boucle
                    r = rnd.randint(1, 4)
                    pts = [(x + r * math.cos(a), y + r * math.sin(a)) for a in np.linspace(0, 2 * math.pi, 9)]
                    pts[-1] = pts[0]
                elif kind < 0.4:  # point isolé doublé (ligne de crête d'un seul point)
                    pts = [(x, y), (x, y)]
                else:
                    pts = [(x + i, y + rnd.randint(-1, 1)) for i in range(rnd.randint(2, 6))]
                lines.append(np.array(pts, dtype=float))
            ref = order_passes_reference(lines)
            new = scallop.order_passes(lines)
            self.assertEqual(len(ref), len(new))
            for a, b in zip(ref, new):
                self.assertTrue(np.array_equal(a, b))


class TestRotarySpiral(unittest.TestCase):
    """Finition 3D rotative en spirale (A tourne sans arrêt, X avance d'un pas par tour)."""

    @classmethod
    def setUpClass(cls):
        from tests import test_nuit_s4

        test_nuit_s4.TestRotary.setUpClass.__func__(cls)  # même pièce : cylindre R20, poche R18, bosse

    _project = __import__("tests.test_nuit_s4", fromlist=["x"]).TestRotary._project
    _speeds = __import__("tests.test_nuit_s4", fromlist=["x"]).TestRotary._speeds

    def test_no_gouge_at_deep_walls(self):
        """Gorge annulaire (X 30..50) et poche en secteur (X 55..75, |A| <= 0,3 rad, parois radiales) de 6 mm de
        profondeur, plus que le rayon de la boule : à la paroi, deux points voisins d'une passe (lignes le long de
        l'axe : parois de la gorge ; spirale : parois du secteur) sont l'un sur l'arête, l'autre 6 mm plus bas, et la
        droite qui les relie entrait dans l'arête (0,26 mm mesurés sur la gorge avant le correctif). Carte radiale fine : aucune entaille au-delà de 0,01 mm (flèche d'une corde de 0,25 mm
        sur l'arc de la boule autour d'une arête : 0,003 mm)."""
        import os
        import tempfile
        import numpy as np
        from cam2027.project import rotary
        from cam2027.project.machine import RotaryAxis

        path = os.path.join(tempfile.mkdtemp(prefix="cam2027-b4r-"), "groove.step")
        cyl = Part.makeCylinder(20.0, 80.0, V(0, 0, 0), V(1, 0, 0))
        groove = Part.makeCylinder(21.0, 20.0, V(30, 0, 0), V(1, 0, 0)).cut(Part.makeCylinder(14.0, 20.0, V(30, 0, 0), V(1, 0, 0)))
        ring = Part.makeCylinder(25.0, 20.0, V(55, 0, 0), V(1, 0, 0)).cut(Part.makeCylinder(14.0, 20.0, V(55, 0, 0), V(1, 0, 0)))
        s, c = 30.0 * math.sin(0.3), 30.0 * math.cos(0.3)
        wedge = Part.Face(Part.makePolygon([V(55, 0, 0), V(55, s, c), V(55, -s, c), V(55, 0, 0)])).extrude(V(20, 0, 0))
        cyl.cut(groove).cut(ring.common(wedge)).removeSplitter().exportStep(path)

        def part_radius(x, theta):
            x, theta = np.broadcast_arrays(np.asarray(x, dtype=float), np.asarray(theta, dtype=float))
            t = np.mod(theta + math.pi, 2 * math.pi) - math.pi
            low = ((x >= 30) & (x <= 50)) | ((x >= 55) & (x <= 75) & (np.abs(t) <= 0.3))
            return np.where(low, 14.0, 20.0)

        lib = starter_library()
        profile = machine()
        profile.rotary = RotaryAxis(present=True, about="X", center_offset_mm=(0.0, 0.0), positive_direction="right_hand",
                                    min_deg=-100000.0, max_deg=100000.0)
        proj = Project.create("Rotary deep walls", lib, profile)
        part = proj.import_model(path, label="Groove").objects[0]
        proj.create_job([part], stock={"kind": "cylinder_x", "radius": 21.0, "length": 84.0, "x_start": -2.0,
                                       "center": (0.0, 0.0)})
        ball = lib.search("6 mm ball end mill")[0]
        asm = lib.assemblies_for_tool(ball.id)[0]
        worst = []  # (motif, écart minimal, X, angle) par fenêtre
        for spiral, windows in ((False, ((27.0, 33.0, -0.3, 0.3), (47.0, 53.0, 2.0, 2.6))),
                                (True, ((60.0, 70.0, -0.6, 0.6),))):
            op, _rec = rotary.add_operation(proj, "rotary3d", "Walls %s" % spiral, asm.id, ball.presets[0].id,
                                            params={"stepover": 0.5, "sample": 0.25, "spiral": spiral})
            _l, moves = rotary.generate(proj, op)
            for x0, x1, t0, t1 in windows:
                rmap = rotary.RadialMap(x0, x1, t0, t1, 21.0, res_x=0.02)
                rmap.sweep_moves(moves, 21.0, "ball", 3.0)
                X, T = np.meshgrid(rmap.xs, rmap.ts, indexing="ij")
                err = rmap.r - part_radius(X, T)
                k = np.unravel_index(int(np.argmin(err)), err.shape)
                worst.append(("spiral" if spiral else "lines", round(float(err.min()), 4), float(X[k]), float(T[k])))
        proj.close()
        self.assertTrue(all(w[1] > -0.01 for w in worst), worst)

    def test_spiral_finishing(self):
        """Spirale : refusée si l'axe A a une course limitée trop courte ; sinon une seule passe continue (A croissant
        sur les mouvements de coupe, presque aucun rapide), carte radiale = pièce à ± 0,05 mm, aucune entaille,
        vitesse réelle = avance à 2 %, export sans erreur."""
        import numpy as np
        from cam2027.i18n import UserError
        from cam2027.project import rotary
        from tests.test_nuit_s4 import ROT_STOCK, ROT_POCKET_HALF, rotary_part_radius

        proj, lib = self._project("Rotary spiral")
        ball = lib.search("6 mm ball end mill")[0]
        asm = lib.assemblies_for_tool(ball.id)[0]
        params = {"stepover": 0.5, "sample": 0.25, "spiral": True}
        with self.assertRaises(UserError) as ctx:  # A de -720 à 720° : 162 tours n'y tiennent pas
            rotary.add_operation(proj, "rotary3d", "Spiral", asm.id, ball.presets[0].id, params=params)
        self.assertIn("spiral", str(ctx.exception))
        machine = proj.machine
        machine.rotary.min_deg, machine.rotary.max_deg = -100000.0, 100000.0
        proj.set_machine(machine)
        op, rec = rotary.add_operation(proj, "rotary3d", "Spiral", asm.id, ball.presets[0].id, params=params)
        self.assertEqual(rec["info"]["levels"], 1)
        _l, moves = rotary.generate(proj, op)
        cuts = [m for m in moves if m[0] == "cut"]
        self.assertLess(sum(1 for m in moves if m[0] == "rapid"), 10)
        ys = np.array([m[2] for m in cuts])
        self.assertTrue((np.diff(ys) >= -1e-9).all())  # A ne revient jamais en arrière
        self.assertGreater(ys[-1] / (2 * math.pi * ROT_STOCK), 160)  # 80 mm / 0,5 mm par tour
        text, analysis, issues = proj.preview_gcode()
        self.assertNotIn("error", [lvl for lvl, _m in issues], issues)
        self.assertGreater(self._speeds(text, {"Spiral": (rec["values"]["feed_mm_min"], rec["values"]["plunge_feed_mm_min"])}), 1000)
        for window in ((14.0, 26.0, math.pi - 1.0, math.pi + 1.0), (52.0, 68.0, -0.45, 0.45)):
            x0, x1, t0, t1 = window
            rmap = rotary.RadialMap(x0, x1, t0, t1, ROT_STOCK, res_x=0.1)
            rmap.sweep_moves(moves, ROT_STOCK, "ball", 3.0)
            X, T = np.meshgrid(rmap.xs, rmap.ts, indexing="ij")
            part = rotary_part_radius(X, T)
            err = rmap.r - part
            dist_wall = np.abs(np.abs(np.mod(T, 2 * math.pi) - math.pi) - ROT_POCKET_HALF) * 18.0
            pocket_floor = (part < 18.5) & (dist_wall > 3.5) & (X > 13.5) & (X < 26.5)
            cylinder = (np.abs(part - 20.0) < 1e-9) & (dist_wall > 3.5) & (np.hypot(X - 60, T * 20) > 9.5)
            for name, sel in (("pocket floor", pocket_floor), ("cylinder", cylinder)):
                if sel.any():
                    self.assertLess(float(np.abs(err[sel]).max()), 0.05, (name, window, float(np.abs(err[sel]).max())))
            self.assertGreater(float(err.min()), -0.05, window)
        proj.close()


def run_probe(lines, start, boxes, tip):
    """GRBL simplifié : exécute un programme de palpage depuis ``start`` (position machine de la pointe : centre en
    XY, bas en Z) contre des boîtes pleines ``(xmin, ymin, zmin, xmax, ymax, zmax)`` ; retourne l'origine (repère
    G54 ou G92, en coordonnées machine). Chaque G38.2 doit toucher (sinon alarme : exception)."""
    import re

    r = tip / 2.0
    m = list(start)
    origin = [0.0, 0.0, 0.0]
    relative = False
    for raw in lines:
        line = re.sub(r"\(.*?\)", "", raw).strip().upper()
        words = dict((w[0], float(w[1:])) for w in line.split()[1:] if w[0] in "XYZLP")
        g = line.split()[0] if line else ""
        if g in ("G90", "G91"):
            relative = g == "G91"
            continue
        if g in ("G10", "G92"):
            for k, axis in enumerate("XYZ"):
                if axis in words:
                    origin[k] = m[k] - words[axis]
            continue
        if g not in ("G0", "G38.2"):
            continue
        target = list(m)
        for k, axis in enumerate("XYZ"):
            if axis in words:
                target[k] = m[k] + words[axis] if relative else origin[k] + words[axis]
        if g == "G0":
            m = target
            continue
        moving = [k for k in range(3) if abs(target[k] - m[k]) > 1e-9]
        assert len(moving) == 1, line
        k = moving[0]
        d = 1.0 if target[k] > m[k] else -1.0
        hits = []
        for b in boxes:
            lo, hi = b[:3], b[3:]
            if k == 2:  # descente : le bas de la pointe touche le dessus d'une boîte sous son centre
                if d < 0 and lo[0] <= m[0] <= hi[0] and lo[1] <= m[1] <= hi[1] and hi[2] <= m[2] + 1e-9:
                    hits.append(hi[2])
                continue
            other = 1 - k
            if lo[other] <= m[other] <= hi[other] and lo[2] < m[2] < hi[2]:
                face = lo[k] - r if d > 0 else hi[k] + r
                if (face - m[k]) * d >= -1e-9:
                    hits.append(face)
        reach = [h for h in hits if (h - target[k]) * d <= 1e-9]
        if not reach:
            raise AssertionError("probe alarm (no contact): %s" % line)
        m[k] = min(reach, key=lambda h: abs(h - m[k]))
    return origin


class TestProbe(unittest.TestCase):
    TIP = 2.0

    def profile(self):
        return machine(probe={"present": True, "tip_diameter_mm": self.TIP, "feed_mm_min": 100.0, "travel_mm": 25.0,
                              "plate_thickness_mm": 0.0, "tool_number": 99})

    def test_outer_corner_origin(self):
        """Référence : coin extérieur avant gauche d'une pièce (X 100 Y 50, dessus Z -20) palpé depuis 10 mm dedans."""
        from cam2027.project import probe

        piece = (100.0, 50.0, -40.0, 180.0, 110.0, -20.0)
        lines = probe.probe_gcode(self.profile(), "corner", corner="front-left")
        origin = run_probe(lines, (110.0, 60.0, -15.0), [piece], self.TIP)
        for got, want in zip(origin, (100.0, 50.0, -20.0)):
            self.assertAlmostEqual(got, want, places=6)

    def test_inner_corner_origin(self):
        """Coin intérieur (poche, butée de montage) : chaque coin d'une poche 80 x 60 palpé de l'intérieur donne le coin
        exact en X et Y (Z non touché) ; le palpeur revient à son point de départ."""
        from cam2027.project import probe

        x0, y0, x1, y1 = 100.0, 50.0, 180.0, 110.0  # poche, parois de Z -40 à -20
        walls = [(x0 - 30, y0 - 30, -40, x0, y1 + 30, -20), (x1, y0 - 30, -40, x1 + 30, y1 + 30, -20),
                 (x0 - 30, y0 - 30, -40, x1 + 30, y0, -20), (x0 - 30, y1, -40, x1 + 30, y1 + 30, -20)]
        for corner, (sx, sy) in probe.CORNERS.items():
            cx, cy = (x0 if sx < 0 else x1), (y0 if sy < 0 else y1)
            start = (cx - sx * 10.0, cy - sy * 10.0, -30.0)
            lines = probe.probe_gcode(self.profile(), "inner_corner", corner=corner, wcs="G55")
            self.assertTrue(any(l.startswith("G10 L20 P2 X") for l in lines), lines)
            self.assertFalse(any(" Z" in l for l in lines if l.startswith(("G38", "G10"))), lines)
            origin = run_probe(lines, start, walls, self.TIP)
            self.assertAlmostEqual(origin[0], cx, places=6, msg=corner)
            self.assertAlmostEqual(origin[1], cy, places=6, msg=corner)
            # G92 : même origine
            lines = probe.probe_gcode(self.profile(), "inner_corner", corner=corner, offset_mode="G92")
            origin = run_probe(lines, start, walls, self.TIP)
            self.assertAlmostEqual(origin[0], cx, places=6, msg=corner)
            self.assertAlmostEqual(origin[1], cy, places=6, msg=corner)
        # analyse de l'export : course de recherche dans la course du palpeur, aucune erreur
        from cam2027.project import probe as p

        a = p.analyze("\n".join(lines))
        self.assertEqual(a["count"], 2)
        self.assertEqual(p.verify({"probe": a}, self.profile()), [])


if __name__ == "__main__":
    unittest.main()
