# SPDX-License-Identifier: LGPL-2.1-or-later
"""Contrôle matière (Z-map) : cas analytiques, puis projets réels (surfaçage juste / trop profond, dôme)."""

import math
import os
import tempfile
import unittest

import FreeCAD
import Part

from cam2027.project import sim
from cam2027.project.project import Project
from cam2027.project.machine import MachineProfile
from cam2027.tools.library import starter_library
from tests.test_pipeline import make_part, plate_top_face


def _cell(zmap, x, y):
    i = int((x - zmap.x0) / zmap.res)
    j = int((y - zmap.y0) / zmap.res)
    return i, j, zmap.xs[i], zmap.ys[j]


class FakeCommand(object):
    def __init__(self, name, **params):
        self.Name = name
        self.Parameters = params


class TestZMap(unittest.TestCase):
    def test_flat_groove(self):
        z = sim.ZMap(0, 0, 50, 50, 0.0, 0.25)
        tool = sim.ToolProfile("flat", 6.0)
        self.assertTrue(z.sweep((10, 25, -2), (40, 25, -2), tool))
        expected = 2.0 * (30 * 6 + math.pi * 9)  # rainure + deux demi-disques, 2 mm de profondeur
        self.assertAlmostEqual(z.removed_volume(), expected, delta=0.02 * expected)
        i, j, _x, _y = _cell(z, 25, 27.6)
        self.assertAlmostEqual(z.top[i, j], -2.0)
        i, j, _x, _y = _cell(z, 25, 28.4)
        self.assertAlmostEqual(z.top[i, j], 0.0)

    def test_ball_and_vbit_profiles(self):
        for kind, kw, lift in (("ball", {}, lambda d: 3 - math.sqrt(9 - d * d)),
                               ("cone", {"included_angle_deg": 90.0}, lambda d: d)):
            z = sim.ZMap(0, 0, 50, 50, 0.0, 0.25)
            tool = sim.ToolProfile(kind, 6.0, **kw)
            z.sweep((10, 25, -2), (40, 25, -2), tool)
            for dy in (0.0, 1.0, 1.9):
                i, j, _x, y = _cell(z, 25, 25 + dy)
                d = abs(y - 25)
                self.assertAlmostEqual(z.top[i, j], min(0.0, -2 + lift(d)), places=6, msg=(kind, dy))

    def test_bull_profile(self):
        tool = sim.ToolProfile("bull", 6.0, corner_radius=1.0)
        import numpy
        lift = tool.lift(numpy.array([0.0, 2.0, 2.5, 3.0]))
        self.assertAlmostEqual(lift[0], 0.0)
        self.assertAlmostEqual(lift[1], 0.0)
        self.assertAlmostEqual(lift[2], 1 - math.sqrt(1 - 0.25))
        self.assertAlmostEqual(lift[3], 1.0)

    def test_arc_and_rapid(self):
        cmds = [FakeCommand("G0", X=30.0, Y=20.0, Z=5.0), FakeCommand("G1", Z=-1.0),
                FakeCommand("G2", X=20.0, Y=10.0, I=-10.0, J=0.0)]
        segs, end = sim.path_segments(cmds)
        self.assertEqual(end, [20.0, 10.0, -1.0])
        arc = [s for s in segs if not s[0]][1:]
        self.assertGreater(len(arc), 20)
        for _r, _p0, p1 in arc:  # quart de cercle horaire de rayon 10 autour de (20, 20)
            self.assertAlmostEqual(math.hypot(p1[0] - 20, p1[1] - 20), 10.0, places=6)
            self.assertLessEqual(p1[1], 20.0 + 1e-9)
        z = sim.ZMap(0, 0, 50, 50, 0.0, 0.5)
        tool = sim.ToolProfile("flat", 3.0)
        z.sweep((5, 5, 10), (5, 5, -1), tool, rapid=True)  # descente rapide dans la matière
        self.assertEqual(z.rapid_hits, 1)
        z.sweep((20, 20, -1), (20, 20, 10), tool, rapid=True)  # dégagement vertical vers le haut : jamais compté
        self.assertEqual(z.rapid_hits, 1)

    def test_model_heights(self):
        z = sim.ZMap(-5, -5, 25, 25, 20.0, 0.5)
        h = sim.model_heights(z, [Part.makeBox(10, 10, 5), Part.makeSphere(4, FreeCAD.Vector(18, 18, 0))])
        i, j, _x, _y = _cell(z, 5, 5)
        self.assertAlmostEqual(h[i, j], 5.0)
        i, j, x, y = _cell(z, 18, 18)
        self.assertAlmostEqual(h[i, j], math.sqrt(16 - (x - 18) ** 2 - (y - 18) ** 2), delta=0.05)
        i, j, _x, _y = _cell(z, 12, 3)
        self.assertEqual(h[i, j], -float("inf"))

    def test_wall_on_grid(self):
        """Paroi verticale pile sur les centres des colonnes, fraise tangente : pas d'entaille."""
        z = sim.ZMap(0, 0, 20, 20, 10.0, 0.5)  # centres à 0.25, 0.75...
        part = Part.makeBox(20, 20, 10).cut(Part.makeBox(9.5, 9.5, 5, FreeCAD.Vector(5.25, 5.25, 5)))
        z.sweep((6.75, 6.75, 5.0), (6.75, 13.25, 5.0), sim.ToolProfile("flat", 3.0))
        heights, low = sim.model_heights(z, [part], lateral=sim.WALL_TOLERANCE)
        self.assertAlmostEqual(sim.compare(z, heights)["gouge_max"], 5.0)  # centre sur la paroi : haut du mur
        self.assertEqual(sim.compare(z, heights, gouge_heights=low)["gouge_max"], 0.0)
        z.sweep((6.15, 6.75, 5.0), (6.15, 13.25, 5.0), sim.ToolProfile("flat", 3.0))  # 0,6 mm dans la paroi
        self.assertAlmostEqual(sim.compare(z, heights, gouge_heights=low)["gouge_max"], 5.0)



class TestMaterialCheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="cam2027-sim-")
        cls.step = os.path.join(cls.tmp, "plate.step")
        make_part(cls.step)
        FreeCAD.ConfigSet("SuppressRecomputeRequiredDialog", "True")

    def _machine(self):
        return MachineProfile("test", controller="grbl", post_processor="grbl",
                              post_processor_args="--no-show-editor --precision=3")

    def test_facing_ok_then_too_deep(self):
        """Surfaçage au dessus de la plaque : aucune entaille ; à 1 mm sous le dessus : entaille de 1 mm."""
        lib = starter_library()
        proj = Project.create("Sim facing", lib, self._machine())
        part = proj.import_model(self.step, label="Plate").objects[0]
        proj.create_job([part], stock={"kind": "box_margins", "xy": 2.0, "z_top": 1.0, "z_bottom": 0.0})
        clone = proj.job.Model.Group[0]
        endmill = lib.search("6 mm flat end mill")[0]
        op, _rec = proj.add_operation("millface", "Top facing", lib.assemblies_for_tool(endmill.id)[0].id,
                                      endmill.presets[0].id, base=[(clone, [plate_top_face(clone)])],
                                      params={"StepDown": 1.0, "FinalDepth": 10.0, "StepOver": 50,
                                              "ClearEdges": True})
        rep = proj.material_check()
        self.assertEqual(rep["simulated"], ["Top facing"])
        self.assertEqual((rep["skipped"], rep["approximations"], rep["rapid_hits"]), ([], [], 0))
        self.assertLess(rep["gouge_max"], 0.03, rep)
        stock_top = 84.0 * 64.0 * 1.0  # 1 mm de brut au-dessus de la plaque, marges 2 mm
        self.assertAlmostEqual(rep["removed_volume"], stock_top, delta=0.03 * stock_top)
        # la poche (fond à Z 4) n'est pas usinée : 6 mm de reste, dans la poche
        self.assertAlmostEqual(rep["leftover_max"], 6.0, delta=0.05)
        x, y, _z = rep["leftover_at"]
        self.assertTrue(15 <= x <= 65 and 15 <= y <= 45, rep["leftover_at"])
        proj.update_operation(op, {"FinalDepth": 9.0})
        rep2 = proj.material_check()
        self.assertAlmostEqual(rep2["gouge_max"], 1.0, delta=0.03)
        self.assertGreater(rep2["gouge_cells"], 1000)
        proj.close()

    def test_dome_finishing(self):
        """Finition 3D boule sur un dôme : aucune entaille, crêtes limitées."""
        step = os.path.join(self.tmp, "dome.step")
        plate = Part.makeBox(60, 40, 5)
        dome = Part.makeSphere(25.0, FreeCAD.Vector(30, 20, -15)).common(Part.makeBox(60, 40, 30, FreeCAD.Vector(0, 0, 5)))
        plate.fuse(dome).removeSplitter().exportStep(step)
        lib = starter_library()
        proj = Project.create("Sim dome", lib, self._machine())
        part = proj.import_model(step, label="Dome").objects[0]
        proj.create_job([part], stock={"kind": "box_margins", "xy": 2.0, "z_top": 1.0, "z_bottom": 0.0})
        clone = proj.job.Model.Group[0]
        ball = lib.search("6 mm ball end mill")[0]
        proj.add_operation("surface3d", "Dome finishing", lib.assemblies_for_tool(ball.id)[0].id, ball.presets[0].id,
                           base=[(clone, [])], params={"CutPattern": "ZigZag", "StepOver": 20, "SampleInterval": 0.5,
                                                       "BoundBox": "BaseBoundBox", "FinalDepth": 5.0})
        rep = proj.material_check()
        self.assertEqual(rep["simulated"], ["Dome finishing"])
        self.assertLess(rep["gouge_max"], 0.05, rep)
        self.assertGreater(rep["removed_volume"], 1000.0)
        self.assertLess(rep["leftover_mean"], 0.3, rep)
        proj.close()

    def test_thread_milling_whole_part(self):
        """Filetage sans sélection : le filet suit l'avant-trou (6,8 mm : M8 x 1,25, pas le M6 demandé) ; le
        filet n'est pas une entaille ; sans perçage avant, un seul défaut qui dit de percer."""
        from cam2027.gui.commands import default_params

        lib = starter_library()
        proj = Project.create("Sim thread", lib, self._machine())
        part = proj.import_model(self.step, label="Plate").objects[0]
        proj.create_job([part], stock={"kind": "box_margins", "xy": 2.0, "z_top": 0.0, "z_bottom": 0.0})
        clone = proj.job.Model.Group[0]
        tm = lib.search("thread mill")[0]
        params = default_params("threadmill", tm, tm.presets[0].resolve(tm))
        self.assertEqual(params["ThreadName"], "M6 x 1")
        op, rec = proj.add_operation("threadmill", "Thread", lib.assemblies_for_tool(tm.id)[0].id, tm.presets[0].id,
                                     base=[(clone, [])], params=params)
        self.assertEqual(op.ThreadName, "M8 x 1.25")
        self.assertEqual(rec["params"]["ThreadName"], "M8 x 1.25")
        self.assertEqual(len(rec["warnings"]), 1, rec["warnings"])
        rep = proj.material_check()
        self.assertLess(rep["gouge_max"], 0.03, rep["gouge_at"])
        self.assertEqual([e[0] for e in rep["collisions"]["events"]], ["undrilled"])
        self.assertEqual(rep["collisions"]["rapids"], "collision")
        proj.close()



class TestCollisions(unittest.TestCase):
    """Collisions : enveloppe de l'assemblage, matière au-dessus de la longueur de coupe / du porte-outil, brides."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="cam2027-col-")
        cls.step = os.path.join(cls.tmp, "plate.step")
        make_part(cls.step)
        FreeCAD.ConfigSet("SuppressRecomputeRequiredDialog", "True")

    def _library(self):
        from cam2027.tools.model import ToolDefinition, CuttingPreset, ToolAssembly

        lib = starter_library()
        er20 = [h for h in lib.holders.values() if h.name.startswith("ER20")][0]
        short = lib.add_tool(ToolDefinition("6 mm short flute", "endmill",
                                            dict(diameter=6, shank_diameter=6, overall_length=30, flute_length=5),
                                            flute_count=2))
        short.add_preset(CuttingPreset("Test", usage="roughing", material="wood", spindle_rpm=18000, feed_mm_min=1000,
                                       plunge_feed_mm_min=300, axial_engagement_mm=2.0, radial_engagement_mm=2.0))
        held = lib.add_assembly(ToolAssembly("T20 short in ER20", short.id, er20.id, stickout=8.0,
                                             output={"tool_number": 20}))
        bare = lib.add_assembly(ToolAssembly("T21 short, no holder", short.id, None, stickout=20.0,
                                             output={"tool_number": 21}))
        return lib, short, held, bare

    def _project(self, name, lib):
        proj = Project.create(name, lib, MachineProfile("test", controller="grbl", post_processor="grbl",
                                                         post_processor_args="--no-show-editor --precision=3"))
        part = proj.import_model(self.step, label="Plate").objects[0]
        proj.create_job([part], stock={"kind": "box_margins", "xy": 2.0, "z_top": 1.0, "z_bottom": 0.0})
        return proj, proj.job.Model.Group[0]

    def test_envelope_and_units(self):
        lib, short, held, _bare = self._library()
        asm, tool, holder = lib.resolve_assembly(held.id)
        env = sim.Envelope.from_assembly(asm, tool, holder)
        self.assertEqual([(lo, hi, r, role) for lo, hi, r, role in env.parts],
                         [(0.0, 5.0, 3.0, "cutter"), (5.0, 8.0, 3.0, "shank"),
                          (8.0, 28.0, 14.0, "holder"), (28.0, 43.0, 17.0, "holder")])
        z = sim.ZMap(0, 0, 50, 50, 0.0, 0.5)
        excess, at = sim.material_excess(z, (10, 25, -9), (40, 25, -9), 3.0, 5.0)  # queue 4 mm sous le dessus
        self.assertAlmostEqual(excess, 4.0)
        self.assertAlmostEqual(at[2], -9.0)
        self.assertLessEqual(sim.material_excess(z, (10, 25, -4), (40, 25, -4), 3.0, 5.0)[0], 0.0)
        box = FreeCAD.BoundBox(40, 0, 0, 50, 10, 10)
        hits = sim.clamp_contacts((30, 5, 5), (45, 5, 5), env, [("Clamp", box)])
        self.assertEqual([(h[0], h[1]) for h in hits], [("Clamp", "cutter")])
        cutter_only = sim.Envelope([(0, 5, 3.0, "cutter")], False)
        self.assertEqual(sim.clamp_contacts((36.9, -20, 5), (36.9, 30, 5), cutter_only, [("Clamp", box)]), [])  # 3,1 mm
        self.assertEqual(len(sim.clamp_contacts((37.1, -20, 5), (37.1, 30, 5), cutter_only, [("Clamp", box)])), 1)
        # porte-outil au-dessus de la bride : la pointe est à 1 mm au-dessus, le porte-outil la frôle-t-il ?
        self.assertEqual(sim.clamp_contacts((20, 5, 11), (30, 5, 11), env, [("Clamp", box)]), [])
        self.assertEqual([h[1] for h in sim.clamp_contacts((20, 5, 1), (30, 5, 1), env, [("Clamp", box)])], ["holder"])

    def test_flute_holder_clamp_collisions(self):
        lib, short, held, bare = self._library()
        proj, clone = self._project("Collisions", lib)
        # passe de 10 mm avec une fraise taillée sur 5 mm : la queue frotte dans la matière
        proj.add_operation("profile", "Deep pass", held.id, short.presets[0].id, base=[(clone, [])],
                           params={"FinalDepth": 0.0, "StepDown": 10.0})
        rep = proj.material_check()
        col = rep["collisions"]
        self.assertEqual(col["flute_length"], "collision", col)
        ev = [e for e in col["events"] if e[0] == "flute_length"][0]
        self.assertEqual(ev[1], "Deep pass")
        self.assertIsInstance(ev[2], int)
        self.assertGreater(ev[4], 4.0)  # 10 mm de passe - 5 mm de coupe
        # sortie 8 mm : le nez du porte-outil (Ø28) descend sous le dessus de la plaque
        self.assertEqual(col["holder"], "collision", col)
        hv = [e for e in col["events"] if e[0] == "holder"][0]
        self.assertLess(hv[3][2], 2.0 + 0.05)  # pointe sous 10 - 8
        # pas de bride déclarée : jamais « ok »
        self.assertEqual(col["clamps"], "not_checked")
        self.assertEqual(col["rapids"], "ok")
        # bride le long du bord X = 0 sur le trajet du contour (centre outil à X -3)
        proj.add_clamp("Left clamp", 4, 20, 12, (-8, 20, 0))
        col2 = proj.material_check()["collisions"]
        self.assertEqual(col2["clamps"], "collision")
        cv = [e for e in col2["events"] if e[0] == "clamp"][0]
        # sortie 8 mm, bride haute de 12 : le nez du porte-outil (Ø28) touche la bride avant la fraise
        self.assertEqual((cv[1], cv[5], cv[6]), ("Deep pass", "Left clamp", "holder"))
        # export : collisions du contrôle courant = erreurs bloquantes, avec opération et commande
        from cam2027.project.project import ExportBlocked
        _t, _a, issues = proj.preview_gcode()
        errors = [m for lvl, m in issues if lvl == "error"]
        self.assertTrue(any("tool holder touches the material" in m and "command" in m for m in errors), errors)
        self.assertTrue(any("collision with clamp Left clamp" in m for m in errors), errors)
        with self.assertRaises(ExportBlocked):
            proj.export_gcode(os.path.join(self.tmp, "collide.nc"))
        # parcours modifiés depuis le contrôle : plus d'erreur reprise, mais jamais « ok » : non vérifiable
        proj.update_operation(proj.operations()[0], {"StepDown": 2.0})
        _t, _a, issues2 = proj.preview_gcode()
        self.assertTrue(any(lvl == "unverifiable" and "collisions not checked for these toolpaths" in m
                            for lvl, m in issues2), issues2)
        self.assertFalse(any("touches" in m for _l, m in issues2))
        proj.close()

    def test_clean_project_and_not_checked(self):
        lib, short, held, bare = self._library()
        proj, clone = self._project("Clean", lib)
        endmill = lib.search("6 mm flat end mill")[0]
        proj.add_operation("millface", "Top facing", lib.assemblies_for_tool(endmill.id)[0].id,
                           endmill.presets[0].id, base=[(clone, [plate_top_face(clone)])],
                           params={"StepDown": 1.0, "FinalDepth": 10.0, "StepOver": 50, "ClearEdges": True})
        proj.add_clamp("Far clamp", 10, 10, 8, (120, 120, 0))
        col = proj.material_check()["collisions"]
        self.assertEqual({k: col[k] for k in ("flute_length", "holder", "clamps", "rapids")},
                         {"flute_length": "ok", "holder": "ok", "clamps": "ok", "rapids": "ok"}, col)
        self.assertEqual(col["events"], [])
        # assemblage sans porte-outil : porte-outil « non contrôlé », pas « ok »
        proj.add_operation("profile", "No holder", bare.id, short.presets[0].id, base=[(clone, [])],
                           params={"FinalDepth": 8.0, "StepDown": 2.0})
        col2 = proj.material_check()["collisions"]
        self.assertEqual(col2["holder"], "not_checked")
        self.assertEqual(col2["no_holder"], ["No holder"])
        proj.close()


if __name__ == "__main__":
    unittest.main()
