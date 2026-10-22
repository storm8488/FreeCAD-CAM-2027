# SPDX-License-Identifier: LGPL-2.1-or-later
"""Flux S5 (nuit 2) : modèles de parcours, dessin vectoriel, vectorisation d'image, temps, décors."""

import math
import os
import shutil
import tempfile
import unittest

import FreeCAD
import Part

from cam2027.tools.library import starter_library
from cam2027.project.project import Project
from cam2027.project.machine import MachineProfile

INK = 'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"'

#: dessin A : découpe (calque Cut), poche (calque Pocket), V-carve (groupe Vcarve)
SVG_A = ('<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" %s width="120mm" height="80mm" viewBox="0 0 120 80">'
         '<g inkscape:groupmode="layer" inkscape:label="Cut" id="layer1"><rect id="outline" x="5" y="5" width="110" height="70" fill="none" stroke="black"/></g>'
         '<g inkscape:groupmode="layer" inkscape:label="Pocket" id="layer2"><circle id="hole" cx="30" cy="40" r="12" fill="none" stroke="black"/></g>'
         '<g id="Vcarve"><path id="star" d="M 70 30 L 100 30 L 85 55 Z" fill="none" stroke="black"/></g>'
         '</svg>') % INK
#: dessin B : autres formes, autres noms ; le V-carve n'a pas de calque mais garde le nom « star »
SVG_B = ('<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" %s width="160mm" height="90mm" viewBox="0 0 160 90">'
         '<g inkscape:groupmode="layer" inkscape:label="Cut" id="l1"><rect id="board" x="0" y="0" width="150" height="85" fill="none" stroke="black"/></g>'
         '<g inkscape:groupmode="layer" inkscape:label="Pocket" id="l2"><rect id="slot1" x="15" y="15" width="30" height="20" fill="none" stroke="black"/>'
         '<circle id="round2" cx="35" cy="60" r="10" fill="none" stroke="black"/></g>'
         '<path id="star" d="M 90 20 L 130 20 L 110 60 Z" fill="none" stroke="black"/>'
         '</svg>') % INK


def machine():
    return MachineProfile("test", controller="grbl", post_processor="grbl",
                          post_processor_args="--no-show-editor --precision=3")


def tool_ids(lib, text, pred=lambda t: True):
    tool = [t for t in lib.search(text) if pred(t)][0]
    return tool, lib.assemblies_for_tool(tool.id)[0]


def cut_points(op):
    out, pos = [], {}
    for c in op.Path.Commands:
        pos.update({k: v for k, v in c.Parameters.items() if k in "XYZ"})
        if c.Name in ("G1", "G2", "G3") and len(pos) == 3:
            out.append((pos["X"], pos["Y"], pos["Z"]))
    return out


class TestTemplates(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cam2027-s5-")

    def tearDown(self):
        for name in list(FreeCAD.listDocuments()):
            FreeCAD.closeDocument(name)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _svg(self, name, text):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as fp:
            fp.write(text)
        return path

    def test_layers_read_from_svg(self):
        from cam2027.project import templates

        layers = templates.svg_layers(self._svg("a.svg", SVG_A))
        self.assertEqual(layers, {"outline": "Cut", "hole": "Pocket", "star": "Vcarve"})

    def test_template_cut_pocket_vcarve_on_second_drawing(self):
        """Modèle « découpe + poche + V-carve » enregistré sur un dessin, appliqué à un autre : 3 opérations
        calculées, poche sur les 2 vecteurs du calque Pocket, V-carve retrouvé par son nom."""
        from cam2027.project import templates

        lib = starter_library()
        proj = Project.create("Template A", lib, machine())
        proj.import_model(self._svg("a.svg", SVG_A))
        proj.create_sheet_job(thickness=12.0)
        doc = proj.doc
        mill, masm = tool_ids(lib, "6 mm flat end mill")
        small, sasm = tool_ids(lib, "3 mm flat end mill", lambda t: t.tool_type == "endmill")
        vbit, vasm = tool_ids(lib, "V-bit", lambda t: t.geometry.tip_included_angle_deg == 60.0)
        proj.add_operation("profile", "Cut out", masm.id, mill.presets[0].id, base=[(doc.getObject("outline"), [])],
                           params={"Side": "Outside", "StartDepth": 0.0, "FinalDepth": -12.0, "StepDown": 4.0})
        proj.add_operation("pocket2d", "Pocket", sasm.id, small.presets[0].id, base=[(doc.getObject("hole"), [])],
                           params={"StartDepth": 0.0, "FinalDepth": -3.0, "StepDown": 1.5})
        proj.add_operation("vcarve", "V-carve", vasm.id, vbit.presets[0].id, base=[(doc.getObject("star_w") or doc.getObject("star"), [])],
                           params={"FinalDepth": -4.0})
        tpl = templates.capture(proj, "Sign")
        self.assertEqual([o["kind"] for o in tpl["operations"]], ["profile", "pocket2d", "vcarve"])
        self.assertEqual(tpl["operations"][1]["targets"], [{"layer": "Pocket", "name": "hole"}])
        path = templates.save(tpl, os.path.join(self.tmp, "sign"))
        self.assertTrue(path.endswith(templates.EXTENSION))

        proj2 = Project.create("Template B", lib, machine())
        proj2.import_model(self._svg("b.svg", SVG_B))
        proj2.create_sheet_job(thickness=12.0)
        rep = templates.apply(proj2, templates.load(path))
        self.assertEqual(rep["missing"], [])
        self.assertEqual([how for _op, how in rep["created"]], ["layer", "layer", "name"])
        results = {r["name"]: r for r in proj2.compute()}
        self.assertEqual(len(results), 3)
        for r in results.values():
            self.assertTrue(r["valid"] and r["commands"] > 5, r)
        self.assertAlmostEqual(results["Cut out"]["zmin"], -12.0, places=3)
        self.assertAlmostEqual(results["Cut out"]["bbox"]["X"][0], -3.0, places=2)  # 6 mm hors du panneau de 150
        self.assertAlmostEqual(results["Pocket"]["zmin"], -3.0, places=3)
        self.assertAlmostEqual(results["V-carve"]["zmin"], -4.0, places=3)
        pocket = [op for op, _h in rep["created"] if op.Label == "Pocket"][0]
        self.assertEqual(len(pocket.Base), 2)
        # aucun point de la poche hors des deux formes (rectangle 15..45 x 65..85 en SVG retourné, disque R10)
        doc2 = proj2.doc
        shapes = [doc2.getObject(n + "_Face").Shape for n in ("slot1", "round2")]
        for x, y, z in cut_points(pocket):
            d = min(s.distToShape(Part.Vertex(FreeCAD.Vector(x, y, 0)))[0] for s in shapes)
            self.assertLess(d, 1e-3, (x, y))
        # dessin sans cible : rapporté, rien de créé
        proj3 = Project.create("Template C", lib, machine())
        proj3.import_model(self._svg("c.svg", SVG_A.replace("Pocket", "Other").replace('id="hole"', 'id="disc"')))
        proj3.create_sheet_job(thickness=12.0)
        rep3 = templates.apply(proj3, templates.load(path))
        self.assertEqual(len(rep3["created"]), 2)
        self.assertEqual(len(rep3["missing"]), 1)


class TestVectors(unittest.TestCase):
    def tearDown(self):
        for name in list(FreeCAD.listDocuments()):
            FreeCAD.closeDocument(name)

    def test_text_shapes_and_operations(self):
        from cam2027.project import vectors

        self.assertTrue(vectors.fonts())
        text = vectors.text_shape("AB", size=10.0)
        self.assertGreater(len(text.Wires), 2)  # A et B ont des trous
        self.assertAlmostEqual(text.BoundBox.ZMax, 0.0, places=9)
        rail = vectors.arc_rail((0, 0), 40.0, 180.0)
        self.assertAlmostEqual(rail.Length, math.pi * 40.0, places=3)
        self.assertLess(rail.valueAt(rail.FirstParameter).x, 0)  # lecture de gauche à droite
        arc = vectors.text_on_curve("CAM2027", rail, size=8.0)
        # chaque lettre au-dessus de l'arc, entre R40 et R40 + 8 (lettres droites sur la tangente)
        for w in arc.Wires:
            for v in w.Vertexes:
                r = math.hypot(v.X, v.Y)
                self.assertGreater(r, 40.0 - 0.6)
                self.assertLess(r, 40.0 + 8.0 + 1.0)
        bb = arc.BoundBox
        self.assertAlmostEqual((bb.XMin + bb.XMax) / 2.0, 0.0, delta=1.5)  # centré sur l'arc
        with self.assertRaises(Exception):
            vectors.text_on_curve("A very long text that cannot fit", vectors.arc_rail((0, 0), 5.0, 90.0), size=8.0)
        sq = Part.Compound([Part.makePolygon([V(0, 0, 0), V(20, 0, 0), V(20, 20, 0), V(0, 20, 0), V(0, 0, 0)])])
        disc = Part.Compound([Part.Wire(Part.makeCircle(10, V(20, 20, 0)))])
        grown = vectors.faces_of(vectors.offset(sq, 2.0))
        self.assertAlmostEqual(grown.Area, 400 + 4 * 20 * 2 + math.pi * 4, delta=0.05)
        shrunk = vectors.faces_of(vectors.offset(sq, -2.0, corners="sharp"))
        self.assertAlmostEqual(shrunk.Area, 256.0, delta=0.05)
        self.assertAlmostEqual(vectors.faces_of(vectors.boolean(sq, disc, "union")).Area, 400 + 0.75 * math.pi * 100, delta=0.5)
        self.assertAlmostEqual(vectors.faces_of(vectors.boolean(sq, disc, "subtract")).Area, 400 - 0.25 * math.pi * 100, delta=0.5)
        self.assertAlmostEqual(vectors.faces_of(vectors.boolean(sq, disc, "intersect")).Area, 0.25 * math.pi * 100, delta=0.5)
        m = vectors.mirror(Part.Compound([Part.makePolygon([V(0, 0, 0), V(10, 0, 0), V(0, 5, 0), V(0, 0, 0)])]), "x")
        self.assertAlmostEqual(m.BoundBox.XMin, 0.0, places=6)
        self.assertTrue(any(abs(v.X - 10) < 1e-6 and abs(v.Y - 5) < 1e-6 for v in m.Vertexes))
        copies = vectors.circular_copies(disc, 6, center=(0, 0))
        self.assertEqual(len(copies.Wires), 6)
        centers = sorted(round(math.degrees(math.atan2(w.CenterOfMass.y, w.CenterOfMass.x))) % 360 for w in copies.Wires)
        self.assertEqual(centers, [45, 105, 165, 225, 285, 345])

    def test_text_on_arc_offset_pocket(self):
        """Critère : texte sur un arc + décalage de 2 mm -> poche 2D calculée dessus, dans le décalage."""
        from cam2027.project import vectors

        lib = starter_library()
        proj = Project.create("Vectors", lib, machine())
        # panneau d'abord (comme Aspire : réglage de la matière, puis dessin)
        frame = vectors.add_vector(proj, Part.Compound([Part.makePolygon(
            [V(-60, -20, 0), V(60, -20, 0), V(60, 60, 0), V(-60, 60, 0), V(-60, -20, 0)])]), "Frame")
        proj.create_sheet_job(vectors=[frame], thickness=12.0)
        arc = vectors.text_on_curve("CAM 27", vectors.arc_rail((0, 0), 35.0, 160.0), size=10.0)
        text = vectors.add_vector(proj, arc, "Text")
        grown = vectors.add_vector(proj, vectors.offset(text.Shape, 2.0), "Text offset 2 mm")
        self.assertIsNotNone(proj.doc.getObject(grown.Name + "_Face"))
        small, sasm = tool_ids(lib, "3 mm flat end mill", lambda t: t.tool_type == "endmill")
        op, _rec = proj.add_operation("pocket2d", "Pocket text", sasm.id, small.presets[0].id, base=[(grown, [])],
                                      params={"StartDepth": 0.0, "FinalDepth": -2.0, "StepDown": 1.0})
        res = {r["name"]: r for r in proj.compute()}["Pocket text"]
        self.assertTrue(res["valid"] and res["commands"] > 20, res)
        self.assertAlmostEqual(res["zmin"], -2.0, places=3)
        face = vectors.faces_of(grown.Shape)
        edges = Part.Compound(face.Edges)
        pts = [p for p in cut_points(op) if p[2] < -1e-6]
        self.assertGreater(len(pts), 50)
        for x, y, z in pts:
            v = Part.Vertex(V(x, y, 0))
            self.assertLess(face.distToShape(v)[0], 1e-3, (x, y))   # dans la zone décalée
            # fraise entière dedans, à la tolérance du contrôle matière (FreeCAD : 0,011 mm sur un polygone)
            self.assertGreater(edges.distToShape(v)[0], 1.5 - 0.02, (x, y))



def write_image(path, w_px, h_px, grey):
    """PNG en niveaux de gris : ``grey(col, row_from_bottom)`` dans [0, 1]."""
    from cam2027.project import relief

    _QtCore, QtGui = relief._qt()
    img = QtGui.QImage(w_px, h_px, QtGui.QImage.Format_RGB32)
    for row in range(h_px):
        for col in range(w_px):
            v = int(round(255 * max(0.0, min(1.0, grey(col, h_px - 1 - row)))))
            img.setPixel(col, row, QtGui.qRgb(v, v, v))
    assert img.save(path)
    return path


def frame_project(name, lib, xmax, ymax):
    """Projet avec un panneau 12 mm sous un cadre (-5, -5) .. (xmax + 5, ymax + 5), dessus à Z 0."""
    from cam2027.project import vectors

    proj = Project.create(name, lib, machine())
    frame = vectors.add_vector(proj, Part.Compound([Part.makePolygon(
        [V(-5, -5, 0), V(xmax + 5, -5, 0), V(xmax + 5, ymax + 5, 0), V(-5, ymax + 5, 0), V(-5, -5, 0)])]), "Frame")
    proj.create_sheet_job(vectors=[frame], thickness=12.0, margin=0.0)
    return proj


class TestBitmap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cam2027-s5b-")

    def tearDown(self):
        for name in list(FreeCAD.listDocuments()):
            FreeCAD.closeDocument(name)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_trace_bitmap_pocket(self):
        """Image 100 x 60 px (1 px = 1 mm) : anneau noir R20 / r8 et carré noir de 20 : 3 contours fermés aux bonnes
        aires, poche 2D sur le tracé (trou de l'anneau respecté)."""
        from cam2027.project import bitmap, vectors

        def grey(i, j):
            r = math.hypot(i - 30, j - 30)
            ring = 8.0 <= r <= 20.0
            square = 65 <= i <= 85 and 20 <= j <= 40
            return 0.0 if ring or square else 1.0

        png = write_image(os.path.join(self.tmp, "logo.png"), 100, 60, grey)
        loops = bitmap.trace(png, 99.0, threshold=0.5, tolerance=0.05)
        self.assertEqual(len(loops), 3)
        areas = sorted(abs(bitmap._area(p)) for p in loops)
        # aires des zones de pixels (1 px = 1 mm²) : le contour passe à mi-chemin entre pixels noirs et blancs
        hole = sum(1 for i in range(100) for j in range(60) if math.hypot(i - 30, j - 30) < 8.0)
        disc = sum(1 for i in range(100) for j in range(60) if math.hypot(i - 30, j - 30) <= 20.0)
        self.assertAlmostEqual(areas[0], hole, delta=0.06 * hole)  # trou de l'anneau
        self.assertAlmostEqual(areas[1], 21.0 * 21.0, delta=0.06 * 441)
        self.assertAlmostEqual(areas[2], disc, delta=0.03 * disc)
        lib = starter_library()
        proj = frame_project("Trace", lib, 99.0, 59.0)
        obj, n = bitmap.trace_to_vector(proj, png, 99.0, threshold=0.5)
        self.assertEqual(n, 3)
        face = vectors.faces_of(obj.Shape)
        self.assertEqual(len(face.Faces), 2)  # anneau (avec trou) + carré
        self.assertAlmostEqual(face.Area, areas[2] - areas[0] + areas[1], delta=1.0)
        small, sasm = tool_ids(lib, "3 mm flat end mill", lambda t: t.tool_type == "endmill")
        op, _rec = proj.add_operation("pocket2d", "Pocket logo", sasm.id, small.presets[0].id, base=[(obj, [])],
                                      params={"StartDepth": 0.0, "FinalDepth": -2.0, "StepDown": 1.0})
        res = {r["name"]: r for r in proj.compute()}["Pocket logo"]
        self.assertTrue(res["valid"] and res["commands"] > 20, res)
        edges = Part.Compound(face.Edges)
        pts = [p for p in cut_points(op) if p[2] < -1e-6]
        self.assertGreater(len(pts), 30)
        for x, y, z in pts:
            v = Part.Vertex(V(x, y, 0))
            self.assertLess(face.distToShape(v)[0], 1e-3, (x, y))
            self.assertGreater(edges.distToShape(v)[0], 1.5 - 0.02, (x, y))
        self.assertFalse(any(math.hypot(x - 30, y - 30) < 8.0 for x, y, z in pts))  # trou de l'anneau intact

    def test_photo_vcarve_depth_follows_grey(self):
        """Dégradé blanc -> noir de gauche à droite, 60 x 40 mm, profondeur maximale 2 mm au V-bit 60° : sur la
        carte de hauteur simulée, profondeur du trait = 2 x sombre (± 0,1), jamais plus de 2 mm, rien dans le blanc."""
        from cam2027.project import bitmap

        png = write_image(os.path.join(self.tmp, "ramp.png"), 121, 81, lambda i, j: 1.0 - i / 120.0)
        lib = starter_library()
        proj = frame_project("Photo", lib, 60.0, 40.0)
        vbit, vasm = tool_ids(lib, "V-bit", lambda t: t.geometry.tip_included_angle_deg == 60.0)
        with self.assertRaises(Exception):  # trop profond pour la largeur du V-bit
            bitmap.add_photo_vcarve(proj, "Too deep", vasm.id, vbit.presets[0].id, png, 60.0, 20.0)
        op, rec = bitmap.add_photo_vcarve(proj, "Photo", vasm.id, vbit.presets[0].id, png, 60.0, 2.0)
        spacing = rec["params"]["spacing"]
        self.assertAlmostEqual(spacing, 0.1 + 2 * 2.0 * math.tan(math.radians(30)), places=6)
        # dégradé linéaire : chaque ligne réduite à ses extrémités (points alignés retirés), 4 commandes par ligne
        self.assertGreaterEqual(len(op.Path.Commands), 4 * int(40.0 / spacing))
        zs = [c.Parameters["Z"] for c in op.Path.Commands if c.Name == "G1" and "Z" in c.Parameters]
        self.assertGreaterEqual(min(zs), -2.0 - 1e-6)
        rep = proj.material_check(resolution=0.1)
        zmap = proj.last_zmap
        self.assertEqual(rep["rapid_hits"] if "rapid_hits" in rep else zmap.rapid_hits, 0)
        self.assertGreaterEqual(float(zmap.top.min()), -2.0 - 0.02)  # rien sous la profondeur maximale
        import numpy as np

        checked = 0
        for k in range(int(40.0 / spacing)):
            y = spacing / 2.0 + k * spacing
            j = int(round((y - zmap.y0) / zmap.res - 0.5))
            for x in (10.0, 20.0, 30.0, 45.0, 55.0):
                i = int(round((x - zmap.x0) / zmap.res - 0.5))
                expected = -2.0 * x / 60.0
                if expected > -0.05:
                    continue
                got = float(zmap.top[i, max(0, j - 1):j + 2].min())  # fond du trait près de la ligne
                self.assertAlmostEqual(got, expected, delta=0.1, msg=(x, y))
                checked += 1
        self.assertGreater(checked, 20)
        # blanc (X < 1,5 mm : profondeur < 0,05) : matière intacte
        i_white = int(round((1.0 - zmap.x0) / zmap.res))
        self.assertAlmostEqual(float(zmap.top[i_white, :].min()), 0.0, places=6)
        self.assertTrue(np.all(zmap.top <= 0.0 + 1e-9))


class TestTiming(unittest.TestCase):
    def tearDown(self):
        for name in list(FreeCAD.listDocuments()):
            FreeCAD.closeDocument(name)

    def test_acceleration_makes_moves_longer(self):
        from cam2027.project import timing

        v = 1000.0 / 60.0  # mm/s
        t = timing.plan_time([((0, 0, 0), (10, 0, 0), v)], accel=500.0)
        self.assertGreater(t, 0.6)  # critère du brief : plus long que distance / avance
        self.assertAlmostEqual(t, 10.0 / v + v / 500.0, places=6)  # trapèze : L/v + v/a
        # segment trop court pour atteindre l'avance : triangle, 2·sqrt(L/a)
        self.assertAlmostEqual(timing.plan_time([((0, 0, 0), (0.1, 0, 0), v)], accel=500.0), 2 * math.sqrt(0.1 / 500.0), places=6)
        # ligne droite coupée en 100 morceaux : aucun arrêt intermédiaire, même temps qu'un seul segment
        pieces = [((0.1 * k, 0, 0), (0.1 * (k + 1), 0, 0), v) for k in range(100)]
        self.assertAlmostEqual(timing.plan_time(pieces, 500.0), t, places=6)
        # aller-retour : arrêt complet au demi-tour
        back = timing.plan_time([((0, 0, 0), (10, 0, 0), v), ((10, 0, 0), (0, 0, 0), v)], 500.0)
        self.assertAlmostEqual(back, 2 * t, places=6)
        # angle droit : ralentissement partiel (entre le tout droit et l'arrêt)
        corner = timing.plan_time([((0, 0, 0), (10, 0, 0), v), ((10, 0, 0), (10, 10, 0), v)], 500.0)
        self.assertGreater(corner, 2 * 10.0 / v + v / 500.0)
        self.assertLess(corner, 2 * t)
        self.assertAlmostEqual(timing.segment_time(10, 0, 0, v, 0), 10.0 / v)

    def test_project_estimate_and_setup_sheet(self):
        from cam2027.project import timing, vectors

        lib = starter_library()
        proj = Project.create("Timing", lib, machine())
        frame = vectors.add_vector(proj, Part.Compound([Part.makePolygon(
            [V(0, 0, 0), V(80, 0, 0), V(80, 50, 0), V(0, 50, 0), V(0, 0, 0)])]), "Frame")
        proj.create_sheet_job(vectors=[frame], thickness=12.0)
        mill, masm = tool_ids(lib, "6 mm flat end mill")
        proj.add_operation("profile", "Cut out", masm.id, mill.presets[0].id, base=[(frame, [])],
                           params={"Side": "Outside", "StartDepth": 0.0, "FinalDepth": -6.0, "StepDown": 3.0})
        proj.compute()
        est = timing.estimate(proj)
        self.assertEqual([r[0] for r in est["operations"]], ["Cut out"])
        self.assertIn("acceleration 500 mm/s²", est["assumed"])
        self.assertGreater(est["total"], est["without_accel"])
        self.assertLess(est["total"], 1.5 * est["without_accel"])
        proj.set_machine(MachineProfile("fast", controller="grbl", post_processor="grbl", acceleration_mm_s2=5000.0,
                                        max_feed_xy_mm_min=3000.0, post_processor_args="--no-show-editor --precision=3"))
        fast = timing.estimate(proj)
        self.assertEqual(fast["assumed"], [])
        self.assertLess(fast["total"], est["total"])
        out = os.path.join(tempfile.mkdtemp(prefix="cam2027-s5t-"), "cut.nc")
        res = proj.export_gcode(out)
        self.assertIn("## Estimated machining time", res["sheet_text"])
        self.assertIn(timing.format_duration(fast["total"]), res["sheet_text"])
        shutil.rmtree(os.path.dirname(out), ignore_errors=True)


class TestDecor(unittest.TestCase):
    def tearDown(self):
        for name in list(FreeCAD.listDocuments()):
            FreeCAD.closeDocument(name)

    def _project(self, lib):
        from cam2027.project import vectors

        proj = frame_project("Decor", lib, 100.0, 40.0)
        rail = vectors.add_vector(proj, Part.Compound([Part.makePolygon([V(0, 10, 0), V(100, 10, 0)])]), "Rail")
        return proj, rail

    def test_ball_on_section(self):
        from cam2027.project import decor

        sec = decor.profile_points("quarter_round", 10.0, 10.0)
        self.assertAlmostEqual(sec[0][1], -10.0)
        self.assertAlmostEqual(sec[-1][1], 0.0)
        # boule de rayon 3 : jamais sous la section, et sur la section là où elle est plus courbée que la boule
        for u in (0.5, 2.0, 5.0, 8.0, 9.5):
            tip = decor.ball_tip_z(sec, u, 3.0)
            for s in [u - 3 + 0.05 * k for k in range(121)]:
                ball = tip + 3.0 - math.sqrt(max(0.0, 9.0 - (s - u) ** 2))
                self.assertGreaterEqual(ball, decor._section_z(sec, s) - 1e-6)
        with self.assertRaises(Exception):
            decor.profile_points("unknown", 10, 10)

    def test_quarter_round_moulding_section(self):
        """Critère : moulure quart-de-rond R10 le long d'une ligne, boule 6 mm : section mesurée sur la carte de
        hauteur simulée à ± 0,05 mm, jamais sous le profil."""
        from cam2027.project import decor

        lib = starter_library()
        proj, rail = self._project(lib)
        ball, basm = tool_ids(lib, "6 mm ball end mill")
        with self.assertRaises(Exception):  # pas une fraise boule
            mill, masm = tool_ids(lib, "6 mm flat end mill")
            decor.add_moulding(proj, "Bad", masm.id, mill.presets[0].id, rail, "quarter_round", 10.0, 10.0)
        op, rec = decor.add_moulding(proj, "Moulding", basm.id, ball.presets[0].id, rail, "quarter_round", 10.0, 10.0,
                                     stepover=0.3, step_down=4.0)
        self.assertGreater(len(op.Path.Commands), 60)
        proj.material_check(resolution=0.1)
        zmap = proj.last_zmap
        section = decor.profile_points("quarter_round", 10.0, 10.0)
        # enveloppe 2D attendue : la plus basse des boules des passes de finition
        centres = []
        u = -3.0
        while u < 10.0 - 1e-9:
            centres.append(u)
            u += 0.3
        centres.append(10.0)
        tips = [(c, decor.ball_tip_z(section, c, 3.0)) for c in centres]

        def envelope(u):
            return min([t + 3.0 - math.sqrt(9.0 - (u - c) ** 2) for c, t in tips if abs(u - c) < 3.0] + [0.0])

        worst_sim, worst_under, worst_reach, n = 0.0, 0.0, 0.0, 0
        for i, x in enumerate(zmap.xs):
            if not 10.0 <= x <= 90.0 or i % 5:
                continue
            for j, y in enumerate(zmap.ys):
                u = y - 10.0
                if not 0.0 <= u <= 10.0:
                    continue
                z = float(zmap.top[i, j])
                worst_sim = max(worst_sim, abs(z - envelope(u)))  # simulation = trajet prévu
                worst_under = min(worst_under, z - decor._section_z(section, u))
                if u >= 1.5:  # pied du profil : congé de R3 inévitable à la boule de 6 mm
                    worst_reach = max(worst_reach, z - decor._section_z(section, u))
                n += 1
        self.assertGreater(n, 1000)
        self.assertLessEqual(worst_sim, 0.05)
        self.assertLessEqual(worst_reach, 0.05)  # section à 0,05 mm partout où la boule peut aller
        self.assertGreaterEqual(worst_under, -0.02)  # aucune entaille sous le profil
        # au-delà du profil, côté pièce : dessus intact
        j_in = int((25.0 - zmap.y0) / zmap.res)
        self.assertAlmostEqual(float(zmap.top[:, j_in].min()), 0.0, places=6)

    def test_fluting_ramps(self):
        from cam2027.project import decor

        lib = starter_library()
        proj, rail = self._project(lib)
        ball, basm = tool_ids(lib, "6 mm ball end mill")
        with self.assertRaises(Exception):  # rampes plus longues que le vecteur
            decor.add_fluting(proj, "Too long", basm.id, ball.presets[0].id, [rail], 2.0, 60.0, 60.0)
        op, _rec = decor.add_fluting(proj, "Flute", basm.id, ball.presets[0].id, [rail], 2.0, 20.0, 20.0)
        proj.material_check(resolution=0.1)
        zmap = proj.last_zmap
        j = int(round((10.0 - zmap.y0) / zmap.res - 0.5))
        for x, expected in ((50.0, -2.0), (30.0, -2.0), (10.0, -1.0), (90.0, -1.0), (5.0, -0.5)):
            i = int(round((x - zmap.x0) / zmap.res - 0.5))
            self.assertAlmostEqual(float(zmap.top[i, j - 1:j + 2].min()), expected, delta=0.05, msg=x)
        self.assertGreaterEqual(float(zmap.top.min()), -2.0 - 0.02)

V = FreeCAD.Vector


if __name__ == "__main__":
    unittest.main()
