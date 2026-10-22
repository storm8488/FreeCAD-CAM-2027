# SPDX-License-Identifier: LGPL-2.1-or-later
"""Nuit 2, flux S2 : entrées/sorties en arc, motifs de parcours, perçage intelligent, palpage de l'origine."""

import math
import os
import tempfile
import unittest

import FreeCAD

from cam2027 import compat
from cam2027.i18n import UserError
from cam2027.tools.library import starter_library
from cam2027.project.project import Project
from cam2027.project.machine import MachineProfile
from tests.test_pipeline import make_part

V11 = compat.freecad_version() >= (1, 1)


def machine(**kw):
    return MachineProfile("test", controller="grbl", post_processor="grbl",
                          post_processor_args="--no-show-editor --precision=3", **kw)


def feed_moves(path):
    """Mouvements d'avance horizontaux : (nom, début, fin, centre XY ou None)."""
    from cam2027.project import leads

    return leads._moves(path.Commands)


def pocket_floor(clone, z=4.0):
    for i, f in enumerate(clone.Shape.Faces, 1):
        bb = f.BoundBox
        if f.Surface.__class__.__name__ == "Plane" and abs(bb.ZMax - z) < 1e-6 and abs(bb.ZMin - z) < 1e-6:
            return "Face%d" % i
    return None


class _PlateCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="cam2027-s2-")
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

    def tool(self, lib, name="6 mm flat end mill"):
        t = lib.search(name)[0]
        return lib.assemblies_for_tool(t.id)[0].id, t.presets[0].id


class TestLeads(_PlateCase):
    def _contour(self, proj, lib, clone):
        asm, pre = self.tool(lib)
        op, _rec = proj.add_operation("profile", "Contour", asm, pre, base=[(clone, [])],
                                      params={"FinalDepth": 0.0, "StepDown": 5.0})
        return op

    def test_arc_lead_on_contour(self):
        """Contour extérieur, arcs de R3 : le premier mouvement de coupe de chaque passe est un arc de R3 tangent au
        contour, aucune entaille ni rapide dans la matière, un arc de sortie par passe ; retrait = parcours nu."""
        proj, lib, clone = self.project("Leads")
        op = self._contour(proj, lib, clone)
        proj.compute()
        base_moves = feed_moves(op.Path)
        base_first = base_moves[0]
        lead, ignored = proj.add_dressup(op, "leads", params={"RadiusIn": 3.0, "RadiusOut": 3.0})
        self.assertEqual(ignored, [])
        self.assertEqual([o.Name for o in proj.operations()], [lead.Name])
        self.assertEqual(proj.registry[op.Name]["dressups"][0]["kind"], "leads")
        proj.compute()
        moves = feed_moves(lead.Path)
        first = moves[0]
        self.assertIn(first[0], ("G2", "G3"), first)
        centre = first[3]
        self.assertAlmostEqual(math.dist(first[1][:2], centre), 3.0, places=3)
        self.assertAlmostEqual(math.dist(first[2][:2], centre), 3.0, places=3)
        # fin de l'arc = début du contour nu, à la même profondeur
        self.assertAlmostEqual(math.dist(first[2], base_first[1]), 0.0, places=3)
        # tangence : la direction du mouvement suivant est perpendiculaire au rayon en fin d'arc
        nxt = moves[1]
        rx, ry = first[2][0] - centre[0], first[2][1] - centre[1]
        if nxt[3] is None:
            dx, dy = nxt[2][0] - nxt[1][0], nxt[2][1] - nxt[1][1]
        else:  # arc : tangente au départ perpendiculaire à son propre rayon
            ux, uy = nxt[1][0] - nxt[3][0], nxt[1][1] - nxt[3][1]
            dx, dy = -uy, ux
        self.assertLess(abs(rx * dx + ry * dy) / (math.hypot(rx, ry) * math.hypot(dx, dy)), 1e-3)
        # une entrée et une sortie par passe : 2 arcs de R3 de plus que le parcours nu par passe
        r3 = [m for m in moves if m[3] is not None and abs(math.dist(m[1][:2], m[3]) - 3.0) < 1e-3]
        r3_base = [m for m in base_moves if m[3] is not None and abs(math.dist(m[1][:2], m[3]) - 3.0) < 1e-3]
        passes = len(set(round(m[1][2], 3) for m in base_moves))
        self.assertGreaterEqual(passes, 2)
        self.assertEqual(len(r3) - len(r3_base), 2 * passes)
        # matière : aucune entaille, aucun rapide dans la matière
        rep = proj.material_check()
        self.assertEqual(rep["gouge_max"], 0.0, rep)
        self.assertEqual(rep["rapid_hits"], 0, rep)
        # export : arcs dans le G-code GRBL, une seule occurrence de l'opération
        from cam2027.project import export as exportmod

        text = "\n".join(g for _n, g in exportmod.postprocess(proj.job))
        self.assertEqual(text.count("(Begin operation: %s)" % lead.Label), 1)
        self.assertEqual(text.count("(Begin operation: %s)" % op.Label), 0)
        # retrait
        proj.remove_dressup(op, "leads")
        self.assertEqual([o.Name for o in proj.operations()], [op.Name])

    def test_pocket_wall_profile(self):
        """Passe de profil d'une poche (intérieur, îlot) : sur 1.1, départ déplacé le long de la paroi tant que
        l'arc toucherait la pièce, aucune entaille ; sur 1.0 (pas de déplacement possible) : refus avec la position."""
        proj, lib, clone = self.project("Leads pocket")
        asm, pre = self.tool(lib)
        op, _rec = proj.add_operation("profile", "Pocket wall", asm, pre, base=[(clone, [pocket_floor(clone)])],
                                      params={"Side": "Inside", "FinalDepth": 4.0, "StepDown": 3.0})
        proj.compute()
        if not V11:
            with self.assertRaises(UserError) as ctx:
                proj.add_dressup(op, "leads", params={"RadiusIn": 3.0, "RadiusOut": 3.0})
            self.assertIn("hits the part", str(ctx.exception))
            self.assertEqual([o.Name for o in proj.operations()], [op.Name])
            return
        lead, _ign = proj.add_dressup(op, "leads", params={"RadiusIn": 3.0, "RadiusOut": 3.0})
        self.assertGreater(float(lead.OffsetIn), 0.0)
        proj.compute()
        first = feed_moves(lead.Path)[0]
        self.assertIn(first[0], ("G2", "G3"))
        rep = proj.material_check()
        self.assertEqual(rep["gouge_max"], 0.0, rep)

    def test_versions_and_styles(self):
        """Paramètres traduits pour 1.0 / 1.1 : angle de balayage (1.1) ou ignoré (1.0), arc vertical (1.1) ou refus."""
        from cam2027.project import leads

        proj, lib, clone = self.project("Leads styles")
        op = self._contour(proj, lib, clone)
        proj.compute()
        lead, ignored = proj.add_dressup(op, "leads", params={"RadiusIn": 4.0, "AngleIn": 45.0, "RadiusOut": 2.0})
        values = leads.read_params(lead)
        self.assertAlmostEqual(values["RadiusIn"], 4.0)
        self.assertAlmostEqual(values["RadiusOut"], 2.0)
        proj.compute()
        first = feed_moves(lead.Path)[0]
        a = math.atan2(first[1][1] - first[3][1], first[1][0] - first[3][0])
        b = math.atan2(first[2][1] - first[3][1], first[2][0] - first[3][0])
        sweep = abs(math.degrees((b - a + math.pi) % (2 * math.pi) - math.pi))
        if V11:
            self.assertEqual(ignored, [])
            self.assertAlmostEqual(values["AngleIn"], 45.0)
            self.assertAlmostEqual(sweep, 45.0, delta=0.1)
        else:
            self.assertEqual(ignored, ["AngleIn"])
            self.assertAlmostEqual(sweep, 90.0, delta=0.1)
        proj.remove_dressup(op, "leads")
        if not V11:
            with self.assertRaises(UserError):
                proj.add_dressup(op, "leads", params={"StyleIn": "ArcZ"})
            self.assertEqual([o.Name for o in proj.operations()], [op.Name])
            return
        lead, _ign = proj.add_dressup(op, "leads", params={"StyleIn": "ArcZ", "StyleOut": "ArcZ", "RadiusIn": 3.0,
                                                           "RadiusOut": 3.0})
        proj.compute()
        moves = feed_moves(lead.Path)
        # arc vertical : descente progressive jusqu'à la passe, Z décroissant, rayon 3 dans le plan vertical
        descent = []
        for m in moves:
            if m[2][2] >= m[1][2] - 1e-9:
                break
            descent.append(m)
        self.assertGreater(len(descent), 5)
        self.assertAlmostEqual(descent[0][1][2] - descent[-1][2][2], 3.0, delta=0.01)
        rep = proj.material_check()
        self.assertEqual(rep["gouge_max"], 0.0, rep)

    def test_tags_under_leads(self):
        """Attaches ajoutées après les entrées/sorties : insérées dessous (contour fermé), entrées toujours en haut."""
        proj, lib, clone = self.project("Leads tags")
        op = self._contour(proj, lib, clone)
        proj.compute()
        lead, _ign = proj.add_dressup(op, "leads", params={"RadiusIn": 3.0, "RadiusOut": 3.0})
        tags, _ign = proj.add_dressup(op, "tags", params={"Height": 4.0, "Width": 8.0}, count=4)
        self.assertEqual([o.Name for o in proj.operations()], [lead.Name])
        self.assertIs(lead.Base, tags)
        self.assertIs(tags.Base, op)
        proj.compute()
        self.assertIn(feed_moves(lead.Path)[0][0], ("G2", "G3"))
        proj.remove_dressup(op, "tags")
        self.assertIs(lead.Base, op)
        self.assertEqual([o.Name for o in proj.operations()], [lead.Name])


POCKETS = [(10.0 + c * 35.0, 12.0 + r * 40.0) for r in range(2) for c in range(3)]  # coin bas-gauche, 20 x 14


def make_grid_part(path):
    """Plaque 120 x 80 x 10 avec 6 poches 20 x 14 x 4 en 3 colonnes (pas 35) et 2 lignes (pas 40)."""
    import Part

    shape = Part.makeBox(120, 80, 10)
    for x, y in POCKETS:
        shape = shape.cut(Part.makeBox(20, 14, 4, FreeCAD.Vector(x, y, 6)))
    shape.exportStep(path)
    return shape


def zmap_at(zmap, x, y):
    return float(zmap.top[int((x - zmap.x0) / zmap.res), int((y - zmap.y0) / zmap.res)])


class TestPatterns(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="cam2027-s2p-")
        cls.step = os.path.join(cls.tmp, "grid.step")
        make_grid_part(cls.step)

    def project(self, name):
        lib = starter_library()
        proj = Project.create(name, lib, machine())
        part = proj.import_model(self.step, label="Grid").objects[0]
        job = proj.create_job([part], stock={"kind": "box_margins", "xy": 2.0, "z_top": 0.0, "z_bottom": 0.0})
        self.addCleanup(proj.close)
        return proj, lib, job.Model.Group[0]

    def pocket(self, proj, lib, clone, name="Pocket", tool="6 mm flat end mill", index=0):
        t = lib.search(tool)[0]
        x, y = POCKETS[index]
        floor = None
        for i, f in enumerate(clone.Shape.Faces, 1):
            bb = f.BoundBox
            if (f.Surface.__class__.__name__ == "Plane" and abs(bb.ZMin - 6.0) < 1e-6 and abs(bb.ZMax - 6.0) < 1e-6
                    and abs(bb.XMin - x) < 1e-6 and abs(bb.YMin - y) < 1e-6):
                floor = "Face%d" % i
        op, _rec = proj.add_operation("pocket", name, lib.assemblies_for_tool(t.id)[0].id, t.presets[0].id,
                                      base=[(clone, [floor])], params={"StepDown": 2.0})
        return op

    def test_grid_3x2(self):
        """3 x 2 copies d'une poche : 6 poches dans la carte de hauteur aux bons endroits, rien entre elles, aucune
        entaille, un seul changement d'outil dans le G-code."""
        from cam2027.project import patterns, export as exportmod

        proj, lib, clone = self.project("Pattern grid")
        op = self.pocket(proj, lib, clone)
        proj.compute()
        n_base = len(op.Path.Commands)
        single = proj.material_check()["removed_volume"]
        made = patterns.add_pattern(proj, [op], {"Kind": "Grid", "Columns": 3, "Rows": 2, "StepX": 35.0, "StepY": 40.0})
        self.assertEqual(len(made), 1)
        pat = made[0]
        self.assertEqual([o.Name for o in proj.operations()], [pat.Name])
        self.assertEqual(patterns.read_params(pat)["Columns"], 3)
        r = {x["name"]: x for x in proj.compute()}
        self.assertEqual(len(pat.Path.Commands), 6 * n_base + 5)
        rep = proj.material_check()
        self.assertEqual(rep["gouge_max"], 0.0, rep)
        self.assertEqual(rep["rapid_hits"], 0, rep)
        z = proj.last_zmap
        for x, y in POCKETS:
            self.assertAlmostEqual(zmap_at(z, x + 10.0, y + 7.0), 6.0, delta=0.02)
            self.assertAlmostEqual(zmap_at(z, x + 4.0, y + 4.0), 6.0, delta=0.02)
        for x, y in ((37.5, 19.0), (72.5, 59.0), (20.0, 39.0), (115.0, 75.0)):
            self.assertAlmostEqual(zmap_at(z, x, y), 10.0, delta=0.02)
        # volume : 6 fois celui de la poche seule (angles arrondis au rayon de la fraise : moins que 6 x 20 x 14 x 4)
        self.assertAlmostEqual(rep["removed_volume"], 6 * single, delta=0.01 * 6 * single)
        self.assertLess(rep["removed_volume"], 6 * 20 * 14 * 4)
        text = "\n".join(g for _n, g in exportmod.postprocess(proj.job))
        self.assertEqual(sum(1 for line in text.splitlines() if "M6" in line.split()), 1, text[:600])
        # retrait : retour à la poche seule
        proj.remove_dressup(op, "pattern")
        self.assertEqual([o.Name for o in proj.operations()], [op.Name])

    def test_circular(self):
        """Cercle : 4 copies sur 360° autour de (60, 40) ; chaque copie = l'original tourné de 90°, arcs compris."""
        from cam2027.project import patterns

        proj, lib, clone = self.project("Pattern circle")
        op = self.pocket(proj, lib, clone)
        proj.compute()
        base = feed_moves(op.Path)
        pat = patterns.add_pattern(proj, [op], {"Kind": "Circular", "Count": 4, "Centre": (60.0, 40.0, 0.0),
                                                "Angle": 360.0})[0]
        proj.compute()
        moves = feed_moves(pat.Path)
        self.assertEqual(len(moves), 4 * len(base))
        n = len(base)
        for k in range(4):
            a = math.radians(90.0 * k)
            for m0, m in zip(base[::7], moves[k * n:(k + 1) * n:7]):
                x, y = m0[2][0] - 60.0, m0[2][1] - 40.0
                self.assertAlmostEqual(m[2][0], 60.0 + x * math.cos(a) - y * math.sin(a), places=3)
                self.assertAlmostEqual(m[2][1], 40.0 + x * math.sin(a) + y * math.cos(a), places=3)
                self.assertAlmostEqual(m[2][2], m0[2][2], places=4)
                if m0[3] is not None:  # centre d'arc tourné aussi
                    cx, cy = m0[3][0] - 60.0, m0[3][1] - 40.0
                    self.assertAlmostEqual(m[3][0], 60.0 + cx * math.cos(a) - cy * math.sin(a), places=3)
        with self.assertRaises(UserError):
            patterns.add_pattern(proj, [op], {"Kind": "Grid", "Columns": 0, "Rows": 2, "StepX": 10, "StepY": 10})

    def test_minimize_tool_changes(self):
        """Trois opérations (6 mm, 3 mm, 6 mm) en motif : regroupées par outil, un seul changement d'outil."""
        from cam2027.project import patterns

        proj, lib, clone = self.project("Pattern tools")
        a = self.pocket(proj, lib, clone, "A")
        b = self.pocket(proj, lib, clone, "B", tool="3 mm flat end mill", index=1)
        c = self.pocket(proj, lib, clone, "C", index=2)
        self.assertEqual(patterns.tool_changes(proj), 2)
        made = patterns.add_pattern(proj, [a, b, c], {"Kind": "Grid", "Columns": 1, "Rows": 2, "StepX": 0.0,
                                                      "StepY": 40.0})
        self.assertEqual(len(made), 3)
        self.assertEqual([proj.base_operation(o).Label for o in proj.operations()], ["A", "C", "B"])
        self.assertEqual(patterns.tool_changes(proj), 1)
        rep = proj.material_check()
        self.assertEqual(rep["gouge_max"], 0.0, rep)


if __name__ == "__main__":
    unittest.main()
