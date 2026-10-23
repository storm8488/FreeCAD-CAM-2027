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


if __name__ == "__main__":
    unittest.main()
