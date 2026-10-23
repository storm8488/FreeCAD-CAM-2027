# SPDX-License-Identifier: LGPL-2.1-or-later
"""Adaptative de FreeCAD calculée en parallèle.

L'ébauche 3D en mode « modèle » (``Path.Op.Adaptive.ExecuteModelAware``) lance un calcul ``area.Adaptive2d``
indépendant par région (nouvel objet, mêmes réglages, son brut et son contour), l'un après l'autre sur un
seul cœur : 35 s sur le chauffage de l'utilisateur. FreeCAD le note lui-même (« TODO ... parallelizes in
C++ »). Ici, ``area`` est remplacé dans le module de l'adaptative par un intermédiaire : chaque ``Execute``
est noté, puis tous les calculs en attente partent ensemble dans des processus Python de FreeCAD
(``bin/python.exe``, qui chargent le même module C++ ``area``) dès que le premier résultat est lu. Les
résultats sont les mêmes listes que celles du calcul en série. Un seul calcul, ou un problème avec les
processus : calcul en série dans FreeCAD, comme avant. L'interface reste vivante pendant l'attente et
« Arrêter le calcul » arrête les processus.

Le même fichier sert de programme aux processus de calcul (``python.exe parallel_adaptive.py tâche
résultat``).
"""

import json
import os
import subprocess
import sys
import tempfile
import time

#: désactive le calcul parallèle (``0``)
ENV_SWITCH = "CAM2027_PARALLEL_ADAPTIVE"
#: au plus tant de processus de calcul
MAX_WORKERS = 12
_PARAMS = ("stepOverFactor", "toolDiameter", "helixRampDiameter", "keepToolDownDistRatio", "stockToLeave",
           "tolerance", "forceInsideOut", "finishingProfile")


#: hélice d'entrée la plus petite essayée, en part du diamètre de la fraise
MIN_HELIX_RATIO = 0.1


def _helix_tries(params):
    """Diamètres d'hélice essayés, comme Fusion (« diamètre de rampe hélicoïdale » puis jusqu'au « diamètre
    minimal ») : celui demandé, puis deux fois plus petit tant qu'il reste au-dessus du minimum. FreeCAD saute
    sinon la région où l'hélice ne tient pas (36 alvéoles laissées pleines sur le plateau de l'utilisateur)."""
    helix = float(params.get("helixRampDiameter", 0.0) or 0.0)
    smallest = MIN_HELIX_RATIO * float(params.get("toolDiameter", 0.0) or 0.0)
    tries = [helix]
    while helix > 0 and helix / 2.0 >= smallest > 0:
        helix /= 2.0
        tries.append(helix)
    return tries


def _execute(area, job, helix, progress):
    a2d = area.Adaptive2d()
    for key in _PARAMS:
        if key in job["params"]:
            setattr(a2d, key, job["params"][key])
    a2d.helixRampDiameter = helix
    a2d.opType = area.AdaptiveOperationType(job["opType"])
    results = a2d.Execute(job["stock"], job["path"], progress or (lambda _paths: False))
    return [{"HelixCenterPoint": r.HelixCenterPoint, "StartPoint": r.StartPoint, "AdaptivePaths": r.AdaptivePaths,
             "ReturnMotionType": r.ReturnMotionType} for r in results]


def _run_job(area, job, progress=None):
    """Une région : hélice demandée, puis plus petite si elle ne donne aucun mouvement de coupe."""
    cutting = int(area.AdaptiveMotionType.Cutting)
    results = []
    for helix in _helix_tries(job["params"]):
        results = _execute(area, job, helix, progress)
        if any(m == cutting and len(pts) > 1 for r in results for m, pts in r["AdaptivePaths"]):
            break
    return results


class _Result(object):
    """Ce que retourne un ``Execute`` : liste de résultats calculée à la première lecture."""

    __slots__ = ("job", "items")

    def __init__(self, job):
        self.job = job
        self.items = None

    def _get(self):
        if self.items is None:
            _BATCH.resolve()
        return self.items

    def __iter__(self):
        return iter(self._get())

    def __len__(self):
        return len(self._get())

    def __getitem__(self, k):
        return self._get()[k]


class _Item(object):
    __slots__ = ("HelixCenterPoint", "StartPoint", "AdaptivePaths", "ReturnMotionType")

    def __init__(self, d):
        self.HelixCenterPoint = tuple(d["HelixCenterPoint"])
        self.StartPoint = tuple(d["StartPoint"])
        self.AdaptivePaths = [(m, [tuple(p) for p in pts]) for m, pts in d["AdaptivePaths"]]
        self.ReturnMotionType = d["ReturnMotionType"]


class _Batch(object):
    def __init__(self):
        self.pending = []  # (job, _Result, progressFn)
        self.area = None

    def add(self, job, progress):
        res = _Result(job)
        self.pending.append((job, res, progress))
        return res

    def resolve(self):
        jobs, self.pending = self.pending, []
        if not jobs:
            return
        if len(jobs) == 1 or os.environ.get(ENV_SWITCH) == "0":
            for job, res, progress in jobs:
                res.items = [_Item(d) for d in _run_job(self.area, job, progress)]
            return
        try:
            outputs = _run_parallel([j for j, _r, _p in jobs], jobs[0][2])
        except _Stopped:
            for _job, res, _p in jobs:
                res.items = []
            return
        except Exception:
            outputs = None
        for k, (job, res, progress) in enumerate(jobs):
            out = outputs[k] if outputs is not None else None
            if out is None:  # processus en échec : ce calcul en série, ici
                out = _run_job(self.area, job, progress)
            res.items = [_Item(d) for d in out]


_BATCH = _Batch()


class _Stopped(Exception):
    pass


class _LazyAdaptive2d(object):
    def __init__(self):
        object.__setattr__(self, "_params", {})
        object.__setattr__(self, "_op", None)

    def __setattr__(self, key, value):
        if key == "opType":
            object.__setattr__(self, "_op", value)
        else:
            self._params[key] = value

    def __getattr__(self, key):
        params = object.__getattribute__(self, "_params")
        if key in params:
            return params[key]
        raise AttributeError(key)

    def Execute(self, stock, path, progress=None):
        job = {"params": {k: (float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v)
                          for k, v in self._params.items()},
               "opType": int(self._op), "stock": stock, "path": path}
        return _BATCH.add(job, progress)


class _AreaProxy(object):
    """Module ``area`` vu par l'adaptative : tout comme l'original, sauf ``Adaptive2d``."""

    cam2027_parallel = True

    def __init__(self, area):
        self._area = area
        _BATCH.area = area

    def __getattr__(self, name):
        if name == "Adaptive2d":
            return _LazyAdaptive2d
        return getattr(self._area, name)


def install(mod):
    """Remplace ``area`` dans le module de l'adaptative (une fois)."""
    area = getattr(mod, "area", None)
    if area is None or getattr(area, "cam2027_parallel", False):
        return
    mod.area = _AreaProxy(area)


def _python():
    import FreeCAD

    exe = os.path.join(FreeCAD.getHomePath(), "bin", "python.exe")
    return exe if os.path.isfile(exe) else None


def _cost(job):
    return sum(len(p) for p in job["path"]) + 1


def _run_parallel(jobs, progress):
    """Calcule ``jobs`` dans des processus ; retourne la liste des résultats (None pour un calcul en échec)."""
    from .operations import keep_gui_alive

    exe = _python()
    if exe is None:
        raise RuntimeError("python.exe not found")
    n = max(1, min(MAX_WORKERS, (os.cpu_count() or 2) - 1, len(jobs)))
    # répartition par coût (taille des contours), le plus gros d'abord vers le processus le moins chargé
    loads = [[0, []] for _k in range(n)]
    for k in sorted(range(len(jobs)), key=lambda k: -_cost(jobs[k])):
        slot = min(loads, key=lambda s: s[0])
        slot[0] += _cost(jobs[k])
        slot[1].append(k)
    tmp = tempfile.mkdtemp(prefix="cam2027-adaptive-")
    procs = []
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    for w, (_load, idx) in enumerate(loads):
        if not idx:
            continue
        task = os.path.join(tmp, "task%d.json" % w)
        out = os.path.join(tmp, "out%d.json" % w)
        with open(task, "w", encoding="utf-8") as fp:
            json.dump({"jobs": [jobs[k] for k in idx]}, fp)
        procs.append((subprocess.Popen([exe, "-I", os.path.abspath(__file__), task, out], creationflags=flags,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL), idx, out))
    results = [None] * len(jobs)
    try:
        while any(p.poll() is None for p, _i, _o in procs):
            keep_gui_alive()
            if progress is not None and progress([]):  # « Arrêter le calcul »
                raise _Stopped()
            time.sleep(0.05)
        for p, idx, out in procs:
            if p.returncode != 0 or not os.path.isfile(out):
                continue
            with open(out, encoding="utf-8") as fp:
                data = json.load(fp)
            for k, r in zip(idx, data["results"]):
                results[k] = r
    finally:
        for p, _i, _o in procs:
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
    return results


def _worker(task, out):
    home = os.path.dirname(os.path.dirname(sys.executable))
    lib = os.path.join(home, "lib")
    sys.path.insert(0, lib)
    for d in (lib, os.path.dirname(sys.executable)):
        if os.path.isdir(d):
            os.add_dll_directory(d)
    import area

    with open(task, encoding="utf-8") as fp:
        jobs = json.load(fp)["jobs"]
    results = [_run_job(area, job) for job in jobs]
    with open(out + ".part", "w", encoding="utf-8") as fp:
        json.dump({"results": results}, fp)
    os.replace(out + ".part", out)


if __name__ == "__main__":
    _worker(sys.argv[1], sys.argv[2])
