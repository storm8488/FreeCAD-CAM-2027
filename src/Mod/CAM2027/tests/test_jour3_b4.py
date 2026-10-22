# SPDX-License-Identifier: LGPL-2.1-or-later
"""Flux B4 du jour 3 : défauts des fonctions de la nuit 2, chacun reproduit par un test avant sa correction."""

import math
import unittest

import FreeCAD
import Part

from cam2027.project.machine import MachineProfile
from cam2027.project.project import Project
from cam2027.tools.library import starter_library

V = FreeCAD.Vector


def machine(**kw):
    return MachineProfile("test", controller="grbl", post_processor="grbl",
                          post_processor_args="--no-show-editor --precision=3", **kw)


class _Ops(object):
    """Projet minimal pour ``timing.estimate`` : des objets Path et un profil machine."""

    def __init__(self, ops, profile):
        self._ops, self.machine = ops, profile

    def operations(self):
        return self._ops


class TestTiming(unittest.TestCase):
    def tearDown(self):
        for name in list(FreeCAD.listDocuments()):
            FreeCAD.closeDocument(name)

    def test_inverse_time_moves(self):
        """G93 (rotatif continu, gravure enroulée) : F = 1 / durée en minutes. Avant : avance lue comme une vitesse
        en mm/s sur la seule longueur X Y Z, rotation pure comptée 0 s."""
        import Path
        from cam2027.project import timing, wrap

        doc = FreeCAD.newDocument("B4Timing")
        op = doc.addObject("Path::Feature", "Rotary")
        # 2 s de rotation pure (F 30 / min), puis 1 s pour 10 mm le long de X avec rotation (F 60 / min)
        lines = ["G0 X0 Y0 Z5 A0", "G93", "G1 X0 A90 Z5 F30", "G1 X10 A180 Z5 F60", "G94",
                 "G1 X20 F600"]  # retour en G94 : 10 mm à 600 mm/min (1 s + accélération)
        path = Path.Path()
        path.setFromGCode("\n".join(wrap.path_gcode(lines)))
        op.Path = path
        est = timing.estimate(_Ops([op], machine()))
        accel = est["acceleration"]
        v = 10.0
        self.assertAlmostEqual(est["total"], 2.0 + 1.0 + 10.0 / v + v / accel, places=3)
        self.assertAlmostEqual(est["without_accel"], 2.0 + 1.0 + 1.0, places=3)


class TestKeepOutPattern(unittest.TestCase):
    def tearDown(self):
        for name in list(FreeCAD.listDocuments()):
            FreeCAD.closeDocument(name)

    def test_pattern_copies_hop_over_zone(self):
        """Poche sur deux fonds (rapide de l'un à l'autre), copiée 60 mm plus loin : le rapide de la copie traverse une
        zone interdite que celui de l'original ne touche pas. Il doit passer au-dessus comme ceux des opérations.
        Avant : le motif recopiait le parcours de l'original sans la correction des rapides."""
        import os
        import tempfile
        from cam2027.project import keepout, patterns, sim

        path = os.path.join(tempfile.mkdtemp(prefix="cam2027-b4k-"), "plate.step")
        plate = Part.makeBox(170, 40, 10).cut(Part.makeBox(20, 14, 4, V(10, 12, 6)))
        plate.cut(Part.makeBox(20, 14, 4, V(80, 12, 6))).exportStep(path)
        lib = starter_library()
        proj = Project.create("B4 keep-out pattern", lib, machine())
        part = proj.import_model(path, label="Plate").objects[0]
        proj.create_job([part], stock={"kind": "box_margins", "xy": 2.0, "z_top": 0.0, "z_bottom": 0.0})
        clone = proj.job.Model.Group[0]
        floor = ["Face%d" % i for i, f in enumerate(clone.Shape.Faces, 1)
                 if f.Surface.__class__.__name__ == "Plane" and abs(f.BoundBox.ZMax - 6.0) < 1e-6
                 and abs(f.BoundBox.ZMin - 6.0) < 1e-6]
        t = lib.search("6 mm flat end mill")[0]
        op, _r = proj.add_operation("pocket", "Pocket", lib.assemblies_for_tool(t.id)[0].id, t.presets[0].id,
                                    base=[(clone, floor)], params={"StepDown": 2.0})
        self.assertEqual(len(floor), 2)
        zone = keepout.add_zone(proj.doc, 110.0, -20.0, 114.0, 60.0, 30.0, 10.0, label="Zone")
        patterns.add_pattern(proj, [op], {"Kind": "Grid", "Columns": 2, "Rows": 1, "StepX": 60.0, "StepY": 0.0})
        proj.compute()
        boxes = [(zone.Label, zone.Shape.BoundBox)]
        crossing = []
        pos = None
        for obj in proj.operations():
            segs, pos = sim.path_segments(obj.Path.Commands, pos)
            crossing += [(p0, p1) for rapid, p0, p1 in segs
                         if rapid and keepout.blocking_top(p0, p1, boxes, 3.0, 0.0) is not None]
        self.assertEqual(crossing, [])
        self.assertEqual(keepout.issues(proj), [])
        # mouvements de coupe inchangés : 2 fois ceux de l'original
        cuts = [c for c in proj.operations()[0].Path.Commands if c.Name in ("G1", "G2", "G3")]
        self.assertEqual(len(cuts), 2 * len([c for c in op.Path.Commands if c.Name in ("G1", "G2", "G3")]))


    def test_trimmed_links_hop_over_zone(self):
        """Contour limité à « dehors » d'un coin : la liaison recalculée d'un bout gardé à l'autre (hauteur de
        dégagement) passait à travers une zone interdite posée sur le coin retiré. Elle passe au-dessus maintenant."""
        import os
        import tempfile
        from cam2027.project import keepout, sim, trim

        path = os.path.join(tempfile.mkdtemp(prefix="cam2027-b4t-"), "plate.step")
        Part.makeBox(100, 40, 10).exportStep(path)
        lib = starter_library()
        proj = Project.create("B4 keep-out trim", lib, machine())
        part = proj.import_model(path, label="Plate").objects[0]
        proj.create_job([part], stock={"kind": "box_margins", "xy": 4.0, "z_top": 1.0, "z_bottom": 0.0})
        clone = proj.job.Model.Group[0]
        t = lib.search("6 mm flat end mill")[0]
        op, _r = proj.add_operation("profile", "Contour", lib.assemblies_for_tool(t.id)[0].id, t.presets[0].id,
                                    base=[(clone, [])], params={"FinalDepth": 5.0, "StepDown": 5.0, "Side": "Outside"})
        # coin avant gauche retiré : liaison en diagonale de (30, -3) à (-3, 10), au-dessus d'une zone posée sur le coin
        # de la pièce, hors de portée des coupes (fraise à X -3 / Y -3, zone élargie du rayon : X, Y >= -1)
        zone = keepout.add_zone(proj.doc, 2.0, 2.0, 15.0, 6.0, 30.0, 0.0, label="Zone")
        dress = trim.set_limit(proj, op, trim.rectangle(-50, -50, 30, 10), inside=False, source="rectangle")
        proj.compute()
        boxes = [(zone.Label, zone.Shape.BoundBox)]
        segs, _pos = sim.path_segments(dress.Path.Commands)
        self.assertTrue(any(not rapid for rapid, _a, _b in segs))
        crossing = [(p0, p1) for rapid, p0, p1 in segs if rapid and keepout.blocking_top(p0, p1, boxes, 3.0, 0.0) is not None]
        self.assertEqual(crossing, [])
        self.assertEqual(keepout.issues(proj), [])


def run_probe(lines, start, boxes, tip):
    """GRBL simplifié : exécute un programme de palpage depuis ``start`` (position machine de la pointe : centre en
    XY, bas en Z) contre des boîtes pleines ``(xmin, ymin, zmin, xmax, ymax, zmax)`` ; retourne l'origine (repère
    G54 ou G92, en coordonnées machine). Chaque G38.2 doit toucher (sinon alarme : exception)."""
    import re

    r = tip / 2.0
    m = list(start)
    origin = [0.0, 0.0, 0.0]
    relative = False
    for raw in lines:
        line = re.sub(r"\(.*?\)", "", raw).strip().upper()
        words = dict((w[0], float(w[1:])) for w in line.split()[1:] if w[0] in "XYZLP")
        g = line.split()[0] if line else ""
        if g in ("G90", "G91"):
            relative = g == "G91"
            continue
        if g in ("G10", "G92"):
            for k, axis in enumerate("XYZ"):
                if axis in words:
                    origin[k] = m[k] - words[axis]
            continue
        if g not in ("G0", "G38.2"):
            continue
        target = list(m)
        for k, axis in enumerate("XYZ"):
            if axis in words:
                target[k] = m[k] + words[axis] if relative else origin[k] + words[axis]
        if g == "G0":
            m = target
            continue
        moving = [k for k in range(3) if abs(target[k] - m[k]) > 1e-9]
        assert len(moving) == 1, line
        k = moving[0]
        d = 1.0 if target[k] > m[k] else -1.0
        hits = []
        for b in boxes:
            lo, hi = b[:3], b[3:]
            if k == 2:  # descente : le bas de la pointe touche le dessus d'une boîte sous son centre
                if d < 0 and lo[0] <= m[0] <= hi[0] and lo[1] <= m[1] <= hi[1] and hi[2] <= m[2] + 1e-9:
                    hits.append(hi[2])
                continue
            other = 1 - k
            if lo[other] <= m[other] <= hi[other] and lo[2] < m[2] < hi[2]:
                face = lo[k] - r if d > 0 else hi[k] + r
                if (face - m[k]) * d >= -1e-9:
                    hits.append(face)
        reach = [h for h in hits if (h - target[k]) * d <= 1e-9]
        if not reach:
            raise AssertionError("probe alarm (no contact): %s" % line)
        m[k] = min(reach, key=lambda h: abs(h - m[k]))
    return origin


class TestProbe(unittest.TestCase):
    TIP = 2.0

    def profile(self):
        return machine(probe={"present": True, "tip_diameter_mm": self.TIP, "feed_mm_min": 100.0, "travel_mm": 25.0,
                              "plate_thickness_mm": 0.0, "tool_number": 99})

    def test_outer_corner_origin(self):
        """Référence : coin extérieur avant gauche d'une pièce (X 100 Y 50, dessus Z -20) palpé depuis 10 mm dedans."""
        from cam2027.project import probe

        piece = (100.0, 50.0, -40.0, 180.0, 110.0, -20.0)
        lines = probe.probe_gcode(self.profile(), "corner", corner="front-left")
        origin = run_probe(lines, (110.0, 60.0, -15.0), [piece], self.TIP)
        for got, want in zip(origin, (100.0, 50.0, -20.0)):
            self.assertAlmostEqual(got, want, places=6)

    def test_inner_corner_origin(self):
        """Coin intérieur (poche, butée de montage) : chaque coin d'une poche 80 x 60 palpé de l'intérieur donne le coin
        exact en X et Y (Z non touché) ; le palpeur revient à son point de départ."""
        from cam2027.project import probe

        x0, y0, x1, y1 = 100.0, 50.0, 180.0, 110.0  # poche, parois de Z -40 à -20
        walls = [(x0 - 30, y0 - 30, -40, x0, y1 + 30, -20), (x1, y0 - 30, -40, x1 + 30, y1 + 30, -20),
                 (x0 - 30, y0 - 30, -40, x1 + 30, y0, -20), (x0 - 30, y1, -40, x1 + 30, y1 + 30, -20)]
        for corner, (sx, sy) in probe.CORNERS.items():
            cx, cy = (x0 if sx < 0 else x1), (y0 if sy < 0 else y1)
            start = (cx - sx * 10.0, cy - sy * 10.0, -30.0)
            lines = probe.probe_gcode(self.profile(), "inner_corner", corner=corner, wcs="G55")
            self.assertTrue(any(l.startswith("G10 L20 P2 X") for l in lines), lines)
            self.assertFalse(any(" Z" in l for l in lines if l.startswith(("G38", "G10"))), lines)
            origin = run_probe(lines, start, walls, self.TIP)
            self.assertAlmostEqual(origin[0], cx, places=6, msg=corner)
            self.assertAlmostEqual(origin[1], cy, places=6, msg=corner)
            # G92 : même origine
            lines = probe.probe_gcode(self.profile(), "inner_corner", corner=corner, offset_mode="G92")
            origin = run_probe(lines, start, walls, self.TIP)
            self.assertAlmostEqual(origin[0], cx, places=6, msg=corner)
            self.assertAlmostEqual(origin[1], cy, places=6, msg=corner)
        # analyse de l'export : course de recherche dans la course du palpeur, aucune erreur
        from cam2027.project import probe as p

        a = p.analyze("\n".join(lines))
        self.assertEqual(a["count"], 2)
        self.assertEqual(p.verify({"probe": a}, self.profile()), [])


if __name__ == "__main__":
    unittest.main()
