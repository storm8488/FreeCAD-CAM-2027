# SPDX-License-Identifier: LGPL-2.1-or-later
"""Préparation des niveaux de l'ébauche 3D (mode « modèle ») en parallèle.

Pour chaque niveau, FreeCAD (``_workingEdgeHelperRoughing``) calcule l'ombre de la pièce au-dessus du niveau,
sa silhouette (région « extérieure ») et les poches à vider (région « intérieure ») par des opérations
booléennes d'OpenCascade, un niveau après l'autre : l'essentiel des 25 s du plateau à 135 alvéoles. Ces
calculs ne dépendent que du niveau ; ils sont faits ici dans des processus Python de FreeCAD
(``bin/python.exe``, 0,5 s de démarrage), chacun sur une suite de niveaux, et les formes reviennent en BREP
(exact). La fusion des niveaux en régions, qui dépend de l'ordre, reste dans FreeCAD (``operations``).

Le même fichier sert de programme aux processus (``python.exe parallel_levels.py tâche résultat``).
"""

import json
import os
import subprocess
import sys
import tempfile
import time

#: désactive la préparation parallèle (``0``)
ENV_SWITCH = "CAM2027_PARALLEL_LEVELS"
MAX_WORKERS = 12
#: en dessous, préparation en série (le démarrage des processus coûterait plus qu'il ne rapporte)
MIN_LEVELS = 4


def level_regions(mod, model_shape, stock_shape, model_outline_faces, z):
    """Ombre, silhouette et poches d'un niveau (``z`` = profondeur - surépaisseur en Z), comme FreeCAD :
    ``(above_model_faces, final_cut, stockface, above)``. ``final_cut`` est calculé avec la silhouette de ce
    niveau."""
    import FreeCAD
    import Part
    import TechDraw
    import DraftGeomUtils

    projdir = FreeCAD.Vector(0, 0, 1)
    stockface = mod._getSolidProjection(stock_shape, z)
    above = mod._getSolidProjection(model_shape, z)
    faces = [Part.makeFace(TechDraw.findShapeOutline(f, 1, projdir)) for f in above.Faces]
    above_model = faces[0].fuse(faces[1:]) if faces else Part.Shape()
    final_cut = final_cut_for(above_model, above, stockface, model_outline_faces, DraftGeomUtils, Part)
    return above_model, final_cut, stockface, above


def final_cut_for(outside_region, above, stockface, model_outline_faces, DraftGeomUtils=None, Part=None):
    """Poches à vider d'un niveau (partie « INSIDE REGIONS » de FreeCAD) pour une silhouette donnée."""
    if DraftGeomUtils is None:
        import DraftGeomUtils
    if Part is None:
        import Part
    if not outside_region.Wires:
        return None  # rien au-dessus : pas de région intérieure à ce niveau
    outsideface = stockface.cut(outside_region.Faces)
    if outsideface.Wires:
        below = [f.cut(outsideface) for f in model_outline_faces]
    else:
        below = [f for f in model_outline_faces]
    if not below:
        return Part.Shape()
    below_cut = below[0].fuse(below[1:]).cut(above)
    if not below_cut.Wires:
        return Part.Shape()
    try:
        return DraftGeomUtils.concatenate(below_cut.removeSplitter())
    except Exception:  # même repli que la projection (patch_adaptive_slicing)
        return below_cut.removeSplitter()


def _brep(shape):
    return None if shape is None else ("" if shape.isNull() else shape.exportBrepToString())


def _shape(text):
    import Part

    if text is None:
        return None
    s = Part.Shape()
    if text:
        s.importBrepFromString(text)
    return s


def _python():
    import FreeCAD

    exe = os.path.join(FreeCAD.getHomePath(), "bin", "python.exe")
    return exe if os.path.isfile(exe) else None


def compute(model_shape, stock_shape, zs, stop=None):
    """Régions de chaque niveau de ``zs`` calculées en parallèle : liste de ``(above_model, final_cut,
    stockface, above)`` dans l'ordre de ``zs``, ou None (calcul parallèle indisponible ou en échec : en série)."""
    from .operations import keep_gui_alive

    if os.environ.get(ENV_SWITCH) == "0" or len(zs) < MIN_LEVELS:
        return None
    exe = _python()
    if exe is None:
        return None
    n = max(1, min(MAX_WORKERS, (os.cpu_count() or 2) - 1, len(zs)))
    # niveaux répartis en alternance : charge équilibrée (les niveaux bas ont plus de faces au-dessus)
    chunks = [list(range(len(zs)))[k::n] for k in range(n)]
    chunks = [sorted(c, key=lambda i: -zs[i]) for c in chunks if c]
    tmp = tempfile.mkdtemp(prefix="cam2027-levels-")
    model_path = os.path.join(tmp, "model.brep")
    stock_path = os.path.join(tmp, "stock.brep")
    model_shape.exportBrep(model_path)
    stock_shape.exportBrep(stock_path)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    procs = []
    here = os.path.dirname(os.path.abspath(__file__))
    mod_root = os.path.dirname(os.path.dirname(here))  # dossier du module CAM2027 (paquet cam2027)
    for w, idx in enumerate(chunks):
        task = os.path.join(tmp, "task%d.json" % w)
        out = os.path.join(tmp, "out%d.json" % w)
        with open(task, "w", encoding="utf-8") as fp:
            json.dump({"model": model_path, "stock": stock_path, "zs": [zs[i] for i in idx], "root": mod_root}, fp)
        procs.append((subprocess.Popen([exe, os.path.abspath(__file__), task, out], creationflags=flags,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL), idx, out))
    results = [None] * len(zs)
    try:
        while any(p.poll() is None for p, _i, _o in procs):
            keep_gui_alive()
            if stop is not None and stop():
                return None
            time.sleep(0.05)
        for p, idx, out in procs:
            if p.returncode != 0 or not os.path.isfile(out):
                return None
            with open(out, encoding="utf-8") as fp:
                data = json.load(fp)["levels"]
            for i, d in zip(idx, data):
                results[i] = tuple(_shape(x) for x in d)
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
    bindir = os.path.dirname(sys.executable)
    for d in (bindir, os.path.join(os.path.dirname(bindir), "lib")):
        if os.path.isdir(d):
            sys.path.insert(0, d)
            os.add_dll_directory(d)
    with open(task, encoding="utf-8") as fp:
        t = json.load(fp)
    sys.path.insert(0, t["root"])
    import FreeCAD  # noqa: F401
    import Part
    import TechDraw
    import Path.Op.Adaptive as mod

    from cam2027.project import operations as opsmod

    opsmod.patch_adaptive_slicing(mod)
    model = Part.Shape()
    model.importBrep(t["model"])
    stock = Part.Shape()
    stock.importBrep(t["stock"])
    projdir = FreeCAD.Vector(0, 0, 1)
    outline = [Part.makeFace(TechDraw.findShapeOutline(s, 1, projdir)) for s in model.Solids]
    levels = []
    for z in t["zs"]:
        levels.append([_brep(x) for x in level_regions(mod, model, stock, outline, z)])
    with open(out + ".part", "w", encoding="utf-8") as fp:
        json.dump({"levels": levels}, fp)
    os.replace(out + ".part", out)


if __name__ == "__main__":
    _worker(sys.argv[1], sys.argv[2])
