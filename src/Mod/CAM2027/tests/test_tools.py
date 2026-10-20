# SPDX-License-Identifier: LGPL-2.1-or-later
"""Tests du modèle et de la bibliothèque d'outils (sans document FreeCAD)."""

import json
import math
import os
import tempfile
import unittest

from cam2027.tools.model import (
    ToolDefinition, ToolGeometry, CuttingPreset, Holder, ToolAssembly, Segment, TOOL_TYPES, geometry_fields_for,
)
from cam2027.tools.library import ToolLibrary, starter_library, migrate
from cam2027.tools.fusion_import import import_fusion_library
from cam2027 import units


class TestUnits(unittest.TestCase):
    def test_lengths(self):
        self.assertAlmostEqual(units.to_mm("5.0000 mm"), 5.0)
        self.assertAlmostEqual(units.to_mm("1 in"), 25.4)
        self.assertAlmostEqual(units.to_mm(3), 3.0)
        self.assertAlmostEqual(units.to_mm("2,5 mm"), 2.5)
        with self.assertRaises(ValueError):
            units.to_mm("5 kg")

    def test_feeds_and_angles(self):
        self.assertAlmostEqual(units.to_mm_min("1 m/min"), 1000.0)
        self.assertAlmostEqual(units.to_mm_min("10 mm/s"), 600.0)
        self.assertAlmostEqual(units.to_deg("90 °"), 90.0)
        self.assertAlmostEqual(units.to_deg("%f rad" % math.pi), 180.0, places=3)


class TestToolModel(unittest.TestCase):
    def test_endmill_defaults(self):
        t = ToolDefinition("6 mm", "endmill", dict(diameter=6, overall_length=50, flute_length=18))
        self.assertEqual(t.geometry.shank_diameter, 6.0)
        self.assertEqual(t.geometry.flute_style, "straight")
        self.assertEqual(len(t.shank_segments), 1)
        self.assertAlmostEqual(t.shank_segments[0].length, 32.0)
        self.assertEqual(geometry_fields_for("endmill")[0], "diameter")

    def test_every_type_builds(self):
        base = dict(diameter=8, shank_diameter=8, overall_length=60, flute_length=20)
        extra = {
            "taper": dict(taper_half_angle_deg=5, corner_radius=1),
            "taperedball": dict(taper_half_angle_deg=3, corner_radius=1),
            "threadmill": dict(pitch=1.0, pitch_min=0.5, thread_teeth=4),
            "form": dict(tip_offset=0),
            "barrel": dict(barrel_radius=48, upper_radius=1, lower_radius=1, axial_distance=12),
            "lens": dict(corner_radius=1, lower_radius=10),
            "ogive": dict(barrel_radius=90, lower_radius=1),
            "taperbarrel": dict(barrel_radius=500, taper_half_angle_deg=20, upper_radius=8, lower_radius=4, tip_diameter=0),
            "dovetail": dict(taper_half_angle_deg=30, corner_radius=0),
            "facemill": dict(taper_half_angle_deg=0, corner_radius=0),
        }
        for ttype in TOOL_TYPES:
            geom = dict(base)
            geom.update(extra.get(ttype, {}))
            t = ToolDefinition("t-" + ttype, ttype, geom)
            self.assertGreater(sum(s.length for s in t.silhouette()), 0, ttype)
            ToolDefinition.from_dict(json.loads(json.dumps(t.to_dict())))

    def test_angle_conventions(self):
        v = ToolDefinition("V60", "vbit", dict(diameter=12.7, overall_length=50, flute_length=11, tip_included_angle_deg=60))
        self.assertEqual(v.geometry.tip_included_angle_deg, 60.0)
        cone = v.silhouette()[0]
        expected_height = (12.7 / 2.0) / math.tan(math.radians(30))
        self.assertAlmostEqual(cone.length, expected_height, places=3)
        with self.assertRaises(ValueError):
            ToolDefinition("bad", "vbit", dict(diameter=12.7, overall_length=50, tip_included_angle_deg=180))
        with self.assertRaises(ValueError):
            ToolDefinition("bad", "taper", dict(diameter=6, overall_length=50, flute_length=10))
        t = ToolDefinition("cone", "taper", dict(diameter=12, overall_length=144, flute_length=24,
                                                   taper_half_angle_deg=10, corner_radius=2.5))
        self.assertEqual(t.geometry.taper_tip, "bullnose")
        cone = t.silhouette()[0]
        self.assertAlmostEqual(cone.lower_diameter, 12.0)
        self.assertAlmostEqual(cone.upper_diameter, 12 + 2 * 24 * math.tan(math.radians(10)), places=6)
        tm = ToolDefinition("tm", "threadmill", dict(diameter=12, overall_length=144, flute_length=24, pitch=1.0))
        self.assertEqual((tm.geometry.pitch_min, tm.geometry.thread_teeth, tm.geometry.thread_tip_type), (1.0, 1, "point"))
        with self.assertRaises(ValueError):
            ToolDefinition("tm", "threadmill", dict(diameter=12, overall_length=144, flute_length=24, pitch=1.0, pitch_min=2.0))

    def test_validation_errors(self):
        with self.assertRaises(ValueError):
            ToolDefinition("x", "endmill", dict(diameter=6, overall_length=20, flute_length=30))
        with self.assertRaises(ValueError):
            ToolDefinition("x", "bullnose", dict(diameter=6, overall_length=50, flute_length=10, corner_radius=4))
        with self.assertRaises(ValueError):
            ToolDefinition("x", "nope", dict(diameter=6, overall_length=50))
        with self.assertRaises(ValueError):
            ToolDefinition("x", "endmill", dict(diameter=6, overall_length=50), flute_count=0)

    def test_preset_relations(self):
        t = ToolDefinition("6 mm", "endmill", dict(diameter=6, overall_length=50, flute_length=18), flute_count=2)
        p = CuttingPreset("vc", surface_speed_m_min=150, rpm_source="vc", feed_per_tooth_mm=0.05, feed_source="fz")
        r = p.resolve(t)
        n = 1000 * 150 / (math.pi * 6)
        self.assertAlmostEqual(r["spindle_rpm"], n, places=6)
        self.assertAlmostEqual(r["feed_mm_min"], n * 2 * 0.05, places=6)
        self.assertIn("spindle_rpm", r["derived"])
        self.assertIn("feed_mm_min", r["derived"])
        q = CuttingPreset("rpm", spindle_rpm=18000, feed_mm_min=1800)
        r2 = q.resolve(t)
        self.assertAlmostEqual(r2["feed_per_tooth_mm"], 1800 / (18000 * 2))
        self.assertAlmostEqual(r2["surface_speed_m_min"], math.pi * 6 * 18000 / 1000)
        self.assertAlmostEqual(r2["plunge_feed_mm_min"], 600.0)
        self.assertAlmostEqual(r2["ramp_angle_deg"], 2.0)
        with self.assertRaises(ValueError):
            CuttingPreset("bad", spindle_rpm=10, coolant="beer")
        with self.assertRaises(ValueError):
            CuttingPreset("bad", spindle_rpm=10, unknown_field=1)

    def test_assembly_checks(self):
        t = ToolDefinition("6 mm", "endmill", dict(diameter=6, overall_length=50, flute_length=18, shoulder_length=22))
        h = Holder("ER20", [dict(lower_diameter=28, upper_diameter=28, length=20)], bore_diameter=6)
        a = ToolAssembly("T1", t.id, h.id, stickout=30)
        a.validate_against(t, h)
        self.assertAlmostEqual(a.gauge_length, 50.0)
        with self.assertRaises(ValueError):
            ToolAssembly("T1", t.id, h.id, stickout=60).validate_against(t, h)
        with self.assertRaises(ValueError):
            ToolAssembly("T1", t.id, h.id, stickout=10).validate_against(t, h)
        h2 = Holder("ER20-8", [dict(lower_diameter=28, upper_diameter=28, length=20)], bore_diameter=8)
        with self.assertRaises(ValueError):
            ToolAssembly("T1", t.id, h2.id, stickout=30).validate_against(t, h2)

    def test_duplicate_gets_new_ids(self):
        t = ToolDefinition("6 mm", "endmill", dict(diameter=6, overall_length=50, flute_length=18))
        t.add_preset(CuttingPreset("p", spindle_rpm=1000, feed_mm_min=100))
        c = t.duplicate()
        self.assertNotEqual(c.id, t.id)
        self.assertNotEqual(c.presets[0].id, t.presets[0].id)
        self.assertEqual(c.name, "6 mm (copy)")


class TestLibrary(unittest.TestCase):
    def test_merge_starter_tools(self):
        """Les outils de démarrage absents sont ajoutés avec des numéros libres ; rien n'est dupliqué."""
        from cam2027.tools.library import merge_starter_tools

        lib = starter_library()
        tm = lib.search("thread mill")[0]
        for asm in lib.assemblies_for_tool(tm.id):
            lib.remove_assembly(asm.id)
        lib.remove_tool(tm.id)
        n_tools, n_asm = lib.summary()["tools"], lib.summary()["assemblies"]
        highest = max(a.output.tool_number for a in lib.assemblies.values())
        added = merge_starter_tools(lib)
        self.assertEqual(added, [tm.name])
        self.assertEqual(lib.summary()["tools"], n_tools + 1)
        self.assertEqual(lib.summary()["assemblies"], n_asm + 1)
        back = lib.search("thread mill")[0]
        asm = lib.assemblies_for_tool(back.id)[0]
        self.assertEqual(asm.output.tool_number, highest + 1)
        self.assertEqual(lib.summary()["holders"], 1)  # porte-outil ER20 réutilisé (même nom)
        self.assertEqual(merge_starter_tools(lib), [])
        self.assertEqual(lib.summary()["tools"], n_tools + 1)

    def test_starter_roundtrip(self):
        lib = starter_library()
        self.assertGreaterEqual(lib.summary()["tools"], 7)
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "lib.cam2027tools")
        lib.save(path)
        self.assertEqual(lib.revision, 1)
        again = ToolLibrary.load(path)
        self.assertEqual(again.to_dict()["tools"], lib.to_dict()["tools"])
        self.assertEqual(again.to_dict()["assemblies"], lib.to_dict()["assemblies"])
        again.save()
        self.assertEqual(again.revision, 2)

    def test_search_and_filters(self):
        lib = starter_library()
        six = lib.search("6 mm")
        self.assertTrue(six and all(t.geometry.diameter == 6.0 for t in six))
        self.assertTrue(all(t.geometry.diameter == 6.0 for t in lib.search("6mm")))
        self.assertTrue(all(t.tool_type == "vbit" for t in lib.search(tool_type="vbit")))
        self.assertEqual(lib.search(favorites_only=True), [])
        first = lib.search()[0]
        lib.set_favorite(first.id)
        self.assertEqual([t.id for t in lib.search(favorites_only=True)], [first.id])
        self.assertTrue(lib.search("compression"))
        self.assertEqual(lib.search("zzz-nothing"), [])

    def test_bulk_edit_atomic(self):
        lib = starter_library()
        ids = [t.id for t in lib.search(tool_type="endmill")]
        lib.bulk_edit(ids, material="hss", coating="TiAlN")
        self.assertTrue(all(lib.tool(i).material == "hss" for i in ids))
        with self.assertRaises(ValueError):
            lib.bulk_edit(ids, **{"geometry.flute_length": 1000})
        self.assertTrue(all(lib.tool(i).geometry.flute_length < 1000 for i in ids))
        self.assertTrue(all(lib.tool(i).coating == "TiAlN" for i in ids))

    def test_remove_guarded(self):
        lib = starter_library()
        asm = list(lib.assemblies.values())[0]
        with self.assertRaises(ValueError):
            lib.remove_tool(asm.tool_id)
        lib.remove_assembly(asm.id)
        lib.remove_tool(asm.tool_id)

    def test_snapshot_is_frozen(self):
        lib = starter_library()
        snap = lib.snapshot()
        tool = list(lib.tools.values())[0]
        tool.geometry.diameter = 99.0
        frozen = ToolLibrary.from_dict(snap)
        self.assertNotEqual(frozen.tool(tool.id).geometry.diameter, 99.0)

    def test_migrate_rejects_newer(self):
        with self.assertRaises(ValueError):
            migrate({"data_version": 999})

    def test_fusion_import_synthetic(self):
        """Import d'un extrait au format supposé des exports Fusion (non validé sur export réel)."""
        sample = {
            "version": 1,
            "data": [
                {
                    "type": "flat end mill", "description": "Fraise 6 mm", "vendor": "ACME", "product-id": "E6",
                    "unit": "millimeters", "BMC": "carbide", "guid": "x",
                    "geometry": {"DC": 6, "SFDM": 6, "OAL": 50, "LB": 30, "LCF": 18, "NOF": 2, "RE": 0, "ZZZ": 1},
                    "start-values": {"presets": [
                        {"name": "Alu", "n": 16000, "v_f": 800, "v_f_plunge": 200, "stepdown": 1.5, "stepover": 2.4}
                    ]},
                    "post-process": {"number": 3, "length-offset": 3, "diameter-offset": 3, "manual-tool-change": True,
                                     "comment": "", "turret": 0},
                    "holder": {"description": "ER20", "segments": [{"height": 20, "upper": 28, "lower": 28}]},
                },
                {"type": "boring bar", "description": "Barre", "geometry": {"DC": 10, "OAL": 100}},
                {"type": "drill", "description": "Foret 1/8", "unit": "inches",
                 "geometry": {"DC": 0.125, "OAL": 2.0, "LCF": 1.0, "SIG": 118, "NOF": 2}},
            ],
        }
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "fusion.json")
        with open(path, "w", encoding="utf-8") as fp:
            json.dump(sample, fp)
        lib = ToolLibrary("import")
        report = import_fusion_library(path, lib)
        self.assertEqual(len(report.imported), 2)
        self.assertEqual(len(report.skipped), 1)
        self.assertIn("Fraise 6 mm", report.unknown_fields)
        self.assertIn("ZZZ", report.unknown_fields["Fraise 6 mm"])
        tool = lib.search("Fraise 6 mm")[0]
        self.assertEqual(tool.geometry.body_length, 30.0)
        self.assertEqual(tool.presets[0].axial_engagement_mm, 1.5)
        asm = lib.assemblies_for_tool(tool.id)[0]
        self.assertEqual(asm.output.tool_number, 3)
        self.assertEqual(asm.output.post_properties.get("turret"), 0)
        self.assertEqual(len(lib.holders), 1)
        drill = lib.search("Foret")[0]
        self.assertAlmostEqual(drill.geometry.diameter, 3.175)
        self.assertIn("drill", report.to_text().lower() + drill.tool_type)

    def test_fusion_import_real_export(self):
        """Export réel de Fusion 2.16 (fixture fusion-library-lunyee.tools, 11 outils, version 37)."""
        path = os.path.join(os.path.dirname(__file__), "fixtures", "fusion-library-lunyee.tools")
        lib = ToolLibrary("real")
        report = import_fusion_library(path, lib)
        self.assertEqual(len(report.imported), 11, report.to_text())
        self.assertEqual(report.skipped, [], report.to_text())
        self.assertEqual(report.unknown_fields, {}, report.to_text())
        self.assertEqual(sorted(a.output.tool_number for a in lib.assemblies.values()), list(range(1, 12)))
        vbit = lib.search("Fraise en V")[0]
        self.assertEqual(vbit.tool_type, "chamfer")
        self.assertAlmostEqual(vbit.geometry.tip_included_angle_deg, 60.0)
        self.assertAlmostEqual(vbit.geometry.tip_diameter, 0.0)
        self.assertEqual(vbit.flute_count, 3)
        graver = lib.search("Pointe")[0]
        self.assertAlmostEqual(graver.geometry.tip_included_angle_deg, 30.0)
        taper = lib.search("Gravure en relief")[0]
        self.assertEqual((taper.tool_type, taper.geometry.taper_tip), ("taper", "bullnose"))
        self.assertAlmostEqual(taper.geometry.taper_half_angle_deg, 5.4)
        self.assertAlmostEqual(taper.geometry.corner_radius, 0.5)
        self.assertAlmostEqual(taper.geometry.body_length, 25.0)
        self.assertAlmostEqual(taper.geometry.shoulder_length, 20.0)
        asm = lib.assemblies_for_tool(taper.id)[0]
        self.assertAlmostEqual(asm.gauge_length, 25.0)
        self.assertAlmostEqual(asm.stickout, 25.0)
        self.assertEqual(asm.output.tool_number, 2)
        self.assertFalse(asm.output.manual_tool_change)
        self.assertEqual(asm.output.post_properties, {"break-control": False, "live": True, "turret": 0})
        face = lib.search(tool_type="facemill")[0]
        self.assertAlmostEqual(face.geometry.diameter, 24.0)
        self.assertAlmostEqual(face.geometry.shank_diameter, 6.35)
        alu = lib.search("Double-Flute ALU")[0]
        p = alu.presets[0]
        self.assertEqual(p.coolant, "mist")
        self.assertAlmostEqual(p.spindle_rpm, 18000)
        self.assertAlmostEqual(p.feed_mm_min, 900)
        self.assertAlmostEqual(p.plunge_feed_mm_min, 200)
        self.assertAlmostEqual(p.ramp_spindle_rpm, 18000)
        self.assertAlmostEqual(p.transition_feed_mm_min, 900)
        self.assertAlmostEqual(p.ramp_angle_deg, 2.0)
        self.assertIsNone(p.axial_engagement_mm)  # use-stepdown = false
        r = p.resolve(alu)
        self.assertAlmostEqual(r["feed_per_tooth_mm"], 0.025)
        self.assertEqual(alu.product_url, "https://www.sorotec.de/shop/End-Mill-Double-Flute-ALU--3-0mm.html")
        self.assertEqual(alu.product_id, "L2SA.0300")
        self.assertTrue(all(t.rotation == "cw" for t in lib.tools.values()))
        self.assertTrue(all(t.presets[0].coolant in ("flood", "none", "mist") for t in lib.tools.values()))
        # noms accentués conservés
        self.assertTrue(any("é" in t.name for t in lib.tools.values()))


if __name__ == "__main__":
    unittest.main()
