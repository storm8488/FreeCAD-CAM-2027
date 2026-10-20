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
        "limits": "No flat-depth clearing with a second tool yet (Aspire 'flat depth' equivalent missing).",
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


def resolve_params(kind, tool, params):
    """Complète les paramètres d'une stratégie à partir de l'outil de la bibliothèque.

    Fraisage de filets : un ``ThreadName`` est résolu en diamètres/pas via la
    table FreeCAD ; sans pas ni TPI, le pas (maximal) de l'outil est utilisé ;
    le pas demandé doit rester dans la plage ``pitch_min``..``pitch`` de l'outil.
    """
    params = dict(params or {})
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
    return importlib.import_module(STRATEGIES[kind]["module"])


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
    explicit = [(model_clone(job, obj), list(subs)) for obj, subs in (base or []) if subs]
    if explicit:
        op.Base = explicit
    elif base and kind not in HOLE_STRATEGIES:
        op.Base = [(model_clone(job, obj), []) for obj, _subs in base]
    # stratégies sur trous sans sous-élément : garder les trous détectés par FreeCAD (findAllHoles)
    ignored = set_params(op, params)
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


def toolpath_summary(op):
    """Résumé du parcours calculé (pour l'examen et les tests).

    Les avances des commandes Path sont en mm/s (unité interne FreeCAD) ; elles
    sont converties en mm/min. L'enveloppe est calculée sur les points
    programmés (``Path.BoundBox`` inclut l'origine et n'est pas utilisable).
    """
    path = op.Path
    cmds = path.Commands
    feeds = set()
    axes = set()
    bbox = {}
    for c in cmds:
        params = c.Parameters
        if "F" in params:
            feeds.add(round(float(params["F"]) * 60.0, 3))
        for k, v in params.items():
            if k in ("X", "Y", "Z", "A", "B", "C"):
                axes.add(k)
                lo, hi = bbox.get(k, (v, v))
                bbox[k] = (min(lo, v), max(hi, v))
    gcodes = sorted(set(c.Name for c in cmds))
    return {
        "name": op.Label,
        "commands": len(cmds),
        "length_mm": float(path.Length),
        "feeds": sorted(feeds),
        "axes": sorted(axes),
        "gcodes": gcodes,
        "bbox": bbox,
        "zmin": bbox["Z"][0] if "Z" in bbox else None,
        "zmax": bbox["Z"][1] if "Z" in bbox else None,
        "cycle_time": getattr(op, "CycleTime", None),
    }
