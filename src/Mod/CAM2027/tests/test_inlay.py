# SPDX-License-Identifier: LGPL-2.1-or-later
"""V-carving à fond plat, incrustations, imbrication : vérifiés sur la matière simulée (carte de hauteur)."""

import math
import os
import tempfile
import unittest

import FreeCAD

from cam2027.project import sim
from cam2027.project.project import Project
from cam2027.project.machine import MachineProfile
from cam2027.tools.library import starter_library
from tests.test_import import SVG


def simulate(proj, ops, resolution=0.2, bounds=None):
    """Matière restante après ``ops`` (dans l'ordre), fraises de la bibliothèque du projet."""
    zmap = sim.ZMap.from_bounds(bounds or proj.stock_bounds(), resolution)
    pos = None
    for op in ops:
        rec = proj.registry[proj.base_operation(op).Name]
        profile, _note = sim.ToolProfile.from_library_tool(proj.library.tool(rec["tool_id"]))
        segments, pos = sim.path_segments(op.Path.Commands, pos)
        for rapid, p0, p1 in segments:
            zmap.sweep(p0, p1, profile, rapid=rapid)
    return zmap


def at(zmap, x, y):
    """(hauteur, x du centre, y du centre) de la colonne qui contient (x, y)."""
    i = int((x - zmap.x0) / zmap.res)
    j = int((y - zmap.y0) / zmap.res)
    return float(zmap.top[i, j]), float(zmap.xs[i]), float(zmap.ys[j])


class TestFlatDepth(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="cam2027-inlay-")
        cls.svg = os.path.join(cls.tmp, "drawing.svg")
        with open(cls.svg, "w", encoding="utf-8") as fp:
            fp.write(SVG)
        FreeCAD.ConfigSet("SuppressRecomputeRequiredDialog", "True")

    def _sheet_project(self, name):
        from cam2027.project import sheet as sheetmod

        lib = starter_library()
        proj = Project.create(name, lib, MachineProfile("test", controller="grbl", post_processor="grbl",
                                                         post_processor_args="--no-show-editor --precision=3"))
        proj.import_model(self.svg)
        vectors = sheetmod.vector_objects(proj.doc)
        proj.create_sheet_job(thickness=12.0, margin=10.0)
        rect = [v for v in vectors if len(v.Shape.Edges) == 4][0]
        return proj, lib, rect

    def test_flat_depth_clearing(self):
        """Rectangle 40×20, V-bit 60° limité à 2 mm : fond plat à -2 au milieu, flancs en V jusqu'au bord."""
        proj, lib, rect = self._sheet_project("Flat depth")
        vbit = [t for t in lib.search("V-bit") if t.geometry.tip_included_angle_deg == 60.0][0]
        vasm = lib.assemblies_for_tool(vbit.id)[0]
        flat = [t for t in lib.search("3 mm flat end mill") if t.tool_type == "endmill"][0]
        fasm = lib.assemblies_for_tool(flat.id)[0]
        face = proj.drawing_clone(rect, face=True)
        vop, _r = proj.add_operation("vcarve", "Vcarve rect", vasm.id, vbit.presets[0].id, base=[(face, ["Face1"])],
                                     params={"FinalDepth": -2.0})
        pocket, outline = proj.add_flat_clearing(vop, fasm.id, flat.presets[0].id, params={"StepDown": 1.0})
        self.assertEqual([o.Label for o in proj.operations()][-3:],
                         ["Vcarve rect - flat", "Vcarve rect - flat outline", "Vcarve rect"])
        reach = 0.05 + 2.0 * math.tan(math.radians(30))
        self.assertAlmostEqual(proj.registry[pocket.Name]["flat_reach"], reach, places=6)
        results = {r["name"]: r for r in proj.compute()}
        for r in results.values():
            self.assertTrue(r["valid"], r)
        bb = rect.Shape.BoundBox  # 40 × 20
        # la fraise plate reste dans la zone plate : centre à au moins portée + rayon du bord
        rf = flat.geometry.diameter / 2.0
        pts = [c.Parameters for c in pocket.Path.Commands if c.Name in ("G1", "G2", "G3")
               and "X" in c.Parameters and "Y" in c.Parameters]
        self.assertGreater(len(pts), 10)
        for p in pts:
            self.assertGreaterEqual(p["X"], bb.XMin + reach + rf - 0.02, p)
            self.assertLessEqual(p["X"], bb.XMax - reach - rf + 0.02, p)
            self.assertGreaterEqual(p["Y"], bb.YMin + reach + rf - 0.02, p)
            self.assertLessEqual(p["Y"], bb.YMax - reach - rf + 0.02, p)
        zmap = simulate(proj, [pocket, outline, vop])
        # fond plat au milieu
        x0, y0 = bb.XMin, bb.YMin  # le SVG est importé Y retourné : points relatifs au rectangle
        for dx, dy in ((10, 10), (20, 5), (30, 15), (20, 10), (6, 4), (34, 16)):
            x, y = x0 + dx, y0 + dy
            z, _x, _y = at(zmap, x, y)
            self.assertAlmostEqual(z, -2.0, delta=0.03, msg=(x, y))
        # flancs en V le long des bords (milieu des grands et petits côtés) : le V-bit centré à la portée
        # passe exactement par le bord, z = -d / tan(30°)
        tan30 = math.tan(math.radians(30))
        for d in (0.3, 0.6, 0.9):
            z, _x, yc = at(zmap, x0 + 20, bb.YMin + d)
            self.assertAlmostEqual(z, -(yc - bb.YMin) / tan30, delta=0.06, msg=("long side", d))
            z, xc, _y = at(zmap, bb.XMin + d, y0 + 10)
            self.assertAlmostEqual(z, -(xc - bb.XMin) / tan30, delta=0.06, msg=("short side", d))
        # rien n'est taillé hors du dessin
        for x, y in ((x0 + 20, bb.YMin - 0.3), (bb.XMax + 0.3, y0 + 10)):
            self.assertGreaterEqual(at(zmap, x, y)[0], -0.02, (x, y))
        # zone trop étroite pour un fond plat : refus explicite
        vdeep, _r = proj.add_operation("vcarve", "Deep", vasm.id, vbit.presets[0].id, base=[(face, ["Face1"])],
                                       params={"FinalDepth": -20.0})
        with self.assertRaises(ValueError):
            proj.add_flat_clearing(vdeep, fasm.id, flat.presets[0].id)
        proj.close()


if __name__ == "__main__":
    unittest.main()
