# SPDX-License-Identifier: LGPL-2.1-or-later
"""[C2] Jour 4, fluidité de l'interface : rendu de la main pendant les calculs, « Arrêter le calcul »,
calculs C++ déplacés dans un processus (résultat identique), dépassement voulu des dogbones, contact exact des
brides, entailles vérifiées en 3D sur toutes les colonnes."""

import math
import os
import tempfile
import time
import types
import unittest

import FreeCAD
import Part

from cam2027.project import operations as opsmod
from cam2027.project import sim

V = FreeCAD.Vector


class _FakeGui(object):
    """``GuiTicker`` hors interface : ``_gui_up`` forcé, ``keep_gui_alive`` compté (instants des appels)."""

    def __enter__(self):
        self.calls = []
        self._gui_up, self._alive = opsmod._gui_up, opsmod.keep_gui_alive
        opsmod._gui_up = lambda: True
        opsmod.keep_gui_alive = lambda: self.calls.append(time.perf_counter())
        return self

    def __exit__(self, *_a):
        opsmod._gui_up, opsmod.keep_gui_alive = self._gui_up, self._alive
        return False


def _python_work(seconds):
    """Calcul en Python pur (aucun appel à ``keep_gui_alive``)."""
    end = time.perf_counter() + seconds
    x = 0
    while time.perf_counter() < end:
        x += sum(i * i for i in range(200))
    return x


class TestGuiTicker(unittest.TestCase):
    """L'horloge rend la main toutes les 0,1 s dans n'importe quel code Python ; « Arrêter » lève l'arrêt."""

    def test_hands_back_at_least_every_quarter_second(self):
        with _FakeGui() as gui:
            t0 = time.perf_counter()
            with opsmod.GuiTicker():
                _python_work(1.2)
            t1 = time.perf_counter()
        stamps = [t0] + gui.calls + [t1]
        worst = max(b - a for a, b in zip(stamps, stamps[1:]))
        self.assertGreaterEqual(len(gui.calls), 8)
        self.assertLess(worst, 0.25)

    def test_no_ticks_without_interface_or_after_the_block(self):
        with opsmod.GuiTicker():  # FreeCADCmd : rien
            self.assertFalse(opsmod.GuiTicker.active())
        with _FakeGui() as gui:
            with opsmod.GuiTicker():
                with opsmod.GuiTicker():  # imbriqué : même horloge
                    _python_work(0.3)
                self.assertTrue(opsmod.GuiTicker.active())
            n = len(gui.calls)
            _python_work(0.4)
            self.assertEqual(len(gui.calls), n)
        self.assertFalse(opsmod.GuiTicker.active())

    def test_stop_raises_in_the_computation_quickly(self):
        with _FakeGui():
            t0 = time.perf_counter()
            with self.assertRaises(opsmod.ComputationStopped):
                with opsmod.GuiTicker():
                    opsmod.GuiTicker.stop()
                    _python_work(5.0)
            self.assertLess(time.perf_counter() - t0, 0.6)
            # l'arrêt ne déborde pas sur la suite
            _python_work(0.5)
        self.assertFalse(opsmod.GuiTicker.active())

    def test_stop_never_raised_while_leaving_the_block(self):
        class Slow(object):
            def __enter__(self):
                return self

            def __exit__(self, *_a):
                _python_work(0.8)  # nettoyage long : protégé
                return False

        with _FakeGui():
            with self.assertRaises(opsmod.ComputationStopped):
                with opsmod.GuiTicker():
                    with Slow():
                        opsmod.GuiTicker.stop()
                        _python_work(3.0)

    def test_stop_hits_again_after_a_swallowed_stop(self):
        """FreeCAD retient l'exception d'une opération qui échoue et passe à la suivante : chacune est arrêtée."""
        hits = 0
        with _FakeGui():
            t0 = time.perf_counter()
            with opsmod.GuiTicker():
                opsmod.GuiTicker.stop()
                for _op in range(4):
                    try:
                        _python_work(5.0)
                    except opsmod.ComputationStopped:
                        hits += 1
            self.assertLess(time.perf_counter() - t0, 2.5)
        self.assertEqual(hits, 4)

    def test_deferred_refresh_runs_once_at_the_end(self):
        seen = []
        fn = lambda: seen.append(1)  # noqa: E731
        self.assertFalse(opsmod.GuiTicker.defer(fn))
        with _FakeGui():
            with opsmod.GuiTicker():
                for _k in range(5):
                    self.assertTrue(opsmod.GuiTicker.defer(fn))
                self.assertEqual(seen, [])
        self.assertEqual(seen, [1])

    def test_stopped_objects_are_not_recomputed_implicitly(self):
        """Opération arrêtée : FreeCAD la garde « à recalculer » et le premier recalcul venu la refaisait en
        entier, sans fenêtre de progression (7 s sur le plateau) ; ``hold_stopped`` l'en retire."""
        class Feature(object):
            runs = 0

            def __init__(self, obj):
                obj.Proxy = self

            def execute(self, obj):
                Feature.runs += 1
                raise opsmod.ComputationStopped()

        doc = FreeCAD.newDocument("C2Hold")
        try:
            obj = doc.addObject("App::FeaturePython", "Op")
            Feature(obj)
            doc.recompute()
            self.assertIn("Invalid", obj.State)
            opsmod.hold_stopped(doc)
            runs = Feature.runs
            doc.recompute()
            self.assertEqual(Feature.runs, runs)
        finally:
            FreeCAD.closeDocument(doc.Name)


class TestOutOfProcess(unittest.TestCase):
    """Calculs C++ d'un seul tenant faits dans un processus : résultat identique au calcul ici."""

    def test_display_mesh_identical(self):
        import numpy as np

        z = sim.ZMap(0.0, 0.0, 120.0, 100.0, 20.0, 0.5)
        X, Y = np.meshgrid(z.xs, z.ys, indexing="ij")
        z.top = np.where(np.hypot(X - 60, Y - 50) < 30, 20.0 - 0.01 * np.hypot(X - 60, Y - 50) ** 2, 20.0)
        z.top[10:30, 10:60] = 12.0
        here = sim.display_mesh(z, 10000, in_process=True)
        there = sim.display_mesh(z, 10000, in_process=False)
        self.assertLess(here.CountFacets, 2 * (z.nx - 1) * (z.ny - 1))  # simplifié
        self.assertEqual(there.CountFacets, here.CountFacets)
        self.assertEqual(there.CountPoints, here.CountPoints)
        self.assertEqual([tuple(p.Vector) for p in there.Points], [tuple(p.Vector) for p in here.Points])
        self.assertEqual(there.Topology[1], here.Topology[1])


class TestDogboneOvercut(unittest.TestCase):
    """Dogbones : l'os dépasse volontairement dans l'angle (r·(1 - 1/√2) = 0,88 mm pour une fraise de 6, 0,75 mm au
    contrôle à 0,5 mm). Le contrôle le comptait comme une entaille ; la zone des os est maintenant exclue des
    entailles et signalée à part, une vraie entaille ailleurs reste vue."""

    @classmethod
    def setUpClass(cls):
        from tests.test_pipeline import make_part

        cls.tmp = tempfile.mkdtemp(prefix="cam2027-c2d-")
        cls.step = os.path.join(cls.tmp, "plate.step")
        make_part(cls.step)
        FreeCAD.ConfigSet("SuppressRecomputeRequiredDialog", "True")

    def _project(self):
        from cam2027.project.project import Project
        from cam2027.tools.library import starter_library

        lib = starter_library()
        proj = Project.create("C2Dog", lib)
        proj.import_model(self.step)
        proj.create_job(proj.model_candidates(), stock={"kind": "box_margins", "xy": 2.0, "z_top": 1.0, "z_bottom": 0.0})
        return proj

    def _add(self, proj, kind, extra=None):
        from cam2027.gui.commands import default_params

        lib = proj.library
        tool = lib.search("6 mm flat end mill 2F")[0]
        asm = lib.assemblies_for_tool(tool.id)[0]
        preset = tool.presets[0]
        models = list(proj.job.Model.Group)
        base = opsmod.auto_geometry(kind, models)
        params = dict(default_params(kind, tool, preset.resolve(tool)), **(extra or {}))
        op, _rec = proj.add_operation(kind, kind, asm.id, preset.id,
                                      base=[(m, []) for m in models] if base is None else base, params=params)
        return op

    def test_bone_moves(self):
        segs = [(False, [0, 0, 5], [10, 0, 5], 1), (False, [10, 0, 5], [11, 1, 5], 2), (False, [11, 1, 5], [10, 0, 5], 3),
                (False, [10, 0, 5], [10, 10, 5], 4), (True, [10, 10, 5], [10, 10, 9], 5),
                (False, [0, 0, 1], [3, 0, 1], 6), (False, [3, 0, 1], [0, 0, 1], 7)]  # 3 mm : plus long que r = 1
        self.assertEqual(sim.bone_moves(segs, 1.0), [((10, 0), (11, 1))])
        z = sim.ZMap(0, 0, 20, 20, 10, 0.5)
        mask = sim.bone_mask(z, [((10.0, 0.0), (11.0, 1.0), 1.0)])
        i, j = int((11.0 - 0.25) / 0.5), int((1.0 - 0.25) / 0.5)
        self.assertTrue(mask[i, j])
        self.assertFalse(mask[int(15 / 0.5), int(5 / 0.5)])

    def test_overcut_not_counted_as_gouge(self):
        proj = self._project()
        op = self._add(proj, "pocket", {"CutMode": "Climb", "OffsetPattern": "Offset", "ClearingPattern": "Offset"})
        proj.compute()
        before = proj.material_check()
        self.assertLessEqual(before["gouge_max"], before["tolerance"])  # sans os : rien
        bone, _ignored = proj.add_dressup(op, "dogbone")
        proj.compute()
        self.assertGreater(bone.Path.Size, op.Path.Size)
        rep = proj.material_check()
        self.assertLessEqual(rep["gouge_max"], rep["tolerance"], rep)  # 0,75 mm compté sur 25562b8
        over = rep["dogbone_overcut"]
        self.assertGreater(over["bones"], 0)
        self.assertGreater(over["max"], 0.3)
        self.assertLess(over["max"], 3.0 * (1.0 - 0.5 ** 0.5) + 0.05)
        from cam2027.gui.commands import material_report_text
        self.assertIn("dogbone", material_report_text(rep))
        proj.close()

    def test_real_gouge_still_seen_with_dogbones(self):
        proj = self._project()
        op = self._add(proj, "pocket", {"CutMode": "Climb", "OffsetPattern": "Offset", "ClearingPattern": "Offset"})
        proj.add_dressup(op, "dogbone")
        # seconde poche agrandie de 0,5 mm (ExtraOffset négatif) : vraie entaille le long des parois, hors des os
        self._add(proj, "pocket", {"CutMode": "Climb", "OffsetPattern": "Offset", "ClearingPattern": "Offset",
                                   "ExtraOffset": -0.5})
        proj.compute()
        rep = proj.material_check()
        self.assertGreater(rep["gouge_max"], 0.4, rep)
        proj.close()


def _old_clamp_contacts(p0, p1, envelope, boxes, step=1.0):
    """``clamp_contacts`` de 25562b8 (segment échantillonné tous les 1 mm), pour montrer ce qu'il manquait."""
    length = math.dist(p0, p1)
    n = max(1, int(math.ceil(length / step)))
    hits = {}
    for k in range(n + 1):
        q = [p0[c] + (p1[c] - p0[c]) * k / n for c in range(3)]
        for name, bb in boxes:
            if name in hits:
                continue
            dist = math.hypot(max(bb.XMin - q[0], 0.0, q[0] - bb.XMax), max(bb.YMin - q[1], 0.0, q[1] - bb.YMax))
            for lo, hi, r, role in envelope.parts:
                if q[2] + lo < bb.ZMax - 1e-6 and q[2] + hi > bb.ZMin + 1e-6 and dist < r - 1e-6:
                    hits[name] = (name, role, r - dist, tuple(q))
                    break
    return list(hits.values())


def _dense_clamp_contacts(p0, p1, envelope, boxes, step=0.0005):
    """Référence : segment échantillonné tous les 0,5 µm ; par bride, le tronçon qui la touche le premier (à
    égalité, le plus bas) et sa plus grande pénétration."""
    import numpy as np

    n = max(1, int(math.ceil(math.dist(p0, p1) / step)))
    t = np.linspace(0.0, 1.0, n + 1)
    q = np.array(p0, float)[None, :] + (np.array(p1, float) - np.array(p0, float))[None, :] * t[:, None]
    out = []
    for name, bb in boxes:
        dist = np.hypot(np.maximum.reduce([bb.XMin - q[:, 0], np.zeros(len(q)), q[:, 0] - bb.XMax]),
                        np.maximum.reduce([bb.YMin - q[:, 1], np.zeros(len(q)), q[:, 1] - bb.YMax]))
        first = None
        for lo, hi, r, role in envelope.parts:
            ok = (q[:, 2] + lo < bb.ZMax - 1e-6) & (q[:, 2] + hi > bb.ZMin + 1e-6) & (dist < r - 1e-6)
            if ok.any():
                k = int(np.argmax(ok))
                if first is None or k < first[0]:
                    first = (k, (name, role, float((r - dist[ok]).max())))
        if first is not None:
            out.append(first[1])
    return out


class TestClampContacts(unittest.TestCase):
    """Brides : contact exact segment / boîte (avant : échantillonnage tous les 1 mm)."""

    ENV = sim.Envelope([(0.0, 5.0, 3.0, "cutter"), (5.0, 25.0, 3.0, "shank"), (25.0, 60.0, 12.0, "holder")], True)
    BOX = FreeCAD.BoundBox(0, 0, 0, 30, 20, 12)

    def test_ramp_leaving_the_clamp_height(self):
        """Plongée en biais qui s'éloigne de la bride : la fraise n'est à sa hauteur et à moins de son rayon que
        sur 0,5 mm du segment, entre deux points de l'échantillonnage à 1 mm."""
        env = sim.Envelope([(0.0, 5.0, 3.0, "cutter")], False)
        p0, p1 = (-2.5, 10.0, 13.0), (-12.5, 10.0, -17.0)  # sous Z 12 après x = -2,83, à moins de 3 mm avant x = -3
        old = _old_clamp_contacts(p0, p1, env, [("Clamp", self.BOX)])
        new = sim.clamp_contacts(p0, p1, env, [("Clamp", self.BOX)])
        ref = _dense_clamp_contacts(p0, p1, env, [("Clamp", self.BOX)])
        self.assertEqual(old, [])  # manqué sur 25562b8
        self.assertEqual([(h[0], h[1]) for h in new], [("Clamp", "cutter")])
        self.assertAlmostEqual(new[0][2], ref[0][2], delta=5e-4)  # pas de la référence : 0,16 µm en x
        self.assertGreater(new[0][2], 0.15)

    def test_matches_a_dense_sampling(self):
        import random

        rnd = random.Random(2027)
        boxes = [("A", self.BOX), ("B", FreeCAD.BoundBox(45, -10, 0, 55, 30, 8))]
        for _k in range(1000):
            p0 = (rnd.uniform(-20, 70), rnd.uniform(-25, 45), rnd.uniform(-5, 40))
            p1 = tuple(c + rnd.uniform(-12, 12) for c in p0)
            new = {h[0]: h for h in sim.clamp_contacts(p0, p1, self.ENV, boxes)}
            ref = {h[0]: h for h in _dense_clamp_contacts(p0, p1, self.ENV, boxes)}
            for name in set(new) | set(ref):
                if name not in ref:  # contact plus court que l'échantillonnage dense
                    self.assertLess(new[name][2], 1e-3, (p0, p1, new[name]))
                    continue
                self.assertIn(name, new, (p0, p1, ref[name]))
                self.assertEqual(new[name][1], ref[name][1], (p0, p1))
                self.assertGreaterEqual(new[name][2], ref[name][2] - 1e-9)
                self.assertLess(new[name][2], ref[name][2] + 1e-3)
                # la position donnée est bien un point du segment où la pénétration est atteinte
                at = new[name][3]
                lo, hi, r, _role = next(p for p in self.ENV.parts if p[3] == new[name][1])
                bb = dict(boxes)[name]
                d = math.hypot(max(bb.XMin - at[0], 0.0, at[0] - bb.XMax), max(bb.YMin - at[1], 0.0, at[1] - bb.YMax))
                self.assertAlmostEqual(r - d, new[name][2], delta=1e-6)

    def test_speed(self):
        """Pas plus lent que l'échantillonnage à 1 mm sur des mouvements courts (cas des parcours réels)."""
        import random

        rnd = random.Random(7)
        segs = []
        for _k in range(3000):
            p0 = (rnd.uniform(-20, 70), rnd.uniform(-25, 45), rnd.uniform(-5, 20))
            segs.append((p0, tuple(c + rnd.uniform(-1.5, 1.5) for c in p0)))
        boxes = [("A", self.BOX), ("B", FreeCAD.BoundBox(45, -10, 0, 55, 30, 8))]
        times = {}
        for name, fn in (("old", _old_clamp_contacts), ("new", sim.clamp_contacts)) * 2:
            t0 = time.perf_counter()
            for p0, p1 in segs:
                fn(p0, p1, self.ENV, boxes)
            times[name] = min(times.get(name, 1e9), time.perf_counter() - t0)
        self.assertLess(times["new"], 1.1 * times["old"], times)


if __name__ == "__main__":
    unittest.main()
