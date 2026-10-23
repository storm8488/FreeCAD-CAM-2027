# SPDX-License-Identifier: LGPL-2.1-or-later
"""Scénarios d'interface du flux C2 (jour 4 : fluidité de l'interface), appelés par ``gui_scenarios.py``.

- **Sonde d'horloge Qt** : une horloge de 50 ms tourne pendant chaque commande ; un écart entre deux tops est une
  durée pendant laquelle l'interface n'a traité aucun événement. Au-delà de ``FREEZE_S`` : ``PROBLEM``, sauf dans
  un appel C++ documenté (``KNOWN_CPP``, reconnu par la pile du fil principal). Active dans les scénarios C2, et
  pour *toutes* les commandes de la suite avec ``CAM2027_C2_PROBE=1`` ; piles au rapport avec
  ``CAM2027_C2_STACKS=1``.
- ``c2-heavy`` : pièce lourde (plateau ``bitTray3030+v7.stl`` s'il existe, ``CAM2027_C2_PART`` pour une autre,
  sinon plateau synthétique à 77 alvéoles) : ajout d'une poche et d'un contour, contrôle matière, export.
- ``c2-stop`` : « Arrêter le calcul » cliqué pendant le recalcul puis pendant le contrôle matière : la commande
  rend la main vite, avec le message d'arrêt, sans rapport.
- ``c2-nest``, ``c2-rotary``, ``c2-inlay``, ``c2-holes`` : imbrication, rotatif, incrustation, perçage (scénarios
  existants) sous la sonde.
"""

import os
import time

import FreeCAD
import FreeCADGui
from PySide import QtCore, QtWidgets

G = None  # module gui_scenarios (outils du pilote)

#: pause de l'interface au-delà de laquelle une commande est signalée (le but est 0,25 s)
FREEZE_S = 0.5
#: délai maximal entre le clic sur « Arrêter » et le retour de la commande
STOP_S = 2.0
DEFAULT_PART = r"C:\Users\damou\Downloads\bitTray3030+v7.stl"
#: appels C++ d'un seul tenant, mesurés et documentés (LIMITS) : la main ne revient qu'à leur fin. Une pause
#: au-delà de ``FREEZE_S`` dont la pile relevée est dans l'un d'eux est notée, pas signalée comme problème.
KNOWN_CPP = ("getEnvelope",  # poche 3D : enveloppe des fonds (Path.Area), 0,7-1,1 s sur le plateau
             "mesh_to_solid",  # import d'un STL : maillage -> solide, affinage (OpenCascade), 0,6-1,3 s
             "import_file")  # import : vérification du solide importé (OpenCascade), 0,6 s

freezes = []  # (scénario, commande, pause)
_scenario = [""]


class Heartbeat(object):
    """Horloge Qt de 50 ms : le plus grand écart entre deux tops = durée sans traitement des événements.
    ``long`` : chaque écart au-delà de ``FREEZE_S`` (début, durée)."""

    def __init__(self):
        self.timer = QtCore.QTimer()
        self.timer.setInterval(50)
        self.timer.timeout.connect(self._tick)
        self.last = None
        self.worst = 0.0
        self.long = []

    def _tick(self):
        now = time.perf_counter()
        if self.last is not None:
            self.worst = max(self.worst, now - self.last)
            if now - self.last > FREEZE_S:
                self.long.append((self.last, now - self.last))
        self.last = now

    def __enter__(self):
        self.last = self.first = time.perf_counter()
        self.worst = 0.0
        self.long = []
        self.timer.start()
        return self

    def __exit__(self, *_a):
        self._tick()
        self.timer.stop()
        return False


class StackWatch(object):
    """Pendant une commande, pile Python du fil principal relevée quand l'horloge Qt n'a pas battu depuis 0,4 s
    (le fil de surveillance n'obtient la main qu'au retour d'un appel C++ long, ou pendant s'il relâche le
    verrou de Python : la ligne relevée est celle de cet appel). ``CAM2027_C2_STACKS=1`` : piles écrites au
    rapport."""

    def __init__(self, hb):
        import threading

        self.hb = hb
        self.main = threading.get_ident()
        self.halt = threading.Event()
        self.samples = {}  # début de l'écart -> pile
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        import sys

        while not self.halt.wait(0.05):
            last = self.hb.last
            if last is not None and time.perf_counter() - last > 0.4 and last not in self.samples:
                frame = sys._current_frames().get(self.main)
                gap = time.perf_counter() - last
                if frame is not None:
                    self.samples.setdefault(last, "%.2f s: %s" % (gap, self._stack(frame)))

    def known(self, start):
        """Pause commencée à ``start`` dans un appel C++ documenté (``KNOWN_CPP``) ?"""
        stack = self.samples.get(start, "")
        return any(" %s" % name in stack for name in KNOWN_CPP)

    def _stack(self, frame):
        import traceback

        st = traceback.extract_stack(frame)[-6:]
        return " <- ".join("%s:%d %s" % (os.path.basename(f.filename), f.lineno, f.name) for f in reversed(st))

    def __enter__(self):
        import sys

        from cam2027.project import operations as opsmod

        self.real = opsmod.keep_gui_alive

        def watched():
            # rendu de main après une longue pause : la pile de l'appelant est là où le calcul a repris, juste
            # après l'appel C++ qui a tenu la main (le fil de surveillance n'arrive qu'après ce rendu)
            last = self.hb.last
            if last is not None and time.perf_counter() - last > 0.4 and last not in self.samples:
                self.samples[last] = "%.2f s: %s" % (time.perf_counter() - last, self._stack(sys._getframe(2)))
            self.real()

        opsmod.keep_gui_alive = watched
        self.thread.start()
        return self

    def __exit__(self, *_a):
        from cam2027.project import operations as opsmod

        opsmod.keep_gui_alive = self.real
        self.halt.set()
        self.thread.join(1.0)
        if os.environ.get("CAM2027_C2_STACKS"):
            for _start, line in sorted(self.samples.items()):
                G.log("    C2 stack after %s" % line)
        return False


def probed(cls, name):
    """Classe de commande dont ``Activated`` est mesuré par l'horloge Qt."""

    class Probed(cls):
        def Activated(self, *args):
            from cam2027.project import operations as opsmod

            calls, spent = opsmod.GUI_STATS["calls"], opsmod.GUI_STATS["seconds"]
            with Heartbeat() as hb, StackWatch(hb) as sw:
                result = cls.Activated(self, *args)
            elapsed = hb.last - hb.first
            G.log("  C2 %s: %.2f s, longest interface pause %.2f s (%d interface updates, %.2f s)" % (
                name, elapsed, hb.worst, opsmod.GUI_STATS["calls"] - calls, opsmod.GUI_STATS["seconds"] - spent))
            for start, gap in hb.long:
                freezes.append((_scenario[0], name, round(gap, 2)))
                if sw.known(start):
                    G.log("  C2 %s: known C++ pause %.2f s (%s)" % (name, gap, sw.samples[start].split(": ", 1)[1][:120]))
                else:
                    G.problem(_scenario[0], "C2 %s: interface not refreshed for %.2f s (command %.1f s) %s"
                              % (name, gap, elapsed, sw.samples.get(start, "")[:200]))
            return result

    Probed.__name__ = cls.__name__
    Probed.c2_probed = True
    return Probed


def install_probe():
    from cam2027.gui import commands

    commands.COMMANDS[:] = [(n, c if getattr(c, "c2_probed", False) else probed(c, n)) for n, c in commands.COMMANDS]


def heavy_part(tmp):
    """Pièce lourde : celle de ``CAM2027_C2_PART``, le plateau réel, ou un plateau synthétique."""
    for p in (os.environ.get("CAM2027_C2_PART"), DEFAULT_PART):
        if p and os.path.isfile(p):
            return p
    import Part

    V = FreeCAD.Vector
    tray = Part.makeBox(300, 200, 20)
    cuts = [Part.makeCylinder(10, 15, V(20 + i * 26, 20 + j * 27, 5)) for i in range(11) for j in range(7)]
    tray = tray.cut(Part.makeCompound(cuts))
    path = os.path.join(tmp, "c2_tray.step")
    tray.exportStep(path)
    return path


def _prepare(scenario, tmp, name):
    proj = G.new_project(scenario, name)
    G.driver.open_files.append(heavy_part(tmp))
    G.run_command(scenario, "CAM2027_ImportModel")
    G.run_command(scenario, "CAM2027_StockFixture")
    return G.project()


def _add(scenario, strategy):
    FreeCADGui.Selection.clearSelection()
    G.driver.handlers[G.tr("Add operation")] = lambda dlg: (G.combo_select(G.find_combo_with(dlg, strategy), strategy), True)[1]
    G.run_command(scenario, "CAM2027_AddOperation")
    G.accept_open_editors(scenario)


def scenario_heavy(scenario, tmp):
    """Pièce lourde : ajout d'opérations, contrôle matière, export sous la sonde ; parcours et rapport
    relevés (comparés d'une version à l'autre par le journal)."""
    proj = _prepare(scenario, tmp, "C2Heavy")
    if proj is None or not proj.has_job:
        G.problem(scenario, "no job on the heavy part")
        return
    for strategy in ("pocket", "profile"):
        _add(scenario, strategy)
    proj = G.project()
    G.log("  C2 operations %s" % [(o.Label, len(o.Path.Commands), proj.operation_state(o)) for o in proj.operations()])
    msgs = G.run_command(scenario, "CAM2027_MaterialCheck")
    G.log("  C2 check: %s" % [t.replace("\n", " | ")[:300] for _k, t in msgs])
    out = os.path.join(tmp, "%s.nc" % scenario)
    G.driver.handlers[G.tr("Export G-code")] = lambda dlg: G._export(dlg, out)
    G.run_command(scenario, "CAM2027_Export")
    if os.path.isfile(out):
        with open(out, encoding="utf-8") as fp:
            G.log("  C2 export: %d lines" % len(fp.read().splitlines()))
    FreeCAD.closeDocument(proj.doc.Name)
    G.pump(0.3)


def _click_stop_after(delay, clicked):
    """Clique « Arrêter le calcul » de la fenêtre de progression ``delay`` s après le début (si l'interface
    traite ses événements)."""
    def click():
        for w in QtWidgets.QApplication.topLevelWidgets():
            if isinstance(w, QtWidgets.QProgressDialog) and w.isVisible():
                for b in w.findChildren(QtWidgets.QPushButton):
                    clicked.append(time.perf_counter())
                    b.click()
                    return
        QtCore.QTimer.singleShot(100, click)  # pas encore de fenêtre : on réessaie
    QtCore.QTimer.singleShot(int(delay * 1000), click)


def scenario_stop(scenario, tmp):
    """« Arrêter le calcul » pendant le recalcul de tout le projet, puis pendant le contrôle matière."""
    proj = _prepare(scenario, tmp, "C2Stop")
    if proj is None or not proj.has_job:
        G.problem(scenario, "no job on the heavy part")
        return
    _add(scenario, "pocket")
    proj = G.project()
    stopped = G.tr("Computation stopped.").rstrip(".")
    # recalcul arrêté ; recalcul complet ; contrôle matière arrêté pendant la simulation (parcours à jour)
    for command, stop in (("CAM2027_Compute", True), ("CAM2027_Compute", False), ("CAM2027_MaterialCheck", True)):
        if command == "CAM2027_Compute":
            for op in proj.operations():
                op.touch()
        clicked = []
        if stop:
            _click_stop_after(1.0, clicked)
        t0 = time.perf_counter()
        msgs = G.run_command(scenario, command)
        end = time.perf_counter()
        if not stop:
            G.log("  C2 %s complete: %.1f s, states %s" % (command, end - t0,
                                                          [proj.operation_state(o) for o in proj.operations()]))
            continue
        if not clicked:
            G.problem(scenario, "C2 %s: no progress window with a Stop button (or finished in %.1f s)"
                      % (command, end - t0))
            continue
        from cam2027.project import operations as opsmod

        G.log("  C2 %s stopped: %.2f s after the click (command %.1f s), raised at %s, messages %s" % (
            command, end - clicked[0], end - t0, opsmod.GUI_STATS["stops"][-12:], [t[:120] for _k, t in msgs]))
        del opsmod.GUI_STATS["stops"][:]
        if end - clicked[0] > STOP_S:
            G.problem(scenario, "C2 %s: returned %.1f s after Stop" % (command, end - clicked[0]))
        if not any(t.startswith(stopped) for _k, t in msgs):
            G.problem(scenario, "C2 %s: no 'computation stopped' message: %s" % (command, msgs))
        if any(t.startswith(G.tr("Material check (height map, {res} mm grid, 3 axes)", res="")[:15]) for _k, t in msgs):
            G.problem(scenario, "C2 %s: a report was shown after Stop" % command)
    FreeCAD.closeDocument(proj.doc.Name)
    G.pump(0.3)


def scenarios(g, files, tmp):
    """Scénarios C2 pour la boucle de ``gui_scenarios.main``."""
    import types

    global G
    G = types.SimpleNamespace(**g)
    if os.environ.get("CAM2027_C2_PROBE"):
        install_probe()

    def named(name, fn, probe=True):
        def run():
            _scenario[0] = name
            if probe:
                install_probe()
            fn()
        return name, run

    out = [named("c2-heavy", lambda: scenario_heavy("c2-heavy", tmp)),
           named("c2-stop", lambda: scenario_stop("c2-stop", tmp))]
    # imbrication, perçage, rotatif, incrustation : scénarios existants, sous la sonde
    for name, fn in (("c2-nest", lambda: g["_s3"]().scenario_nest_shapes("c2-nest", tmp)),
                     ("c2-rotary", lambda: g["scenario_machine_and_wrap"]("c2-rotary", files)),
                     ("c2-inlay", lambda: g["scenario_inlay"]("c2-inlay", files)),
                     ("c2-holes", lambda: __import__("tests.gui_scenarios_s2", fromlist=["*"]).scenario_holes(
                         g, "c2-holes", tmp))):
        out.append(named(name, fn))
    out.append(("c2-summary", lambda: g["log"]("C2 probe: freezes %s" % freezes)))
    return tuple(out)
