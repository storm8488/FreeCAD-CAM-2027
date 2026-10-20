# SPDX-License-Identifier: LGPL-2.1-or-later
"""Chaîne complète : outil → préréglage → pièce → brut/montage → opération → parcours → export → sauvegarde/réouverture."""

import os
import tempfile
import unittest

import FreeCAD
import Part

from cam2027 import compat
from cam2027.tools.library import starter_library
from cam2027.tools import bridge
from cam2027.project.project import Project, ExportBlocked
from cam2027.project.machine import MachineProfile
from cam2027.project import export as exportmod


HOLE_CENTER = (72.0, 8.0)
HOLE_DIAMETER = 6.8  # avant-trou M8 x 1.25


def make_part(path):
    """Plaque 80x60x10 avec une poche rectangulaire, un îlot et un avant-trou débouchant, exportée en STEP."""
    plate = Part.makeBox(80, 60, 10)
    pocket = Part.makeBox(50, 30, 6, FreeCAD.Vector(15, 15, 4))
    island = Part.makeCylinder(6, 6, FreeCAD.Vector(40, 30, 4))
    hole = Part.makeCylinder(HOLE_DIAMETER / 2.0, 10, FreeCAD.Vector(HOLE_CENTER[0], HOLE_CENTER[1], 0))
    shape = plate.cut(pocket).fuse(island).cut(hole)
    shape.exportStep(path)
    return shape


def plate_top_face(clone):
    """Nom de la face supérieure de la plaque (z = 10, la plus grande)."""
    best = None
    for i, f in enumerate(clone.Shape.Faces, 1):
        if f.Surface.__class__.__name__ == "Plane" and abs(f.BoundBox.ZMax - 10.0) < 1e-6 and abs(f.BoundBox.ZMin - 10.0) < 1e-6:
            if best is None or f.Area > best[1]:
                best = ("Face%d" % i, f.Area)
    return best[0]


def plate_top_outer_edges(clone):
    """Arêtes du contour extérieur de la face supérieure (z = 10, sur le périmètre 80x60)."""
    names = []
    for i, e in enumerate(clone.Shape.Edges, 1):
        bb = e.BoundBox
        if abs(bb.ZMin - 10.0) > 1e-6 or abs(bb.ZMax - 10.0) > 1e-6:
            continue
        on_x = abs(bb.XMax - bb.XMin) < 1e-6 and (abs(bb.XMin) < 1e-6 or abs(bb.XMin - 80.0) < 1e-6)
        on_y = abs(bb.YMax - bb.YMin) < 1e-6 and (abs(bb.YMin) < 1e-6 or abs(bb.YMin - 60.0) < 1e-6)
        if on_x or on_y:
            names.append("Edge%d" % i)
    return names


def cutting_points(path):
    """Positions complètes (X, Y, Z modaux) atteintes par les mouvements de coupe G1/G2/G3."""
    pos = {}
    points = []
    for c in path.Commands:
        for k in "XYZ":
            if k in c.Parameters:
                pos[k] = c.Parameters[k]
        if c.Name in ("G1", "G2", "G3") and len(pos) == 3:
            points.append(dict(pos))
    return points


def vertical_plunges(path):
    """Nombre de descentes en avance de travail (G1) sans déplacement XY."""
    x = y = z = None
    count = 0
    for c in path.Commands:
        p = c.Parameters
        nx, ny, nz = p.get("X", x), p.get("Y", y), p.get("Z", z)
        if c.Name == "G1" and None not in (x, y, z, nz) and nz < z - 1e-6 and abs(nx - x) < 1e-6 and abs(ny - y) < 1e-6:
            count += 1
        x, y, z = nx, ny, nz
    return count


def hole_face(clone):
    """Face cylindrique de l'avant-trou."""
    for i, f in enumerate(clone.Shape.Faces, 1):
        if f.Surface.__class__.__name__ == "Cylinder" and abs(f.BoundBox.XMin - (HOLE_CENTER[0] - HOLE_DIAMETER / 2.0)) < 1e-3:
            return "Face%d" % i
    return None


class TestPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="cam2027-")
        cls.step = os.path.join(cls.tmp, "plate.step")
        make_part(cls.step)
        FreeCAD.ConfigSet("SuppressRecomputeRequiredDialog", "True")

    def _machine(self, **kw):
        m = MachineProfile("test", controller="grbl", post_processor="grbl",
                           post_processor_args="--no-show-editor --precision=3", **kw)
        return m

    def _project_with_job(self, name):
        """Projet + plaque importée + brut à marges 2 mm ; retourne (projet, bibliothèque, clone du modèle)."""
        lib = starter_library()
        proj = Project.create(name, lib, self._machine())
        part = proj.import_model(self.step, label="Plate").objects[0]
        job = proj.create_job([part], stock={"kind": "box_margins", "xy": 2.0, "z_top": 1.0, "z_bottom": 0.0})
        return proj, lib, job.Model.Group[0]

    def _single_result(self, proj):
        results = proj.compute()
        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertTrue(r["valid"], r)
        self.assertGreater(r["commands"], 10, r)
        self.assertEqual(r["axes"], ["X", "Y", "Z"], r)
        return r

    def test_full_chain(self):
        lib = starter_library()
        proj = Project.create("Chain test", lib, self._machine())
        self.assertEqual(proj.library.summary()["tools"], lib.summary()["tools"])

        # pièce
        res = proj.import_model(self.step, label="Plate")
        self.assertEqual(res.kind, "solid")
        self.assertEqual(len(res.objects), 1)
        self.assertEqual(res.warnings, [])
        part = res.objects[0]

        # brut : marges XY 2 mm, +1 mm au-dessus ; montage G54
        job = proj.create_job([part], stock={"kind": "box_margins", "xy": 2.0, "z_top": 1.0, "z_bottom": 0.0})
        sb = proj.stock_bounds()
        self.assertAlmostEqual(sb["length"], 84.0, places=3)
        self.assertAlmostEqual(sb["zmax"], 11.0, places=3)
        self.assertEqual(job.Fixtures, ["G54"])
        clamp = proj.add_clamp("Clamp left", 10, 20, 15, (-12, 20, 0))
        self.assertEqual(clamp.Label, "Clamp left")

        # outil / préréglage
        endmill = lib.search("6 mm flat end mill")[0]
        asm = lib.assemblies_for_tool(endmill.id)[0]
        preset = endmill.presets[0]

        # face du fond de poche : chercher la face plane à z=4 dans le clone du modèle
        clone = job.Model.Group[0]
        bottom = None
        for i, f in enumerate(clone.Shape.Faces, 1):
            if f.Surface.__class__.__name__ == "Plane" and abs(f.BoundBox.ZMax - 4.0) < 1e-6 and abs(f.BoundBox.ZMin - 4.0) < 1e-6:
                bottom = "Face%d" % i
        self.assertIsNotNone(bottom)

        op, rec = proj.add_operation(
            "pocket", "Pocket roughing", asm.id, preset.id, base=[(clone, [bottom])],
            params={"StepDown": 2.0, "StepOver": 40, "FinalDepth": 4.0, "NotAProperty": 1},
        )
        self.assertEqual(rec["ignored_params"], ["NotAProperty"])
        self.assertAlmostEqual(rec["values"]["feed_mm_min"], 1800.0)
        tc = proj.doc.getObject(rec["tool_controller"])
        vals = bridge.tool_controller_values(tc)
        self.assertAlmostEqual(vals["feed_mm_min"], 1800.0)
        self.assertAlmostEqual(vals["spindle_rpm"], 18000.0)
        self.assertAlmostEqual(vals["diameter_mm"], 6.0)
        self.assertEqual(vals["tool_number"], asm.output.tool_number)

        # changer le préréglage après coup ne modifie pas l'opération
        preset.feed_mm_min = 10.0
        self.assertAlmostEqual(bridge.tool_controller_values(tc)["feed_mm_min"], 1800.0)

        op2, rec2 = proj.add_operation(
            "profile", "Outside contour", asm.id, preset.id, base=[(clone, [])],
            params={"StepDown": 5.0, "FinalDepth": 0.0, "Side": "Outside", "Direction": "CW"},
        )

        # calcul
        results = proj.compute()
        self.assertEqual(len(results), 2)
        for r in results:
            self.assertTrue(r["valid"], r)
            self.assertGreater(r["commands"], 10, r)
            self.assertGreater(r["length_mm"], 50.0, r)
            self.assertEqual(r["axes"], ["X", "Y", "Z"], r)
        pocket = results[0]
        self.assertAlmostEqual(pocket["zmin"], 4.0, places=3)
        self.assertIn(1800.0, pocket["feeds"])
        contour = results[1]
        self.assertAlmostEqual(contour["zmin"], 0.0, places=3)
        # le contour extérieur doit sortir de la pièce (80x60) d'au moins un rayon d'outil
        bb = contour["bbox"]
        self.assertLess(bb["X"][0], -2.9)
        self.assertGreater(bb["X"][1], 82.9)

        # export
        out = os.path.join(self.tmp, "chain.nc")
        result = proj.export_gcode(out)
        self.assertTrue(os.path.isfile(out))
        self.assertTrue(os.path.isfile(result["sheet"]))
        a = result["analysis"]
        self.assertEqual(a["units"], "mm")
        self.assertIn("G54", a["fixtures"])
        self.assertIn("G1", a["codes"])
        self.assertEqual(a["axes"], ["X", "Y", "Z"])
        self.assertAlmostEqual(a["bbox"]["Z"][0], 0.0, places=3)
        self.assertEqual(a["max_feed"], 1800.0)
        self.assertIn(18000.0, a["spindle_speeds"])
        levels = [lvl for lvl, _ in result["issues"]]
        self.assertNotIn("error", levels)
        self.assertIn("unverifiable", levels)  # courses inconnues : signalé, pas inventé
        self.assertIn("| 1 |", result["sheet_text"])
        self.assertIn("Machine data still to fill in", result["sheet_text"])

        # sauvegarde / réouverture
        fcstd = os.path.join(self.tmp, "chain.FCStd")
        proj.save(fcstd)
        name = proj.doc.Name
        op_names = {op.Name, op2.Name}
        proj.close()
        self.assertNotIn(name, FreeCAD.listDocuments())
        again = Project.open(fcstd)
        self.assertEqual(again.library.summary()["tools"], lib.summary()["tools"])
        self.assertEqual(again.machine.controller, "grbl")
        self.assertEqual(len(again.operations()), 2)
        self.assertEqual(set(again.registry), op_names)
        self.assertAlmostEqual(again.registry[sorted(op_names)[0]]["values"]["feed_mm_min"], 1800.0)
        results2 = again.compute()
        self.assertEqual([r["commands"] for r in results2], [r["commands"] for r in results])
        text, analysis2, issues2 = again.preview_gcode()
        self.assertEqual(analysis2["bbox"], a["bbox"])
        again.close()

    def test_export_blocked_on_travel(self):
        lib = starter_library()
        proj = Project.create("Travel test", lib, self._machine(travel_x_mm=20, travel_y_mm=20, travel_z_mm=50))
        part = proj.import_model(self.step).objects[0]
        proj.create_job([part])
        endmill = lib.search("6 mm flat end mill")[0]
        asm = lib.assemblies_for_tool(endmill.id)[0]
        clone = proj.job.Model.Group[0]
        proj.add_operation("profile", "Contour", asm.id, endmill.presets[0].id, base=[(clone, [])],
                           params={"FinalDepth": 0.0})
        proj.compute()
        with self.assertRaises(ExportBlocked) as ctx:
            proj.export_gcode(os.path.join(self.tmp, "blocked.nc"))
        msgs = " ".join(m for _l, m in ctx.exception.issues)
        self.assertIn("exceeds travel", msgs)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "blocked.nc")))
        proj.close()

    def test_rotary_words_rejected(self):
        machine = self._machine()
        analysis = exportmod.analyze_gcode("G21 G54\nG0 X1 Y2 Z3 A90\nG1 X2 F100 S1000 M3\n")
        self.assertEqual(analysis["axes"], ["A", "X", "Y", "Z"])
        issues = exportmod.verify(analysis, machine)
        self.assertTrue(any("rotary" in m for _l, m in issues))
        analysis = exportmod.analyze_gcode("G20\nG0 X1\nG99\n")
        issues = exportmod.verify(analysis, machine)
        self.assertTrue(any("inches" in m for _l, m in issues))
        self.assertTrue(any("G99" in m for _l, m in issues))

    def test_facing(self):
        """Surfaçage de la face supérieure : Z final = 10 - passe, outil dépassant les bords."""
        proj, lib, clone = self._project_with_job("Facing test")
        endmill = lib.search("6 mm flat end mill")[0]
        asm = lib.assemblies_for_tool(endmill.id)[0]
        op, rec = proj.add_operation(
            "millface", "Top facing", asm.id, endmill.presets[0].id, base=[(clone, [plate_top_face(clone)])],
            params={"StepDown": 1.0, "FinalDepth": 9.0, "StepOver": 50, "ClearEdges": True},
        )
        self.assertEqual(rec["ignored_params"], [])
        r = self._single_result(proj)
        self.assertAlmostEqual(r["zmin"], 9.0, places=3)
        self.assertIn("G1", r["gcodes"])
        # le centre de l'outil sort de la pièce (80x60) : la fraise déborde d'au moins un rayon
        bb = r["bbox"]
        radius = endmill.geometry.diameter / 2.0
        self.assertLess(bb["X"][0] - radius, -radius)
        self.assertGreater(bb["X"][1] + radius, 80.0 + radius)
        self.assertLess(bb["Y"][0] - radius, -radius)
        self.assertGreater(bb["Y"][1] + radius, 60.0 + radius)
        proj.close()

    def test_thread_milling(self):
        """Filet M8 x 1.25 dans l'avant-trou avec la fraise à fileter de la bibliothèque de démarrage."""
        from cam2027.project import operations as opsmod

        proj, lib, clone = self._project_with_job("Thread test")
        tm = lib.search("thread mill")[0]
        self.assertEqual(tm.tool_type, "threadmill")
        asm = lib.assemblies_for_tool(tm.id)[0]
        preset = tm.presets[0]
        face = hole_face(clone)
        self.assertIsNotNone(face)

        # pas hors de la plage de l'outil (M12 x 1.75 > 1.25) et outil inadapté : refusés avant création
        with self.assertRaises(ValueError):
            opsmod.resolve_params("threadmill", tm, {"ThreadName": "M12 x 1.75"})
        endmill = lib.search("6 mm flat end mill")[0]
        with self.assertRaises(ValueError):
            opsmod.resolve_params("threadmill", endmill, {"ThreadName": "M8 x 1.25"})
        with self.assertRaises(ValueError):
            opsmod.thread_spec("MetricInternal6H", "M8 x 9")
        # sans nom ni pas : le pas (maximal) de l'outil est repris
        self.assertAlmostEqual(opsmod.resolve_params("threadmill", tm, {})["Pitch"], 1.25)

        op, rec = proj.add_operation(
            "threadmill", "Thread M8", asm.id, preset.id, base=[(clone, [face])],
            params={"ThreadType": "MetricInternal6H", "ThreadName": "M8 x 1.25", "Passes": 2,
                    "StartDepth": 10.0, "FinalDepth": 0.0, "LeadInOut": True},
        )
        self.assertEqual(rec["ignored_params"], [])
        p = rec["params"]
        # table FreeCAD metric-internal-6H, ajustement 50 % : 8 + (8.34-8)/2 ; 6.647 + (6.912-6.647)/2
        self.assertAlmostEqual(p["MajorDiameter"], 8.17, places=3)
        self.assertAlmostEqual(p["MinorDiameter"], 6.7795, places=3)
        self.assertAlmostEqual(p["Pitch"], 1.25)
        self.assertEqual(p["TPI"], 0)
        self.assertAlmostEqual(float(op.Pitch.getValueAs("mm")), 1.25)
        self.assertAlmostEqual(float(op.MajorDiameter.getValueAs("mm")), 8.17, places=3)
        self.assertEqual(op.Passes, 2)

        r = self._single_result(proj)
        self.assertIn("G3", r["gcodes"])  # filet à droite intérieur, avalant : G3 de bas en haut
        self.assertAlmostEqual(r["zmin"], 0.0, places=3)
        self.assertIn(400.0, r["feeds"])
        # dernière passe : rayon du centre outil = D maj/2 + H/8 - D outil/2 autour du centre du trou
        bb = r["bbox"]
        h = (p["MajorDiameter"] - p["MinorDiameter"]) / 2.0 * 1.6
        last_pass = p["MajorDiameter"] / 2.0 + h / 8.0 - tm.geometry.diameter / 2.0
        self.assertAlmostEqual(bb["Y"][1], HOLE_CENTER[1] + last_pass, places=2)
        self.assertAlmostEqual(bb["Y"][0], HOLE_CENTER[1] - last_pass, places=2)
        self.assertLess(abs(bb["X"][0] - HOLE_CENTER[0]), last_pass + 1e-3)
        proj.close()

    def test_chamfer(self):
        """Chanfrein 1 mm des arêtes supérieures de la plaque avec le V-bit 90°."""
        proj, lib, clone = self._project_with_job("Chamfer test")
        vbit = [t for t in lib.search("V-bit") if t.geometry.tip_included_angle_deg == 90.0][0]
        asm = lib.assemblies_for_tool(vbit.id)[0]
        edges = plate_top_outer_edges(clone)
        self.assertEqual(len(edges), 4)
        op, rec = proj.add_operation(
            "chamfer", "Top chamfer", asm.id, vbit.presets[0].id, base=[(clone, edges)],
            params={"Width": 1.0, "ExtraDepth": 0.5, "Direction": "CW", "EntryPoint": 0},
        )
        self.assertEqual(rec["ignored_params"], [])
        r = self._single_result(proj)
        # V-bit 90° : profondeur = largeur / tan(45°) + surprofondeur = 1.5 ; décalage = pointe/2 + 0.5
        self.assertAlmostEqual(r["zmin"], 10.0 - 1.5, places=3)
        self.assertIn("G2", r["gcodes"])  # arcs de raccordement aux angles (sens horaire)
        bb = r["bbox"]
        offset = vbit.geometry.tip_diameter / 2.0 + 0.5
        self.assertAlmostEqual(bb["X"][0], -offset, places=2)
        self.assertAlmostEqual(bb["X"][1], 80.0 + offset, places=2)
        self.assertAlmostEqual(bb["Y"][0], -offset, places=2)
        self.assertAlmostEqual(bb["Y"][1], 60.0 + offset, places=2)
        proj.close()

    def test_param_specs(self):
        """Chaque paramètre de chaque stratégie a une spec traduite ; lecture/écriture typée sur une opération."""
        import json
        from cam2027 import i18n
        from cam2027.project import operations as opsmod
        from cam2027.project import paramspec

        self.assertEqual(paramspec.unknown_params(opsmod.STRATEGIES), [])
        with open(os.path.join(os.path.dirname(i18n.__file__), "i18n", "fr.json"), "r", encoding="utf-8") as fp:
            catalog = json.load(fp)
        for _key, label in paramspec.GROUPS:
            self.assertIn(label, catalog)
        for name, (label, group, help_text) in paramspec.PARAM_SPECS.items():
            self.assertIn(group, dict(paramspec.GROUPS), name)
            self.assertIn(label, catalog, name)
            if help_text:
                self.assertIn(help_text, catalog, name)

        proj, lib, clone = self._project_with_job("Params test")
        endmill = lib.search("6 mm flat end mill")[0]
        asm = lib.assemblies_for_tool(endmill.id)[0]
        op, _rec = proj.add_operation("profile", "Contour", asm.id, endmill.presets[0].id, base=[(clone, [])],
                                      params={"FinalDepth": 0.0, "StepDown": 5.0, "Side": "Outside"})
        self.assertEqual(opsmod.param_kind(op, "StepDown")[0], "length")
        kind, choices = opsmod.param_kind(op, "Side")
        self.assertEqual(kind, "enum")
        self.assertIn("Inside", choices)
        self.assertEqual(opsmod.param_kind(op, "processHoles")[0], "bool")
        values = opsmod.read_params(op, opsmod.STRATEGIES["profile"]["params"])
        self.assertAlmostEqual(values["StepDown"], 5.0)
        self.assertAlmostEqual(values["FinalDepth"], 0.0)
        self.assertEqual(values["Side"], "Outside")
        self.assertIs(values["processHoles"], False)
        ignored = opsmod.set_params(op, {"StepDown": 2.5, "Side": "Inside", "Nope": 1})
        self.assertEqual(ignored, ["Nope"])
        self.assertAlmostEqual(opsmod.read_params(op, ["StepDown"])["StepDown"], 2.5)
        self.assertEqual(op.Side, "Inside")
        proj.close()

    def test_operation_edits(self):
        """Modification, ordre, activation, duplication, suppression et géométrie d'opérations existantes."""
        proj, lib, clone = self._project_with_job("Edit test")
        endmill = lib.search("6 mm flat end mill")[0]
        asm = lib.assemblies_for_tool(endmill.id)[0]
        preset = endmill.presets[0]
        op1, _r1 = proj.add_operation("profile", "Contour", asm.id, preset.id, base=[(clone, [])],
                                      params={"FinalDepth": 0.0, "StepDown": 5.0})
        op2, _r2 = proj.add_operation("millface", "Facing", asm.id, preset.id, base=[(clone, [plate_top_face(clone)])],
                                      params={"StepDown": 1.0, "FinalDepth": 9.0, "ClearEdges": True})
        # modification + registre
        self.assertEqual(proj.update_operation(op1, {"StepDown": 2.5, "Nope": 1}), ["Nope"])
        self.assertAlmostEqual(float(op1.StepDown.getValueAs("mm")), 2.5)
        self.assertAlmostEqual(proj.registry[op1.Name]["params"]["StepDown"], 2.5)
        # ordre
        self.assertEqual(proj.move_operation(op2, -1), 0)
        self.assertEqual(proj.operations()[0].Name, op2.Name)
        self.assertEqual(proj.registry[op2.Name]["order"], 0)
        self.assertEqual(proj.move_operation(op2, -1), 0)
        # activation
        proj.set_operation_active(op2, False)
        r2 = [r for r in proj.compute() if r["name"] == op2.Label][0]
        self.assertLessEqual(r2["commands"], 1)
        proj.set_operation_active(op2, True)
        r2 = [r for r in proj.compute() if r["name"] == op2.Label][0]
        self.assertGreater(r2["commands"], 10)
        # duplication : juste après l'original, mêmes valeurs, même parcours
        dup, drec = proj.duplicate_operation(op1)
        ops = proj.operations()
        self.assertEqual(len(ops), 3)
        self.assertEqual(ops[ops.index(op1) + 1].Name, dup.Name)
        self.assertAlmostEqual(float(dup.StepDown.getValueAs("mm")), 2.5)
        results = {r["name"]: r for r in proj.compute()}
        self.assertEqual(results[dup.Label]["commands"], results[op1.Label]["commands"])
        # filet : changer la désignation recalcule diamètres et pas
        tm = lib.search("thread mill")[0]
        tasm = lib.assemblies_for_tool(tm.id)[0]
        top, _t = proj.add_operation("threadmill", "Thread", tasm.id, tm.presets[0].id, base=[(clone, [hole_face(clone)])],
                                     params={"ThreadName": "M8 x 1.25", "StartDepth": 10.0, "FinalDepth": 0.0})
        proj.update_operation(top, {"ThreadName": "M8 x 1", "Passes": 3})
        self.assertAlmostEqual(float(top.Pitch.getValueAs("mm")), 1.0)
        self.assertAlmostEqual(float(top.MajorDiameter.getValueAs("mm")), 8.147, places=3)
        self.assertEqual(proj.registry[top.Name]["params"]["ThreadName"], "M8 x 1")
        with self.assertRaises(ValueError):
            proj.update_operation(top, {"ThreadName": "M12 x 1.75"})
        # suppression : opération, ToolController, ToolBit et registre
        tc_name, bit_name, dup_name = drec["tool_controller"], drec["toolbit"], dup.Name
        proj.remove_operation(dup)
        self.assertEqual([o.Name for o in proj.operations()], [op2.Name, op1.Name, top.Name])
        self.assertIsNone(proj.doc.getObject(tc_name))
        self.assertIsNone(proj.doc.getObject(bit_name))
        self.assertIsNone(proj.doc.getObject(dup_name))
        self.assertNotIn(dup_name, proj.registry)
        self.assertEqual([proj.registry[o.Name]["order"] for o in proj.operations()], [0, 1, 2])
        # géométrie
        face = plate_top_face(clone)
        proj.set_operation_base(op1, [(clone, [face])])
        self.assertEqual(list(op1.Base[0][1]), [face])
        proj.set_operation_base(op1, [])
        self.assertEqual(list(op1.Base), [])
        proj.close()

    def test_dressups(self):
        """Attaches sur un contour (remontées au-dessus de Z final, pas de double export) ; rampe d'entrée."""
        from cam2027.project import export as exportmod

        proj, lib, clone = self._project_with_job("Dressup test")
        endmill = lib.search("6 mm flat end mill")[0]
        asm = lib.assemblies_for_tool(endmill.id)[0]
        op, _rec = proj.add_operation("profile", "Contour", asm.id, endmill.presets[0].id, base=[(clone, [])],
                                      params={"FinalDepth": 0.0, "StepDown": 5.0})
        base_cmds = proj.compute()[0]["commands"]
        self.assertGreater(vertical_plunges(op.Path), 0)
        lines0 = len("\n".join(g for _n, g in exportmod.postprocess(proj.job)).splitlines())

        tags, ignored = proj.add_dressup(op, "tags", params={"Height": 4.0, "Width": 8.0}, count=4)
        self.assertEqual(ignored, [])
        self.assertEqual(len(tags.Positions), 4)
        self.assertEqual([o.Name for o in proj.operations()], [tags.Name])
        self.assertIs(proj.base_operation(tags), op)
        self.assertEqual(proj.registry[op.Name]["dressups"][0]["kind"], "tags")
        r = proj.compute()[0]
        self.assertGreater(r["commands"], base_cmds)
        self.assertAlmostEqual(r["zmin"], 0.0, places=3)
        # à la dernière couche (Z 0), le parcours remonte au sommet des attaches (Z = 0 + hauteur)
        feed_z = sorted(set(round(c.Parameters["Z"], 3) for c in tags.Path.Commands
                            if c.Name in ("G1", "G2", "G3") and "Z" in c.Parameters))
        self.assertIn(4.0, feed_z)
        # export : une seule occurrence du contour (l'habillage remplace l'opération)
        text = "\n".join(g for _n, g in exportmod.postprocess(proj.job))
        self.assertEqual(text.count("(Begin operation: %s)" % op.Label), 0)
        self.assertEqual(text.count("(Begin operation: %s)" % tags.Label), 1)
        self.assertGreater(len(text.splitlines()), lines0)

        with self.assertRaises(ValueError):
            proj.add_dressup(op, "tags")
        ramp, _ignored = proj.add_dressup(op, "ramp", params={"Angle": 5.0})
        self.assertEqual(len(proj.dressups(op)), 2)
        self.assertEqual([o.Name for o in proj.operations()], [ramp.Name])
        proj.compute()
        self.assertEqual(vertical_plunges(ramp.Path), 0)
        self.assertEqual(sorted(d["kind"] for d in proj.registry[op.Name]["dressups"]), ["ramp", "tags"])

        proj.remove_dressup(op, "tags")
        self.assertEqual([o.Name for o in proj.operations()], [ramp.Name])
        self.assertEqual(len(proj.dressups(op)), 1)
        proj.remove_dressup(op, "ramp")
        self.assertEqual([o.Name for o in proj.operations()], [op.Name])
        self.assertEqual(proj.registry[op.Name]["dressups"], [])
        self.assertEqual(proj.compute()[0]["commands"], base_cmds)
        proj.close()

    def test_drilling_all_holes(self):
        """Perçage sans géométrie sélectionnée : FreeCAD détecte les trous plus grands que le foret."""
        proj, lib, clone = self._project_with_job("Drill test")
        drill = lib.search("3 mm drill")[0]
        asm = lib.assemblies_for_tool(drill.id)[0]
        op, rec = proj.add_operation("drilling", "Drill all", asm.id, drill.presets[0].id, base=[(clone, [])],
                                     params={"PeckEnabled": True, "PeckDepth": 2.0})
        self.assertEqual(rec["ignored_params"], [])
        self.assertEqual(len(op.Base), 1)
        self.assertEqual(list(op.Base[0][1]), [hole_face(clone)])
        r = proj.compute()[0]
        self.assertTrue(r["valid"], r)
        self.assertGreaterEqual(r["commands"], 5, r)  # cycle G83 : une ligne par trou
        self.assertIn("G83", r["gcodes"])
        self.assertAlmostEqual(r["zmin"], 0.0, places=3)
        bb = r["bbox"]
        self.assertAlmostEqual(bb["X"][0], HOLE_CENTER[0], places=3)
        self.assertAlmostEqual(bb["Y"][0], HOLE_CENTER[1], places=3)
        # géométrie explicite vide pour une autre stratégie : tout le modèle
        endmill = lib.search("6 mm flat end mill")[0]
        easm = lib.assemblies_for_tool(endmill.id)[0]
        op2, _r2 = proj.add_operation("profile", "Contour", easm.id, endmill.presets[0].id, base=[(clone, [])],
                                      params={"FinalDepth": 0.0})
        self.assertEqual([subs for _o, subs in op2.Base if subs], [])  # FreeCAD normalise (objet, []) en vide
        r2 = {r["name"]: r for r in proj.compute()}["Contour"]
        self.assertGreater(r2["commands"], 10)
        proj.close()

    def test_helix_and_engrave(self):
        """Alésage hélicoïdal de l'avant-trou avec la fraise 3 mm ; gravure des arêtes supérieures au V-bit 60°."""
        proj, lib, clone = self._project_with_job("Helix test")
        small = [t for t in lib.search("3 mm flat end mill") if t.tool_type == "endmill"][0]
        sasm = lib.assemblies_for_tool(small.id)[0]
        op, rec = proj.add_operation("helix", "Helix bore", sasm.id, small.presets[0].id, base=[(clone, [hole_face(clone)])],
                                     params={"StartDepth": 10.0, "FinalDepth": 0.0, "StepDown": 1.0, "StepOver": 50})
        self.assertEqual(rec["ignored_params"], [])
        results = {r["name"]: r for r in proj.compute()}
        r = results["Helix bore"]
        self.assertTrue(r["valid"] and r["commands"] > 10, r)
        self.assertTrue({"G2", "G3"} & set(r["gcodes"]), r["gcodes"])
        self.assertAlmostEqual(r["zmin"], 0.0, places=3)
        reach = (HOLE_DIAMETER - small.geometry.diameter) / 2.0
        self.assertLessEqual(r["bbox"]["X"][1] - HOLE_CENTER[0], reach + 1e-3)
        self.assertGreaterEqual(r["bbox"]["X"][0] - HOLE_CENTER[0], -reach - 1e-3)

        vbit = [t for t in lib.search("V-bit") if t.geometry.tip_included_angle_deg == 60.0][0]
        vasm = lib.assemblies_for_tool(vbit.id)[0]
        op2, rec2 = proj.add_operation("engrave", "Engrave edges", vasm.id, vbit.presets[0].id,
                                       base=[(clone, plate_top_outer_edges(clone))],
                                       params={"StartDepth": 10.0, "FinalDepth": 9.5, "StepDown": 0.5})
        self.assertEqual(rec2["ignored_params"], [])
        results = {r["name"]: r for r in proj.compute()}
        r2 = results["Engrave edges"]
        self.assertTrue(r2["valid"] and r2["commands"] > 5, r2)
        self.assertAlmostEqual(r2["zmin"], 9.5, places=3)
        self.assertAlmostEqual(r2["bbox"]["X"][0], 0.0, places=3)
        self.assertAlmostEqual(r2["bbox"]["X"][1], 80.0, places=3)
        self.assertAlmostEqual(r2["bbox"]["Y"][1], 60.0, places=3)
        proj.close()

    def test_change_operation_tool(self):
        """Changer le préréglage met à jour le ToolController ; changer l'outil le remplace et recalcule le parcours."""
        proj, lib, clone = self._project_with_job("Tool change test")
        endmill = lib.search("6 mm flat end mill")[0]
        asm = lib.assemblies_for_tool(endmill.id)[0]
        rough, finish = endmill.presets[0], endmill.presets[1]
        op, rec = proj.add_operation("profile", "Contour", asm.id, rough.id, base=[(clone, [])],
                                     params={"FinalDepth": 0.0, "StepDown": 5.0})
        r0 = proj.compute()[0]
        self.assertAlmostEqual(r0["bbox"]["X"][0], -3.0, places=2)
        tc_name = rec["tool_controller"]
        # même outil, autre préréglage : valeurs du contrôleur mises à jour, même contrôleur
        rec2 = proj.change_operation_tool(op, asm.id, finish.id)
        self.assertEqual(rec2["tool_controller"], tc_name)
        self.assertAlmostEqual(rec2["values"]["feed_mm_min"], 600.0)
        tc = proj.doc.getObject(tc_name)
        self.assertAlmostEqual(bridge.tool_controller_values(tc)["feed_mm_min"], 600.0)
        self.assertAlmostEqual(bridge.tool_controller_values(tc)["spindle_rpm"], 16000.0)
        self.assertIn(600.0, proj.compute()[0]["feeds"])
        # autre outil (3 mm) : nouveau contrôleur, ancien supprimé, contour décalé d'un rayon plus petit
        small = [t for t in lib.search("3 mm flat end mill") if t.tool_type == "endmill"][0]
        sasm = lib.assemblies_for_tool(small.id)[0]
        rec3 = proj.change_operation_tool(op, sasm.id, small.presets[0].id)
        self.assertNotEqual(rec3["tool_controller"], tc_name)
        self.assertIsNone(proj.doc.getObject(tc_name))
        self.assertEqual(op.ToolController.Name, rec3["tool_controller"])
        self.assertAlmostEqual(bridge.tool_controller_values(op.ToolController)["diameter_mm"], 3.0)
        self.assertEqual([t.Name for t in proj.job.Tools.Group], [rec3["tool_controller"]])
        r3 = proj.compute()[0]
        self.assertAlmostEqual(r3["bbox"]["X"][0], -1.5, places=2)
        self.assertAlmostEqual(float(op.StepDown.getValueAs("mm")), 5.0)  # réglages conservés
        # filetage : un outil non fileteur est refusé
        tm = lib.search("thread mill")[0]
        tasm = lib.assemblies_for_tool(tm.id)[0]
        top, _t = proj.add_operation("threadmill", "Thread", tasm.id, tm.presets[0].id, base=[(clone, [hole_face(clone)])],
                                     params={"ThreadName": "M8 x 1.25", "StartDepth": 10.0, "FinalDepth": 0.0})
        with self.assertRaises(ValueError):
            proj.change_operation_tool(top, asm.id, rough.id)
        proj.close()

    def test_dogbones(self):
        """Dogbones sur la poche rectangulaire : le centre de l'outil entre dans les angles au-delà du décalage."""
        proj, lib, clone = self._project_with_job("Dogbone test")
        endmill = lib.search("6 mm flat end mill")[0]
        asm = lib.assemblies_for_tool(endmill.id)[0]
        bottom = None
        for i, f in enumerate(clone.Shape.Faces, 1):
            if f.Surface.__class__.__name__ == "Plane" and abs(f.BoundBox.ZMax - 4.0) < 1e-6 and abs(f.BoundBox.ZMin - 4.0) < 1e-6:
                bottom = "Face%d" % i
        op, _rec = proj.add_operation("pocket", "Pocket", asm.id, endmill.presets[0].id, base=[(clone, [bottom])],
                                      params={"StepDown": 2.0, "StepOver": 40, "FinalDepth": 4.0})
        r0 = proj.compute()[0]
        radius = endmill.geometry.diameter / 2.0
        self.assertAlmostEqual(r0["bbox"]["X"][0], 15.0 + radius, places=2)  # paroi de la poche à X = 15
        bones, ignored = proj.add_dressup(op, "dogbone", params={"Style": "Dogbone", "Incision": "adaptive"})
        self.assertEqual(ignored, [])
        self.assertEqual(bones.Style, "Dogbone")
        r1 = proj.compute()[0]
        self.assertGreater(r1["commands"], r0["commands"])
        # un os à 45° dans chaque angle : le centre dépasse le décalage d'environ r·(√2 − 1) ≈ 1,24 mm
        self.assertLess(r1["bbox"]["X"][0], 15.0 + radius - 0.5)
        self.assertGreater(r1["bbox"]["X"][0], 15.0)
        self.assertGreater(r1["bbox"]["X"][1], 65.0 - radius + 0.5)
        self.assertAlmostEqual(r1["zmin"], 4.0, places=3)
        proj.remove_dressup(op, "dogbone")
        self.assertEqual(proj.compute()[0]["commands"], r0["commands"])
        proj.close()

    def test_vcarve_and_slot(self):
        """V-carving du fond de poche (profondeur limitée) ; rainure entre deux points personnalisés."""
        proj, lib, clone = self._project_with_job("Vcarve test")
        bottom = None
        for i, f in enumerate(clone.Shape.Faces, 1):
            if f.Surface.__class__.__name__ == "Plane" and abs(f.BoundBox.ZMax - 4.0) < 1e-6 and abs(f.BoundBox.ZMin - 4.0) < 1e-6:
                bottom = "Face%d" % i
        vbit = [t for t in lib.search("V-bit") if t.geometry.tip_included_angle_deg == 60.0][0]
        vasm = lib.assemblies_for_tool(vbit.id)[0]
        op, rec = proj.add_operation("vcarve", "Vcarve floor", vasm.id, vbit.presets[0].id, base=[(clone, [bottom])],
                                     params={"FinalDepth": 2.0})
        self.assertEqual(rec["ignored_params"], [])
        results = {r["name"]: r for r in proj.compute()}
        r = results["Vcarve floor"]
        self.assertTrue(r["valid"] and r["commands"] > 10, r)
        # axe médian de la face 50x30 : reste dans la poche ; profondeur bornée par FinalDepth
        self.assertGreaterEqual(r["bbox"]["X"][0], 15.0 - 1e-3)
        self.assertLessEqual(r["bbox"]["X"][1], 65.0 + 1e-3)
        self.assertAlmostEqual(r["zmin"], 2.0, places=3)

        endmill = lib.search("6 mm flat end mill")[0]
        asm = lib.assemblies_for_tool(endmill.id)[0]
        op2, rec2 = proj.add_operation("slot", "Slot", asm.id, endmill.presets[0].id, base=None,
                                       params={"StepDown": 2.0, "StartDepth": 10.0, "FinalDepth": 8.0})
        from cam2027.project import operations as opsmod

        self.assertEqual(opsmod.param_kind(op2, "CustomPoint1")[0], "vector")
        self.assertEqual(proj.update_operation(op2, {"CustomPoint1": (10, 50, 10), "CustomPoint2": [70, 50, 10]}), [])
        self.assertEqual(opsmod.read_params(op2, ["CustomPoint2"])["CustomPoint2"], (70.0, 50.0, 10.0))
        results = {r["name"]: r for r in proj.compute()}
        r2 = results["Slot"]
        self.assertTrue(r2["valid"] and r2["commands"] > 5, r2)
        self.assertAlmostEqual(r2["zmin"], 8.0, places=3)
        self.assertAlmostEqual(r2["bbox"]["X"][0], 10.0, places=3)
        self.assertAlmostEqual(r2["bbox"]["X"][1], 70.0, places=3)
        self.assertAlmostEqual(r2["bbox"]["Y"][0], 50.0, places=3)
        proj.close()

    def test_sheet_from_drawing(self):
        """Flux 2D : SVG, panneau 12 mm sous le dessin, découpe, poche 2D, V-carving, gravure, export."""
        from tests.test_import import SVG
        from cam2027.project import sheet as sheetmod

        svg = os.path.join(self.tmp, "drawing.svg")
        with open(svg, "w", encoding="utf-8") as fp:
            fp.write(SVG)
        lib = starter_library()
        proj = Project.create("Sheet test", lib, self._machine())
        res = proj.import_model(svg)
        self.assertEqual(res.kind, "vector")
        vectors = sheetmod.vector_objects(proj.doc)
        self.assertEqual(len(vectors), 3)
        job = proj.create_sheet_job(thickness=12.0, margin=10.0)
        sb = proj.stock_bounds()
        self.assertAlmostEqual(sb["zmax"], 0.0, places=6)
        self.assertAlmostEqual(sb["zmin"], -12.0, places=6)
        rect = [v for v in vectors if len(v.Shape.Edges) == 4][0]
        circle = [v for v in vectors if len(v.Shape.Edges) == 1][0]
        bbr, bbc = rect.Shape.BoundBox, circle.Shape.BoundBox
        self.assertAlmostEqual(sb["xmin"], min(v.Shape.BoundBox.XMin for v in vectors) - 10.0, places=3)

        endmill = lib.search("6 mm flat end mill")[0]
        asm = lib.assemblies_for_tool(endmill.id)[0]
        small = [t for t in lib.search("3 mm flat end mill") if t.tool_type == "endmill"][0]
        sasm = lib.assemblies_for_tool(small.id)[0]
        vbit = [t for t in lib.search("V-bit") if t.geometry.tip_included_angle_deg == 60.0][0]
        vasm = lib.assemblies_for_tool(vbit.id)[0]
        rclone = proj.drawing_clone(rect)
        proj.add_operation("profile", "Cut out", asm.id, endmill.presets[0].id,
                           base=[(rclone, ["Edge%d" % i for i in range(1, 5)])],
                           params={"Side": "Outside", "StartDepth": 0.0, "FinalDepth": -12.0, "StepDown": 4.0})
        proj.add_operation("pocket2d", "Pocket circle", sasm.id, small.presets[0].id,
                           base=[(proj.drawing_clone(circle, face=True), ["Face1"])],
                           params={"StartDepth": 0.0, "FinalDepth": -3.0, "StepDown": 1.5, "StepOver": 40})
        proj.add_operation("vcarve", "Vcarve rect", vasm.id, vbit.presets[0].id,
                           base=[(proj.drawing_clone(rect, face=True), ["Face1"])], params={"FinalDepth": -4.0})
        proj.add_operation("engrave", "Engrave circle", vasm.id, vbit.presets[0].id,
                           base=[(proj.drawing_clone(circle), ["Edge1"])],
                           params={"StartDepth": 0.0, "FinalDepth": -1.0, "StepDown": 1.0})
        results = {r["name"]: r for r in proj.compute()}
        for r in results.values():
            self.assertTrue(r["valid"] and r["commands"] > 5, r)
        cut = results["Cut out"]
        self.assertAlmostEqual(cut["zmin"], -12.0, places=3)
        self.assertAlmostEqual(cut["bbox"]["X"][0], bbr.XMin - 3.0, places=2)
        self.assertAlmostEqual(cut["bbox"]["X"][1], bbr.XMax + 3.0, places=2)
        pocket = results["Pocket circle"]
        self.assertAlmostEqual(pocket["zmin"], -3.0, places=3)
        self.assertGreater(pocket["bbox"]["X"][0], bbc.XMin + 1.5 - 1e-3)
        self.assertLess(pocket["bbox"]["X"][1], bbc.XMax - 1.5 + 1e-3)
        carve = results["Vcarve rect"]
        self.assertAlmostEqual(carve["zmin"], -4.0, places=3)
        self.assertGreaterEqual(carve["bbox"]["X"][0], bbr.XMin - 1e-3)
        self.assertAlmostEqual(results["Engrave circle"]["zmin"], -1.0, places=3)
        # sélection « entière » d'un vecteur (clic dans la vue) : arêtes ou face selon la stratégie
        op_e, _r = proj.add_operation("profile", "Cut circle", asm.id, endmill.presets[0].id, base=[(circle, [])],
                                      params={"Side": "Inside", "StartDepth": 0.0, "FinalDepth": -12.0, "StepDown": 6.0})
        self.assertEqual(list(op_e.Base[0][1]), ["Edge1"])
        op_f, _r = proj.add_operation("pocket2d", "Pocket rect", sasm.id, small.presets[0].id, base=[(rect, [])],
                                      params={"StartDepth": 0.0, "FinalDepth": -2.0, "StepDown": 1.0})
        self.assertEqual(list(op_f.Base[0][1]), ["Face1"])
        self.assertTrue(op_f.Base[0][0].Name.startswith("Clone"))
        triangle = [v for v in vectors if v not in (rect, circle)][0]
        results = {r["name"]: r for r in proj.compute()}
        # contour intérieur : chaque point de coupe à la profondeur est sur le rayon r - 3 (centre outil)
        # sur 1.0.2 le cercle SVG est une B-spline et sa BoundBox est approchée : centre et rayon
        # déduits du centre de gravité et de la longueur de l'arête
        import math
        edge = circle.Shape.Edges[0]
        cx, cy, rad = edge.CenterOfMass.x, edge.CenterOfMass.y, edge.Length / (2.0 * math.pi)
        cut_pts = [c.Parameters for c in op_e.Path.Commands if c.Name in ("G1", "G2", "G3")
                   and "X" in c.Parameters and "Y" in c.Parameters and c.Parameters.get("Z", -1.0) < 0.0]
        self.assertGreater(len(cut_pts), 0)
        for p in cut_pts:
            self.assertAlmostEqual(((p["X"] - cx) ** 2 + (p["Y"] - cy) ** 2) ** 0.5, rad - 3.0, delta=0.05)
        self.assertAlmostEqual(results["Pocket rect"]["zmin"], -2.0, places=3)
        self.assertTrue(triangle.Shape.isClosed())
        out = os.path.join(self.tmp, "sheet.nc")
        result = proj.export_gcode(out)
        self.assertNotIn("error", [lvl for lvl, _m in result["issues"]])
        self.assertAlmostEqual(result["analysis"]["bbox"]["Z"][0], -12.0, places=3)
        proj.close()

    def test_compute_states(self):
        """À calculer, Calculé, À recalculer après modification, Inactive, Avertissement, Échec."""
        proj, lib, clone = self._project_with_job("States test")
        endmill = lib.search("6 mm flat end mill")[0]
        asm = lib.assemblies_for_tool(endmill.id)[0]
        op, _rec = proj.add_operation("profile", "Contour", asm.id, endmill.presets[0].id, base=[(clone, [])],
                                      params={"FinalDepth": 0.0, "StepDown": 5.0})
        self.assertEqual(proj.operation_state(op), "todo")
        proj.compute()
        self.assertEqual(proj.operation_state(op), "computed")
        proj.update_operation(op, {"StepDown": 2.0})
        self.assertEqual(proj.operation_state(op), "stale")
        proj.compute()
        self.assertEqual(proj.operation_state(op), "computed")
        proj.set_operation_active(op, False)
        self.assertEqual(proj.operation_state(op), "inactive")
        proj.set_operation_active(op, True)
        proj.compute()
        # avertissement : paramètre ignoré enregistré
        proj.update_operation(op, {"NotAProperty": 1})
        proj.compute()
        self.assertEqual(proj.operation_state(op), "warning")
        # échec : gravure sans aucune arête -> aucun mouvement de coupe
        vbit = [t for t in lib.search("V-bit") if t.geometry.tip_included_angle_deg == 60.0][0]
        op2, _r2 = proj.add_operation("engrave", "Empty engrave", lib.assemblies_for_tool(vbit.id)[0].id,
                                      vbit.presets[0].id, base=None, params={})
        proj.compute()
        self.assertEqual(proj.operation_state(op2), "failed")
        proj.close()

    def test_export_summary(self):
        """Récapitulatif avant export : machine, post, unités, repères, axes, état de chaque opération, contrôles."""
        proj, lib, clone = self._project_with_job("Summary test")
        endmill = lib.search("6 mm flat end mill")[0]
        asm = lib.assemblies_for_tool(endmill.id)[0]
        op, _rec = proj.add_operation("profile", "Contour", asm.id, endmill.presets[0].id, base=[(clone, [])],
                                      params={"FinalDepth": 0.0, "StepDown": 5.0})
        proj.compute()
        text, analysis, issues = proj.preview_gcode()
        rows = exportmod.export_summary(proj, analysis, issues)
        d = {label: (value, level) for label, value, level, _params in rows}
        self.assertEqual(d["Units"], ("mm", "ok"))
        self.assertEqual(d["Work offsets"], ("G54", "ok"))
        self.assertEqual(d["Operation: Contour"], ("Computed", "ok"))
        self.assertEqual(d["Checks"][1], "unverifiable")  # courses inconnues : jamais « ok »
        self.assertEqual(d["Machine validation"][1], "unverifiable")
        proj.update_operation(op, {"StepDown": 2.0})
        rows = exportmod.export_summary(proj, analysis, issues)
        self.assertIn(("Operation: Contour", "To recompute", "warning", {}), rows)
        proj.close()

    def test_machine_field_labels(self):
        """Chaque champ machine (et de l'axe A) qui peut manquer a un libellé traduit."""
        import json
        from cam2027 import i18n
        from cam2027.project.machine import FIELD_LABELS, RotaryAxis

        with open(os.path.join(os.path.dirname(i18n.__file__), "i18n", "fr.json"), "r", encoding="utf-8") as fp:
            catalog = json.load(fp)
        fields = list(MachineProfile.FIELDS) + ["rotary.%s" % f for f in RotaryAxis.FIELDS if f not in ("name", "about", "present")]
        for f in fields:
            self.assertIn(f, FIELD_LABELS, f)
            self.assertIn(FIELD_LABELS[f], catalog, f)
        m = MachineProfile("x")
        self.assertTrue(all(f in FIELD_LABELS for f in m.unknown_fields()))

    def test_3d_finishing(self):
        """Dôme sur plaque : surfaçage 3D sans pénétration de la surface, Z constant en plusieurs niveaux."""
        import math

        step = os.path.join(self.tmp, "dome.step")
        cx, cy, cz, radius = 30.0, 20.0, -15.0, 25.0  # sphère tronquée : sommet à Z 10, raccord à Z 5
        plate = Part.makeBox(60, 40, 5)
        dome = Part.makeSphere(radius, FreeCAD.Vector(cx, cy, cz)).common(Part.makeBox(60, 40, 30, FreeCAD.Vector(0, 0, 5)))
        plate.fuse(dome).removeSplitter().exportStep(step)

        def surface_z(x, y):
            d2 = (x - cx) ** 2 + (y - cy) ** 2
            top = cz + math.sqrt(radius ** 2 - d2) if d2 < radius ** 2 else -1e9
            return max(5.0, top) if 0 <= x <= 60 and 0 <= y <= 40 else -1e9

        lib = starter_library()
        proj = Project.create("3D test", lib, self._machine())
        part = proj.import_model(step, label="Dome").objects[0]
        job = proj.create_job([part], stock={"kind": "box_margins", "xy": 2.0, "z_top": 1.0, "z_bottom": 0.0})
        clone = job.Model.Group[0]
        ball = lib.search("6 mm ball end mill")[0]
        basm = lib.assemblies_for_tool(ball.id)[0]
        op, rec = proj.add_operation("surface3d", "Dome finishing", basm.id, ball.presets[0].id, base=[(clone, [])],
                                     params={"CutPattern": "ZigZag", "StepOver": 40, "SampleInterval": 0.5,
                                             "BoundBox": "BaseBoundBox", "FinalDepth": 5.0})
        self.assertEqual(rec["ignored_params"], [])
        op2, rec2 = proj.add_operation("waterline", "Dome waterline", basm.id, ball.presets[0].id, base=[(clone, [])],
                                       params={"LayerMode": "Multi-pass", "StepDown": 1.0, "StartDepth": 10.0,
                                               "FinalDepth": 5.0, "SampleInterval": 0.5, "BoundBox": "BaseBoundBox"})
        self.assertEqual(rec2["ignored_params"], [])
        results = {r["name"]: r for r in proj.compute()}
        r = results["Dome finishing"]
        self.assertTrue(r["valid"] and r["commands"] > 100, r)
        cuts = [c.Parameters for c in op.Path.Commands if c.Name in ("G1", "G2", "G3")
                and all(k in c.Parameters for k in "XYZ")]
        self.assertGreater(len(cuts), 100)
        # la pointe de la fraise boule ne descend jamais sous la surface (pas de pénétration)
        for p in cuts:
            self.assertGreaterEqual(p["Z"], surface_z(p["X"], p["Y"]) - 0.05, p)
        self.assertAlmostEqual(min(p["Z"] for p in cuts), 5.0, places=2)
        self.assertGreater(max(p["Z"] for p in cuts), 9.5)  # le sommet du dôme est suivi
        r2 = results["Dome waterline"]
        self.assertTrue(r2["valid"] and r2["commands"] > 20, r2)
        levels = sorted(set(round(c.Parameters["Z"], 2) for c in op2.Path.Commands
                            if c.Name in ("G1", "G2", "G3") and "Z" in c.Parameters))
        self.assertGreaterEqual(len(levels), 4, levels)
        self.assertAlmostEqual(levels[0], 5.0, places=2)
        self.assertEqual(proj.operation_state(op), "computed")

        # ébauche 3D : modèle entier sélectionné -> faces en relief (le dôme) ; surépaisseur respectée
        from cam2027.project import operations as opsmod
        self.assertEqual([clone.Shape.getElement(n).Surface.__class__.__name__ for n in opsmod.raised_faces(clone)],
                         ["Sphere"])
        endmill = lib.search("6 mm flat end mill")[0]
        rop, rrec = proj.add_operation("rough3d", "Dome roughing", lib.assemblies_for_tool(endmill.id)[0].id,
                                       endmill.presets[0].id, base=[(clone, [])],
                                       params={"StepDown": 1.0, "StepOver": 20, "StockToLeave": 0.5, "FinalDepth": 5.0})
        self.assertEqual(rrec["ignored_params"], [])
        self.assertEqual(rop.Side, "Outside")
        proj.compute()
        rcuts = cutting_points(rop.Path)  # l'adaptatif n'écrit Z qu'une fois par niveau (modal)
        self.assertGreater(len(rcuts), 100)
        rlevels = sorted(set(round(p["Z"], 2) for p in rcuts))
        self.assertEqual(rlevels[0], 5.0)
        self.assertGreaterEqual(len(rlevels), 5, rlevels)
        tool_r = endmill.geometry.diameter / 2.0
        for p in rcuts:
            if p["Z"] > 5.01:  # au-dessus de la plaque : jamais plus près du dôme que rayon outil + surépaisseur
                dome_r = math.sqrt(max(0.0, radius ** 2 - (p["Z"] - cz) ** 2))
                dist = math.sqrt((p["X"] - cx) ** 2 + (p["Y"] - cy) ** 2)
                self.assertGreaterEqual(dist, dome_r + tool_r + 0.5 - 0.05, p)
        proj.close()

    def test_relief_from_image(self):
        """Relief depuis une image : bosse gaussienne connue -> solide fidèle, ébauche et finition 3D sans pénétration."""
        import math
        from cam2027.project import relief

        try:
            from PySide6 import QtGui
        except ImportError:
            from PySide2 import QtGui
        width, length, height, base = 60.0, 45.0, 6.0, 3.0
        w_px, h_px = 80, 60

        def bump(x, y):
            return math.exp(-((x - 30.0) ** 2 + (y - 22.5) ** 2) / (2 * 8.0 ** 2))

        def surface_z(x, y):
            return base + height * bump(x, y) if 0 <= x <= width and 0 <= y <= length else -1e9

        img = QtGui.QImage(w_px, h_px, QtGui.QImage.Format_RGB32)
        for row in range(h_px):
            for col in range(w_px):
                v = int(round(255 * bump(col * width / (w_px - 1), (h_px - 1 - row) * length / (h_px - 1))))
                img.setPixel(col, row, QtGui.qRgb(v, v, v))
        png = os.path.join(self.tmp, "bump.png")
        self.assertTrue(img.save(png))
        self.assertTrue(relief.ensure_image_plugins(), relief.supported_formats())  # JPG lisible même en console
        jpg = os.path.join(self.tmp, "bump.jpg")
        self.assertTrue(img.save(jpg, "JPG", 95))
        grid, size = relief.load_heightmap(jpg)
        self.assertEqual(size, (w_px, h_px))
        self.assertGreater(grid[40][30], 0.95)
        self.assertLess(grid[0][0], 0.05)

        lib = starter_library()
        proj = Project.create("Relief test", lib, self._machine())
        res = proj.import_relief(png, width, height, base=base, smoothing=0)
        self.assertEqual(res.warnings, [])
        obj = res.objects[0]
        shape = obj.Shape
        self.assertTrue(shape.isValid() and len(shape.Solids) == 1)
        bb = shape.optimalBoundingBox()
        for got, want in ((bb.XLength, width), (bb.YLength, length), (bb.ZMin, 0.0), (bb.ZMax, base + height)):
            self.assertAlmostEqual(got, want, delta=0.05)
        # fidélité : 0,15 mm sous la hauteur attendue -> matière, 0,15 mm au-dessus -> vide
        for x in (1.0, 10.0, 20.0, 26.0, 30.0, 34.0, 45.0, 59.0):
            for y in (1.0, 12.0, 18.0, 22.5, 27.0, 35.0, 44.0):
                z = surface_z(x, y)
                self.assertTrue(shape.isInside(FreeCAD.Vector(x, y, z - 0.15), 1e-4, True), (x, y, z))
                self.assertFalse(shape.isInside(FreeCAD.Vector(x, y, z + 0.15), 1e-4, True), (x, y, z))
        inv, inv_warnings = relief.make_relief(proj.doc, png, width, height, base=base, invert=True, smoothing=0)
        self.assertEqual(inv_warnings, [])
        self.assertTrue(shape.isInside(FreeCAD.Vector(30, 22.5, 6.0), 1e-4, True))
        self.assertFalse(inv.Shape.isInside(FreeCAD.Vector(30, 22.5, 6.0), 1e-4, True))  # bosse inversée = creux
        self.assertAlmostEqual(inv.Shape.optimalBoundingBox().ZMax, base + height, delta=0.05)
        proj.doc.removeObject(inv.Name)

        job = proj.create_job([obj], stock={"kind": "box_margins", "xy": 2.0, "z_top": 0.0, "z_bottom": 0.0})
        clone = job.Model.Group[0]
        ball = lib.search("6 mm ball end mill")[0]
        op, rec = proj.add_operation("surface3d", "Relief finishing", lib.assemblies_for_tool(ball.id)[0].id,
                                     ball.presets[0].id, base=[(clone, [])],
                                     params={"CutPattern": "ZigZag", "StepOver": 40, "SampleInterval": 0.5,
                                             "BoundBox": "BaseBoundBox", "FinalDepth": base})
        self.assertEqual(rec["ignored_params"], [])
        endmill = lib.search("6 mm flat end mill")[0]
        rop, rrec = proj.add_operation("rough3d", "Relief roughing", lib.assemblies_for_tool(endmill.id)[0].id,
                                       endmill.presets[0].id, base=[(clone, [])],
                                       params={"StepDown": 1.0, "StepOver": 20, "StockToLeave": 0.5,
                                               "FinalDepth": base})
        self.assertEqual(rrec["ignored_params"], [])
        results = {r["name"]: r for r in proj.compute()}
        self.assertTrue(results["Relief finishing"]["valid"], results["Relief finishing"])
        cuts = cutting_points(op.Path)
        self.assertGreater(len(cuts), 100)
        # la pointe de la fraise boule ne descend jamais sous la surface connue
        for p in cuts:
            self.assertGreaterEqual(p["Z"], surface_z(p["X"], p["Y"]) - 0.05, p)
        self.assertGreater(max(p["Z"] for p in cuts), base + height - 0.5)  # le sommet est suivi
        rcuts = cutting_points(rop.Path)
        self.assertGreater(len(rcuts), 50)
        self.assertGreaterEqual(len(set(round(p["Z"], 2) for p in rcuts)), 4)
        tool_r = endmill.geometry.diameter / 2.0
        ring = [(tool_r * math.cos(a * math.pi / 8), tool_r * math.sin(a * math.pi / 8)) for a in range(16)] + [(0, 0)]
        for p in rcuts:  # fond plat de la fraise : jamais de matière au-dessus de Z sous le disque de coupe
            highest = max(surface_z(p["X"] + dx, p["Y"] + dy) for dx, dy in ring)
            self.assertLessEqual(highest, p["Z"] + 0.05, p)
        proj.close()

    def test_indexed_4th_axis(self):
        """3+1 : poche du dessus à A0, poche du flanc +Y à A90 sur un barreau centré sur l'axe A."""
        from cam2027.project.machine import RotaryAxis
        from cam2027.project import indexing

        step = os.path.join(self.tmp, "bar.step")
        bar = Part.makeBox(80, 30, 30, FreeCAD.Vector(0, -15, -15))
        bar = bar.cut(Part.makeBox(30, 10, 5, FreeCAD.Vector(25, -5, 10)))   # poche sur +Z, fond à Z 10
        bar = bar.cut(Part.makeBox(30, 5, 10, FreeCAD.Vector(25, 10, -5)))   # poche sur +Y, fond à Y 10
        bar.exportStep(step)
        lib = starter_library()
        proj = Project.create("4th test", lib, self._machine())
        part = proj.import_model(step, label="Bar").objects[0]
        proj.create_job([part], stock={"kind": "cylinder_x", "radius": 22.0, "length": 84.0, "x_start": -2.0,
                                       "center": (0.0, 0.0)})
        sb = proj.stock_bounds()
        self.assertAlmostEqual(sb["ymin"], -22.0, places=3)
        self.assertAlmostEqual(sb["zmax"], 22.0, places=3)
        self.assertAlmostEqual(sb["xmin"], -2.0, places=3)
        clone = proj.job.Model.Group[0]

        def floor(axis, value):
            for i, f in enumerate(clone.Shape.Faces, 1):
                bb = f.BoundBox
                lo, hi = {"y": (bb.YMin, bb.YMax), "z": (bb.ZMin, bb.ZMax)}[axis]
                if f.Surface.__class__.__name__ == "Plane" and abs(lo - value) < 1e-6 and abs(hi - value) < 1e-6 \
                        and abs(f.Area - 300.0) < 1e-3:
                    return "Face%d" % i
        top_floor, side_floor = floor("z", 10.0), floor("y", 10.0)
        self.assertIsNotNone(top_floor)
        self.assertIsNotNone(side_floor)
        small = [t for t in lib.search("3 mm flat end mill") if t.tool_type == "endmill"][0]
        asm = lib.assemblies_for_tool(small.id)[0]
        pre = small.presets[0]
        # sans axe A renseigné : refus explicite
        with self.assertRaises(ValueError):
            proj.add_operation("pocket", "x", asm.id, pre.id, base=[(clone, [side_floor])], index_deg=90)
        machine = self._machine()
        machine.rotary = RotaryAxis(present=True, about="X", center_offset_mm=(0.0, 0.0),
                                    positive_direction="right_hand", min_deg=-360.0, max_deg=360.0)
        proj.set_machine(machine)
        with self.assertRaises(ValueError):  # « toute la pièce » n'a pas de sens pour un index
            proj.add_operation("pocket", "x", asm.id, pre.id, base=[(clone, [])], index_deg=90)
        top, _r1 = proj.add_operation("pocket2d", "Top pocket", asm.id, pre.id, base=[(clone, [top_floor])],
                                      params={"StepDown": 2.0, "StartDepth": 15.0, "FinalDepth": 10.0}, index_deg=0)
        side, rec2 = proj.add_operation("pocket2d", "Side pocket", asm.id, pre.id, base=[(clone, [side_floor])],
                                        params={"StepDown": 2.0, "StartDepth": 15.0, "FinalDepth": 10.0}, index_deg=90)
        self.assertEqual(rec2["index_deg"], 90.0)
        self.assertEqual(side.Base[0][0].Name, part.Name + "_A90")
        self.assertNotIn(side.Base[0][0], proj.job.Model.Group)  # la copie tournée reste hors du modèle
        names = [o.Label for o in proj.operations()]
        self.assertEqual(names, ["Index A0", "Top pocket", "Index A90", "Side pocket"])
        results = {r["name"]: r for r in proj.compute()}
        for label in ("Top pocket", "Side pocket"):
            r = results[label]
            self.assertTrue(r["valid"] and r["commands"] > 10, r)
            o = proj.doc.getObjectsByLabel(label)[0]
            self.assertAlmostEqual(r["zmin"], 10.0, places=3,
                                   msg="%s start %s final %s step %s" % (label, o.StartDepth, o.FinalDepth, o.StepDown))
            # après rotation de +90° autour de X, la poche du flanc +Y occupe X 25..55, Y -5..5
            self.assertGreaterEqual(r["bbox"]["X"][0], 25.0 - 1e-3)
            self.assertLessEqual(r["bbox"]["X"][1], 55.0 + 1e-3)
            self.assertGreaterEqual(r["bbox"]["Y"][0], -5.0 - 1e-3)
            self.assertLessEqual(r["bbox"]["Y"][1], 5.0 + 1e-3)
        text, analysis, issues = proj.preview_gcode()
        lines = [l.strip() for l in text.splitlines()]
        a_moves = [l for l in lines if l.startswith("G0") and " A" in l]
        self.assertEqual([l.split("A")[-1] for l in a_moves], ["0.000", "90.000"])
        self.assertLess(lines.index(a_moves[1]), lines.index("(Begin operation: Side pocket)"))
        self.assertEqual(analysis["a_feed_lines"], 0)
        self.assertEqual(analysis["bbox"]["A"], (0.0, 90.0))
        levels = [lvl for lvl, _m in issues]
        self.assertNotIn("error", levels, issues)
        self.assertTrue(any("GRBL 1.1 has no A axis" in m for _l, m in issues))
        # même géométrie que la pièce : réordonner recrée les positionnements
        proj.move_operation(side, -1)
        self.assertEqual([o.Label for o in proj.operations()], ["Index A90", "Side pocket", "Index A0", "Top pocket"])
        # réindexer : la géométrie suit (copie A90 -> pièce réelle à A0), les positionnements sont recréés
        proj.set_operation_index(side, 0)
        self.assertIs(side.Base[0][0], clone)  # A0 : clone de la pièce réelle dans le job
        self.assertEqual(proj.registry[side.Name]["index_deg"], 0.0)
        self.assertEqual([o.Label for o in proj.operations()], ["Index A0", "Side pocket", "Top pocket"])
        proj.set_operation_index(side, 90)
        self.assertEqual(side.Base[0][0].Name, part.Name + "_A90")
        self.assertEqual([o.Label for o in proj.operations()], ["Index A90", "Side pocket", "Index A0", "Top pocket"])
        # positionnement manquant -> erreur de cohérence
        proj.job.Operations.Group = [o for o in proj.job.Operations.Group if o.Label != "Index A90"]
        self.assertTrue(any("expects A90" in m for _l, m in indexing.order_issues(proj)))
        indexing.sync(proj)
        self.assertEqual(indexing.order_issues(proj), [])
        # plage A dépassée
        machine.rotary.max_deg = 45.0
        proj.set_machine(machine)
        with self.assertRaises(ValueError):
            proj.add_operation("pocket", "x", asm.id, pre.id, base=[(clone, [side_floor])], index_deg=90)
        _t, _a, issues2 = proj.preview_gcode()
        self.assertTrue(any(l == "error" and "outside the A range" in m for l, m in issues2), issues2)
        # A pendant une coupe = 4 axes simultanés : refusé
        a2 = exportmod.analyze_gcode("G21 G54\nG0 X0 Y0 Z5 A0\nG1 X10 A15 F500\n")
        self.assertEqual(a2["a_feed_lines"], 1)
        self.assertTrue(any("simultaneous" in m for _l, m in exportmod.verify(a2, machine)))
        proj.close()

    def test_strategy_translations(self):
        """Libellés et limites de chaque stratégie traduits ; aucune chaîne tr() manquante."""
        import json
        from cam2027 import i18n
        from cam2027.project.operations import STRATEGIES

        self.assertEqual(i18n.missing_translations("fr"), [])
        with open(os.path.join(os.path.dirname(i18n.__file__), "i18n", "fr.json"), "r", encoding="utf-8") as fp:
            catalog = json.load(fp)
        for kind, meta in STRATEGIES.items():
            self.assertIn(meta["label"], catalog, kind)
            if meta["limits"]:
                self.assertIn(meta["limits"], catalog, kind)

    def test_toolbit_shapes(self):
        """Chaque type d'outil produit un ToolBit FreeCAD (avec avertissement si approximé)."""
        lib = starter_library()
        doc = FreeCAD.newDocument("Bits")
        try:
            for tool in lib.tools.values():
                obj, warnings = bridge.create_toolbit(doc, tool)
                self.assertAlmostEqual(float(obj.Diameter.getValueAs("mm")), tool.geometry.diameter, places=3)
                if tool.tool_type == "vbit":
                    self.assertAlmostEqual(float(obj.CuttingEdgeAngle.getValueAs("deg")),
                                           tool.geometry.tip_included_angle_deg, places=3)
                if tool.tool_type == "drill":
                    self.assertAlmostEqual(float(obj.TipAngle.getValueAs("deg")), 118.0, places=3)
            from cam2027.tools.model import ToolDefinition
            tb = ToolDefinition("tb", "taperedball", dict(diameter=6, overall_length=50, flute_length=20,
                                                          taper_half_angle_deg=3, corner_radius=0.5))
            obj, warnings = bridge.create_toolbit(doc, tb)
            if compat.tool_api() == "legacy":
                self.assertTrue(any("ball end" in w for w in warnings))
        finally:
            FreeCAD.closeDocument(doc.Name)


if __name__ == "__main__":
    unittest.main()
