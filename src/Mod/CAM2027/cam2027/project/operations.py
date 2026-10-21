# SPDX-License-Identifier: LGPL-2.1-or-later
"""Création d'opérations CAM à partir d'une spécification simple.

Chaque opération reçoit son propre ``ToolController`` portant les valeurs
copiées du préréglage au moment de la création (« valeurs utilisées dans
l'opération »). Le registre du projet mémorise l'assemblage, le préréglage et
les valeurs résolues.

Les stratégies disponibles sont celles de FreeCAD CAM 1.0/1.1. Les limites
connues (par type) sont dans ``STRATEGIES[kind]["limits"]`` et reprises dans la
documentation. La poche FreeCAD n'est pas une ébauche adaptative : l'ébauche
adaptative est l'opération ``adaptive`` (algorithme de Kalman/Adaptive de
FreeCAD, engagement contrôlé en 2D).
"""

from ..i18n import UserError
import csv
import importlib
import os

STRATEGIES = {
    "profile": {
        "module": "Path.Op.Profile",
        "label": "2D contour (profile)",
        "params": ("Side", "Direction", "OffsetExtra", "UseComp", "processHoles", "processPerimeter",
                   "processCircles", "StepDown", "StartDepth", "FinalDepth", "FinishDepth",
                   "ClearanceHeight", "SafeHeight", "EnableRotation"),
        "limits": "Lead-in/out are provided by dressups (not inline); tabs via the Holding Tags dressup.",
    },
    "pocket": {
        "module": "Path.Op.Pocket",
        "label": "2.5D pocket (offset / zigzag)",
        "params": ("CutMode", "StepOver", "ZigZagAngle", "OffsetPattern", "StartAt", "ExtraOffset",
                   "KeepToolDown", "MinTravel", "UseOutline", "StepDown", "StartDepth", "FinalDepth",
                   "FinishDepth", "ClearanceHeight", "SafeHeight", "HelixAngle", "HelixDiameterLimit"),
        "limits": "Offset/zigzag/spiral patterns are NOT adaptive (no engagement control); use 'adaptive'.",
    },
    "pocket2d": {
        "module": "Path.Op.PocketShape",
        "label": "2D pocket (inside a drawing contour)",
        "params": ("CutMode", "StepOver", "ZigZagAngle", "OffsetPattern", "StartAt", "ExtraOffset",
                   "KeepToolDown", "MinTravel", "UseOutline", "StepDown", "StartDepth", "FinalDepth",
                   "FinishDepth", "ClearanceHeight", "SafeHeight"),
        "limits": "Works on flat faces (the faces generated from closed drawing contours); depth set by the "
                  "start / final depth, walls vertical.",
    },
    "adaptive": {
        "module": "Path.Op.Adaptive",
        "label": "2D adaptive roughing (controlled engagement)",
        "params": ("Side", "OperationType", "Tolerance", "StepOver", "LiftDistance", "KeepToolDownRatio",
                   "StockToLeave", "HelixAngle", "HelixConeAngle", "HelixDiameterLimit", "ForceInsideOut",
                   "FinishingProfile", "UseHelixArcs", "UseOutline", "StepDown", "StartDepth", "FinalDepth",
                   "FinishDepth", "ClearanceHeight", "SafeHeight"),
        "limits": "2D engagement control only (no 3D rest-aware adaptive). Computation is single-threaded C++.",
    },
    "drilling": {
        "module": "Path.Op.Drilling",
        "label": "Drilling (G81/G82/G83 cycles)",
        "params": ("PeckEnabled", "PeckDepth", "DwellEnabled", "DwellTime", "RetractHeight", "ExtraOffset",
                   "RetractMode", "StartDepth", "FinalDepth", "ClearanceHeight", "SafeHeight"),
        "limits": "Hole recognition is by selected circular edges/faces; no automatic hole feature recognition.",
    },
    "millface": {
        "module": "Path.Op.MillFace",
        "label": "Facing",
        "params": ("BoundaryShape", "StepOver", "CutMode", "ZigZagAngle", "OffsetPattern", "StepDown",
                   "StartDepth", "FinalDepth", "ClearanceHeight", "SafeHeight", "ExcludeRaisedAreas",
                   "ClearEdges"),
        "limits": "Flat faces only; with 'ClearEdges' the tool centre passes just beyond the face edges.",
    },
    "engrave": {
        "module": "Path.Op.Engrave",
        "label": "Engrave (follow edges)",
        "params": ("StartVertex", "StepDown", "StartDepth", "FinalDepth", "ClearanceHeight", "SafeHeight"),
        "limits": "Constant depth along selected edges/wires.",
    },
    "vcarve": {
        "module": "Path.Op.Vcarve",
        "label": "V-carve (variable depth, Voronoi medial axis)",
        "params": ("Discretize", "Colinear", "Tolerance", "StartDepth", "FinalDepth", "ClearanceHeight",
                   "SafeHeight"),
        "limits": "Depth limited by the final depth; for wide areas use Machine > Flat depth clearing (flat end mill, V-bit outline, sharp corners).",
    },
    "helix": {
        "module": "Path.Op.Helix",
        "label": "Helical boring",
        "params": ("Direction", "StartSide", "StepOver", "StartRadius", "StepDown", "StartDepth",
                   "FinalDepth", "ClearanceHeight", "SafeHeight"),
        "limits": "",
    },
    "slot": {
        "module": "Path.Op.Slot",
        "label": "Slot",
        "params": ("CustomPoint1", "CustomPoint2", "Reference1", "Reference2", "ExtendRadius", "CutPattern",
                   "ExtendPathStart", "ExtendPathEnd", "LayerMode", "PathOrientation", "ReverseDirection",
                   "StepDown", "StartDepth", "FinalDepth", "ClearanceHeight", "SafeHeight"),
        "limits": "Without selected geometry the slot runs between the two custom points (XY at the start depth).",
    },
    "rough3d": {
        "module": "Path.Op.Adaptive",
        "label": "3D roughing (adaptive, stock to model)",
        "params": ("StepOver", "StepDown", "StockToLeave", "Tolerance", "LiftDistance", "KeepToolDownRatio",
                   "HelixAngle", "HelixConeAngle", "HelixDiameterLimit", "UseHelixArcs", "ForceInsideOut",
                   "FinishingProfile", "StartDepth", "FinalDepth", "ClearanceHeight", "SafeHeight"),
        "limits": "Clears the stock around the selected raised faces level by level (adaptive, flat end mill), leaving "
                  "'stock to leave' for a 3D finishing pass; steps remain between levels.",
    },
    "surface3d": {
        "module": "Path.Op.Surface",
        "label": "3D surface finishing (parallel / zigzag / offset, OpenCamLib)",
        "params": ("CutPattern", "CutPatternAngle", "CutMode", "StepOver", "SampleInterval", "BoundBox",
                   "BoundaryAdjustment", "DepthOffset", "LayerMode", "StepDown", "OptimizeLinearPaths",
                   "LinearDeflection", "AngularDeflection", "StartDepth", "FinalDepth", "ClearanceHeight", "SafeHeight"),
        "limits": "3-axis drop-cutter (OpenCamLib) following the surface; best with a ball or bull nose mill; "
                  "no rest machining from a previous roughing; rotational scan (4th axis) not exposed.",
    },
    "waterline": {
        "module": "Path.Op.Waterline",
        "label": "3D constant-Z finishing (waterline, OpenCamLib)",
        "params": ("Algorithm", "CutMode", "LayerMode", "StepDown", "SampleInterval", "BoundBox", "BoundaryAdjustment",
                   "DepthOffset", "ClearLastLayer", "OptimizeLinearPaths", "LinearDeflection", "AngularDeflection",
                   "StartDepth", "FinalDepth", "ClearanceHeight", "SafeHeight"),
        "limits": "Contours at constant Z, suited to steep walls (pair it with 3D surface finishing for flat areas); "
                  "multi-pass layers spaced by the step down.",
    },
    "threadmill": {
        "module": "Path.Op.ThreadMilling",
        "label": "Thread milling (helical, internal / external)",
        "params": ("ThreadOrientation", "ThreadType", "ThreadName", "ThreadFit", "MajorDiameter", "MinorDiameter",
                   "Pitch", "TPI", "Passes", "Direction", "LeadInOut", "StartDepth", "FinalDepth",
                   "ClearanceHeight", "SafeHeight"),
        "limits": "Needs a thread mill; the helix always runs over the whole thread length (tool teeth count "
                  "unused), tool crest taken as 0; the thread must be pre-drilled (no clearing op linked).",
    },
    "chamfer": {
        "module": "Path.Op.Deburr",
        "label": "Chamfer / deburr (edges)",
        "params": ("Width", "ExtraDepth", "Direction", "EntryPoint", "StepDown", "ClearanceHeight", "SafeHeight"),
        "limits": "Selected edges or a flat face outline; depth derives from the tool angle (chamfer / V-bit); "
                  "no collision check with adjacent walls.",
    },
}

#: valeurs par défaut de FreeCAD pour un filet sans type explicite
DEFAULT_THREAD_TYPE = "MetricInternal6H"

#: stratégies qui travaillent sur des trous : sans sélection, FreeCAD détecte tous les trous
#: cylindriques plus grands que l'outil (``findAllHoles``)
HOLE_STRATEGIES = ("drilling", "helix", "threadmill")
#: ébauche 3D en mode classique (FreeCAD 1.0) : au-delà, le calcul fige l'interface plusieurs minutes
MAX_CLASSIC_ROUGH_FACES = 200

_MILLS = ("endmill", "bullnose", "ballend")
#: types d'outil de la bibliothèque proposés pour chaque stratégie (le premier présent est présélectionné)
TOOLS_FOR = {
    "profile": _MILLS, "pocket": _MILLS, "pocket2d": _MILLS, "adaptive": ("endmill", "bullnose"),
    "millface": ("facemill", "endmill", "bullnose"), "slot": _MILLS, "helix": ("endmill", "bullnose"),
    "rough3d": ("endmill", "bullnose"), "surface3d": ("ballend", "bullnose", "taperedball", "endmill"),
    "waterline": ("ballend", "bullnose", "endmill"), "drilling": ("drill",), "threadmill": ("threadmill",),
    "vcarve": ("vbit", "engrave", "chamfer"), "engrave": ("vbit", "engrave", "chamfer", "ballend", "endmill"),
    "chamfer": ("chamfer", "vbit", "engrave"),
}


def tool_fits(kind, tool):
    """L'outil convient-il à la stratégie ? (V-carving : outil à pointe en V, etc.)"""
    allowed = TOOLS_FOR.get(kind)
    if allowed is None:
        return True
    if tool.tool_type not in allowed:
        return False
    if kind in ("vcarve", "chamfer") and not tool.geometry.tip_included_angle_deg:
        return False
    return True


def tool_rank(kind, tool):
    allowed = TOOLS_FOR.get(kind) or ()
    return allowed.index(tool.tool_type) if tool.tool_type in allowed else len(allowed)


def _horizontal_planes(shape, tol=1e-6):
    for i, f in enumerate(shape.Faces, 1):
        if f.Surface.__class__.__name__ == "Plane" and abs(f.BoundBox.ZMax - f.BoundBox.ZMin) < tol:
            yield i, f


def pocket_floor_faces(obj, tol=1e-6):
    """Fonds de poche d'un solide : faces planes horizontales strictement entre le dessous et le dessus, sans
    matière au-dessus d'elles. Un fond sous un surplomb n'est pas accessible par le dessus : la poche FreeCAD
    l'extrude vers le haut et usine à travers le surplomb."""
    import FreeCAD

    shape = obj.Shape
    bb = shape.BoundBox
    out = []
    for i, f in _horizontal_planes(shape, tol):
        if not bb.ZMin + 1e-3 < f.BoundBox.ZMin < bb.ZMax - 1e-3:
            continue
        above = f.copy()
        above.translate(FreeCAD.Vector(0, 0, 1e-3))
        if above.extrude(FreeCAD.Vector(0, 0, bb.ZMax - f.BoundBox.ZMin + 1.0)).common(shape).Volume > 1e-3:
            continue
        out.append("Face%d" % i)
    return out


def top_faces(obj, tol=1e-6):
    """Faces planes horizontales au sommet du solide (surfaçage)."""
    top = obj.Shape.BoundBox.ZMax
    return ["Face%d" % i for i, f in _horizontal_planes(obj.Shape, tol) if abs(f.BoundBox.ZMax - top) < 1e-3]


def auto_geometry(kind, models):
    """Géométrie choisie sans sélection : ``[(objet, sous-éléments)]``, ``[]`` si rien de pertinent, ``None``
    quand la stratégie travaille sur la pièce entière."""
    if kind in ("pocket", "adaptive"):
        finder = pocket_floor_faces
    elif kind == "millface":
        finder = top_faces
    else:
        return None
    out = []
    for obj in models:
        shape = getattr(obj, "Shape", None)
        if shape is None or not shape.Solids:
            continue
        subs = finder(obj)
        if subs:
            out.append((obj, subs))
    return out


def thread_table(thread_type):
    """Lignes (dict) de la table FreeCAD des filets standard ``Mod/CAM/Data/Threads``."""
    import FreeCAD

    mod = strategy_module("threadmill")
    filename = mod.ThreadTypeData.get(thread_type)
    if filename is None:
        raise ValueError("type de filet sans table standard : %r" % (thread_type,))
    path = os.path.join(FreeCAD.getHomePath(), "Mod", "CAM", "Data", "Threads", filename)
    with open(path, "r", newline="", encoding="utf-8") as fp:
        return list(csv.DictReader(fp))


def thread_names(thread_type=DEFAULT_THREAD_TYPE):
    return [row["name"] for row in thread_table(thread_type)]


def thread_spec(thread_type, name, fit=50):
    """Propriétés ThreadMilling d'un filet standard (comme le panneau FreeCAD).

    ``fit`` (0-100) interpole entre les tolérances min et max des diamètres.
    """
    rows = [r for r in thread_table(thread_type) if r["name"] == name]
    if not rows:
        raise ValueError("filet %r inconnu dans la table %s" % (name, thread_type))
    row = rows[0]
    f = float(fit) / 100.0
    major = float(row["dMajorMin"]) + (float(row["dMajorMax"]) - float(row["dMajorMin"])) * f
    minor = float(row["dMinorMin"]) + (float(row["dMinorMax"]) - float(row["dMinorMin"])) * f
    spec = {"ThreadType": thread_type, "ThreadName": name, "ThreadFit": int(fit)}
    if thread_type in strategy_module("threadmill").ThreadTypesImperial:
        tpi = int(row["tpi"])
        spec.update({"TPI": tpi, "Pitch": 25.4 / tpi, "MajorDiameter": major * 25.4, "MinorDiameter": minor * 25.4})
    else:
        spec.update({"TPI": 0, "Pitch": float(row["pitch"]), "MajorDiameter": major, "MinorDiameter": minor})
    return spec


#: avant-trou d'un filet : diamètre mineur de la table, à cette marge près (mm)
TAP_DRILL_TOLERANCE = 0.15


def fit_thread_to_holes(op, tool, params):
    """Filetage sans sélection : FreeCAD retient tous les trous de la pièce, quel que soit leur diamètre (un
    filet M6 dans un trou de 4,1 mm entaille la pièce). Garde les trous percés pour un même filet (diamètre
    entre les diamètres mineurs de la table, à ``TAP_DRILL_TOLERANCE`` près) : le filet demandé s'il en a,
    sinon celui qui en a le plus, parmi les filets que l'outil peut fraiser (pas dans sa plage, diamètre
    majeur au-delà de son diamètre). Retourne ``(params, nombre de trous gardés, diamètres écartés)``."""
    holes = [(b, sub, float(op.Proxy.holeDiameter(op, b, sub))) for b, subs in op.Base for sub in subs]
    if not holes:
        return params, 0, []
    thread_type = params.get("ThreadType", DEFAULT_THREAD_TYPE)
    imperial = thread_type in strategy_module("threadmill").ThreadTypesImperial
    scale = 25.4 if imperial else 1.0
    g = tool.geometry
    groups = {}
    for row in thread_table(thread_type):
        pitch = 25.4 / int(row["tpi"]) if imperial else float(row["pitch"])
        if pitch < (g.pitch_min or 0.0) - 1e-6 or pitch > g.pitch + 1e-6 or float(row["dMajorMin"]) * scale <= g.diameter:
            continue
        lo = float(row["dMinorMin"]) * scale - TAP_DRILL_TOLERANCE
        hi = float(row["dMinorMax"]) * scale + TAP_DRILL_TOLERANCE
        hits = [h for h in holes if lo <= h[2] <= hi]
        if hits:
            groups[row["name"]] = (hits, pitch)
    if not groups:
        raise UserError("No hole of the part is drilled for a thread this tool can mill (hole diameters: {d} mm): select the holes, or drill them to the tap drill size first",
                        d=", ".join("%.2f" % d for d in sorted({round(h[2], 2) for h in holes})))
    name = params.get("ThreadName")
    if name not in groups:
        name = max(groups, key=lambda n: (len(groups[n][0]), groups[n][1]))  # le plus de trous, puis pas gros
    kept = groups[name][0]
    base = {}
    for b, sub, _d in kept:
        base.setdefault(b.Name, (b, []))[1].append(sub)
    op.Base = list(base.values())
    params = dict(params)
    for key in ("MajorDiameter", "MinorDiameter", "Pitch", "TPI"):
        params.pop(key, None)
    params.update(thread_spec(thread_type, name, params.get("ThreadFit", 50)))
    set_params(op, params)
    others = sorted({round(h[2], 2) for h in holes if h not in kept})
    return params, len(kept), others

def resolve_params(kind, tool, params):
    """Complète les paramètres d'une stratégie à partir de l'outil de la bibliothèque.

    Fraisage de filets : un ``ThreadName`` est résolu en diamètres/pas via la
    table FreeCAD ; sans pas ni TPI, le pas (maximal) de l'outil est utilisé ;
    le pas demandé doit rester dans la plage ``pitch_min``..``pitch`` de l'outil.
    """
    params = dict(params or {})
    if kind == "rough3d":
        defaults = {"Side": "Outside", "OperationType": "Clearing", "StockToLeave": 0.5}
        for key, value in defaults.items():
            params.setdefault(key, value)
        return params
    if kind != "threadmill":
        return params
    if tool.tool_type != "threadmill":
        raise ValueError("le fraisage de filets exige un outil « threadmill » (outil : %s)" % tool.tool_type)
    g = tool.geometry
    if "ThreadName" in params and "MajorDiameter" not in params:
        params.setdefault("ThreadType", DEFAULT_THREAD_TYPE)
        params.update(thread_spec(params["ThreadType"], params["ThreadName"], params.get("ThreadFit", 50)))
    if not params.get("TPI") and "Pitch" not in params:
        params["Pitch"] = g.pitch
    pitch = 25.4 / params["TPI"] if params.get("TPI") else float(params["Pitch"])
    if pitch < (g.pitch_min or 0.0) - 1e-6 or pitch > g.pitch + 1e-6:
        raise ValueError("pas de filet %.3f mm hors de la plage de l'outil %s (%.3f-%.3f mm)"
                         % (pitch, tool.name, g.pitch_min or 0.0, g.pitch))
    return params


def strategy_module(kind):
    if kind not in STRATEGIES:
        raise ValueError("stratégie inconnue : %r (disponibles : %s)" % (kind, ", ".join(sorted(STRATEGIES))))
    mod = importlib.import_module(STRATEGIES[kind]["module"])
    if kind in ("adaptive", "rough3d"):
        patch_adaptive_slicing(mod)
    if kind == "surface3d":
        patch_surface_keepalive()
    if kind == "pocket":
        patch_pocket(mod)
    return mod


def patch_surface_keepalive():
    """Finition 3D : FreeCAD simplifie chaque ligne du balayage (``PathUtils.simplify3dLine``) ; on y rend la
    main à l'interface (``keep_gui_alive``), sans rien changer au calcul."""
    import PathScripts.PathUtils as PathUtils

    original = getattr(PathUtils, "simplify3dLine", None)
    if original is None or getattr(original, "cam2027_patched", False):
        return

    def simplify(line, tolerance=1e-4):
        keep_gui_alive()
        return original(line, tolerance=tolerance)

    simplify.cam2027_patched = True
    PathUtils.simplify3dLine = simplify


def patch_adaptive_slicing(mod=None):
    """Mode « modèle » de l'adaptative (FreeCAD 1.1) : à chaque niveau, les faces de la pièce au-dessus de la
    tranche sont projetées sur XY puis réunies en une face par ``DraftGeomUtils.concatenate``. Sur certaines
    pièces (chauffage Vz330 : tranches 6,5-9,5 et 28,5-36,5 mm) cette dernière étape lève « Wire is not
    closed » et toute l'opération échoue, sans parcours. Chaque face se projette pourtant seule : en cas
    d'échec, la réunion des projections est gardée telle quelle (faces coplanaires à Z 0)."""
    if mod is None:
        mod = importlib.import_module("Path.Op.Adaptive")
    original = getattr(mod, "projectFacesToXY", None)
    if original is None or getattr(original, "cam2027_patched", False):
        return

    def projection(faces, *args, **kwargs):
        try:
            return original(faces, *args, **kwargs)
        except Exception:
            parts = [original([f], *args, **kwargs) for f in faces]
            parts = [p for p in parts if not p.isNull() and p.Faces]
            if not parts:
                raise
            return parts[0].fuse(parts[1:]).removeSplitter() if len(parts) > 1 else parts[0]

    projection.cam2027_patched = True
    mod.projectFacesToXY = projection
    _patch_roughing_regions(mod)
    from . import parallel_adaptive

    parallel_adaptive.install(mod)


def keep_gui_alive(_state={"t": 0.0}):
    """Rend la main à l'interface (au plus toutes les 0,2 s) pendant un calcul long en Python : sans cela
    Windows marque CAM2027 « Ne répond pas » et « Arrêter le calcul » reste sans effet. La fenêtre de
    progression est modale : seuls son bouton et le rafraîchissement passent."""
    import time

    now = time.time()
    if now - _state["t"] < 0.2:
        return
    _state["t"] = now
    try:
        import FreeCAD

        if FreeCAD.GuiUp:
            import FreeCADGui

            FreeCADGui.updateGui()
    except Exception:
        pass


#: empreinte SHA-1 de ``_workingEdgeHelperRoughing`` de FreeCAD 1.1.4 (le remplacement n'est installé que sur
#: cette version exacte du code)
ROUGHING_HELPER_SHA1 = "dba8a4f537de339e8a419ff74a3291e9e5447226"


def _patch_roughing_regions(mod):
    """Ébauche 3D en mode « modèle » : à chaque niveau, FreeCAD compare chaque nouvelle face aux régions déjà
    connues par une découpe booléenne complète (``region.cut(f)``), soit 73 000 découpes et 37 s des 97 s de
    calcul sur un plateau à 135 alvéoles. Une région incluse dans ``f`` a forcément sa boîte dans celle de
    ``f`` et une aire au plus égale : ces deux tests évitent presque toutes les découpes, sans changer le
    résultat. Copie de la fonction FreeCAD avec ce filtre, installée seulement si le code d'origine est
    exactement celui attendu."""
    import hashlib
    import inspect

    original = getattr(mod, "_workingEdgeHelperRoughing", None)
    if original is None or getattr(original, "cam2027_patched", False):
        return
    try:
        if hashlib.sha1(inspect.getsource(original).encode()).hexdigest() != ROUGHING_HELPER_SHA1:
            return
    except Exception:
        return
    import Part
    import TechDraw
    import DraftGeomUtils
    import FreeCAD

    def _included(region, f, tol=1e-4):
        rb, fb = region.BoundBox, f.BoundBox
        return (rb.XMin >= fb.XMin - tol and rb.XMax <= fb.XMax + tol and rb.YMin >= fb.YMin - tol
                and rb.YMax <= fb.YMax + tol and region.Area <= f.Area + tol)

    def helper(op, obj, depths):
        from . import parallel_levels

        insideRegions = list()
        outsideRegions = list()
        shps = op.model[0].Shape.fuse([k.Shape for k in op.model[1:]])
        projdir = FreeCAD.Vector(0, 0, 1)
        modelOutlineFaces = [Part.makeFace(TechDraw.findShapeOutline(s, 1, projdir)) for s in shps.Solids]
        stock_top = op.stock.Shape.BoundBox.ZMax
        work = [d for d in depths if d < stock_top]
        # CAM2027 : régions de chaque niveau préparées en parallèle (parallel_levels), sinon une par une ici ;
        # la fusion des niveaux en régions reste dans l'ordre
        stop = lambda: bool(getattr(obj, "StopProcessing", False))  # noqa: E731
        pre = parallel_levels.compute(shps, op.stock.Shape, [d - obj.ZStockToLeave.Value for d in work], stop)
        pre = dict(zip(work, pre)) if pre is not None else {}
        for depth in depths:
            keep_gui_alive()
            if stop():  # « Arrêter le calcul » pendant la préparation
                break
            if depth >= stock_top:
                continue
            if depth in pre:
                aboveModelFaces, finalCut, stockface, aboveRefined = pre[depth]
            else:
                aboveModelFaces, finalCut, stockface, aboveRefined = parallel_levels.level_regions(
                    mod, shps, op.stock.Shape, modelOutlineFaces, depth - obj.ZStockToLeave.Value)
            if (outsideRegions and outsideRegions[-1]["region"].Wires and aboveModelFaces.Wires
                    and not aboveModelFaces.cut(outsideRegions[-1]["region"]).Wires):
                outsideRegions[-1]["depths"].append(depth)
                prev = outsideRegions[-1]["region"]
                if aboveModelFaces.Wires and abs(prev.Area - aboveModelFaces.Area) > 1e-6 * max(prev.Area, 1.0):
                    # silhouette plus petite que celle de la région gardée : poches recalculées avec celle-ci,
                    # comme FreeCAD (outsideRegions[-1])
                    finalCut = parallel_levels.final_cut_for(prev, aboveRefined, stockface, modelOutlineFaces)
            else:
                outsideRegions.append({"region": aboveModelFaces, "depths": [depth]})
            if aboveModelFaces.Wires and finalCut is not None:
                for f in finalCut.Faces:
                    addNew = True
                    for rdict in insideRegions:
                        if not _included(rdict["region"], f):  # CAM2027 : filtre avant la découpe
                            continue
                        if not rdict["region"].cut(f).Wires:
                            rdict["depths"].append(depth)
                            addNew = False
                            break
                    if addNew:
                        insideRegions.append({"region": f, "depths": [depth]})
        return insideRegions, outsideRegions

    helper.cam2027_patched = True
    mod._workingEdgeHelperRoughing = helper


#: empreintes SHA-1 du code FreeCAD remplacé par ``patch_pocket`` (même code en 1.0.2 et 1.1.4, sauf
#: ``_buildPathArea`` : une empreinte par version, la partie utilisée est identique)
POCKET_SHAPES_SHA1 = "a9c3e2225a919f4b0d9dff1524197fe101612391"
POCKET_REMOVAL_SHA1 = "b57fc89eee79edc8a647e0d70f066236ff25c6b7"
AREA_BUILD_SHA1 = ("c947d9bb22a0e7b54043af311f1572c5fcb30703",  # 1.1.4
                   "af27b6f0ede71f0493e55f8aeaf05ae1dd1660c1")  # 1.0.2


def _sha1(fn):
    import hashlib
    import inspect

    try:
        return hashlib.sha1(inspect.getsource(fn).encode()).hexdigest()
    except Exception:
        return None


def patch_pocket(mod=None):
    """Poche 3D sur des faces traitées « collectivement » (fonds d'alvéoles choisis automatiquement) : les
    booléens d'OpenCascade de ``areaOpShapes`` (découpe de l'enveloppe, intersections avec les fonds) et la
    découpe en niveaux de ``_buildPathArea`` sont faits dans des processus (``parallel_pocket``), l'interface
    restant vivante : 26 s -> moins de 10 s sur un plateau à 135 alvéoles, mêmes volumes. Installé seulement
    si le code FreeCAD est exactement celui attendu ; les autres cas passent par le code d'origine."""
    if mod is None:
        mod = importlib.import_module("Path.Op.Pocket")
    cls = getattr(mod, "ObjectPocket", None)
    original = getattr(cls, "areaOpShapes", None)
    if original is None or getattr(original, "cam2027_patched", False):
        return
    import Path.Op.Area as area_mod

    build = area_mod.ObjectOp._buildPathArea
    if (_sha1(original) != POCKET_SHAPES_SHA1 or _sha1(getattr(mod, "_identifyRemovalSolids", None)) != POCKET_REMOVAL_SHA1
            or _sha1(build) not in AREA_BUILD_SHA1):
        return
    from . import parallel_pocket

    def collective(obj):
        if obj.HandleMultipleFeatures != "Collectively" or obj.AdaptivePocketStart or obj.AdaptivePocketFinish:
            return False
        return all(base[1] and all("Face" in sub for sub in base[1]) for base in obj.Base)

    def area_op_shapes(self, obj):
        if not obj.Base or not collective(obj):
            return original(self, obj)
        # branche « faces, collectivement » de FreeCAD, la découpe et les intersections en parallèle
        import FreeCAD
        import Part

        removalshapes = []
        for base in obj.Base:
            Faces = [getattr(base[0].Shape, sub) for sub in base[1]]
            (fzmin, fzmax) = self.getMinMaxOfFaces(Faces)
            if obj.FinalDepth.Value < fzmin:
                mod.Path.Log.warning(mod.translate("CAM", "Final depth set below ZMin of face(s) selected."))
            shape = Part.makeCompound(Faces)
            env = mod.PathUtils.getEnvelope(base[0].Shape, subshape=shape, depthparams=self.depthparams)
            faceExtrusions = [f.extrude(FreeCAD.Vector(0.0, 0.0, 1.0)) for f in Faces]
            removal = parallel_pocket.removal_solids(env, base[0].Shape, faceExtrusions)
            if removal is None:
                removal = mod._identifyRemovalSolids(env.cut(base[0].Shape), faceExtrusions)
            obj.removalshape = removal
            removalshapes.append((obj.removalshape, False, "3DPocket"))
        return removalshapes

    def build_path_area(self, obj, baseobject, isHole, start, getsim):
        return parallel_pocket.build_path_area(area_mod, build, self, obj, baseobject, isHole, start, getsim)

    area_op_shapes.cam2027_patched = True
    cls.areaOpShapes = area_op_shapes
    cls._buildPathArea = build_path_area


def create_operation(job, kind, name, tool_controller, base=None, params=None):
    """Crée l'opération dans le job ; retourne (objet, liste de paramètres ignorés).

    ``base`` : liste de tuples ``(objet, ["Face6", "Edge3"])``. Les objets
    doivent être les clones du modèle du job (``job.Model.Group``) ; un objet
    source est remplacé automatiquement par son clone.
    ``params`` : propriétés FreeCAD de l'opération ; les noms inconnus pour la
    stratégie sont retournés dans la liste « ignorés » (et signalés).
    """
    import FreeCAD

    import PathScripts.PathUtils as PathUtils

    doc = job.Document
    previous = FreeCAD.ActiveDocument
    FreeCAD.setActiveDocument(doc.Name)
    # FreeCAD choisit le ToolController par défaut via PathUtils.UserInput (dialogue
    # en mode graphique, variable non liée en mode console quand le job a plusieurs
    # contrôleurs). On impose le nôtre le temps de la création.
    saved_input = PathUtils.UserInput
    PathUtils.UserInput = _ForcedToolController(tool_controller)
    # FreeCAD 1.0 : Create() des opérations sur trous (perçage, hélice, filetage) cherche
    # les trous avant que le modèle du job soit résolu (self.model = None) ; on le fournit.
    import Path.Op.CircularHoleBase as CircularHoleBase

    saved_find = CircularHoleBase.ObjectOp.findAllHoles

    def _find_all_holes(proxy, obj):
        if proxy.model is None:
            proxy.model = job.Model.Group
        return saved_find(proxy, obj)

    CircularHoleBase.ObjectOp.findAllHoles = _find_all_holes
    try:
        mod = strategy_module(kind)
        op = mod.Create(name, parentJob=job)
    finally:
        PathUtils.UserInput = saved_input
        CircularHoleBase.ObjectOp.findAllHoles = saved_find
        if previous is not None and previous.Name != doc.Name:
            try:
                FreeCAD.setActiveDocument(previous.Name)
            except Exception:
                pass
    op.Label = name
    op.ToolController = tool_controller
    if FreeCAD.GuiUp and op.ViewObject is not None:
        # même fournisseur de vue que l'atelier CAM (icône, panneau de tâches, affichage du parcours)
        import Path.Op.Gui.Base as PathOpGui

        gui_mod = importlib.import_module(STRATEGIES[kind]["module"].replace("Path.Op.", "Path.Op.Gui."))
        op.ViewObject.Proxy = PathOpGui.ViewProvider(op.ViewObject, gui_mod.Command.res)
        op.ViewObject.Visibility = True
    model_aware_objects = None
    if kind == "rough3d":
        whole = all(not subs for _o, subs in (base or []))
        if whole and "ModelAwareExperiment" in op.PropertiesList:
            # pièce entière : mode « modèle » de l'adaptative (FreeCAD 1.1) : pièce et brut tranchés à chaque
            # niveau. Le mode classique avec toutes les faces en relief comme base (1152 faces pour un plateau
            # à alvéoles) calculait plus de 15 min, interface figée.
            op.ModelAwareExperiment = True
            model_aware_objects = [model_clone(job, obj) for obj, _s in (base or [])] or list(job.Model.Group)
            base = []
        else:
            base = [(obj, list(subs) or raised_faces(model_clone(job, obj))) for obj, subs in (base or [])]
            faces = sum(len(subs) for _o, subs in base)
            if whole and faces > MAX_CLASSIC_ROUGH_FACES:
                raise UserError("3D roughing of the whole part ({n} faces in relief) is too slow without the model-aware mode of FreeCAD 1.1: select the faces to rough",
                                n=faces)
    explicit = [(model_clone(job, obj), list(subs)) for obj, subs in (base or []) if subs]
    if explicit:
        op.Base = explicit
    elif base and kind not in HOLE_STRATEGIES:
        op.Base = [(model_clone(job, obj), []) for obj, _subs in base]
    # stratégies sur trous sans sous-élément : garder les trous détectés par FreeCAD (findAllHoles)
    ignored = set_params(op, params)
    if model_aware_objects is not None:
        extra = {"ZStockToLeave": params.get("StockToLeave", 0.5)}
        if "FinalDepth" not in params:  # sinon : dessus de la pièce, un seul niveau
            extra["FinalDepth"] = min(o.Shape.BoundBox.ZMin for o in model_aware_objects)
        set_params(op, extra)
    if getattr(op, "Active", None) is False:
        op.Active = True
    return op, ignored


def set_params(op, params):
    """Applique des propriétés à une opération ; retourne la liste des noms inconnus (ignorés)."""
    ignored = []
    for key, value in (params or {}).items():
        if key not in op.PropertiesList:
            ignored.append(key)
            continue
        type_id = op.getTypeIdOfProperty(key)
        if type_id in _QUANTITY_TYPES:
            # couper l'expression héritée de la feuille de réglage avant d'imposer une valeur
            op.setExpression(key, None)
        if _KINDS.get(type_id) == "vector" and isinstance(value, (tuple, list)):
            import FreeCAD

            value = FreeCAD.Vector(*[float(v) for v in value])
        setattr(op, key, value)
    return ignored


_QUANTITY_TYPES = ("App::PropertyLength", "App::PropertyDistance", "App::PropertyAngle", "App::PropertyQuantity",
                   "App::PropertySpeed", "App::PropertyTime")

#: type de propriété FreeCAD -> genre simple pour l'éditeur
_KINDS = {
    "App::PropertyLength": "length",
    "App::PropertyDistance": "length",
    "App::PropertyAngle": "angle",
    "App::PropertyPercent": "percent",
    "App::PropertyInteger": "int",
    "App::PropertyIntegerConstraint": "int",
    "App::PropertyBool": "bool",
    "App::PropertyEnumeration": "enum",
    "App::PropertyFloat": "float",
    "App::PropertyFloatConstraint": "float",
    "App::PropertyQuantity": "float",
    "App::PropertyTime": "float",
    "App::PropertyString": "string",
    "App::PropertyVector": "vector",
    "App::PropertyVectorDistance": "vector",
    "App::PropertyPosition": "vector",
}


def param_kind(op, name):
    """Retourne (genre, choix) d'une propriété : genre parmi length/angle/percent/int/bool/enum/float/string/other."""
    type_id = op.getTypeIdOfProperty(name)
    kind = _KINDS.get(type_id, "other")
    choices = tuple(op.getEnumerationsOfProperty(name)) if kind == "enum" else ()
    return kind, choices


def read_params(op, names):
    """Valeurs courantes (nombres en mm / degrés, chaînes, booléens) des propriétés existantes."""
    values = {}
    for name in names:
        if name not in op.PropertiesList:
            continue
        kind, _choices = param_kind(op, name)
        value = getattr(op, name)
        if kind in ("length", "angle"):
            value = float(value.getValueAs("mm" if kind == "length" else "deg")) if hasattr(value, "getValueAs") else float(value)
        elif kind == "float" and hasattr(value, "Value"):
            value = float(value.Value)
        elif kind == "vector":
            value = (float(value.x), float(value.y), float(value.z))
        elif kind == "other":
            continue
        values[name] = value
    return values


class _ForcedToolController(object):
    def __init__(self, tc):
        self.tc = tc

    def selectedToolController(self):
        return self.tc

    def chooseToolController(self, controllers):
        return self.tc


def raised_faces(obj, tol=1e-6):
    """Faces « en relief » d'un solide pour l'ébauche 3D : faces non planes et faces planes non horizontales
    situées au-dessus du plus bas plancher horizontal supérieur (le dessus de la plaque d'appui)."""
    shape = obj.Shape
    source = (getattr(obj, "Objects", None) or [obj])[0]
    if hasattr(source, "ReliefBase") or hasattr(obj, "ReliefBase"):
        # relief depuis une image : la surface du dessus seule (ses parois descendent jusqu'au fond)
        curved = [(f.Area, i) for i, f in enumerate(shape.Faces, 1) if f.Surface.__class__.__name__ != "Plane"]
        return ["Face%d" % max(curved)[1]] if curved else []
    floors = []
    for f in shape.Faces:
        if f.Surface.__class__.__name__ == "Plane" and abs(f.BoundBox.ZMax - f.BoundBox.ZMin) < tol \
                and f.BoundBox.ZMax > shape.BoundBox.ZMin + tol:
            floors.append(f.BoundBox.ZMax)
    floor = min(floors) if floors else shape.BoundBox.ZMin
    names = []
    for i, f in enumerate(shape.Faces, 1):
        bb = f.BoundBox
        horizontal = f.Surface.__class__.__name__ == "Plane" and abs(bb.ZMax - bb.ZMin) < tol
        if not horizontal and bb.ZMax > floor + tol:
            names.append("Face%d" % i)
    return names


def model_clone(job, obj):
    """Clone du job correspondant a un objet source (ou l'objet lui-meme s'il est deja un clone)."""
    if obj in job.Model.Group:
        return obj
    for clone in job.Model.Group:
        if getattr(clone, "Objects", None) and obj in clone.Objects:
            return clone
        if getattr(clone, "Base", None) is obj:
            return clone
    return obj


#: états de calcul normalisés (charte « Atelier ») -> (libellé anglais, niveau d'état pour la couleur)
COMPUTE_STATES = {
    "inactive": ("Inactive", "muted"),
    "todo": ("To compute", "todo"),
    "stale": ("To recompute", "stale"),
    "failed": ("Failed", "error"),
    "warning": ("Warning", "warning"),
    "computed": ("Computed", "ok"),
}


_CUTTING_CODES = ("G1", "G01", "G2", "G02", "G3", "G03", "G73", "G81", "G82", "G83", "G84", "G85")


def compute_state(obj, base=None, record=None):
    """État de calcul d'une opération (ou de son habillage ``obj``) d'après l'objet FreeCAD.

    Lu sur l'état réel du document (``State`` / ``isValid`` / commandes), jamais maintenu à part :
    ``todo`` = jamais calculée, ``stale`` = dépendance modifiée depuis le dernier calcul,
    ``failed`` = calcul en erreur ou parcours vide, ``warning`` = calculée avec avertissements
    (approximation d'outil, paramètres ignorés), ``computed`` = calculée. « computed » ne veut pas
    dire « vérifiée » ni « sûre pour la machine ».
    """
    base = base or obj
    if getattr(base, "Active", True) is False:
        return "inactive"
    states = set(getattr(obj, "State", []) or []) | set(getattr(base, "State", []) or [])
    stats = path_stats(obj.Path, obj) if getattr(obj, "Path", None) is not None else None
    cutting = stats["cutting"] if stats else 0
    if "Invalid" in states or not obj.isValid():
        return "failed"
    if "Touched" in states:
        return "todo" if not (stats and stats["commands"]) else "stale"
    if cutting == 0:
        return "failed"  # aucun mouvement de coupe : rien ne sera usiné
    if record and (record.get("warnings") or record.get("ignored_params")):
        return "warning"
    return "computed"


#: statistiques de parcours déjà lues : empreinte -> statistiques (le panneau Projet les relit à chaque
#: rafraîchissement ; relire 350 000 commandes en Python prend environ une seconde)
_PATH_STATS = {}
_PATH_STATS_MAX = 64


def _feed_key(obj):
    """Avances et vitesse du contrôleur d'outil de l'opération (ou de l'opération habillée) : elles changent
    les F du parcours sans changer sa géométrie."""
    seen = 0
    while obj is not None and seen < 8:
        tc = getattr(obj, "ToolController", None)
        if tc is not None:
            return tuple(round(float(getattr(getattr(tc, k, None), "Value", getattr(tc, k, 0) or 0)), 6)
                         for k in ("HorizFeed", "VertFeed", "SpindleSpeed"))
        obj = getattr(obj, "Base", None)
        seen += 1
    return ()


def path_stats(path, owner=None):
    """Commandes, mouvements de coupe, avances (mm/min), axes, codes et enveloppe d'un ``Path`` ; lus une fois
    par parcours (empreinte sans relire les commandes : nombre, longueur, boîte englobante, avances du
    contrôleur d'outil de ``owner``)."""
    bb = path.BoundBox
    key = (path.Size, round(float(path.Length), 9),
           tuple(round(v, 9) for v in (bb.XMin, bb.YMin, bb.ZMin, bb.XMax, bb.YMax, bb.ZMax)),
           getattr(owner, "Name", None), _feed_key(owner))
    hit = _PATH_STATS.get(key)
    if hit is not None:
        return hit
    cmds = path.Commands
    feeds = set()
    axes = set()
    bbox = {}
    cutting = 0
    for c in cmds:
        if c.Name in _CUTTING_CODES:
            cutting += 1
        params = c.Parameters
        if "F" in params:
            feeds.add(round(float(params["F"]) * 60.0, 3))
        for k, v in params.items():
            if k in ("X", "Y", "Z", "A", "B", "C"):
                axes.add(k)
                lo, hi = bbox.get(k, (v, v))
                bbox[k] = (min(lo, v), max(hi, v))
    stats = {"commands": len(cmds), "cutting": cutting, "feeds": sorted(feeds), "axes": sorted(axes),
             "gcodes": sorted(set(c.Name for c in cmds)), "bbox": bbox, "length_mm": float(path.Length)}
    if len(_PATH_STATS) >= _PATH_STATS_MAX:
        _PATH_STATS.clear()
    _PATH_STATS[key] = stats
    return stats


def toolpath_summary(op):
    """Résumé du parcours calculé (pour l'examen et les tests).

    Les avances des commandes Path sont en mm/s (unité interne FreeCAD) ; elles
    sont converties en mm/min. L'enveloppe est calculée sur les points
    programmés (``Path.BoundBox`` inclut l'origine et n'est pas utilisable).
    """
    st = path_stats(op.Path, op)
    bbox = st["bbox"]
    return {
        "name": op.Label,
        "commands": st["commands"],
        "length_mm": st["length_mm"],
        "feeds": st["feeds"],
        "axes": st["axes"],
        "gcodes": st["gcodes"],
        "bbox": dict(bbox),
        "zmin": bbox["Z"][0] if "Z" in bbox else None,
        "zmax": bbox["Z"][1] if "Z" in bbox else None,
        "cycle_time": getattr(op, "CycleTime", None),
    }
