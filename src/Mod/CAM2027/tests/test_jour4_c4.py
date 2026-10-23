# SPDX-License-Identifier: LGPL-2.1-or-later
"""Flux C4 du jour 4 : fonctions incomplètes (parois radiales XYZA et contrôle matière 4e axe, dessin vectoriel
paramétrique, imbrication avec sens du fil et groupes)."""

import math
import os
import tempfile
import time
import unittest

import FreeCAD
import Part

from cam2027.project.machine import MachineProfile
from cam2027.project.project import Project
from cam2027.tools.library import starter_library

V = FreeCAD.Vector

# pièce rotative : cylindre R20 (X 0..60), poche à parois radiales X 15..35 autour de A 180°, fond à R17
ROT_R = 20.0
FLOOR_R = 17.0
HALF = 6.0 / FLOOR_R  # demi-largeur angulaire de la poche (6 mm d'arc au fond)
POCKET_X = (15.0, 35.0)


def rotary_part(path):
    cyl = Part.makeCylinder(ROT_R, 60.0, V(0, 0, 0), V(1, 0, 0))
    x0, x1 = POCKET_X
    ring = Part.makeCylinder(30.0, x1 - x0, V(x0, 0, 0), V(1, 0, 0)).cut(
        Part.makeCylinder(FLOOR_R, x1 - x0, V(x0, 0, 0), V(1, 0, 0)))
    s, c = 40.0 * math.sin(HALF), -40.0 * math.cos(HALF)  # A 180° = le bas (z < 0)
    tri = Part.Face(Part.makePolygon([V(x0, 0, 0), V(x0, s, c), V(x0, -s, c), V(x0, 0, 0)]))
    cyl.cut(ring.common(tri.extrude(V(x1 - x0, 0, 0)))).removeSplitter().exportStep(path)


def rotary_project(name, step):
    from cam2027.project.machine import RotaryAxis

    lib = starter_library()
    machine = MachineProfile("test", controller="grbl", post_processor="grbl",
                             post_processor_args="--no-show-editor --precision=4")
    machine.rotary = RotaryAxis(present=True, about="X", center_offset_mm=(0.0, 0.0),
                                positive_direction="right_hand", min_deg=-720.0, max_deg=720.0)
    proj = Project.create(name, lib, machine)
    part = proj.import_model(step, label="Rotary").objects[0]
    proj.create_job([part], stock={"kind": "cylinder_x", "radius": ROT_R, "length": 60.0, "x_start": 0.0,
                                   "center": (0.0, 0.0)})
    return proj, lib


def pocket_drawing(proj):
    y0, y1 = (math.pi - HALF) * ROT_R, (math.pi + HALF) * ROT_R
    x0, x1 = POCKET_X
    drawing = proj.doc.addObject("Part::Feature", "PocketDrawing")
    drawing.Shape = Part.makePolygon([V(x0, y0, 0), V(x1, y0, 0), V(x1, y1, 0), V(x0, y1, 0), V(x0, y0, 0)])
    proj.doc.recompute()
    return drawing


def wall_errors(moves, tool_d):
    """Position des deux parois radiales (A 180° ± HALF) dans la matière simulée, à plusieurs rayons entre le fond et
    la surface : écart (mm, perpendiculaire au plan radial) le plus grand, paroi par paroi."""
    import numpy as np
    from cam2027.project import sim, sim_rotary

    out = []
    for wall, sense in ((math.pi - HALF, -1), (math.pi + HALF, 1)):
        rs = sim_rotary.RadialStock(20.0, 30.0, ROT_R, res=0.25, t0=wall - 0.12, t1=wall + 0.12,
                                    res_t=0.004 / ROT_R)
        rs.sweep_moves(moves, sim.ToolProfile("flat", tool_d))
        ts = rs.ts if sense < 0 else rs.ts[::-1]  # depuis le côté de la pièce
        worst = 0.0
        for rho in (FLOOR_R + 0.15, 17.8, 18.6, 19.4, ROT_R - 0.15):
            for i in range(len(rs.xs)):
                rr = rs.r[i] if sense < 0 else rs.r[i][::-1]
                empty = np.nonzero(rr < rho)[0]  # plus de matière au rayon rho : la poche
                assert len(empty) and empty[0] > 0, (wall, rho)
                err = rho * math.sin((ts[empty[0]] - wall) * -sense)  # > 0 : matière laissée dans la poche
                worst = max(worst, abs(err))
        out.append(worst)
    return out


class TestRotaryRadialWalls(unittest.TestCase):
    """Parois radiales (X, Y, Z et A simultanés) et contrôle matière 4e axe (``sim_rotary``)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="cam2027-c4r-")
        cls.step = os.path.join(cls.tmp, "radial.step")
        rotary_part(cls.step)
        FreeCAD.ConfigSet("SuppressRecomputeRequiredDialog", "True")

    def test_radial_walls_and_rotary_check(self):
        """Poche enroulée en une passe de 3 mm, fraise plate 3 : sans l'option, paroi en biais (0,26 mm en haut) ;
        avec, paroi radiale à ± 0,05 mm à tous les rayons, contrôle matière 4e axe sans entaille, export valide ;
        poche descendue de 0,4 mm de trop : entaille détectée."""
        from cam2027.project import rotary

        proj, lib = rotary_project("Radial walls", self.step)
        flat = lib.search("3 mm flat end mill")[0]
        asm = lib.assemblies_for_tool(flat.id)[0].id
        drawing = pocket_drawing(proj)
        params = {"depth": FLOOR_R - ROT_R, "step_down": 3.0, "stepover": 0.4}
        op, rec = rotary.add_operation(proj, "wrap_pocket", "Pocket", asm, flat.presets[0].id,
                                       base=[(drawing, [])], params=params)
        _l, moves_old = rotary.generate(proj, op)
        old = wall_errors(moves_old, 3.0)
        self.assertGreater(max(old), 0.2, old)  # enroulement seul : paroi en biais
        t0 = time.time()
        _l, moves = rotary.update_operation(proj, op, radial_walls=True)
        t_gen = time.time() - t0
        self.assertTrue(rotary.has_y_offset(moves))
        new = wall_errors(moves, 3.0)
        FreeCAD.Console.PrintMessage("radial walls: error before %s, after %s, generate %.2f s\n" % (old, new, t_gen))
        self.assertLess(max(new), 0.05, new)
        # G-code : Y bouge avec A en G93, avance réelle de la pointe = avance de l'opération
        text, analysis, issues = proj.preview_gcode()
        self.assertNotIn("error", [lvl for lvl, _m in issues], issues)
        self.assertEqual((analysis["a_feed_lines"], analysis["g93_missing_f"], analysis["ends_in_g93"]), (0, 0, False))
        self.assertGreater(sum(1 for ln in text.splitlines() if ln.startswith("G1") and " Y" in ln and " A" in ln), 50)
        feeds = {False: rec["values"]["feed_mm_min"], True: rec["values"]["plunge_feed_mm_min"]}
        speeds = self._tip_speeds(text)
        good = [s for s, pure_z in speeds if abs(s - feeds[pure_z]) <= 0.02 * feeds[pure_z]]
        self.assertGreater(len(speeds), 100)
        self.assertGreater(len(good), 0.9 * len(speeds), (len(good), len(speeds)))
        # contrôle matière 4e axe (accroche de Project.material_check)
        t0 = time.time()
        rep = proj.material_check()
        t_check = time.time() - t0
        FreeCAD.Console.PrintMessage("rotary check: %.2f s, cells %s, gouge %.3f, leftover %.3f, removed %.0f mm3\n"
                                     % (t_check, rep["cells"], rep["gouge_max"], rep["leftover_max"],
                                        rep["removed_volume"]))
        self.assertTrue(rep["rotary"])
        self.assertEqual(rep["simulated"], ["Pocket"])
        self.assertEqual(rep["gouge_max"], 0.0, rep["gouge_at"])
        self.assertEqual(rep["rapid_hits"], 0)
        pocket_volume = (POCKET_X[1] - POCKET_X[0]) * HALF * (ROT_R ** 2 - FLOOR_R ** 2)
        self.assertAlmostEqual(rep["removed_volume"], pocket_volume, delta=0.03 * pocket_volume)
        self.assertEqual(proj.last_check()["gouge_max"], 0.0)
        # entaille volontaire : 0,4 mm sous le fond
        rotary.update_operation(proj, op, depth=FLOOR_R - ROT_R - 0.4, step_down=3.4)
        rep = proj.material_check()
        self.assertAlmostEqual(rep["gouge_max"], 0.4, delta=0.03)
        x, y, z = rep["gouge_at"]
        self.assertTrue(POCKET_X[0] <= x <= POCKET_X[1] and z < 0, rep["gouge_at"])
        proj.close()

    def test_radial_stock_profiles_and_rapids(self):
        """Carte de rayon seule : rainure à la boule et au V-bit 90° (profondeur et largeur exactes sur le cylindre),
        rapide dans la matière compté, remontée dans la rainure non comptée."""
        import numpy as np
        from cam2027.project import sim, sim_rotary

        R = 20.0
        # demi-largeur (arc au rayon R) où la fraise coupe la surface du brut, pointe à R - 1
        ball = R * math.acos((R * R + 22.0 ** 2 - 9.0) / (2 * R * 22.0))  # centre de la boule à R - 1 + 3
        cone = R * (math.acos(19.0 / (R * math.sqrt(2.0))) - math.pi / 4)  # 20 sin d = 20 cos d - 19
        for profile, depth, half_width in ((sim.ToolProfile("ball", 6.0), 1.0, ball),
                                           (sim.ToolProfile("cone", 6.0, included_angle_deg=90.0), 1.0, cone)):
            rs = sim_rotary.RadialStock(0.0, 30.0, R, res=0.05, t0=-0.3, t1=0.3)
            moves = [("rapid", 5.0, 0.0, 5.0), ("plunge", 5.0, 0.0, -depth), ("cut", 25.0, 0.0, -depth),
                     ("rapid", 25.0, 0.0, 5.0)]
            self.assertEqual(rs.sweep_moves(moves, profile), 0)  # remontée dans la rainure : pas de rapide compté
            row = rs.r[int(15.0 / rs.res_x)]
            self.assertAlmostEqual(float(row.min()), R - depth, delta=0.03)  # rayon au centre de cellule (V-bit)
            cut = rs.ts[row < R - 1e-6]
            self.assertAlmostEqual((cut.max() - cut.min()) * R / 2.0, half_width, delta=0.03, msg=profile.kind)
            self.assertEqual(rs.sweep_moves([("rapid", 15.0, 3.0, 5.0), ("rapid", 15.0, 3.0, -0.5)], profile), 1)
            self.assertIsNotNone(rs.rapid_hit_at)

    @staticmethod
    def _tip_speeds(text):
        """Vitesse de la pointe sur la pièce (mm/min) de chaque G1 en G93 avec Y : (déplacement × F, plongée seule)."""
        from cam2027.project.rotary import _tip

        out, inverse, prev = [], False, None
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("G93"):
                inverse = True
            elif line.startswith("G94"):
                inverse = False
            if not line.startswith(("G0", "G1")):
                continue
            w = dict((t[0], float(t[1:])) for t in line.split()[1:] if t[0] in "XYZAF")
            cur = [w.get(k, prev[i] if prev else 0.0) for i, k in enumerate("XYZA")]
            if line.startswith("G1") and inverse and prev is not None and "Y" in w and "F" in w:
                a = _tip(prev[0], math.radians(prev[3]) * ROT_R, prev[2] - ROT_R, prev[1], ROT_R)
                b = _tip(cur[0], math.radians(cur[3]) * ROT_R, cur[2] - ROT_R, cur[1], ROT_R)
                length = math.dist(a, b)
                if length > 0.05:
                    out.append((length * w["F"], cur[0] == prev[0] and cur[1] == prev[1] and cur[3] == prev[3]))
            prev = cur
        return out
