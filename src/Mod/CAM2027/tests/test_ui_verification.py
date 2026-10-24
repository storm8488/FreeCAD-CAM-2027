# SPDX-License-Identifier: LGPL-2.1-or-later
"""Charte « Atelier » : panneau de vérification (portée de chaque contrôle, statut d'ensemble) et avances et
vitesses par opération (valeur du préréglage ou surcharge, source affichée, retour au préréglage)."""

import unittest

import FreeCAD
import Part

from cam2027.project.project import Project
from cam2027.tools.library import starter_library
from cam2027.tools import bridge
from cam2027.gui.commands import default_params
from cam2027.gui.verification import verification_rows, overall_status

V = FreeCAD.Vector


def report(**kw):
    rep = {"resolution": 0.5, "tolerance": 0.02, "simulated": ["Op"], "gouge_max": 0.0, "gouge_cells": 0, "gouge_at": None,
           "part_cells": 100, "leftover_max": 1.0, "leftover_mean": 0.3, "leftover_at": (1.0, 2.0, 0.0),
           "removed_volume": 1234.0, "rapid_hits": 0, "skipped": [], "approximations": [], "dogbone_overcut": {},
           "collisions": {"events": [], "flute_length": "ok", "holder": "ok", "clamps": "ok", "rapids": "ok",
                          "no_holder": [], "clamps_defined": ["Clamp"], "not_run": []}}
    rep.update(kw)
    return rep


class TestVerificationRows(unittest.TestCase):
    def _by_check(self, rows):
        return {c: (s, r, p) for c, s, r, p in rows}

    def test_all_checked_ok(self):
        rows = verification_rows(report())
        by = self._by_check(rows)
        self.assertEqual(by["Gouges on the part"][0], "ok")
        self.assertEqual(by["Tool holder"][0], "ok")
        self.assertEqual(by["Clamps"][0], "ok")
        self.assertEqual(by["Machine limits"][0], "not_checked")  # toujours dit : contrôlées à l'export
        self.assertEqual(overall_status(rows)[0], "ok")

    def test_gouge_is_a_problem(self):
        rows = verification_rows(report(gouge_max=0.5, gouge_cells=12, gouge_at=(10.0, 20.0, 0.0)))
        by = self._by_check(rows)
        self.assertEqual(by["Gouges on the part"][0], "danger")
        self.assertIn("0.50", by["Gouges on the part"][1])
        self.assertEqual(overall_status(rows)[0], "danger")

    def test_missing_holder_and_clamps_make_it_incomplete(self):
        rep = report()
        rep["collisions"].update({"holder": "not_checked", "no_holder": ["Pocket"], "clamps": "not_checked", "clamps_defined": []})
        rows = verification_rows(rep)
        by = self._by_check(rows)
        self.assertEqual(by["Tool holder"][0], "warning")
        self.assertIn("Pocket", by["Tool holder"][1])
        self.assertEqual(by["Clamps"][0], "not_checked")
        self.assertEqual(overall_status(rows)[0], "warning")  # jamais « réussi » quand un contrôle manque

    def test_nothing_simulated(self):
        rows = verification_rows(report(simulated=[], skipped=[("Wrap", "uses the A axis")]))
        by = self._by_check(rows)
        self.assertEqual(by["Gouges on the part"][0], "not_checked")
        self.assertEqual(by["Operation not simulated"][0], "warning")
        self.assertEqual(overall_status(rows)[0], "warning")


class TestFeedOverrides(unittest.TestCase):
    def setUp(self):
        self.lib = starter_library()
        self.proj = Project.create("Feeds", self.lib)
        obj = self.proj.doc.addObject("Part::Feature", "Part")
        obj.Shape = Part.makeBox(40, 30, 10)
        self.proj.doc.recompute()
        self.proj.create_job([obj], stock={"kind": "box_margins", "xy": 2.0, "z_top": 1.0, "z_bottom": 0.0})
        self.tool = [t for t in self.lib.search("6 mm flat end mill") if t.tool_type == "endmill"][0]
        self.asm = self.lib.assemblies_for_tool(self.tool.id)[0]
        self.preset = self.tool.presets[0]
        params = default_params("stockrough", self.tool, self.preset.resolve(self.tool))
        self.op, self.rec = self.proj.add_operation("stockrough", "Rough", self.asm.id, self.preset.id, params=params)

    def tearDown(self):
        for name in list(FreeCAD.listDocuments()):
            FreeCAD.closeDocument(name)

    def _tc(self):
        return bridge.tool_controller_values(self.proj.doc.getObject(self.rec["tool_controller"]))

    def test_override_then_back_to_preset(self):
        preset_feed = self.rec["values"]["feed_mm_min"]
        rec = self.proj.set_operation_feeds(self.op, {"feed_mm_min": 900.0, "spindle_rpm": 12000.0})
        self.assertEqual(rec["overrides"], {"feed_mm_min": 900.0, "spindle_rpm": 12000.0})
        self.assertEqual(rec["values"]["feed_mm_min"], preset_feed)  # le préréglage reste la source
        eff = self.proj.effective_values(rec)
        self.assertEqual((eff["feed_mm_min"], eff["spindle_rpm"]), (900.0, 12000.0))
        tc = self._tc()
        self.assertAlmostEqual(tc["feed_mm_min"], 900.0)
        self.assertAlmostEqual(tc["spindle_rpm"], 12000.0)
        # réouverture : le registre garde la surcharge
        self.assertEqual(self.proj.registry[self.op.Name]["overrides"]["feed_mm_min"], 900.0)
        # retour exact à la valeur du préréglage = plus de surcharge
        rec = self.proj.set_operation_feeds(self.op, {"feed_mm_min": preset_feed, "spindle_rpm": None})
        self.assertNotIn("overrides", rec)
        self.assertAlmostEqual(self._tc()["feed_mm_min"], preset_feed)

    def test_invalid_override_refused(self):
        from cam2027.i18n import UserError

        with self.assertRaises(UserError):
            self.proj.set_operation_feeds(self.op, {"feed_mm_min": 0.0})
        with self.assertRaises(UserError):
            self.proj.set_operation_feeds(self.op, {"bogus": 1.0})

    def test_new_preset_clears_overrides(self):
        self.proj.set_operation_feeds(self.op, {"feed_mm_min": 777.0})
        other = [p for p in self.tool.presets if p.id != self.preset.id]
        preset = other[0] if other else self.preset
        rec = self.proj.change_operation_tool(self.op, self.asm.id, preset.id)
        self.assertNotIn("overrides", rec)
        self.assertAlmostEqual(self._tc()["feed_mm_min"], rec["values"]["feed_mm_min"])


if __name__ == "__main__":
    unittest.main()
