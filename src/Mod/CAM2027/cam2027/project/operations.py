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

import importlib

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
        "limits": "",
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
        "params": ("CutPattern", "ExtendPathStart", "ExtendPathEnd", "LayerMode", "PathOrientation",
                   "ReverseDirection", "StepDown", "StartDepth", "FinalDepth", "ClearanceHeight", "SafeHeight"),
        "limits": "",
    },
}


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
    try:
        mod = strategy_module(kind)
        op = mod.Create(name, parentJob=job)
    finally:
        PathUtils.UserInput = saved_input
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
    if base:
        op.Base = [(_model_clone(job, obj), list(subs)) for obj, subs in base]
    ignored = []
    for key, value in (params or {}).items():
        if key not in op.PropertiesList:
            ignored.append(key)
            continue
        if key in ("StartDepth", "FinalDepth", "StepDown", "ClearanceHeight", "SafeHeight", "FinishDepth",
                   "OffsetExtra", "ExtraOffset", "StockToLeave", "StepOver", "PeckDepth", "RetractHeight",
                   "LiftDistance", "StartRadius", "Tolerance"):
            # couper l'expression héritée de la feuille de réglage avant d'imposer une valeur
            op.setExpression(key, None)
        setattr(op, key, value)
    if getattr(op, "Active", None) is False:
        op.Active = True
    return op, ignored


class _ForcedToolController(object):
    def __init__(self, tc):
        self.tc = tc

    def selectedToolController(self):
        return self.tc

    def chooseToolController(self, controllers):
        return self.tc


def _model_clone(job, obj):
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
