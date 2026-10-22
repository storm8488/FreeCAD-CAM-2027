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
