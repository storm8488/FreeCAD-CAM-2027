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


if __name__ == "__main__":
    unittest.main()
