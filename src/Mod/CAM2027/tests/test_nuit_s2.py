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


HOLES = {3.0: [(10.0, 10.0), (10.0, 50.0)], 5.0: [(30.0, 10.0), (30.0, 50.0)], 8.0: [(55.0, 15.0), (55.0, 45.0)]}


def make_hole_plate(path):
    """Plaque 80 x 60 x 10 : 2 trous de 3 débouchants, 2 trous de 5 borgnes (6 mm), 2 trous de 8 débouchants
    avec chanfrein d'entrée de 1 mm à 90°."""
    import Part

    V = FreeCAD.Vector
    shape = Part.makeBox(80, 60, 10)
    for x, y in HOLES[3.0]:
        shape = shape.cut(Part.makeCylinder(1.5, 10, V(x, y, 0)))
    for x, y in HOLES[5.0]:
        shape = shape.cut(Part.makeCylinder(2.5, 6, V(x, y, 4)))
    for x, y in HOLES[8.0]:
        shape = shape.cut(Part.makeCylinder(4.0, 10, V(x, y, 0)))
        shape = shape.cut(Part.makeCone(4.0, 5.0, 1.0, V(x, y, 9)))
    shape = shape.removeSplitter()
    shape.exportStep(path)
    return shape


def drill_library():
    """Bibliothèque de démarrage + forets de 5 et 8 mm."""
    from cam2027.tools.model import ToolDefinition, ToolAssembly, CuttingPreset

    lib = starter_library()
    holder = next(iter(lib.holders.values()))
    for d in (5.0, 8.0):
        t = lib.add_tool(ToolDefinition("%g mm drill" % d, "drill",
                                        dict(diameter=d, shank_diameter=d, overall_length=80, flute_length=40,
                                             tip_included_angle_deg=118), flute_count=2))
        t.add_preset(CuttingPreset("Wood drilling", usage="drilling", material="wood", spindle_rpm=8000,
                                   feed_mm_min=300, plunge_feed_mm_min=150, axial_engagement_mm=d,
                                   radial_engagement_mm=d))
        lib.add_assembly(ToolAssembly("T%d %s" % (20 + int(d), t.name), t.id, holder.id, stickout=50,
                                      output={"tool_number": 20 + int(d), "manual_tool_change": True}))
    return lib


class TestHoles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="cam2027-s2h-")
        cls.step = os.path.join(cls.tmp, "holes.step")
        make_hole_plate(cls.step)

    def project(self, name, lib=None):
        lib = lib or drill_library()
        proj = Project.create(name, lib, machine())
        part = proj.import_model(self.step, label="Holes").objects[0]
        job = proj.create_job([part], stock={"kind": "box_margins", "xy": 2.0, "z_top": 0.0, "z_bottom": 0.0})
        self.addCleanup(proj.close)
        return proj, job.Model.Group[0]

    def test_recognition(self):
        """6 trous reconnus : diamètres, débouchants / borgnes, profondeur, chanfrein de 10 mm à 90°."""
        from cam2027.project import holes

        proj, clone = self.project("Holes recognition")
        found = holes.find_holes(clone)
        self.assertEqual(len(found), 6, found)
        by_d = {}
        for h in found:
            by_d.setdefault(round(h.diameter, 2), []).append(h)
        self.assertEqual(sorted(by_d), [3.0, 5.0, 8.0])
        for d, pts in HOLES.items():
            got = sorted((round(h.x, 3), round(h.y, 3)) for h in by_d[d])
            self.assertEqual(got, sorted(pts))
        self.assertTrue(all(h.through for h in by_d[3.0] + by_d[8.0]))
        self.assertTrue(all(not h.through and abs(h.depth - 6.0) < 1e-6 for h in by_d[5.0]))
        for h in by_d[8.0]:
            self.assertAlmostEqual(h.chamfer_diameter, 10.0, places=3)
            self.assertAlmostEqual(h.chamfer_angle, 90.0, places=3)
            self.assertAlmostEqual(h.top, 10.0, places=6)
        self.assertEqual(len(holes.groups(found)), 3)

    def test_sequence_and_material(self):
        """Pointage, perçage, chanfrein : une opération par étape et par diamètre, dans cet ordre ; trous au bon
        diamètre et à la bonne profondeur dans la carte de hauteur, chanfrein à 45°, aucune entaille."""
        from cam2027.project import holes

        proj, clone = self.project("Holes sequence")
        steps, notes = holes.plan(proj.library, holes.find_holes(clone))
        self.assertEqual(notes, [])
        self.assertEqual([(s["step"], round(s["model"].diameter, 1)) for s in steps],
                         [("spot", 3.0), ("spot", 5.0), ("spot", 8.0), ("drill", 3.0), ("drill", 5.0), ("drill", 8.0),
                          ("chamfer", 8.0)])
        self.assertEqual([round(s["tool"].geometry.diameter, 1) for s in steps if s["step"] == "drill"],
                         [3.0, 5.0, 8.0])
        ops = holes.apply_plan(proj, clone, steps)
        self.assertEqual(len(ops), 7)
        results = proj.compute()
        self.assertTrue(all(r["valid"] and r["commands"] > 3 for r in results), results)
        rep = proj.material_check()
        self.assertEqual(rep["gouge_max"], 0.0, rep)
        self.assertEqual(rep["rapid_hits"], 0, rep)
        z = proj.last_zmap
        for d, pts in HOLES.items():
            r = d / 2.0
            for x, y in pts:
                centre = zmap_at(z, x, y)
                if d == 5.0:
                    # pointe du foret (118°) au fond du trou borgne : cône de pointe au centre de la cellule
                    i, j = int((x - z.x0) / z.res), int((y - z.y0) / z.res)
                    dist = math.hypot(float(z.xs[i]) - x, float(z.ys[j]) - y)
                    self.assertAlmostEqual(centre, 4.0 + dist / math.tan(math.radians(59.0)), delta=0.05)
                else:
                    self.assertLessEqual(centre, 0.0)  # débouchant
                    # pleine largeur jusqu'au fond : à 0,3 mm de la paroi, sous la pièce
                    self.assertLessEqual(zmap_at(z, x + r - 0.3, y), 0.0)
                # matière intacte juste hors du trou (et de son chanfrein)
                outside = r + (1.0 if d == 8.0 else 0.0) + 0.4
                self.assertAlmostEqual(zmap_at(z, x + outside, y), 10.0, delta=0.02)
            if d == 8.0:  # chanfrein : 45° entre le rayon 4 et 5 (z = 10 - (5 - r) au centre de la cellule)
                x, y = pts[0]
                for px in (x + 4.3, x + 4.6, x - 4.4):
                    i, j = int((px - z.x0) / z.res), int((y - z.y0) / z.res)
                    dist = math.hypot(float(z.xs[i]) - x, float(z.ys[j]) - y)
                    self.assertAlmostEqual(zmap_at(z, px, y), 10.0 - (5.0 - dist), delta=0.05)

    def test_peck_bore_and_notes(self):
        """Débourrage au-delà de 3 D ; sans foret : alésage hélicoïdal à la plus grosse fraise qui passe ; sans
        foret ni fraise : trous laissés de côté, signalés."""
        from cam2027.project import holes

        proj, clone = self.project("Holes peck", lib=starter_library())
        steps, notes = holes.plan(proj.library, holes.find_holes(clone))
        drills = {round(s["model"].diameter, 1): s for s in steps if s["step"] == "drill"}
        self.assertTrue(drills[3.0]["params"].get("PeckEnabled"))  # 10 mm > 3 x 3 mm
        self.assertEqual(drills[8.0]["kind"], "helix")
        self.assertAlmostEqual(drills[8.0]["tool"].geometry.diameter, 6.0)
        self.assertEqual(drills[5.0]["kind"], "helix")  # pas de foret de 5 : fraise de 3
        self.assertAlmostEqual(drills[5.0]["tool"].geometry.diameter, 3.0)
        self.assertEqual(notes, [])
        lib = starter_library()
        for t in [t for t in lib.tools.values() if t.tool_type in ("drill", "endmill")]:
            for a in lib.assemblies_for_tool(t.id):
                lib.remove_assembly(a.id)
        steps2, notes2 = holes.plan(lib, holes.find_holes(clone))
        self.assertEqual(steps2, [])
        self.assertEqual(len(notes2), 3)

    def test_cycles_expanded(self):
        """Cycles G81 / G83 traduits pour la simulation : plan R, fond, retrait G98 / G99."""
        import Path
        from cam2027.project import holes

        cmds = [Path.Command("G0", {"Z": 15.0}), Path.Command("G98"),
                Path.Command("G81", {"X": 5.0, "Y": 6.0, "Z": -2.0, "R": 12.0, "F": 100.0}),
                Path.Command("G99"), Path.Command("G83", {"X": 9.0, "Y": 6.0, "Z": -3.0, "R": 12.0, "Q": 1.0}),
                Path.Command("G80")]
        out = [(c.Name, dict(c.Parameters)) for c in holes.expand_cycles(cmds)]
        moves = [m for m in out if m[0] in ("G0", "G1")]
        self.assertEqual(moves[1:5], [("G0", {"X": 5.0, "Y": 6.0}), ("G0", {"Z": 12.0}), ("G1", {"Z": -2.0}),
                                      ("G0", {"Z": 15.0})])
        self.assertEqual(moves[5:9], [("G0", {"X": 9.0, "Y": 6.0}), ("G0", {"Z": 12.0}), ("G1", {"Z": -3.0}),
                                      ("G0", {"Z": 12.0})])


PROBE = {"present": True, "tip_diameter_mm": 2.0, "plate_thickness_mm": 0.0, "feed_mm_min": 100.0, "travel_mm": 25.0}

CORNER_FL = ["(CAM2027 probe origin: corner front-left)", "M5", "G21", "G90", "G54", "G91",
             "G38.2 Z-25 F100", "G10 L20 P1 Z0", "G0 Z2",
             "G0 X-16", "G0 Z-5", "G38.2 X11 F100", "G10 L20 P1 X-1", "G0 X-5", "G0 Z5",
             "G90", "G0 X10", "G91",
             "G0 Y-16", "G0 Z-5", "G38.2 Y11 F100", "G10 L20 P1 Y-1", "G0 Y-5", "G0 Z5",
             "G90", "G0 X0 Y0"]


def gcode_words(line):
    """Mots d'une ligne de G-code normalisés (nombres en float, sans commentaire) ; None si rien."""
    import re

    line = re.sub(r"\(.*?\)", "", line.split(";")[0]).strip().upper()
    words = re.findall(r"([A-Z])\s*([-+]?\d*\.?\d+)", line)
    if not words:
        return None
    out = []
    for letter, n in words:
        if letter == "G":
            out.append((letter, n.rstrip("0").rstrip(".") if "." in n else str(int(n))))
        else:
            out.append((letter, float(n)))
    return tuple(out)


class TestProbe(unittest.TestCase):
    def test_gcode_line_by_line(self):
        """Coin avant gauche, Z de surface, centre de trou, G92 : G-code attendu ligne à ligne."""
        from cam2027.project import probe

        m = machine(probe=dict(PROBE))
        self.assertEqual(probe.probe_gcode(m, "corner"), CORNER_FL)
        self.assertEqual(probe.probe_gcode(m, "z"), ["(CAM2027 probe origin: z)", "M5", "G21", "G90", "G54", "G91",
                                                     "G38.2 Z-25 F100", "G10 L20 P1 Z0", "G0 Z2", "G90"])
        back_right = probe.probe_gcode(m, "corner", corner="back-right", wcs="G55")
        self.assertIn("G0 X16", back_right)
        self.assertIn("G38.2 X-11 F100", back_right)
        self.assertIn("G10 L20 P2 X1", back_right)
        self.assertIn("G10 L20 P2 Y1", back_right)
        hole = probe.probe_gcode(m, "hole", hole_diameter=8.0, offset_mode="G92")
        self.assertEqual(hole[5:], ["G91", "G38.2 X9 F100", "G92 X3", "G90", "G0 X0",
                                    "G91", "G38.2 Y9 F100", "G92 Y3", "G90", "G0 X0 Y0"])
        plate = machine(probe=dict(PROBE, plate_thickness_mm=19.6))
        self.assertIn("G10 L20 P1 Z19.6", probe.probe_gcode(plate, "z"))
        with self.assertRaises(UserError):
            probe.probe_gcode(machine(), "z")  # profil sans palpeur
        with self.assertRaises(UserError):
            probe.probe_gcode(machine(probe={"present": True}), "corner")  # pointe inconnue
        with self.assertRaises(UserError):
            probe.probe_gcode(m, "hole", hole_diameter=1.5)

    def test_verify(self):
        """export.verify : palpage refusé sans palpeur, broche en marche, sans avance, G10 incomplet."""
        from cam2027.project import export as exportmod, probe

        m = machine(probe=dict(PROBE))
        text = "\n".join(probe.probe_gcode(m, "corner"))
        issues = exportmod.verify(exportmod.analyze_gcode(text), m)
        self.assertEqual([i for i in issues if "prob" in i[1] or "G10" in i[1]], [], issues)
        errors = [i[1] for i in exportmod.verify(exportmod.analyze_gcode(text), machine()) if i[0] == "error"]
        self.assertTrue(any("has no probe" in e for e in errors), errors)
        bad = "G21\nG54\nM3 S10000\nG91\nG38.2 Z-5\nG10 L20 Z0\n"
        errors = [i[1] for i in exportmod.verify(exportmod.analyze_gcode(bad), m) if i[0] == "error"]
        self.assertTrue(any("spindle running" in e for e in errors), errors)
        self.assertTrue(any("without a feed rate" in e for e in errors), errors)
        self.assertTrue(any("G10 line" in e for e in errors), errors)


class TestProbeProject(_PlateCase):
    def test_probe_operation_exported(self):
        """Palpage du coin en tête du programme : G-code exporté vérifié ligne à ligne, aucune erreur de
        contrôle, pas simulé comme une coupe ; export refusé sur un profil sans palpeur."""
        from cam2027.project import export as exportmod, probe

        proj, lib, clone = self.project("Probe", probe=dict(PROBE))
        asm, pre = self.tool(lib)
        op, _rec = proj.add_operation("profile", "Contour", asm, pre, base=[(clone, [])],
                                      params={"FinalDepth": 0.0, "StepDown": 5.0})
        pop = probe.add_probe(proj, "corner")
        self.assertTrue(probe.is_probe_op(pop))
        self.assertEqual([o.Name for o in proj.operations()], [pop.Name, op.Name])
        proj.compute()
        text = "\n".join(g for _n, g in exportmod.postprocess(proj.job))
        lines = text.splitlines()
        start = next(i for i, l in enumerate(lines) if l.startswith("(Begin operation: %s" % pop.Label))
        end = next(i for i, l in enumerate(lines) if i > start and l.startswith("(Begin operation:"))
        got = [w for w in (gcode_words(l) for l in lines[start:end]) if w and w[0][0] == "G" and w[0][1] in
               ("0", "10", "38.2", "90", "91")]
        expected = [gcode_words(l) for l in CORNER_FL if l.startswith(("G0", "G10", "G38.2", "G90", "G91"))]
        # le postprocesseur réordonne les mots (« G10 Z0 L20 P1 ») : même commande, mêmes mots
        norm = lambda ws: [(w[0], tuple(sorted(w[1:]))) for w in ws]
        self.assertEqual(norm(got), norm(expected), "\n".join(lines[start:end]))
        # broche arrêtée pendant le palpage : aucun M3 avant la fin du palpage
        self.assertFalse(any(w and ("M", 3.0) in w for w in (gcode_words(l) for l in lines[:end])))
        issues = exportmod.verify(exportmod.analyze_gcode(text), proj.machine)
        self.assertEqual([i for i in issues if i[0] == "error"], [], issues)
        rep = proj.material_check()
        self.assertEqual(rep["simulated"], [op.Label])
        self.assertEqual([s[0] for s in rep["skipped"]], [pop.Label])
        self.assertEqual(rep["gouge_max"], 0.0, rep)
        # même programme, profil sans palpeur : refusé
        errors = [i[1] for i in exportmod.verify(exportmod.analyze_gcode(text), machine()) if i[0] == "error"]
        self.assertTrue(any("has no probe" in e for e in errors), errors)


if __name__ == "__main__":
    unittest.main()
