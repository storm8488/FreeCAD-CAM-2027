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


if __name__ == "__main__":
    unittest.main()
