# SPDX-License-Identifier: LGPL-2.1-or-later
"""Reprise de matière depuis les opérations précédentes (Fusion « Rest machining », source « From previous
operation(s) », « Ignore stock less than »).

Le brut de départ de l'opération est la **carte de hauteur simulée** (``sim.ZMap``) après les opérations
actives qui la précèdent dans le job (mêmes parcours que le contrôle matière : habillages compris, opérations
indexées hors A0 et enroulées ignorées). L'opération est calculée normalement par FreeCAD, puis un habillage
CAM2027 ne garde que les morceaux de coupe où la fraise **rencontre de la matière** : au moins une colonne
sous son disque (rayon de la fraise moins une demi-cellule) dépasse la pointe de plus de « Ignorer moins de »
(défaut 0,1 mm comme Fusion). Le reste est sauté ; les liaisons entre les morceaux gardés sont recalculées
(``trim.trim_commands`` : remontée, rapide, plongée en avance verticale).

Différences avec Fusion : la région usinée découle du parcours complet de l'opération (calculé sur toute la
géométrie demandée), pas d'un nouveau calcul limité aux zones restantes ; les entrées dans un morceau gardé
sont des plongées verticales (Fusion : hélice / rampe) ; la fraise est vue comme plate pour décider ce qui
reste (une boule garde un peu plus de parcours que nécessaire, jamais moins).
"""

import hashlib
import math
import time

import FreeCAD

from ..i18n import Msg, UserError

SUFFIX = "_DressupRest"
LABEL = "Rest machining: from previous operations"
STRATEGIES = ("rough3d", "adaptive", "pocket", "pocket2d")
DEFAULT_IGNORE = 0.1
DEFAULT_RESOLUTION = 0.25
MAX_CELLS = 1_500_000

_CACHE = {}  # (document, habillage) -> (empreinte, (zmap, carte dilatée, rayon))


def _np():
    import numpy

    return numpy


def is_rest(obj):
    return SUFFIX in obj.Name


def previous_tops(project, op):
    """Objets du groupe « Operations » placés avant ``op`` et simulables (actifs, 3 axes à A0)."""
    from . import dressups as dressupmod, indexing, wrap as wrapmod

    base = dressupmod.base_operation(op)
    out = []
    for obj in project.operations():
        b = dressupmod.base_operation(obj)
        if b.Name == base.Name:
            break
        if indexing.is_index_op(obj) or wrapmod.is_wrap_op(obj) or getattr(b, "Active", True) is False:
            continue
        rec = project.registry.get(b.Name) or {}
        if rec.get("index_deg") not in (None, 0, 0.0) or not rec.get("tool_id"):
            continue
        out.append(obj)
    return out


def _resolution(bounds, wanted):
    res = wanted
    while ((bounds["xmax"] - bounds["xmin"]) / res) * ((bounds["ymax"] - bounds["ymin"]) / res) > MAX_CELLS:
        res *= 1.25
    return res


def remaining_stock(project, tops, resolution=DEFAULT_RESOLUTION):
    """Carte de hauteur du brut après les parcours ``tops`` (dans l'ordre)."""
    from . import sim, dressups as dressupmod, holes as holesmod

    if getattr(project.job.Stock, "Radius", None) is not None:
        raise UserError("rest machining: round stock (4th axis) is not supported, only box stock")
    bounds = project.stock_bounds()
    zmap = sim.ZMap.from_bounds(bounds, _resolution(bounds, resolution))
    items = []
    for obj in tops:
        rec = project.registry.get(dressupmod.base_operation(obj).Name) or {}
        _asm, tool, _holder = project.library.resolve_assembly(rec["assembly_id"])
        profile, _note = sim.ToolProfile.from_library_tool(tool)
        commands = obj.Path.Commands
        if holesmod.has_cycles(commands):  # cycles de perçage : mouvements équivalents, comme le contrôle matière
            commands = holesmod.expand_cycles(commands)
        items.append((commands, profile))
    sim.simulate_paths(zmap, items)
    return zmap


def engagement_map(zmap, radius):
    """Plus haute matière restante sous le disque de la fraise (rayon - demi-cellule) centrée sur chaque colonne."""
    from . import sim

    return sim.disc_max(zmap.top, max(0.0, radius / zmap.res - 0.5))


def rest_keep(zmap, reach, ignore):
    """Prédicat : la pointe en (x, y, z) a de la matière au-dessus d'elle (plus de ``ignore``) sous son disque."""
    np = _np()

    def keep(points):
        i = np.floor((points[:, 0] - zmap.x0) / zmap.res).astype(int)
        j = np.floor((points[:, 1] - zmap.y0) / zmap.res).astype(int)
        ok = (i >= 0) & (i < zmap.nx) & (j >= 0) & (j < zmap.ny)
        res = np.zeros(len(points), dtype=bool)
        res[ok] = reach[i[ok], j[ok]] > points[ok, 2] + ignore
        return res

    return keep


def _fingerprint(project, tops, resolution, radius):
    h = hashlib.sha1()
    h.update(repr((sorted(project.stock_bounds().items()), resolution, round(radius, 6))).encode())
    for obj in tops:
        h.update(obj.Name.encode())
        h.update(obj.Path.toGCode().encode())
    return h.hexdigest()


class RestDressup(object):
    """Habillage « Reprise de matière » : ``Base``, ``Previous`` (opérations simulées), ``IgnoreBelow``,
    ``Resolution`` ; ``Report`` résume le dernier calcul."""

    def __init__(self, obj, base):
        obj.addProperty("App::PropertyLink", "Base", "Base", "The base path to modify")
        obj.addProperty("App::PropertyLinkList", "Previous", "Rest", "Operations whose remaining stock is machined")
        obj.addProperty("App::PropertyDistance", "IgnoreBelow", "Rest", "Ignore stock less than this thickness")
        obj.addProperty("App::PropertyDistance", "Resolution", "Rest", "Cell size of the simulated stock")
        obj.addProperty("App::PropertyString", "Report", "Rest", "Last computation")
        obj.Base = base
        obj.IgnoreBelow = DEFAULT_IGNORE
        obj.Resolution = DEFAULT_RESOLUTION
        obj.Proxy = self

    def dumps(self):
        return None

    def loads(self, state):
        return None

    def execute(self, obj):
        import Path
        from .project import Project
        from . import trim, dressups as dressupmod

        if obj.Base is None or not hasattr(obj.Base, "Path"):
            obj.Path = Path.Path()
            return
        t0 = time.time()
        project = Project.from_document(obj.Document)
        tops = [o for o in obj.Previous if o is not None]
        base = dressupmod.base_operation(obj)
        radius = float(base.ToolController.Tool.Diameter) / 2.0
        resolution = max(0.05, float(obj.Resolution.Value) if hasattr(obj.Resolution, "Value") else float(obj.Resolution))
        ignore = max(0.0, float(obj.IgnoreBelow.Value) if hasattr(obj.IgnoreBelow, "Value") else float(obj.IgnoreBelow))
        key = (obj.Document.Name, obj.Name)
        fp = _fingerprint(project, tops, resolution, radius)
        cached = _CACHE.get(key)
        if cached is not None and cached[0] == fp:
            zmap, reach = cached[1]
        else:
            zmap = remaining_stock(project, tops, resolution)
            reach = engagement_map(zmap, radius)
            _CACHE[key] = (fp, (zmap, reach))
        clearance, safe, vfeed = trim.op_heights(obj)
        cmds, stats = trim.trim_commands(obj.Base.Path.Commands, rest_keep(zmap, reach, ignore), clearance, safe, vfeed,
                                         step=min(trim.SAMPLE_STEP, zmap.res / 2.0))
        obj.Path = Path.Path(cmds)
        from .patterns import _avoid_keepout

        _avoid_keepout(obj)  # liaisons recalculées : à la hauteur de dégagement, peut-être sous une zone interdite
        obj.Report = "cut %.0f of %.0f mm, %d links, %d previous operation(s), %.1f s" % (
            stats["cut_out"], stats["cut_in"], stats["links"], len(tops), time.time() - t0)


def sync(project):
    """Met à jour la liste des opérations précédentes de chaque reprise (ordre ou activation changés)."""
    for obj in project.operations():
        for d in [obj] + _chain(obj):
            # habillage « reprise », ou ébauche sur le modèle de brut en mode reprise (même liste)
            if hasattr(d, "Previous") and (is_rest(d) or getattr(d, "RestMachining", False)):
                tops = previous_tops(project, d)
                if [o.Name for o in d.Previous] != [o.Name for o in tops]:
                    d.Previous = tops


def _chain(obj):
    from . import dressups as dressupmod

    return dressupmod.dressup_chain(obj)


def set_rest(project, op, enabled=True, ignore_below=DEFAULT_IGNORE, resolution=None):
    """Active (ou retire) la reprise de matière de ``op`` ; retourne l'habillage ou None."""
    from . import trim, dressups as dressupmod, operations as opsmod

    base = dressupmod.base_operation(op)
    kind = (project.registry.get(base.Name) or {}).get("kind")
    existing = trim.find_dressup(project, base, SUFFIX)
    if not enabled:
        if existing is not None:
            dressupmod.remove_dressup(project.job, existing)
            project._renumber()
        return None
    if kind not in STRATEGIES:
        raise UserError("rest machining is available for 3D roughing, adaptive and pocket operations, not {op}",
                        op=Msg((opsmod.STRATEGIES.get(kind) or {}).get("label", kind or "?")))
    if ignore_below is not None and float(ignore_below) < 0:
        raise UserError("rest machining: 'ignore stock less than' must be positive or zero")
    if existing is None:
        if not previous_tops(project, base):
            raise UserError("rest machining: no active operation before {op} (nothing to take the remaining stock from)",
                            op=base.Label)
        existing = trim.add_dressup_object(project, base, SUFFIX, RestDressup, trim.tr_label("Rest machining"))
    existing.IgnoreBelow = float(DEFAULT_IGNORE if ignore_below is None else ignore_below)
    if resolution:
        existing.Resolution = float(resolution)
    existing.Previous = previous_tops(project, existing)
    project._renumber()
    return existing


def rest_params(project, op):
    """``None`` ou ``{"ignore_below", "report"}`` de la reprise de matière de ``op``."""
    from . import trim

    obj = trim.find_dressup(project, op, SUFFIX)
    if obj is None:
        return None
    return {"ignore_below": float(obj.IgnoreBelow.Value), "resolution": float(obj.Resolution.Value), "report": obj.Report}
