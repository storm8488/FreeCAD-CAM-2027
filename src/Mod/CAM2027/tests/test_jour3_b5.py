# SPDX-License-Identifier: LGPL-2.1-or-later
"""Jour 3, flux B5 : entrées / sorties (import, export G-code GRBL 1.1, fiche) et outils."""

import os
import tempfile
import unittest

import FreeCAD

from cam2027.tools.library import starter_library
from cam2027.project.project import Project
from cam2027.project.machine import MachineProfile
from cam2027.project import export as exportmod
from tests.test_pipeline import make_part, hole_face


def machine(**kw):
    return MachineProfile("test", controller="grbl", post_processor="grbl",
                          post_processor_args="--no-show-editor --precision=3", **kw)


def code_lines(text):
    """Lignes de G-code sans commentaires ni lignes vides."""
    out = []
    for raw in text.splitlines():
        line = raw.split(";")[0]
        while "(" in line and ")" in line:
            line = line[:line.index("(")] + line[line.index(")") + 1:]
        line = line.strip()
        if line:
            out.append(line)
    return out


class _PlateCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="cam2027-b5-")
        cls.step = os.path.join(cls.tmp, "plate.step")
        make_part(cls.step)
        FreeCAD.ConfigSet("SuppressRecomputeRequiredDialog", "True")

    def project(self, name, **mkw):
        lib = starter_library()
        proj = Project.create(name, lib, machine(**mkw))
        part = proj.import_model(self.step, label="Plate").objects[0]
        job = proj.create_job([part], stock={"kind": "box_margins", "xy": 2.0, "z_top": 1.0, "z_bottom": 0.0})
        self.addCleanup(proj.close)
        return proj, lib, job.Model.Group[0]

    def tool(self, lib, name):
        t = [t for t in lib.search(name) if t.tool_type == "endmill"][0]
        return lib.assemblies_for_tool(t.id)[0].id, t.presets[0].id


class TestToolChangeStops(_PlateCase):
    def test_commented_m6_becomes_a_stop(self):
        """GRBL 1.1 n'a pas de M6 : le postprocesseur ``grbl`` le met en commentaire, le programme enchaînait
        donc l'opération suivante avec l'outil précédent (bug B5-1). Changement d'outil réel = broche arrêtée
        puis pause M0 ; même outil = pas de pause ; premier outil = pas de pause (chargé selon la fiche)."""
        text = "\n".join(["G21", "G54", "(Begin toolchange)", "( M6 T2 )", "M3 S18000", "G1 X1 F100",
                          "(Begin toolchange)", "( M6 T2 )", "M3 S18000", "G1 X2",
                          "(Begin toolchange)", "( M6 T1 )", "M3 S16000", "G1 X3", "M5", "M2"])
        out, stops = exportmod.tool_change_stops(text)
        self.assertEqual(stops, 1)
        lines = code_lines(out)
        self.assertEqual(lines, ["G21", "G54", "M3 S18000", "G1 X1 F100", "M3 S18000", "G1 X2",
                                 "M5", "M0", "M3 S16000", "G1 X3", "M5", "M2"])
        self.assertIn("T1", out[out.index("M5\n"):out.index("M0")])  # l'opérateur sait quel outil monter
        self.assertEqual(exportmod.analyze_gcode(out)["pauses"], 1)

    def test_two_tools_pause_between_operations(self):
        """Programme réel : hélice à la fraise 3 mm puis contour à la 6 mm (postprocesseur grbl de FreeCAD)."""
        proj, lib, clone = self.project("Two tools")
        a3, p3 = self.tool(lib, "3 mm flat end mill")
        a6, p6 = self.tool(lib, "6 mm flat end mill")
        proj.add_operation("helix", "Helix bore", a3, p3, base=[(clone, [hole_face(clone)])],
                           params={"StartDepth": 10.0, "FinalDepth": 0.0, "StepDown": 2.0, "StepOver": 50})
        proj.add_operation("profile", "Contour A", a6, p6, base=[(clone, [])],
                           params={"StepDown": 5.0, "FinalDepth": 5.0, "Side": "Outside"})
        proj.add_operation("profile", "Contour B", a6, p6, base=[(clone, [])],
                           params={"StepDown": 5.0, "FinalDepth": 0.0, "Side": "Outside"})
        proj.compute()
        text, analysis, _issues = proj.preview_gcode()
        lines = code_lines(text)
        self.assertEqual(lines.count("M0"), 1, text)
        i = lines.index("M0")
        self.assertEqual(lines[i - 1], "M5")
        self.assertTrue(lines[i + 1].startswith("M3"), lines[i + 1])
        raw = text.splitlines()
        stop = next(n for n, l in enumerate(raw) if l.strip() == "M0")
        self.assertGreater(stop, next(n for n, l in enumerate(raw) if l.startswith("(Finish operation: Helix bore")))
        self.assertLess(stop, next(n for n, l in enumerate(raw) if l.startswith("(Begin operation: Contour A")))
        self.assertEqual(analysis["pauses"], 1)
        self.assertNotIn("M6", analysis["codes"])  # GRBL 1.1 : M6 refusé (error:20)


class TestToolNumbers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="cam2027-b5-")
        cls.step = os.path.join(cls.tmp, "plate.step")
        make_part(cls.step)

    def test_same_number_for_two_tools_blocks_export(self):
        """Deux outils différents sous le même T (bibliothèque de démarrage T1..T8 + import Fusion T1..T11) : le
        programme ne s'arrêtait pas entre eux (bug B5-3). Refus à l'export, avec les noms des outils."""
        lib = starter_library()
        small = [t for t in lib.search("3 mm flat end mill") if t.tool_type == "endmill"][0]
        big = lib.search("6 mm flat end mill")[0]
        lib.assemblies_for_tool(small.id)[0].output.tool_number = lib.assemblies_for_tool(big.id)[0].output.tool_number
        proj = Project.create("Same T", lib, machine())
        self.addCleanup(proj.close)
        part = proj.import_model(self.step, label="Plate").objects[0]
        clone = proj.create_job([part], stock={"kind": "box_margins", "xy": 2.0, "z_top": 1.0}).Model.Group[0]
        plib = proj.library
        for tool, label, side in ((small, "Small", "Inside"), (big, "Big", "Outside")):
            asm = plib.assemblies_for_tool(tool.id)[0]
            proj.add_operation("profile", label, asm.id, plib.tool(tool.id).presets[0].id, base=[(clone, [])],
                               params={"FinalDepth": 5.0, "StepDown": 5.0, "Side": side})
        proj.compute()
        text, _analysis, issues = proj.preview_gcode()
        self.assertEqual(code_lines(text).count("M0"), 0)  # rien dans le G-code ne permet de les distinguer
        errors = [str(m) for lvl, m in issues if lvl == "error"]
        self.assertTrue(any("T1 is used by several tools" in e and small.name in e and big.name in e for e in errors),
                        errors)
        # même outil dans deux opérations : pas de conflit
        self.assertEqual(exportmod.tool_number_issues(proj)[0][0], "error")
        proj.remove_operation(proj.operations()[0])
        self.assertEqual(exportmod.tool_number_issues(proj), [])


FUSION = os.path.join(os.path.dirname(__file__), "fixtures", "fusion-library-lunyee.tools")


class TestFusionImport(unittest.TestCase):
    def test_reimport_adds_no_duplicate(self):
        """Importer deux fois le même export Fusion doublait les 11 outils et leurs numéros (bug B5-4)."""
        from cam2027.tools.library import ToolLibrary
        from cam2027.tools.fusion_import import import_fusion_library

        lib = ToolLibrary("real")
        import_fusion_library(FUSION, lib)
        report = import_fusion_library(FUSION, lib)
        self.assertEqual(report.imported, [])
        self.assertEqual(len(report.skipped), 11)
        self.assertTrue(all("already in the library" in why for _n, why in report.skipped), report.skipped)
        self.assertEqual(lib.summary()["tools"], 11)
        self.assertEqual(lib.summary()["assemblies"], 11)

    def test_numbers_already_used_are_renumbered(self):
        """Import dans la bibliothèque de démarrage (T1..T8) : les numéros Fusion déjà pris recevaient le même T
        qu'un autre outil (bug B5-4) ; ils sont renumérotés après le plus grand et le rapport le dit."""
        from cam2027.tools.fusion_import import import_fusion_library

        lib = starter_library()
        report = import_fusion_library(FUSION, lib)
        self.assertEqual(len(report.imported), 11)
        numbers = [a.output.tool_number for a in lib.assemblies.values()]
        self.assertEqual(len(numbers), len(set(numbers)), sorted(numbers))
        self.assertEqual(sorted(numbers), list(range(1, 20)))
        renumbered = [w for w in report.warnings if "already used" in w]
        self.assertEqual(len(renumbered), 8, report.warnings)
        self.assertTrue(any("T1 already used" in w and "T12" in w for w in renumbered), renumbered)
        for a in lib.assemblies.values():
            self.assertTrue(a.name.startswith("T%d " % a.output.tool_number), a.name)

    def test_corrupted_files_give_a_clear_error(self):
        """Fichier abîmé : ValueError lisible (affichée par la bibliothèque), jamais une autre exception qui
        laisse la commande sans message (bug B5-5) ; un outil illisible est ignoré et listé, les autres importés."""
        import json
        import zipfile
        from cam2027.tools.library import ToolLibrary
        from cam2027.tools.fusion_import import import_fusion_library

        tmp = tempfile.mkdtemp(prefix="cam2027-b5-")
        good = zipfile.ZipFile(FUSION).read("tools.json") if "tools.json" in zipfile.ZipFile(FUSION).namelist() \
            else zipfile.ZipFile(FUSION).read(zipfile.ZipFile(FUSION).namelist()[0])
        cases = {}
        # archive tronquée (téléchargement interrompu)
        raw = open(FUSION, "rb").read()
        cases["truncated.tools"] = raw[: len(raw) // 2]
        # archive dont le contenu est abîmé (CRC faux)
        broken = bytearray(raw)
        start = raw.index(b"PK\x03\x04") + 30 + len(zipfile.ZipFile(FUSION).namelist()[0].encode())
        for i in range(start + 20, start + 60):
            broken[i] ^= 0x55
        cases["crc.tools"] = bytes(broken)
        cases["garbage.json"] = bytes(range(256)) * 4
        cases["empty.json"] = b""
        cases["list.json"] = b"[1, 2, 3]"
        cases["notjson.json"] = b"{\"data\": [ {\"type\": "
        for name, data in cases.items():
            path = os.path.join(tmp, name)
            with open(path, "wb") as fp:
                fp.write(data)
            lib = ToolLibrary("x")
            try:
                report = import_fusion_library(path, lib)
            except ValueError as exc:
                self.assertTrue(str(exc), name)
                continue
            except Exception as exc:  # noqa: BLE001
                self.fail("%s: %s %s" % (name, type(exc).__name__, exc))
            self.assertEqual(report.imported, [], name)
        # outils mal formés au milieu d'outils valides
        data = json.loads(good.decode("utf-8"))
        data["data"] = [None, "text", {"type": "flat end mill", "geometry": [1, 2]},
                        {"type": "flat end mill", "description": "bad preset", "geometry": data["data"][3]["geometry"],
                         "start-values": {"presets": [None]}}] + data["data"][:2]
        path = os.path.join(tmp, "mixed.json")
        with open(path, "w", encoding="utf-8") as fp:
            json.dump(data, fp)
        lib = ToolLibrary("x")
        report = import_fusion_library(path, lib)
        self.assertEqual(len(report.imported), 3, report.to_text())
        self.assertEqual(len(report.skipped), 3, report.to_text())

    def test_report_message_is_true(self):
        """La fenêtre de rapport disait l'importateur « pas encore validé sur un export réel » alors qu'il l'est
        (fixture réelle ci-dessus, LIMITS.md) ; elle donne maintenant les nombres importés et ignorés."""
        src = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cam2027", "gui", "panels.py")
        with open(src, encoding="utf-8") as fp:
            text = fp.read()
        self.assertNotIn("not yet validated on a real Fusion export", text)
        self.assertIn("skipped {s}", text)


class TestModelImport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cam2027-b5-")
        self.proj = Project.create("Import", starter_library())
        self.addCleanup(self.proj.close)

    def write(self, name, data):
        path = os.path.join(self.tmp, name)
        with open(path, "wb") as fp:
            fp.write(data)
        return path

    def test_empty_mesh_clear_message(self):
        """STL / OBJ vide : « No shells or compsolids found in shape » (exception OCC) au lieu d'un message
        (bug B5-6) ; un maillage vide est « fermé » pour Mesh, sa conversion en solide échouait."""
        from cam2027.project import importers

        for name in ("empty.stl", "empty.obj"):
            res = self.proj.import_model(self.write(name, b""))
            self.assertEqual(res.objects, [], name)
            self.assertTrue(any("no triangle" in str(w) for w in res.warnings), res.warnings)
        self.assertEqual([o for o in self.proj.doc.Objects if o.TypeId.startswith("Mesh::")], [])
        self.assertEqual(importers.meshes_to_solids(self.proj.doc, [])[0], [])

    def test_3mf_imported(self):
        """3MF (format des trancheuses) : lu par le module Mesh de FreeCAD 1.0 et 1.1, refusé « unsupported
        format » par CAM2027 (bug B5-7) ; boîte fermée -> solide comme un STL."""
        import Mesh
        from cam2027.project import importers

        path = os.path.join(self.tmp, "box.3mf")
        Mesh.createBox(10, 20, 30).write(path)
        res = self.proj.import_model(path)
        self.assertEqual(res.kind, "solid")
        self.assertEqual(len(res.objects), 1)
        bb = res.objects[0].Shape.BoundBox
        self.assertAlmostEqual(res.objects[0].Shape.Volume, 6000.0, places=3)
        self.assertAlmostEqual(bb.ZLength, 30.0, places=6)
        self.assertIn(".3mf", importers.SUPPORTED_EXTENSIONS)


class TestSheet(unittest.TestCase):
    def test_drawing_off_z0_is_moved_onto_the_sheet(self):
        """Dessin plan hors de Z 0 (DXF avec élévation, esquisse décalée) : posé sur le dessus du panneau (Z 0),
        contour jamais sous le fond demandé. Soupçon d'audit (``o.Placement.move`` sur une copie) non confirmé :
        garde-fou."""
        import Part

        V = FreeCAD.Vector
        for z in (5.0, -3.0):
            proj = Project.create("Sheet Z", starter_library())
            self.addCleanup(proj.close)
            square = proj.doc.addObject("Part::Feature", "Square")
            square.Shape = Part.makePolygon([V(0, 0, z), V(40, 0, z), V(40, 30, z), V(0, 30, z), V(0, 0, z)])
            proj.doc.recompute()
            proj.create_sheet_job(thickness=12.0)
            self.assertAlmostEqual(square.Shape.BoundBox.ZMin, 0.0, places=6, msg=z)
            face = proj.doc.getObject("Square_Face")
            self.assertAlmostEqual(face.Shape.BoundBox.ZMax, 0.0, places=6, msg=z)
            sb = proj.stock_bounds()
            self.assertAlmostEqual(sb["zmax"], 0.0, places=6)
            lib = proj.library
            t = [t for t in lib.search("3 mm flat end mill") if t.tool_type == "endmill"][0]
            asm = lib.assemblies_for_tool(t.id)[0]
            proj.add_operation("profile", "Cut", asm.id, t.presets[0].id, base=[(square, [])],
                               params={"FinalDepth": -12.0, "StepDown": 4.0, "Side": "Outside"})
            r = proj.compute()[0]
            self.assertTrue(r["valid"], r)
            self.assertGreaterEqual(r["zmin"], -12.0 - 1e-6, (z, r["zmin"]))


class TestGrblRules(unittest.TestCase):
    def test_arc_radius_mismatch_refused(self):
        """GRBL 1.1 (``gc_execute_line``) refuse un arc I/J/K dont le rayon de fin diffère de celui du début de
        plus de 0,005 mm et 0,1 % (ou 0,5 mm) : error:33, programme arrêté en pleine coupe. Non contrôlé (B5-9)."""
        ok = "\n".join(["G21", "G17 G90", "G54", "G0 X10 Y0 Z1", "G1 Z-1 F100", "G2 X0 Y10 I-10 J0 F500",
                        "G3 X10 Y0 I0 J-10", "G2 X10.001 Y0.002 I-10 J0", "G0 Z5", "M5", "M2"])
        a = exportmod.analyze_gcode(ok)
        self.assertEqual(a["bad_arcs"], 0, a)
        self.assertFalse(any("arc" in str(m) for _l, m in exportmod.verify(a, machine())))
        bad = ok.replace("G2 X0 Y10 I-10 J0 F500", "G2 X0 Y10.02 I-10 J0 F500")  # fin à 10,02 du centre
        a = exportmod.analyze_gcode(bad)
        self.assertEqual(a["bad_arcs"], 1, a)
        self.assertAlmostEqual(a["max_arc_error"], 0.02, places=6)
        errors = [str(m) for lvl, m in exportmod.verify(a, machine()) if lvl == "error"]
        self.assertTrue(any("arc" in e and "error:33" in e for e in errors), errors)
        # plan G18 (X/Z, I/K) : le même arc juste n'est pas compté faux
        xz = "\n".join(["G21", "G90", "G54", "G18", "G0 X10 Y0 Z0", "G2 X0 Z10 I-10 K0 F500", "G17", "M2"])
        self.assertEqual(exportmod.analyze_gcode(xz)["bad_arcs"], 0)
        # arc sans centre ni rayon : refusé par GRBL (error:26 / 33)
        self.assertEqual(exportmod.analyze_gcode("G21\nG90\nG0 X0 Y0\nG2 X10 Y0 F100\n")["bad_arcs"], 1)
        # arc en rayon R impossible (corde plus longue que le diamètre)
        self.assertEqual(exportmod.analyze_gcode("G21\nG90\nG0 X0 Y0\nG2 X30 Y0 R10 F100\n")["bad_arcs"], 1)
        self.assertEqual(exportmod.analyze_gcode("G21\nG90\nG0 X0 Y0\nG2 X20 Y0 R10.001 F100\n")["bad_arcs"], 0)


class TestGrblProgramState(unittest.TestCase):
    def msgs(self, text, level=None, **mkw):
        return [str(m) for lvl, m in exportmod.verify(exportmod.analyze_gcode(text), machine(**mkw))
                if level is None or lvl == level]

    def test_undefined_feed(self):
        """GRBL 1.1 refuse G1/G2/G3 sans avance définie (error:22), y compris juste après G93 -> G94 sans F
        (l'avance n'est pas reprise de G93). Non contrôlé (B5-10)."""
        head = "G21\nG90\nG54\n"
        self.assertEqual(exportmod.analyze_gcode(head + "G0 X0\nG1 X10\n")["undefined_feed"], 1)
        self.assertEqual(exportmod.analyze_gcode(head + "G0 X0\nG1 X10 F500\nG1 X20\nG2 X30 I5 J0\n")["undefined_feed"], 0)
        a = exportmod.analyze_gcode(head + "G1 X1 F300\nG93\nG1 X2 A5 F10\nG94\nG1 X3\nG1 X4 F300\nG1 X5\n")
        self.assertEqual(a["undefined_feed"], 1)
        self.assertEqual(exportmod.analyze_gcode(head + "G93\nG1 X2 A5 F10\nG94 G1 X3 F300\n")["undefined_feed"], 0)
        errors = self.msgs(head + "G0 X0\nG1 X10\nM2\n", "error")
        self.assertTrue(any("without a feed rate" in e and "error:22" in e for e in errors), errors)

    def test_program_end(self):
        """Fin de programme : broche encore en marche après la dernière ligne, M2 / M30 absent (B5-11)."""
        good = "G21\nG90\nG54\nM3 S12000\nG1 X1 F100\nM5\nM2\n"
        self.assertFalse(any("spindle" in m and "end" in m or "M2" in m for m in self.msgs(good)), self.msgs(good))
        open_end = "G21\nG90\nG54\nM3 S12000\nG1 X1 F100\n"
        msgs = self.msgs(open_end, "warning")
        self.assertTrue(any("still running at the end" in m for m in msgs), msgs)
        self.assertTrue(any("no program end (M2 / M30)" in m for m in msgs), msgs)
        # M30 arrête aussi la broche (GRBL : fin de programme)
        self.assertFalse(any("still running" in m for m in self.msgs("G21\nG54\nM3 S1000\nG1 X1 F100\nM30\n")))

    def test_mist_and_parking_codes(self):
        """M7 (brouillard) et M56 (forçage du parking) n'existent dans GRBL 1.1 qu'avec ENABLE_M7 /
        ENABLE_PARKING_OVERRIDE_CONTROL (désactivés par défaut) : error:20 sur la machine, alors que le contrôle
        les acceptait (B5-12). M7 accepté si le profil déclare l'arrosage brouillard."""
        text = "G21\nG90\nG54\nM3 S12000\nM7\nG1 X1 F100\nM9\nM5\nM2\n"
        self.assertTrue(any("M7" in m for m in self.msgs(text, "error")), self.msgs(text, "error"))
        self.assertFalse(any("M7" in m for m in self.msgs(text, "error", coolant_options=["none", "mist"])))
        self.assertTrue(any("M56" in m for m in self.msgs(text.replace("M7", "M56"), "error")))
        self.assertFalse(any("M8" in m for m in self.msgs(text.replace("M7", "M8"), "error")))


class TestSetupSheet(_PlateCase):
    def test_sheet_lists_what_the_gcode_contains(self):
        """Fiche de préparation : une opération désactivée (absente du G-code) et son outil étaient listés comme à
        préparer, une opération supprimée de l'arbre FreeCAD aussi (registre resté) ; ordre = ordre du registre,
        pas celui du programme (B5-13). Le contrôle des numéros T voit aussi les opérations habillées."""
        proj, lib, clone = self.project("Sheet")
        a3, p3 = self.tool(lib, "3 mm flat end mill")
        a6, p6 = self.tool(lib, "6 mm flat end mill")
        op1, _ = proj.add_operation("profile", "Small contour", a3, p3, base=[(clone, [])],
                                    params={"FinalDepth": 5.0, "StepDown": 5.0, "Side": "Outside"})
        op2, _ = proj.add_operation("profile", "Big contour", a6, p6, base=[(clone, [])],
                                    params={"FinalDepth": 0.0, "StepDown": 5.0, "Side": "Outside"})
        op3, _ = proj.add_operation("profile", "Gone", a6, p6, base=[(clone, [])],
                                    params={"FinalDepth": 0.0, "StepDown": 5.0, "Side": "Outside"})
        proj.compute()
        op2.Active = False
        proj.job.Operations.Group = [o for o in proj.job.Operations.Group if o.Name != op3.Name]
        proj.doc.removeObject(op3.Name)  # suppression dans l'arbre FreeCAD : le registre garde l'entrée
        proj.doc.recompute()
        text, analysis, issues = proj.preview_gcode()
        sheet = exportmod.prep_sheet(proj, [("all", text)], analysis, issues, ["x.nc"])
        tools = sheet.split("## Tools")[1].split("## Operations")[0]
        ops = sheet.split("## Operations")[1].split("##")[0]
        self.assertIn("3 mm flat end mill", tools)
        self.assertNotIn("6 mm flat end mill", tools, sheet)
        self.assertIn("Small contour", ops)
        self.assertNotIn("| Big contour", ops)
        self.assertNotIn("Gone", ops)
        self.assertIn("Big contour", sheet.split("## Operations")[1])  # signalée comme non exportée
        # habillage : l'opération reste comptée par le contrôle des numéros T
        for asm in proj.library.assemblies.values():
            asm.output.tool_number = 1
        op2.Active = True
        proj.add_dressup(op1, "tags", count=2)
        top = [o for o in proj.operations() if dressupmod_base(o).Name == op1.Name][0]
        self.assertNotEqual(top.Name, op1.Name)
        self.assertTrue(exportmod.tool_number_issues(proj), "dressed operation ignored")


def dressupmod_base(obj):
    from cam2027.project import dressups

    return dressups.base_operation(obj)


PROBE = {"present": True, "tip_diameter_mm": 2.0, "plate_thickness_mm": 0.0, "feed_mm_min": 100.0, "travel_mm": 25.0}


class TestEnvelope(_PlateCase):
    def test_envelope_ignores_relative_moves_and_offsets(self):
        """Enveloppe XYZ : les mouvements relatifs (G91, palpage) et les mots d'axe de G10 / G92 / G28 / G53 ne
        sont pas des positions de travail (bug B5-2 : Z -25 du palpage relatif compté comme position)."""
        text = "\n".join(["G21", "G90", "G54", "G91", "G38.2 Z-25 F100", "G10 L20 P1 Z0", "G0 Z2", "G0 X-16",
                          "G90", "G92 X40", "G28 G91 Z0", "G90", "G53 G0 Z-90", "G0 X0 Y0 Z5",
                          "G1 X10 Y20 Z-1 F500", "G0 Z5", "M5", "M2"])
        a = exportmod.analyze_gcode(text)
        self.assertEqual(a["bbox"]["X"], (0.0, 10.0))
        self.assertEqual(a["bbox"]["Y"], (0.0, 20.0))
        self.assertEqual(a["bbox"]["Z"], (-1.0, 5.0))

    def test_probe_program_not_refused_on_z_travel(self):
        """Palpage du coin + contour, course Z 30 mm : le programme réel (Z 0..16) n'est pas refusé et Z n'est
        pas « sous le brut »."""
        proj, lib, clone = self.project("Probe travel", probe=dict(PROBE), travel_z_mm=30.0)
        from cam2027.project import probe

        a6, p6 = self.tool(lib, "6 mm flat end mill")
        proj.add_operation("profile", "Contour", a6, p6, base=[(clone, [])],
                           params={"FinalDepth": 0.0, "StepDown": 5.0})
        probe.add_probe(proj, "corner")
        proj.compute()
        text, analysis, issues = proj.preview_gcode()
        self.assertEqual(analysis["bbox"]["Z"], (0.0, 16.0))
        self.assertEqual([i for i in issues if i[0] == "error"], [], issues)
        self.assertFalse(any("below the stock" in str(m) for _l, m in issues), issues)
        # palpeur (T99) puis fraise : pause pour retirer le palpeur
        self.assertEqual(code_lines(text).count("M0"), 1)


if __name__ == "__main__":
    unittest.main()
