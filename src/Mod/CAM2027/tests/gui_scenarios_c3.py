# SPDX-License-Identifier: LGPL-2.1-or-later
"""Scénarios d'interface du flux C3 (jour 4 : mémoire), appelés par ``gui_scenarios.py``.

- ``c3-memory-cycles`` : ``CAM2027_C3_CYCLES`` cycles (3 par défaut) « nouveau projet, plateau importé, brut,
  ``CAM2027_C3_OPS`` opérations ajoutées (20 par défaut, calculées comme dans l'interface), une sur deux
  supprimée, contrôle matière, projet fermé ». Mémoire privée relevée avant le premier projet et après chaque
  fermeture : un cycle ne doit pas laisser plus de ``GROWTH_MB`` pour 50 opérations, au prorata (au-delà du
  premier, qui charge les modules, les outils et les caches de FreeCAD). Le rapport donne aussi ce qui reste après chaque cycle : objets Python
  par type, tableaux numpy, documents, fenêtres Qt.
"""

import gc
import os
import sys

import FreeCAD
import FreeCADGui

G = None  # module gui_scenarios (outils du pilote)

#: mémoire laissée par un cycle complet (après le premier), en Mo
GROWTH_MB = 200  # pour 50 opérations (critère du brief n° 4)
STRATEGIES = ("profile", "pocket2d", "pocket", "adaptive", "millface")


def _b3():
    return sys.modules.get("tests.gui_scenarios_b3") or __import__("tests.gui_scenarios_b3", fromlist=["*"])


def _census():
    """Objets Python vivants par type, tableaux numpy (nombre, Mo), documents, fenêtres Qt."""
    from PySide import QtWidgets

    gc.collect()
    counts = {}
    arrays, nbytes = 0, 0
    np = sys.modules.get("numpy")
    for o in gc.get_objects():
        t = type(o)
        key = "%s.%s" % (getattr(t, "__module__", "?"), t.__name__)
        counts[key] = counts.get(key, 0) + 1
        if np is not None and isinstance(o, np.ndarray) and o.base is None:
            arrays += 1
            nbytes += o.nbytes
    return {"types": counts, "arrays": arrays, "array_mb": nbytes / 2.0 ** 20,
            "docs": sorted(FreeCAD.listDocuments()), "widgets": len(QtWidgets.QApplication.allWidgets())}


def _holders(type_names, sample=40):
    """Diagnostic (``CAM2027_C3_DEBUG=1``) : cible des références faibles, et qui garde un échantillon des
    objets des types donnés (chaîne de référents sur 3 niveaux)."""
    import weakref

    gc.collect()
    objs = gc.get_objects()
    targets = {}
    for o in objs:
        if type(o) is weakref.ReferenceType:
            t = o()
            key = "dead" if t is None else "%s.%s" % (type(t).__module__, type(t).__name__)
            targets[key] = targets.get(key, 0) + 1
    G.log("  C3 debug: weakref targets %s" % sorted(targets.items(), key=lambda kv: -kv[1])[:8])
    callbacks = {}
    for o in objs:
        if type(o) is weakref.ReferenceType and o() is None:
            cb = o.__callback__
            key = "none" if cb is None else "%s %s" % (getattr(cb, "__qualname__", type(cb).__name__),
                                                      getattr(getattr(cb, "__code__", None), "co_filename", "")[-50:])
            callbacks[key] = callbacks.get(key, 0) + 1
    G.log("  C3 debug: dead weakref callbacks %s" % sorted(callbacks.items(), key=lambda kv: -kv[1])[:6])
    deads = [o for o in objs if type(o) is weakref.ReferenceType and o() is None]
    kinds = {}
    for w in deads[-300:]:
        refs = [r for r in gc.get_referrers(w) if r is not deads and r is not objs and type(r).__name__ != "frame"]
        key = ", ".join(sorted(set("%s(%d)" % (type(r).__name__, sys.getrefcount(w)) for r in refs))) or "no Python referrer (refcount %d)" % sys.getrefcount(w)
        kinds[key] = kinds.get(key, 0) + 1
    G.log("  C3 debug: last 300 dead weakrefs referenced by %s" % sorted(kinds.items(), key=lambda kv: -kv[1])[:5])
    owners = {}
    funcs = [o for o in objs if type(o).__name__ == "function" and o.__closure__]
    cell_owner = {}
    for f in funcs:
        for c in f.__closure__:
            cell_owner[id(c)] = f
    for w in deads[-300:]:
        for r in gc.get_referrers(w):
            if type(r).__name__ == "cell" and id(r) in cell_owner:
                f = cell_owner[id(r)]
                key = "%s %s:%d refcount %d" % (f.__qualname__, f.__code__.co_filename[-60:], f.__code__.co_firstlineno,
                                                sys.getrefcount(f))
                owners[key] = owners.get(key, 0) + 1
    G.log("  C3 debug: closures holding them %s" % sorted(owners.items(), key=lambda kv: -kv[1])[:5])
    cells = {}
    for w in deads[-50:]:
        for r in gc.get_referrers(w):
            if type(r).__name__ == "cell":
                up = [type(u).__name__ for u in gc.get_referrers(r) if u is not objs]
                key = "cell refcount %d, contents %s, held by %s" % (sys.getrefcount(r) - 1, type(r.cell_contents).__name__, up)
                cells[key] = cells.get(key, 0) + 1
    G.log("  C3 debug: cells %s" % sorted(cells.items(), key=lambda kv: -kv[1])[:4])
    import tracemalloc

    if tracemalloc.is_tracing():
        for label, group in (("dead weakref", deads[-400:]),
                             ("PropertyBag", [o for o in objs if type(o).__name__ == "PropertyBag"][-40:])):
            sites = {}
            for o in group:
                tb = tracemalloc.get_object_traceback(o)
                key = " | ".join("%s:%d" % (f.filename[-45:], f.lineno) for f in list(tb)[-6:]) if tb else "?"
                sites[key] = sites.get(key, 0) + 1
            for k, n in sorted(sites.items(), key=lambda kv: -kv[1])[:3]:
                G.log("  C3 debug: %d %s created at %s" % (n, label, k))
        snap = tracemalloc.take_snapshot()
        for st in snap.statistics("traceback")[:6]:
            G.log("  C3 debug: %.1f MB in %d blocks at %s" % (st.size / 2.0 ** 20, st.count, " | ".join(
                "%s:%d" % (f.filename[-45:], f.lineno) for f in list(st.traceback)[-5:])))
    del funcs, cell_owner
    del deads
    bag = next((o for o in objs if type(o).__name__ == "PropertyBag"), None)
    if bag is not None:
        G.log("  C3 debug: a kept PropertyBag: refcount %d, attributes %s" % (
            sys.getrefcount(bag), {k: type(v).__name__ for k, v in vars(bag).items()}))
    mine = set()

    def describe(o):
        d = type(o).__name__
        if isinstance(o, dict):
            d += str(list(o.keys())[:5])
        elif type(o).__name__ == "function":
            d += "(%s %s)" % (o.__qualname__, getattr(o.__code__, "co_filename", "?")[-40:])
        elif type(o).__name__ == "cell":
            pass
        elif isinstance(o, (list, tuple, set)):
            d += "[%d]" % len(o)
        return d

    def chain_of(o, depth=5):
        out = []
        cur = o
        for _d in range(depth):
            refs = [r for r in gc.get_referrers(cur) if id(r) not in mine and type(r).__name__ != "frame"]
            mine.add(id(refs))
            if not refs:
                break
            cur = refs[0]
            out.append(describe(cur))
        return " <- ".join(out)

    mine.update((id(objs), id(mine)))
    # conteneurs qui gardent beaucoup de références faibles mortes
    holders = {}
    for o in objs:
        if isinstance(o, (list, set, dict)) and id(o) not in mine:
            vals = o.values() if isinstance(o, dict) else o
            try:
                dead = sum(1 for v in vals if type(v) is weakref.ReferenceType and v() is None)
            except Exception:
                continue
            if dead > 500:
                holders[id(o)] = (dead, o)
    for dead, o in sorted(holders.values(), key=lambda dv: -dv[0])[:4]:
        G.log("  C3 debug: %s with %d dead weakrefs, kept by %s" % (describe(o), dead, chain_of(o)))
    for name in type_names:
        found = [o for o in objs if type(o).__name__ == name][:sample]
        mine.add(id(found))
        chains = {}
        for o in found:
            k = chain_of(o)
            chains[k] = chains.get(k, 0) + 1
        G.log("  C3 debug: %d %s kept by %s" % (len(found), name, sorted(chains.items(), key=lambda kv: -kv[1])[:3]))
    del objs


def _diff(a, b, limit=12):
    keys = set(a["types"]) | set(b["types"])
    d = sorted(((b["types"].get(k, 0) - a["types"].get(k, 0), k) for k in keys), reverse=True)
    return [(k, n) for n, k in d[:limit] if n > 0]


def _cycle(scenario, files, i, n_ops):
    from cam2027.gui import panels

    b3 = _b3()
    proj = b3._tray_project(scenario, files, "C3 memory %d" % i)
    doc = proj.doc
    p = G.panel()
    for k in range(n_ops):
        b3._add(scenario, STRATEGIES[k % len(STRATEGIES)])
    proj = G.project()
    added = p.tree.topLevelItemCount()
    for _k in range(added // 2):
        b3._select_row(0)
        p.buttons["del"].click()
        G.pump(0.05)
    panels.refresh_project_panel()
    rep = proj.material_check()
    G.log("  C3 cycle %d: %d operations added, %d left, check gouge %s, memory %.0f MB" % (
        i, added, p.tree.topLevelItemCount(), rep.get("gouge_max"), b3.memory_mb()[0]))
    if added < n_ops * 0.8:
        G.problem(scenario, "C3 cycle %d: only %d operations added out of %d" % (i, added, n_ops))
    if os.environ.get("CAM2027_C3_CLEARUNDO"):  # diagnostic : pile d'annulation vidée avant la fermeture
        G.log("  C3 cycle %d: %d undo steps cleared" % (i, doc.UndoCount))
        doc.clearUndos()
    FreeCAD.closeDocument(doc.Name)
    G.pump(0.5)


def _cycle_api(scenario, files, i, n_ops):
    """Diagnostic (``CAM2027_C3_API=1``) : le même cycle par l'API du projet, sans commandes ni dialogues."""
    from cam2027.gui.commands import default_params
    from cam2027.project import operations as opsmod
    from cam2027.project.project import Project
    from cam2027.tools.library import starter_library

    lib = starter_library()
    proj = Project.create("C3 api %d" % i, lib)
    proj.import_model(files["step"])
    proj.create_job(proj.model_candidates(), stock={"kind": "box_margins", "xy": 2.0, "z_top": 1.0, "z_bottom": 0.0})
    models = list(proj.job.Model.Group)
    tool = lib.search("6 mm flat end mill")[0]
    asm, preset = lib.assemblies_for_tool(tool.id)[0], tool.presets[0]
    skip = set(os.environ.get("CAM2027_C3_SKIP", "").split(","))  # ops, compute, delete, check
    ops = []
    for k in range(0 if "ops" in skip else n_ops):
        kind = STRATEGIES[k % len(STRATEGIES)]
        auto = opsmod.auto_geometry(kind, models)
        base = [(m, []) for m in models] if auto is None else auto
        ops.append(proj.add_operation(kind, "%s %d" % (kind, k), asm.id, preset.id, base=base,
                                      params=default_params(kind, tool, preset.resolve(tool)))[0])
        if "compute" not in skip:
            proj.compute()
        G.pump(0.02)
    for op in ([] if "delete" in skip else ops[: len(ops) // 2]):
        proj.remove_operation(op)
    if "check" not in skip and "compute" not in skip:
        proj.material_check()
    G.log("  C3 api cycle %d: %d operations, memory %.0f MB" % (i, n_ops, _b3().memory_mb()[0]))
    FreeCAD.closeDocument(proj.doc.Name)
    G.pump(0.5)


def scenario_memory_cycles(scenario, files):
    b3 = _b3()
    b3.G = G
    cycles = int(os.environ.get("CAM2027_C3_CYCLES", "3"))
    n_ops = int(os.environ.get("CAM2027_C3_OPS", "20"))
    G.pump(0.5)
    if os.environ.get("CAM2027_C3_TRACE"):
        import tracemalloc

        tracemalloc.start(25)
    gc.collect()
    mem = [b3.memory_mb()[0]]
    census = [_census()]
    G.log("  C3 memory before the first project: %.0f MB, %d numpy arrays (%.1f MB), %d widgets" % (
        mem[0], census[0]["arrays"], census[0]["array_mb"], census[0]["widgets"]))
    for i in range(1, cycles + 1):
        (_cycle_api if os.environ.get("CAM2027_C3_API") else _cycle)(scenario, files, i, n_ops)
        b3.live_dialogs()
        gc.collect()
        mem.append(b3.memory_mb()[0])
        census.append(_census())
        c = census[-1]
        G.log("  C3 after cycle %d (project closed): %.0f MB (%+.0f MB), %d numpy arrays (%.1f MB), %d widgets, "
              "documents %s" % (i, mem[-1], mem[-1] - mem[-2], c["arrays"], c["array_mb"], c["widgets"], c["docs"]))
        G.log("  C3 Python objects added by cycle %d: %s" % (i, _diff(census[-2], c)))
        if os.environ.get("CAM2027_C3_DEBUG"):
            _holders(("PropertyBag", "ViewProvider", "QPushButton"))
    growth = [mem[k + 1] - mem[k] for k in range(1, len(mem) - 1)]
    G.log("  C3 memory per cycle: %s MB (first cycle %+.0f MB)" % ([round(g) for g in growth], mem[1] - mem[0]))
    limit = GROWTH_MB * n_ops / 50.0
    if any(g > limit for g in growth):
        G.problem(scenario, "C3 memory grows by %s MB per cycle (> %.0f MB)" % ([round(g) for g in growth], limit))
    if census[-1]["docs"]:
        G.problem(scenario, "C3 documents left open: %s" % census[-1]["docs"])


def scenarios(gs, files, tmp):
    global G
    G = sys.modules[gs["__name__"]] if isinstance(gs, dict) else gs  # ``globals()`` du pilote
    return (("c3-memory-cycles", lambda: scenario_memory_cycles("c3-memory-cycles", files)),)
