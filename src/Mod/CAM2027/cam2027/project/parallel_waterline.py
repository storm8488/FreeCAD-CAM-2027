# SPDX-License-Identifier: LGPL-2.1-or-later
"""Niveaux du Z constant de FreeCAD (``Path.Op.Waterline``, algorithme « OCL Dropcutter ») calculés en parallèle.

Le balayage OpenCamLib de la pièce est fait une fois ; ensuite, pour chaque niveau, FreeCAD
(``_getWaterline``) construit une carte des points hauts et bas, en tire les contours et les convertit en
commandes, en Python pur, un niveau après l'autre : 48 niveaux et l'essentiel des 16 s sur le chauffage Vz330.
Un niveau ne dépend que du balayage et de sa hauteur. Ici, au premier niveau demandé, tous les niveaux sont
calculés dans des processus Python de FreeCAD (``bin/python.exe``) par le même code de FreeCAD (non modifié),
puis rendus un par un dans l'ordre. Peu de niveaux, ou un problème avec les processus : en série, comme avant.

Le même fichier sert de programme aux processus (``python.exe parallel_waterline.py tâche résultat``).
"""

import json
import os
import subprocess
import sys
import tempfile
import time

#: désactive le calcul parallèle (``0``)
ENV_SWITCH = "CAM2027_PARALLEL_WATERLINE"
MAX_WORKERS = 8
#: en dessous, en série (le démarrage des processus coûterait plus qu'il ne rapporte)
MIN_LAYERS = 4
_STATE = ("CutClimb", "horizFeed", "horizRapid", "vertFeed", "vertRapid")


def _python():
    import FreeCAD

    exe = os.path.join(FreeCAD.getHomePath(), "bin", "python.exe")
    return exe if os.path.isfile(exe) else None


def compute(op, obj, scan_lines, depths, len_sl, pts_per_line):
    """Commandes de chaque niveau de ``depths`` (listes de ``Path.Command`` dans l'ordre), ou None."""
    import numpy as np
    import Path

    from .operations import keep_gui_alive

    if os.environ.get(ENV_SWITCH) == "0" or len(depths) < MIN_LAYERS:
        return None
    exe = _python()
    if exe is None:
        return None
    n = max(1, min(MAX_WORKERS, (os.cpu_count() or 2) - 1, len(depths)))
    chunks = [list(range(len(depths)))[k::n] for k in range(n)]
    tmp = tempfile.mkdtemp(prefix="cam2027-waterline-")
    scan_path = os.path.join(tmp, "scan.npy")
    np.save(scan_path, np.array([[(p.x, p.y, p.z) for p in line[:pts_per_line]] for line in scan_lines[:len_sl]],
                                dtype=float))
    state = {k: getattr(op, k) for k in _STATE}
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(os.path.dirname(here))
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    procs = []
    results = [None] * len(depths)
    try:
        for w, idx in enumerate(chunks):
            task = os.path.join(tmp, "task%d.json" % w)
            out = os.path.join(tmp, "out%d.json" % w)
            with open(task, "w", encoding="utf-8") as fp:
                json.dump({"scan": scan_path, "root": root, "state": state, "clearance": obj.ClearanceHeight.Value,
                           "layers": [[i, depths[i]] for i in idx], "len_sl": len_sl, "pts": pts_per_line}, fp)
            procs.append((subprocess.Popen([exe, os.path.abspath(__file__), task, out], creationflags=flags,
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL), out))
        while any(p.poll() is None for p, _o in procs):
            keep_gui_alive()
            time.sleep(0.05)
        for p, out in procs:
            if p.returncode != 0 or not os.path.isfile(out):
                return None
            with open(out, encoding="utf-8") as fp:
                for i, cmds in json.load(fp)["layers"]:
                    results[i] = [Path.Command(name, params) for name, params in cmds]
    finally:
        for p, _o in procs:
            if p.poll() is None:
                p.kill()
        for name in os.listdir(tmp):
            try:
                os.remove(os.path.join(tmp, name))
            except OSError:
                pass
        try:
            os.rmdir(tmp)
        except OSError:
            pass
    return results if all(r is not None for r in results) else None


def install(mod):
    """``ObjectWaterline._getWaterline`` : au premier niveau d'un balayage, tous ses niveaux en parallèle."""
    cls = getattr(mod, "ObjectWaterline", None)
    original = getattr(cls, "_getWaterline", None)
    if original is None or getattr(original, "cam2027_parallel", False):
        return

    def get_waterline(self, obj, scanLines, layDep, lyr, lenSL, pntsPerLine):
        cache = getattr(self, "_cam2027_layers", None)
        if cache is None or cache[0] is not scanLines:
            # mêmes niveaux que ``_oclWaterlineOp`` de FreeCAD
            depths = [obj.FinalDepth.Value] if obj.LayerMode == "Single-pass" else [d for d in self.depthParams]
            try:
                layers = compute(self, obj, scanLines, depths, lenSL, pntsPerLine)
            except Exception:
                layers = None
            cache = self._cam2027_layers = (scanLines, depths, layers)
        _scan, depths, layers = cache
        if lyr >= len(depths) - 1:  # dernier niveau : balayage et commandes libérés
            self._cam2027_layers = None
        if layers is not None and lyr < len(depths) and depths[lyr] == layDep:
            return layers[lyr]
        return original(self, obj, scanLines, layDep, lyr, lenSL, pntsPerLine)

    get_waterline.cam2027_parallel = True
    cls._getWaterline = get_waterline


def _worker(task, out):
    bindir = os.path.dirname(sys.executable)
    for d in (bindir, os.path.join(os.path.dirname(bindir), "lib")):
        if os.path.isdir(d):
            sys.path.insert(0, d)
            os.add_dll_directory(d)
    with open(task, encoding="utf-8") as fp:
        t = json.load(fp)
    sys.path.insert(0, t["root"])
    import types

    import numpy as np
    import FreeCAD
    import Path.Op.Waterline as mod

    scan = np.load(t["scan"])
    scan_lines = [[FreeCAD.Vector(*p) for p in line.tolist()] for line in scan]
    op = object.__new__(mod.ObjectWaterline)
    for key, value in t["state"].items():
        setattr(op, key, value)
    op.topoMap = []
    op.layerEndPnt = None
    obj = types.SimpleNamespace(ClearanceHeight=types.SimpleNamespace(Value=t["clearance"]))
    layers = []
    for i, depth in t["layers"]:
        cmds = mod.ObjectWaterline._getWaterline(op, obj, scan_lines, depth, i, t["len_sl"], t["pts"])
        layers.append([i, [[c.Name, c.Parameters] for c in cmds]])
    with open(out + ".part", "w", encoding="utf-8") as fp:
        json.dump({"layers": layers}, fp)
    os.replace(out + ".part", out)


if __name__ == "__main__":
    _worker(sys.argv[1], sys.argv[2])
