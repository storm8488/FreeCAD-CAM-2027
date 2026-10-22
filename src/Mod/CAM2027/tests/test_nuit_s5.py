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


if __name__ == "__main__":
    unittest.main()
