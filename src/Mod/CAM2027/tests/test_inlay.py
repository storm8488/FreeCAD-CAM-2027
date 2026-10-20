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


class _SheetCase(unittest.TestCase):
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


class TestFlatDepth(_SheetCase):
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
        pocket, outline, corners = proj.add_flat_clearing(vop, fasm.id, flat.presets[0].id, params={"StepDown": 1.0})
        self.assertEqual([o.Label for o in proj.operations()][-4:],
                         ["Vcarve rect - flat", "Vcarve rect - flat outline", "Vcarve rect - sharp corners",
                          "Vcarve rect"])
        self.assertEqual(proj.registry[corners.Name]["params"], {"corners": 4})
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
        zmap = simulate(proj, [pocket, outline, corners, vop])
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
        # angles vifs : sur la diagonale, z = -d·k (d = distance aux deux bords), comme un V-carving non limité
        for d in (0.4, 0.8, 1.0):
            z, xc, yc = at(zmap, bb.XMin + d, bb.YMin + d)
            self.assertAlmostEqual(z, -min(xc - bb.XMin, yc - bb.YMin) / tan30, delta=0.1, msg=("corner", d))
        # rien n'est taillé hors du dessin
        for x, y in ((x0 + 20, bb.YMin - 0.3), (bb.XMax + 0.3, y0 + 10)):
            self.assertGreaterEqual(at(zmap, x, y)[0], -0.02, (x, y))
        # zone trop étroite pour un fond plat : refus explicite
        vdeep, _r = proj.add_operation("vcarve", "Deep", vasm.id, vbit.presets[0].id, base=[(face, ["Face1"])],
                                       params={"FinalDepth": -20.0})
        with self.assertRaises(ValueError):
            proj.add_flat_clearing(vdeep, fasm.id, flat.presets[0].id)
        proj.close()


class TestInlay(_SheetCase):
    def test_male_female_fit(self):
        """Rectangle 40×20, V 60°, femelle 4 mm, mâle départ 2 / fond 4 : le bouchon retourné entre sans
        interférence, flancs en contact, 2 mm de colle au fond et 2 mm entre les planches."""
        proj, lib, rect = self._sheet_project("Inlay")
        vbit = [t for t in lib.search("V-bit") if t.geometry.tip_included_angle_deg == 60.0][0]
        vasm = lib.assemblies_for_tool(vbit.id)[0]
        flat = [t for t in lib.search("3 mm flat end mill") if t.tool_type == "endmill"][0]
        fasm = lib.assemblies_for_tool(flat.id)[0]
        with self.assertRaises(ValueError):  # départ du mâle plus profond que la femelle
            proj.create_inlay(rect, vasm.id, vbit.presets[0].id, fasm.id, flat.presets[0].id, 2.0, 3.0, 4.0)
        res = proj.create_inlay(rect, vasm.id, vbit.presets[0].id, fasm.id, flat.presets[0].id, 4.0, 2.0, 4.0)
        self.assertEqual((res["bottom_gap"], res["surface_gap"], res["notes"]), (2.0, 2.0, []))
        male = res["male_project"]
        self.assertEqual(len(res["female_ops"]), 4)  # fond plat, contour, angles vifs, V-carving
        self.assertEqual(len(res["male_ops"]), 4)  # angles vifs du rectangle extérieur seulement
        for p in (proj, male):
            for r in p.compute():
                self.assertTrue(r["valid"] and r["commands"] > 5, r)
        bb = rect.Shape.BoundBox
        bounds = {"xmin": bb.XMin - 4, "xmax": bb.XMax + 4, "ymin": bb.YMin - 4, "ymax": bb.YMax + 4, "zmax": 0.0}
        F = simulate(proj, res["female_ops"], 0.1, bounds)
        M = simulate(male, res["male_ops"], 0.1, bounds)  # miroir autour du centre : même étendue en X
        cx = res["mirror_x"]
        worst_interference, min_gap, inside = -1e9, 1e9, 0
        for i, x in enumerate(F.xs):
            for j, y in enumerate(F.ys):
                plug = -2.0 - at(M, 2 * cx - x, y)[0]  # dessous du bouchon retourné, enfoncé de Ps = 2
                gap = plug - float(F.top[i, j])
                worst_interference = max(worst_interference, -gap)
                if bb.XMin < x < bb.XMax and bb.YMin < y < bb.YMax:
                    min_gap = min(min_gap, gap)
                    inside += 1
        self.assertGreater(inside, 50000)
        self.assertLess(worst_interference, 0.12)  # au pas de la grille près (pente k = 1,73)
        self.assertLess(min_gap, 0.15)  # les flancs se touchent
        cxr, cyr = (bb.XMin + bb.XMax) / 2.0, (bb.YMin + bb.YMax) / 2.0
        self.assertAlmostEqual(-2.0 - at(M, 2 * cx - cxr, cyr)[0] - at(F, cxr, cyr)[0], 2.0, delta=0.05)  # colle
        out_x, out_y = bb.XMax + 3.0, cyr  # hors de la forme : écart entre les planches
        self.assertAlmostEqual(-2.0 - at(M, 2 * cx - out_x, out_y)[0] - at(F, out_x, out_y)[0], 2.0, delta=0.05)
        male.close()
        proj.close()


class TestNesting(unittest.TestCase):
    def _no_overlap(self, rects, spacing):
        for a in range(len(rects)):
            for b in range(a + 1, len(rects)):
                ax0, ay0, ax1, ay1 = rects[a]
                bx0, by0, bx1, by1 = rects[b]
                gap = max(bx0 - ax1, ax0 - bx1, by0 - ay1, ay0 - by1)
                self.assertGreaterEqual(gap, spacing - 1e-6, (rects[a], rects[b]))

    def test_skyline_pack(self):
        from cam2027.project import nesting

        items = [("a", 100, 50), ("b", 60, 60), ("c", 200, 30), ("d", 100, 50), ("e", 100, 50), ("f", 30, 120)]
        placed, unplaced = nesting.skyline_pack(items, 280, 180, spacing=5)
        self.assertEqual(unplaced, [])
        rects = []
        for key, w, h in items:
            x, y, rot = placed[key]
            pw, ph = (h, w) if rot else (w, h)
            self.assertGreaterEqual(x, -1e-9)
            self.assertGreaterEqual(y, -1e-9)
            self.assertLessEqual(x + pw, 280 + 1e-9)
            self.assertLessEqual(y + ph, 180 + 1e-9)
            rects.append((x, y, x + pw, y + ph))
        self._no_overlap(rects, 5)
        # bande plus longue que le panneau n'est large : posée tournée
        placed, unplaced = nesting.skyline_pack([("strip", 250, 20)], 200, 300)
        self.assertEqual((unplaced, placed["strip"][2]), ([], True))
        placed, unplaced = nesting.skyline_pack([("big", 400, 400), ("ok", 50, 50)], 200, 300)
        self.assertEqual(unplaced, ["big"])
        self.assertIn("ok", placed)

    def test_nest_drawings_project(self):
        import Part
        from cam2027.project import sheet as sheetmod

        V = FreeCAD.Vector
        lib = starter_library()
        proj = Project.create("Nesting", lib, MachineProfile("test", controller="grbl", post_processor="grbl",
                                                              post_processor_args="--no-show-editor --precision=3"))

        def drawing(name, wire):
            obj = proj.doc.addObject("Part::Feature", name)
            obj.Shape = wire
            return obj

        rect = drawing("Rect", Part.makePolygon([V(500, 500, 0), V(600, 500, 0), V(600, 550, 0), V(500, 550, 0), V(500, 500, 0)]))
        disc = drawing("Disc", Part.Wire(Part.makeCircle(30, V(-200, 40, 0))))
        tri = drawing("Tri", Part.makePolygon([V(0, 0, 0), V(150, 0, 0), V(0, 40, 0), V(0, 0, 0)]))
        proj.doc.recompute()
        rep = proj.nest_drawings([rect, disc, tri], 300, 200, spacing=5, margin=10, copies={rect: 3})
        self.assertEqual(rep["unplaced"], [])
        self.assertEqual(len(rep["placed"]), 5)  # 3 rectangles, disque, triangle
        boxes = []
        for obj in rep["objects"]:
            bb = obj.Shape.BoundBox
            self.assertGreaterEqual(bb.XMin, 10 - 1e-6)
            self.assertGreaterEqual(bb.YMin, 10 - 1e-6)
            self.assertLessEqual(bb.XMax, 290 + 1e-6)
            self.assertLessEqual(bb.YMax, 190 + 1e-6)
            boxes.append((bb.XMin, bb.YMin, bb.XMax, bb.YMax))
        self._no_overlap(boxes, 5)
        faces = [Part.makeFace(sheetmod.closed_wires(o), "Part::FaceMakerBullseye") for o in rep["objects"]]
        for a in range(len(faces)):
            for b in range(a + 1, len(faces)):
                self.assertLess(faces[a].common(faces[b]).Area, 1e-6)
        expected = (3 * 100 * 50 + math.pi * 30 ** 2 + 150 * 40 / 2.0) / (300 * 200)
        self.assertAlmostEqual(rep["utilization"], expected, places=3)
        # panneau imposé : le brut est exactement le panneau
        proj.create_sheet_job(rep["objects"], thickness=18.0, sheet_rect=(0, 0, 300, 200))
        sb = proj.stock_bounds()
        self.assertEqual([round(sb[k], 6) for k in ("xmin", "xmax", "ymin", "ymax", "zmin", "zmax")],
                         [0.0, 300.0, 0.0, 200.0, -18.0, 0.0])
        with self.assertRaises(ValueError):  # après le job : refus
            proj.nest_drawings([rect], 300, 200)
        proj.close()
        # panneau trop petit pour tout : les pièces restantes sont rapportées, pas posées dehors
        proj2 = Project.create("Nesting small", lib)
        objs = []
        for k in range(6):  # 6 × 100 × 80 dans 210 × 180 utiles : la surface n'en permet que 4
            o = proj2.doc.addObject("Part::Feature", "R%d" % k)
            o.Shape = Part.makePolygon([V(0, 0, 0), V(100, 0, 0), V(100, 80, 0), V(0, 80, 0), V(0, 0, 0)])
            objs.append(o)
        rep2 = proj2.nest_drawings(objs, 230, 200, spacing=5, margin=10)
        self.assertEqual((len(rep2["placed"]), len(rep2["unplaced"])), (4, 2))
        proj2.close()


if __name__ == "__main__":
    unittest.main()
