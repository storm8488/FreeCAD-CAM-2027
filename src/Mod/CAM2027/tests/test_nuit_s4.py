# SPDX-License-Identifier: LGPL-2.1-or-later
"""Flux S4 de la nuit 2 : finition à crête constante, usinage rotatif continu, projection sur une surface."""

import math
import os
import tempfile
import time
import unittest

import FreeCAD
import Part

from cam2027.project import sim
from cam2027.project.machine import MachineProfile
from cam2027.project.project import Project
from cam2027.tools.library import starter_library

DOME = (30.0, 20.0, -15.0, 25.0)  # sphère tronquée : sommet à Z 10, raccord avec la plaque à Z 5 (rayon 15)


def make_dome(path):
    cx, cy, cz, r = DOME
    plate = Part.makeBox(60, 40, 5)
    dome = Part.makeSphere(r, FreeCAD.Vector(cx, cy, cz)).common(Part.makeBox(60, 40, 30, FreeCAD.Vector(0, 0, 5)))
    plate.fuse(dome).removeSplitter().exportStep(path)


def strip_crest(commands, window, ball_d, dome_r_max, res=0.05):
    """Carte de hauteur fine sur une bande : (crête normale max sur le dôme, crête max sur le plat, entaille max).

    La crête du dôme est la distance de la matière restante à la sphère (normale à la surface), mesurée à moins
    de ``dome_r_max`` de l'axe (le raccord concave avec la plaque est hors de portée de la boule)."""
    import numpy as np

    x0, y0, x1, y1 = window
    zm = sim.ZMap(x0, y0, x1, y1, 11.0, res)
    segs, _pos = sim.path_segments(commands)
    cuts = [(p0, p1) for rapid, p0, p1 in segs if not rapid]
    P0 = np.array([c[0] for c in cuts], dtype=float)
    P1 = np.array([c[1] for c in cuts], dtype=float)
    near = ((np.minimum(P0[:, 0], P1[:, 0]) < x1 + ball_d) & (np.maximum(P0[:, 0], P1[:, 0]) > x0 - ball_d)
            & (np.minimum(P0[:, 1], P1[:, 1]) < y1 + ball_d) & (np.maximum(P0[:, 1], P1[:, 1]) > y0 - ball_d))
    zm.sweep_arrays(P0[near], P1[near], sim.ToolProfile("ball", ball_d))
    cx, cy, cz, r = DOME
    X, Y = np.meshgrid(zm.xs, zm.ys, indexing="ij")
    d2 = (X - cx) ** 2 + (Y - cy) ** 2
    part = np.maximum(5.0, np.where(d2 < r * r, cz + np.sqrt(np.maximum(r * r - d2, 0.0)), -1e9))
    inside = (X >= 0) & (X <= 60) & (Y >= 0) & (Y <= 40)
    gouge = float(np.max(np.where(inside, part - zm.top, -1.0)))
    rxy = np.sqrt(d2)
    on_dome = rxy < dome_r_max
    normal = np.sqrt(d2 + (zm.top - cz) ** 2) - r
    flat = (rxy > 15.0 + ball_d / 2.0 + 0.5) & (X > 0.5) & (X < 59.5) & (Y > 0.5) & (Y < 39.5)
    return float(normal[on_dome].max()), float((zm.top[flat] - 5.0).max()), gouge


class TestScallop(unittest.TestCase):
    """Finition à hauteur de crête constante (Fusion « Scallop ») et mode pentu / peu incliné."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="cam2027-s4-")
        cls.step = os.path.join(cls.tmp, "dome.step")
        make_dome(cls.step)
        FreeCAD.ConfigSet("SuppressRecomputeRequiredDialog", "True")

    def _project(self, name):
        lib = starter_library()
        proj = Project.create(name, lib, MachineProfile("test", controller="grbl", post_processor="grbl",
                                                        post_processor_args="--no-show-editor --precision=3"))
        part = proj.import_model(self.step, label="Dome").objects[0]
        proj.create_job([part], stock={"kind": "box_margins", "xy": 2.0, "z_top": 1.0, "z_bottom": 0.0})
        ball = lib.search("6 mm ball end mill")[0]
        return proj, lib, ball, lib.assemblies_for_tool(ball.id)[0]

    def test_stepover_formula(self):
        from cam2027.project import scallop

        s = scallop.stepover(0.02, 3.0, 6.0)
        self.assertAlmostEqual(s, 2.0 * math.sqrt(0.02 * 5.98), places=9)
        self.assertAlmostEqual(scallop.scallop_of(s, 3.0, 6.0), 0.02, places=9)
        # torique D10 R1 : la partie plate (8 mm) s'ajoute
        self.assertAlmostEqual(scallop.stepover(0.01, 1.0, 10.0), 8.0 + 2.0 * math.sqrt(0.01 * 1.99), places=9)
        with self.assertRaises(Exception):
            scallop.stepover(0.02, 0.0, 6.0)  # fraise plate : pas de crête définie

    def test_dome_constant_scallop(self):
        """Dôme : crête mesurée <= crête demandée (+ 10 %) sur le dôme et le plat, aucune entaille, temps <= 2 x surface3d."""
        from cam2027.gui.commands import default_params

        proj, lib, ball, basm = self._project("Scallop dome")
        clone = proj.job.Model.Group[0]
        target = 0.02
        op, rec = proj.add_operation("scallop", "Dome scallop", basm.id, ball.presets[0].id, base=[(clone, [])],
                                     params=dict(default_params("scallop", ball, ball.presets[0].resolve(ball)),
                                                 ScallopHeight=target))
        self.assertEqual(rec["ignored_params"], [])
        t0 = time.time()
        results = {r["name"]: r for r in proj.compute()}
        t_scallop = time.time() - t0
        self.assertTrue(results["Dome scallop"]["valid"], results["Dome scallop"])
        self.assertEqual(proj.operation_state(op), "computed")
        self.assertAlmostEqual(op.Stepover3D.Value, 2.0 * math.sqrt(target * (6.0 - target)), places=6)
        cuts = [c.Parameters for c in op.Path.Commands if c.Name == "G1"]
        self.assertGreater(len(cuts), 1000)
        self.assertGreater(max(p["Z"] for p in cuts), 9.9)  # le sommet est suivi
        # crête sur deux bandes qui croisent toutes les passes (dôme et plat)
        for window in ((28.0, -2.0, 32.0, 42.0), (-2.0, 18.0, 62.0, 22.0)):
            crest_dome, crest_flat, gouge = strip_crest(op.Path.Commands, window, 6.0, 12.0)
            self.assertLessEqual(crest_dome, 1.1 * target, window)
            self.assertLessEqual(crest_flat, 1.1 * target, window)
            self.assertGreater(crest_flat, 0.5 * target, window)  # pas de passes inutilement serrées
            self.assertLess(gouge, 0.02, window)
        rep = proj.material_check()
        self.assertEqual(rep["gouge_max"], 0.0, rep.get("gouge_at"))
        # temps : <= 2 x la finition 3D de FreeCAD (réglages par défaut de CAM2027) sur la même pièce
        proj.set_operation_active(op, False)
        sop, _srec = proj.add_operation("surface3d", "Dome surface", basm.id, ball.presets[0].id, base=[(clone, [])],
                                        params=default_params("surface3d", ball, ball.presets[0].resolve(ball)))
        t0 = time.time()
        proj.compute()
        t_surface = time.time() - t0
        FreeCAD.Console.PrintMessage("scallop %.1f s, surface3d %.1f s\n" % (t_scallop, t_surface))
        self.assertLessEqual(t_scallop, 2.0 * t_surface, (t_scallop, t_surface))
        proj.close()

    def test_steep_and_shallow(self):
        """Pentu / peu incliné (angle limite 30°) : passes à Z constant sur la bande raide du dôme, crête respectée."""
        proj, lib, ball, basm = self._project("Steep shallow")
        clone = proj.job.Model.Group[0]
        target = 0.02
        op, rec = proj.add_operation("scallop", "Steep and shallow", basm.id, ball.presets[0].id, base=[(clone, [])],
                                     params={"ScallopHeight": target, "SteepShallow": True, "ThresholdAngle": 30.0})
        self.assertEqual(rec["ignored_params"], [])
        proj.compute()
        self.assertEqual(proj.operation_state(op), "computed")
        cx, cy, _cz, _r = DOME
        # passes à Z constant : suites de mouvements de coupe au même Z sur la bande raide (pente 30-37°)
        runs, run, last_z = 0, 0, None
        for c in op.Path.Commands:
            p = c.Parameters
            if c.Name != "G1" or "Z" not in p:
                run, last_z = 0, None
                continue
            rxy = math.hypot(p["X"] - cx, p["Y"] - cy)
            if last_z is not None and abs(p["Z"] - last_z) < 0.01 and 12.5 < rxy < 18.0:
                run += 1
                if run == 50:
                    runs += 1
            else:
                run = 0
            last_z = p["Z"]
        self.assertGreaterEqual(runs, 2)
        crest_dome, crest_flat, gouge = strip_crest(op.Path.Commands, (28.0, -2.0, 32.0, 42.0), 6.0, 14.0)
        self.assertLessEqual(crest_dome, 1.1 * target)
        self.assertLessEqual(crest_flat, 1.1 * target)
        self.assertLess(gouge, 0.02)
        self.assertEqual(proj.material_check()["gouge_max"], 0.0)
        proj.close()


ROT_STOCK = 21.0
ROT_POCKET_HALF = 10.0 / 18.0  # demi-largeur angulaire de la poche (10 mm d'arc au fond)


def rotary_part_radius(x, theta):
    """Rayon de la pièce rotative de test : cylindre R20 (X 0..80), poche jusqu'à R18 (X 10..30, autour de A 180°),
    bosse sphérique R5 centrée à 15,5 mm de l'axe (X 60, A 0)."""
    import numpy as np

    x, theta = np.broadcast_arrays(np.asarray(x, dtype=float), np.asarray(theta, dtype=float))
    t = np.mod(theta, 2 * math.pi)
    pocket = (x >= 10) & (x <= 30) & (np.abs(t - math.pi) <= ROT_POCKET_HALF)
    r = np.where(pocket, 18.0, 20.0)
    c = 15.5 * np.cos(theta)
    disc = c * c - (15.5 ** 2 + (x - 60.0) ** 2 - 25.0)
    bump = np.where(disc >= 0, c + np.sqrt(np.maximum(disc, 0.0)), -np.inf)
    return np.maximum(r, bump)


class TestRotary(unittest.TestCase):
    """Usinage rotatif continu : finition 3D rotative, poche et contour enroulés (G93), carte radiale."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="cam2027-s4r-")
        cls.step = os.path.join(cls.tmp, "rotary.step")
        V = FreeCAD.Vector
        cyl = Part.makeCylinder(20.0, 80.0, V(0, 0, 0), V(1, 0, 0))
        # poche : secteur X 10..30 autour de A 180° (le bas, z < 0), fond à R18
        ring = Part.makeCylinder(25.0, 20.0, V(10, 0, 0), V(1, 0, 0)).cut(
            Part.makeCylinder(18.0, 20.0, V(10, 0, 0), V(1, 0, 0)))
        # secteur angulaire |A - 180°| <= demi-largeur (y = r sin A, z = r cos A) : triangle extrudé le long de X
        s, c = 30.0 * math.sin(ROT_POCKET_HALF), -30.0 * math.cos(ROT_POCKET_HALF)
        tri = Part.Face(Part.makePolygon([V(10, 0, 0), V(10, s, c), V(10, -s, c), V(10, 0, 0)]))
        sector = ring.common(tri.extrude(V(20, 0, 0)))
        bump = Part.makeSphere(5.0, V(60, 0, 15.5))
        cyl.cut(sector).fuse(bump).removeSplitter().exportStep(cls.step)
        FreeCAD.ConfigSet("SuppressRecomputeRequiredDialog", "True")

    def _project(self, name):
        from cam2027.project.machine import RotaryAxis

        lib = starter_library()
        machine = MachineProfile("test", controller="grbl", post_processor="grbl",
                                 post_processor_args="--no-show-editor --precision=4")
        machine.rotary = RotaryAxis(present=True, about="X", center_offset_mm=(0.0, 0.0),
                                    positive_direction="right_hand", min_deg=-720.0, max_deg=720.0)
        proj = Project.create(name, lib, machine)
        part = proj.import_model(self.step, label="Rotary").objects[0]
        proj.create_job([part], stock={"kind": "cylinder_x", "radius": ROT_STOCK, "length": 84.0, "x_start": -2.0,
                                       "center": (0.0, 0.0)})
        return proj, lib

    def test_part_geometry(self):
        """La pièce de test est celle que décrit ``rotary_part_radius`` (contrôle du contrôle)."""
        shape = Part.read(self.step)
        V = FreeCAD.Vector
        for x, theta in ((20.0, math.pi), (20.0, math.pi + 0.5), (20.0, 0.5), (60.0, 0.0), (61.0, 0.2), (40.0, 2.0)):
            r_exp = float(rotary_part_radius(x, theta))
            line = Part.makeLine(V(x, 0, 0), V(x, 30 * math.sin(theta), 30 * math.cos(theta)))
            pts = [v.Point for v in shape.section(line).Vertexes]
            r_got = max(math.hypot(p.y, p.z) for p in pts)
            self.assertAlmostEqual(r_got, r_exp, delta=1e-3, msg=(x, theta))

    def _speeds(self, text, feeds):
        """Vitesse réelle de chaque mouvement G93 (longueur au rayon de coupe x F) comparée à l'avance de
        l'opération en cours (``feeds`` : {nom de l'opération : (avance, plongée)}, repérée par son commentaire)."""
        inverse, prev, checked = False, None, 0
        feed, plunge = None, None
        for raw in text.splitlines():
            line = raw.strip()
            if line.startswith("("):
                feed, plunge = feeds.get(line.strip("() "), (feed, plunge))
                continue
            if not line:
                continue
            if line.startswith("G93"):
                inverse = True
            elif line.startswith("G94"):
                inverse = False
            words = dict((w[0], float(w[1:])) for w in line.split() if w[0] in "XAZF" and len(w) > 1)
            if line.startswith("G1") and inverse and prev is not None:
                x, a, z = words.get("X", prev[0]), words.get("A", prev[1]), words.get("Z", prev[2])
                r_mid = (z + prev[2]) / 2.0
                length = math.sqrt((x - prev[0]) ** 2 + (math.radians(a - prev[1]) * r_mid) ** 2 + (z - prev[2]) ** 2)
                if length > 0.05:
                    self.assertIsNotNone(feed, line)
                    self.assertIn("F", words, line)
                    speed = length * words["F"]
                    pure_z = abs(x - prev[0]) < 1e-6 and abs(a - prev[1]) < 1e-6
                    target = plunge if pure_z else feed
                    self.assertAlmostEqual(speed, target, delta=0.02 * target, msg=line)
                    checked += 1
            if line.startswith(("G0", "G1")):
                prev = (words.get("X", prev[0] if prev else 0.0), words.get("A", prev[1] if prev else 0.0),
                        words.get("Z", prev[2] if prev else 0.0))
        return checked

    def test_rotary_finishing_and_wrapped_pocket(self):
        """Finition 3D rotative (boule 6) puis poche enroulée (plate 3) : carte radiale déroulée = pièce à ± 0,05 mm,
        vitesse réelle = avance ± 2 %, export vérifié."""
        import numpy as np
        from cam2027.project import rotary

        proj, lib = self._project("Rotary")
        ball = lib.search("6 mm ball end mill")[0]
        flat = lib.search("3 mm flat end mill")[0]
        t0 = time.time()
        op3d, rec3d = rotary.add_operation(proj, "rotary3d", "Rotary finishing", lib.assemblies_for_tool(ball.id)[0].id,
                                           ball.presets[0].id, params={"stepover": 0.5, "sample": 0.25, "step_down": 1.0})
        t_3d = time.time() - t0
        self.assertEqual(rec3d["kind"], "rotary3d")
        self.assertGreaterEqual(rec3d["info"]["levels"], 3)
        # dessin déroulé de la poche : rectangle X 10..30, Y = arc au rayon du brut autour de A 180°
        V = FreeCAD.Vector
        y0 = (math.pi - ROT_POCKET_HALF) * ROT_STOCK
        y1 = (math.pi + ROT_POCKET_HALF) * ROT_STOCK
        drawing = proj.doc.addObject("Part::Feature", "PocketDrawing")
        drawing.Shape = Part.makePolygon([V(10, y0, 0), V(30, y0, 0), V(30, y1, 0), V(10, y1, 0), V(10, y0, 0)])
        proj.doc.recompute()
        t0 = time.time()
        opp, recp = rotary.add_operation(proj, "wrap_pocket", "Wrapped pocket", lib.assemblies_for_tool(flat.id)[0].id,
                                         flat.presets[0].id, base=[(drawing, [])],
                                         params={"depth": -3.0, "step_down": 1.0, "stepover": 0.4})
        t_pocket = time.time() - t0
        FreeCAD.Console.PrintMessage("rotary3d %.1f s, wrapped pocket %.1f s\n" % (t_3d, t_pocket))
        summary = {r["name"]: r for r in proj.compute()}
        self.assertTrue(summary["Rotary finishing"]["valid"] and summary["Wrapped pocket"]["valid"], summary)
        text, analysis, issues = proj.preview_gcode()
        self.assertIn("G93", analysis["codes"])
        self.assertEqual((analysis["a_feed_lines"], analysis["g93_missing_f"], analysis["ends_in_g93"]), (0, 0, False))
        self.assertNotIn("error", [lvl for lvl, _m in issues], issues)
        checked = self._speeds(text, dict((r["label"], (r["values"]["feed_mm_min"], r["values"]["plunge_feed_mm_min"])) for r in (rec3d, recp)))
        self.assertGreater(checked, 1000)
        # carte radiale déroulée sur deux bandes : la poche (et le cylindre autour), la bosse
        _l, moves3d = rotary.generate(proj, op3d)
        _l, movesp = rotary.generate(proj, opp)
        for window in ((14.0, 26.0, math.pi - 1.0, math.pi + 1.0), (52.0, 68.0, -0.45, 0.45)):
            x0, x1, t0_, t1_ = window
            rmap = rotary.RadialMap(x0, x1, t0_, t1_, ROT_STOCK, res_x=0.1)
            rmap.sweep_moves(moves3d, ROT_STOCK, "ball", 3.0)
            rmap.sweep_moves(movesp, ROT_STOCK, "flat", 1.5)
            X, T = np.meshgrid(rmap.xs, rmap.ts, indexing="ij")
            part = rotary_part_radius(X, T)
            err = rmap.r - part
            # le bas de la boule ne rentre pas dans les angles concaves (raccord bosse / cylindre, parois de poche)
            dist_wall = np.abs(np.abs(np.mod(T, 2 * math.pi) - math.pi) - ROT_POCKET_HALF) * 18.0
            pocket_floor = (part < 18.5) & (dist_wall > 0.5) & (X > 10.5) & (X < 29.5)
            cylinder = (np.abs(part - 20.0) < 1e-9) & (dist_wall > 3.5) & (np.hypot(X - 60, T * 20) > 9.5)
            bump = part > 20.25
            for name, sel in (("pocket floor", pocket_floor), ("cylinder", cylinder), ("bump", bump)):
                if sel.any():
                    self.assertLess(float(np.abs(err[sel]).max()), 0.05, (name, window, float(np.abs(err[sel]).max())))
            self.assertGreater(int((pocket_floor | cylinder | bump).sum()), 1000)
            self.assertGreater(float(err.min()), -0.05, window)  # aucune entaille dans la bande
        preview = proj.doc.getObject(op3d.Name + "_Preview")
        self.assertIsNotNone(preview)
        self.assertGreater(len(preview.Shape.Edges), 100)
        proj.close()

    def test_wrapped_contour(self):
        """Contour enroulé extérieur d'un rectangle : centre de l'outil à un rayon d'outil du dessin dans le plan réel
        du niveau (compensation au rayon courant), deux niveaux ; outil trop gros pour l'intérieur refusé."""
        from cam2027.project import rotary

        proj, lib = self._project("Wrapped contour")
        flat = lib.search("3 mm flat end mill")[0]
        V = FreeCAD.Vector
        drawing = proj.doc.addObject("Part::Feature", "ContourDrawing")
        drawing.Shape = Part.makePolygon([V(35, 20, 0), V(50, 20, 0), V(50, 50, 0), V(35, 50, 0), V(35, 20, 0)])
        proj.doc.recompute()
        op, rec = rotary.add_operation(proj, "wrap_contour", "Wrapped contour", lib.assemblies_for_tool(flat.id)[0].id,
                                       flat.presets[0].id, base=[(drawing, [])],
                                       params={"depth": -2.0, "step_down": 1.0, "side": "outside"})
        _lines, moves = rotary.generate(proj, op)
        cuts = [m for m in moves if m[0] == "cut"]
        self.assertGreater(len(cuts), 40)
        self.assertEqual(sorted(set(round(m[3], 6) for m in cuts)), [-2.0, -1.0])
        for _k, x, y, z in cuts:
            k = (ROT_STOCK + z) / ROT_STOCK
            real = Part.makePolygon([V(35, 20 * k, 0), V(50, 20 * k, 0), V(50, 50 * k, 0), V(35, 50 * k, 0),
                                     V(35, 20 * k, 0)])
            d = real.distToShape(Part.Vertex(V(x, y * k, 0)))[0]
            self.assertAlmostEqual(d, 1.5, delta=0.02)
        _t, _a, issues = proj.preview_gcode()
        self.assertNotIn("error", [lvl for lvl, _m in issues], issues)
        drawing.Shape = Part.makePolygon([V(35, 20, 0), V(37, 20, 0), V(37, 22, 0), V(35, 22, 0), V(35, 20, 0)])
        proj.doc.recompute()
        with self.assertRaises(Exception):
            rotary.update_operation(proj, op, side="inside")
        proj.close()


FONT = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "arial.ttf")


def dome_z(x, y):
    """Hauteur exacte de la pièce « dôme sur plaque » (``make_dome``)."""
    import numpy as np

    cx, cy, cz, r = DOME
    d2 = (np.asarray(x) - cx) ** 2 + (np.asarray(y) - cy) ** 2
    return np.maximum(5.0, np.where(d2 < r * r, cz + np.sqrt(np.maximum(r * r - d2, 0.0)), -1e9))


class TestProjection(unittest.TestCase):
    """Projection d'un parcours 2D sur la pièce : texte gravé à 0,5 mm sur un dôme."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="cam2027-s4p-")
        cls.step = os.path.join(cls.tmp, "dome.step")
        make_dome(cls.step)
        FreeCAD.ConfigSet("SuppressRecomputeRequiredDialog", "True")

    def _engraving(self, name, text_wires, kind="engrave", params=None):
        lib = starter_library()
        proj = Project.create(name, lib, MachineProfile("test", controller="grbl", post_processor="grbl",
                                                        post_processor_args="--no-show-editor --precision=4"))
        part = proj.import_model(self.step, label="Dome").objects[0]
        proj.create_job([part], stock={"kind": "box_margins", "xy": 2.0, "z_top": 1.0, "z_bottom": 0.0})
        drawing = proj.doc.addObject("Part::Feature", "Text")
        drawing.Shape = Part.Compound(text_wires)
        proj.doc.recompute()
        vbit = [t for t in lib.search("V-bit") if t.geometry.tip_included_angle_deg == 90.0][0]
        edges = ["Edge%d" % (i + 1) for i in range(len(drawing.Shape.Edges))]
        op, rec = proj.add_operation(kind, name, lib.assemblies_for_tool(vbit.id)[0].id, vbit.presets[0].id,
                                     base=[(drawing, edges)], params=params)
        return proj, op, vbit

    def test_text_on_dome(self):
        """Texte « S4 » gravé à 0,5 mm (V-bit 90°) projeté sur le dôme : chaque point de coupe à 0,5 mm sous la
        surface, profondeur mesurée sur la carte de hauteur 0,5 ± 0,05 mm le long de tout le texte, rien
        d'enlevé hors de la portée du V-bit, export sans erreur."""
        import numpy as np
        from scipy.spatial import cKDTree
        from cam2027.project import projection

        if not os.path.isfile(FONT):
            self.skipTest("arial.ttf absent")
        chars = Part.makeWireString("S4", os.path.dirname(FONT) + os.sep, os.path.basename(FONT), 14.0, 0.0)
        wires = []
        for char in chars:
            for w in char:
                w.translate(FreeCAD.Vector(19.0, 13.0, 10.0))
                wires.append(w)
        depth = 0.5
        proj, op, vbit = self._engraving("Text", wires, params={"StartDepth": 10.0, "FinalDepth": 10.0 - depth,
                                                                "StepDown": depth})
        t0 = time.time()
        dressup = projection.add_projection(proj, op)
        proj.compute()
        t_proj = time.time() - t0
        self.assertEqual(proj.operation_state(op), "computed")
        self.assertIn(dressup, proj.job.Operations.Group)
        self.assertNotIn(op, proj.job.Operations.Group)
        cuts = np.array([[c.Parameters[k] for k in "XYZ"] for c in dressup.Path.Commands
                         if c.Name == "G1" and all(k in c.Parameters for k in "XYZ")])
        surf = dome_z(cuts[:, 0], cuts[:, 1])
        on_text = cuts[:, 2] < surf - 0.25  # points de coupe (pas les approches)
        self.assertGreater(int(on_text.sum()), 300)
        self.assertLess(float(np.abs(cuts[on_text, 2] - (surf[on_text] - depth)).max()), 0.01)
        self.assertGreater(float(cuts[on_text, 2].max() - cuts[on_text, 2].min()), 1.0)  # le texte suit la courbure
        # carte de hauteur fine sur le texte : profondeur sous la surface le long du tracé
        bb = Part.Compound(wires).BoundBox
        zm = sim.ZMap(bb.XMin - 2, bb.YMin - 2, bb.XMax + 2, bb.YMax + 2, 11.0, 0.05)
        segs, _pos = sim.path_segments(dressup.Path.Commands)
        P0 = np.array([s[1] for s in segs if not s[0]], dtype=float)
        P1 = np.array([s[2] for s in segs if not s[0]], dtype=float)
        profile, _note = sim.ToolProfile.from_library_tool(vbit)
        zm.sweep_arrays(P0, P1, profile)
        X, Y = np.meshgrid(zm.xs, zm.ys, indexing="ij")
        cut = dome_z(X, Y) - np.minimum(zm.top, dome_z(X, Y))
        # profondeur au droit du tracé : la plus grande dans 0,05 mm autour de chaque point de coupe
        tree = cKDTree(np.column_stack([X.ravel(), Y.ravel()]))
        depths = [max(cut.ravel()[k] for k in tree.query_ball_point(p[:2], 0.05)) for p in cuts[on_text][::3]]
        self.assertGreater(min(depths), depth - 0.05, min(depths))
        self.assertLess(max(depths), depth + 0.05, max(depths))
        # rien d'enlevé hors de la portée du V-bit autour du tracé : demi-largeur d / tan(45°) à plat, d / (1 - pente)
        # côté montée (le cône rencontre plus loin une surface qui monte vers lui)
        tp = cuts[on_text]
        e = 1e-3
        slope = np.hypot(dome_z(tp[:, 0] + e, tp[:, 1]) - dome_z(tp[:, 0] - e, tp[:, 1]),
                         dome_z(tp[:, 0], tp[:, 1] + e) - dome_z(tp[:, 0], tp[:, 1] - e)) / (2 * e)
        self.assertLess(float(slope.max()), 0.9)
        reach = depth / (1.0 - slope)
        path_tree = cKDTree(tp[:, :2])
        removed = np.argwhere(cut > 0.02)
        pts = np.column_stack([zm.xs[removed[:, 0]], zm.ys[removed[:, 1]]])
        near = path_tree.query_ball_point(pts, float(reach.max()) + 0.1)
        for p, idx in zip(pts, near):
            ok = any(math.hypot(*(p - tp[k, :2])) <= reach[k] + 0.1 for k in idx)
            self.assertTrue(ok, p)
        _t, _a, issues = proj.preview_gcode()
        self.assertNotIn("error", [lvl for lvl, _m in issues], issues)
        FreeCAD.Console.PrintMessage("projection %.1f s, depth %.3f..%.3f\n" % (t_proj, min(depths), max(depths)))
        # retour à plat
        projection.remove_projection(proj, op)
        self.assertIn(op, proj.job.Operations.Group)
        proj.close()

    def test_vcarve_and_contour_projected(self):
        """V-carving (profondeur variable) et contour projetés : profondeur sous la surface identique à celle
        sous le plan de référence à plat, pour chaque point."""
        import numpy as np
        from cam2027.project import projection

        V = FreeCAD.Vector
        wire = Part.makePolygon([V(22, 14, 10), V(38, 14, 10), V(38, 26, 10), V(22, 26, 10), V(22, 14, 10)])
        proj, vop, vbit = self._engraving("Square", [wire], kind="profile",
                                          params={"StartDepth": 10.0, "FinalDepth": 9.7, "Side": "Outside"})
        lib = proj.library
        face = proj.doc.addObject("Part::Feature", "SquareFace")
        face.Shape = Part.Face(wire)
        proj.doc.recompute()
        cop, _r = proj.add_operation("vcarve", "VCarve", lib.assemblies_for_tool(vbit.id)[0].id, vbit.presets[0].id,
                                     base=[(face, ["Face1"])], params={"StartDepth": 10.0, "FinalDepth": 8.0})
        proj.compute()
        flat = {}
        for op in (vop, cop):
            flat[op.Name] = sorted(round(10.0 - c.Parameters["Z"], 3) for c in op.Path.Commands
                                   if c.Name in ("G1", "G2", "G3") and "Z" in c.Parameters and c.Parameters["Z"] < 10.0 - 1e-6)
            self.assertTrue(flat[op.Name], op.Label)
            d = projection.add_projection(proj, op)
            proj.compute()
            cuts = np.array([[c.Parameters[k] for k in "XYZ"] for c in d.Path.Commands
                             if c.Name == "G1" and all(k in c.Parameters for k in "XYZ")])
            below = dome_z(cuts[:, 0], cuts[:, 1]) - cuts[:, 2]
            cutting = below > 1e-3
            self.assertGreater(int(cutting.sum()), 20, op.Label)
            # profondeur sous la surface dans la plage des profondeurs à plat (0,3 pour le contour, 0..2 en V-carving)
            self.assertLess(float(below[cutting].max()), max(flat[op.Name]) + 0.01, op.Label)
            self.assertGreater(float(below[cutting].max()), max(flat[op.Name]) - 0.01, op.Label)
            if op is vop:
                self.assertLess(float(np.abs(below[below > 0.25] - 0.3).max()), 0.01)
        proj.close()

    def test_projection_refused(self):
        """Seules gravure, contour, V-carving (et poche 2D, rainure, chanfrein) se projettent ; pas deux fois."""
        from cam2027.project import projection

        V = FreeCAD.Vector
        square = [Part.makePolygon([V(25, 15, 10), V(35, 15, 10), V(35, 25, 10), V(25, 25, 10), V(25, 15, 10)])]
        proj, op, _vbit = self._engraving("Square", square, params={"StartDepth": 10.0, "FinalDepth": 9.7})
        projection.add_projection(proj, op)
        with self.assertRaises(Exception):
            projection.add_projection(proj, op)
        lib = proj.library
        ball = lib.search("6 mm ball end mill")[0]
        sop, _r = proj.add_operation("surface3d", "Surface", lib.assemblies_for_tool(ball.id)[0].id, ball.presets[0].id,
                                     base=[(proj.job.Model.Group[0], [])], params={"SampleInterval": 0.5, "StepOver": 50})
        with self.assertRaises(Exception):
            projection.add_projection(proj, sop)
        proj.close()


if __name__ == "__main__":
    unittest.main()
