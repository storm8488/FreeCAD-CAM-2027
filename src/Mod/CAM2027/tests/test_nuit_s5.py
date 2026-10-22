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


V = FreeCAD.Vector


if __name__ == "__main__":
    unittest.main()
