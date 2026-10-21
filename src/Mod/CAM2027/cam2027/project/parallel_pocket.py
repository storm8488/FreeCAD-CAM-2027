# SPDX-License-Identifier: LGPL-2.1-or-later
"""Poche 3D de FreeCAD (``Path.Op.Pocket``) préparée en parallèle.

Sur un plateau à 135 alvéoles (fonds choisis automatiquement, traités « collectivement »), la poche passe
26 s dans des opérations d'OpenCascade, interface figée : une découpe de l'enveloppe des fonds par la pièce
(11 s), 135 intersections pour garder les volumes sous les fonds choisis (6 s) et la découpe du volume à
enlever en niveaux par ``Path.Area`` (8 s). Ces calculs sont indépendants par volume d'enveloppe (un par
fond, disjoints) puis par niveau ; ils sont faits ici dans des processus Python de FreeCAD
(``bin/python.exe``), les formes revenant en BREP (exact). Chaque volume subit les mêmes opérations que
dans FreeCAD, seulement séparément ; chaque niveau est découpé par une zone ``Path.Area`` réglée à
l'identique. Problème avec les processus : calcul en série dans FreeCAD, comme avant.

Le même fichier sert de programme aux processus (``python.exe parallel_pocket.py tâche résultat``).
"""

import json
import os
import subprocess
import sys
import tempfile
import time

#: désactive la préparation parallèle (``0``)
ENV_SWITCH = "CAM2027_PARALLEL_POCKET"
MAX_WORKERS = 12
#: en dessous (volumes d'enveloppe, niveaux), en série : le démarrage des processus coûterait plus
MIN_SOLIDS = 8
MIN_HEIGHTS = 4


def _brep(shape):
    return "" if shape is None or shape.isNull() else shape.exportBrepToString()


def _shape(text):
    import Part

    s = Part.Shape()
    if text:
        s.importBrepFromString(text)
    return s


def _python():
    import FreeCAD

    exe = os.path.join(FreeCAD.getHomePath(), "bin", "python.exe")
    return exe if os.path.isfile(exe) else None


def _enabled(count, minimum):
    return os.environ.get(ENV_SWITCH) != "0" and count >= minimum and _python() is not None


def _run(tasks, files):
    """Lance un processus par tâche (dict JSON) ; ``files`` : formes partagées ``{nom: forme}`` écrites en BREP
    (le chemin remplace le nom dans les tâches). Retourne la liste des résultats, ou None en cas d'échec."""
    from .operations import keep_gui_alive

    tmp = tempfile.mkdtemp(prefix="cam2027-pocket-")
    paths = {}
    for name, shape in files.items():
        paths[name] = os.path.join(tmp, name + ".brep")
        shape.exportBrep(paths[name])
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(os.path.dirname(here))  # dossier du module CAM2027 (paquet cam2027)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    procs = []
    try:
        for w, task in enumerate(tasks):
            path = os.path.join(tmp, "task%d.json" % w)
            out = os.path.join(tmp, "out%d.json" % w)
            task = dict(task, files=paths, root=root)
            with open(path, "w", encoding="utf-8") as fp:
                json.dump(task, fp)
            procs.append((subprocess.Popen([_python(), os.path.abspath(__file__), path, out], creationflags=flags,
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL), out))
        while any(p.poll() is None for p, _o in procs):
            keep_gui_alive()
            time.sleep(0.02)
        results = []
        for p, out in procs:
            if p.returncode != 0 or not os.path.isfile(out):
                return None
            with open(out, encoding="utf-8") as fp:
                results.append(json.load(fp)["result"])
        return results
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


def _workers(count):
    return max(1, min(MAX_WORKERS, (os.cpu_count() or 2) - 1, count))


def removal_solids(env, part, extrusions):
    """``_identifyRemovalSolids(env.cut(part), extrusions)`` de FreeCAD, volume d'enveloppe par volume
    d'enveloppe dans des processus : compound des volumes à enlever, ou None (calcul en série)."""
    import Part

    solids = env.Solids
    if not _enabled(len(solids), MIN_SOLIDS):
        return None
    n = _workers(len(solids))
    chunks = [list(range(len(solids)))[k::n] for k in range(n)]
    out = _run([{"kind": "removal", "indices": c} for c in chunks],
               {"env": env, "part": part, "common": Part.makeCompound(extrusions)})
    if out is None:
        return None
    kept = [None] * len(solids)
    for c, res in zip(chunks, out):
        for i, texts in zip(c, res):
            kept[i] = [_shape(t) for t in texts]
    return Part.makeCompound([s for k in kept for s in k])


class _Section(object):
    """Niveau calculé dans un processus : ce que ``_buildPathArea`` lit d'une section ``Path.Area``."""

    def __init__(self, topo, shape):
        self._topo = topo
        self._shape = shape

    def toTopoShape(self):
        return self._topo

    def getShape(self):
        return self._shape


def _circle(plane):
    """Cercle de plan de travail (``PathUtils.makeWorkplane``) : ``[rayon, centre, axe]``, ou None. Il est
    refait dans le processus : relu en BREP, il donne des niveaux légèrement différents (constaté)."""
    curve = getattr(plane, "Curve", None) if getattr(plane, "ShapeType", None) == "Edge" else None
    if curve is None or curve.__class__.__name__ != "Circle" or not plane.isClosed():
        return None
    return [curve.Radius, list(curve.Center), list(curve.Axis)]


def sections(plane, shapes, params, mode, project, heights):
    """``area.makeSections(mode, project, heights)`` niveau par niveau dans des processus, pour une zone
    ``Path.Area`` de plan ``plane`` (cercle), des formes ``shapes`` et réglages ``params`` : liste de sections,
    ou None."""
    import Part

    circle = _circle(plane)
    if circle is None or not _enabled(len(heights), MIN_HEIGHTS):
        return None
    n = _workers(len(heights))
    chunks = [list(range(len(heights)))[k::n] for k in range(n)]
    params = {k: v for k, v in params.items() if isinstance(v, (bool, int, float, str))}
    out = _run([{"kind": "sections", "heights": [heights[i] for i in c], "params": params, "mode": mode,
                 "project": bool(project), "plane": circle} for c in chunks],
               {"shapes": shapes[0] if len(shapes) == 1 else Part.makeCompound(shapes)})
    if out is None:
        return None
    per_height = [None] * len(heights)
    for c, res in zip(chunks, out):
        for i, secs in zip(c, res):
            per_height[i] = [_Section(_shape(topo), _shape(shape)) for topo, shape in secs]
    return [s for secs in per_height for s in secs]


class _HookedArea(object):
    """``Path.Area`` vu par ``_buildPathArea`` : le premier ``makeSections`` est calculé par ``sections``."""

    def __init__(self, area):
        self._area = area
        self._plane = None
        self._shapes = []
        self._used = False

    def setPlane(self, shape):
        self._plane = shape
        self._area.setPlane(shape)
        return self

    def add(self, shape):
        self._shapes.append(shape)
        self._area.add(shape)
        return self

    def makeSections(self, mode=0, project=False, heights=None, **kwargs):
        if not self._used and heights and not kwargs:
            self._used = True
            res = sections(self._plane, self._shapes, self._area.getParams(), mode, project, list(heights))
            if res is not None:
                return res
        return self._area.makeSections(mode=mode, project=project, heights=heights, **kwargs)

    def __getattr__(self, name):
        return getattr(self._area, name)


class _PathModule(object):
    """Module ``Path`` vu par ``Path.Op.Area`` pendant un ``_buildPathArea`` : tout comme l'original, sauf la
    première ``Area()``."""

    def __init__(self, path):
        self._path = path
        self._first = True

    def Area(self, *args, **kwargs):
        area = self._path.Area(*args, **kwargs)
        if self._first:
            self._first = False
            return _HookedArea(area)
        return area

    def __getattr__(self, name):
        return getattr(self._path, name)


def build_path_area(area_mod, original, op, obj, baseobject, isHole, start, getsim):
    """``_buildPathArea`` de FreeCAD avec les niveaux calculés en parallèle (pas en reprise d'usinage, qui
    a besoin des vraies sections ``Path.Area``)."""
    if getattr(obj, "UseRestMachining", False) or os.environ.get(ENV_SWITCH) == "0":
        return original(op, obj, baseobject, isHole, start, getsim)
    path = area_mod.Path
    area_mod.Path = _PathModule(path)
    try:
        return original(op, obj, baseobject, isHole, start, getsim)
    finally:
        area_mod.Path = path


def _worker(task, out):
    bindir = os.path.dirname(sys.executable)
    for d in (bindir, os.path.join(os.path.dirname(bindir), "lib")):
        if os.path.isdir(d):
            sys.path.insert(0, d)
            os.add_dll_directory(d)
    with open(task, encoding="utf-8") as fp:
        t = json.load(fp)
    sys.path.insert(0, t["root"])
    import FreeCAD
    import Part

    shapes = {}
    for name, path in t["files"].items():
        shapes[name] = Part.Shape()
        shapes[name].importBrep(path)
    if t["kind"] == "removal":
        env, part, common = shapes["env"], shapes["part"], shapes["common"]
        solids = env.Solids
        result = []
        for i in t["indices"]:
            # FreeCAD : env.cut(part), puis les volumes ayant une partie commune avec les fonds extrudés
            raw = solids[i].cut(part)
            result.append([_brep(s) for s in raw.Solids if s.common(common).Volume > 0.0])
    else:
        import Path

        radius, center, axis = t["plane"]
        plane = Part.makeCircle(radius, FreeCAD.Vector(*center), FreeCAD.Vector(*axis))
        result = []
        for h in t["heights"]:
            area = Path.Area()
            area.setPlane(plane)
            area.add(shapes["shapes"])
            area.setParams(**t["params"])
            secs = area.makeSections(mode=t["mode"], project=t["project"], heights=[h])
            result.append([[_brep(s.toTopoShape()), _brep(s.getShape())] for s in secs])
    with open(out + ".part", "w", encoding="utf-8") as fp:
        json.dump({"result": result}, fp)
    os.replace(out + ".part", out)


if __name__ == "__main__":
    _worker(sys.argv[1], sys.argv[2])
