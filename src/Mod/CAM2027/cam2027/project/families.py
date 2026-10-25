# SPDX-License-Identifier: LGPL-2.1-or-later
"""Familles d'opérations par résultat (Surfaçage, Poche, Contour / découpe, Perçage, Gravure / V-carving,
Ébauche, Finition 3D) : c'est l'ordre et le vocabulaire de « Ajouter une opération ».

Chaque stratégie de ``operations.STRATEGIES`` est dans une famille et une seule, avec un nom court, un usage,
la sélection attendue et le moteur qui la calcule. Un moteur alternatif (``alternatives``) est proposé comme
choix secondaire explicite de la stratégie principale ; le moteur d'une opération existante n'est jamais
remplacé en silence (une autre stratégie = une autre opération).

Module pur (sans Qt ni FreeCAD) : testé par ``tests/test_families.py``.
"""

from .operations import STRATEGIES, TOOLS_FOR

#: (clé, libellé, icône « Atelier », stratégies dans l'ordre de présentation)
FAMILIES = (
    ("facing", "Facing", "surface", ("millface",)),
    ("pocket", "Pocket", "pocket", ("offsetpocket", "pocket", "pocket2d")),
    ("contour", "Contour and cut-out", "contour", ("profile", "slot", "chamfer")),
    ("drilling", "Drilling", "drill", ("drilling", "helix", "threadmill")),
    ("engraving", "Engraving and V-carving", "engrave", ("engrave", "vcarve")),
    ("roughing", "Roughing", "pocket", ("stockrough", "adaptive", "rough3d")),
    ("finishing3d", "3D finishing", "surface", ("surface3d", "waterline", "scallop", "flat3d", "pencil")),
)

#: stratégie -> nom court, usage, sélection attendue, moteur, moteurs alternatifs (stratégies secondaires)
STRATEGY_INFO = {
    "millface": {"short": "Facing", "usage": "Flatten the top of the stock or a face down to a height.",
                 "selection": "Nothing (top of the part), or the faces to face.", "engine": "FreeCAD", "alternatives": ()},
    "offsetpocket": {"short": "Pocket", "usage": "Clear a closed area down to its floor, every floor in one operation, helical entry.",
                     "selection": "Nothing (pocket floors found automatically), floors, or closed drawing contours.",
                     "engine": "CAM2027", "alternatives": ("pocket",)},
    "pocket": {"short": "Pocket (FreeCAD engine)", "usage": "Clear a closed area with offset, zigzag or spiral passes.",
               "selection": "Pocket floors, or nothing (floors found automatically).", "engine": "FreeCAD", "alternatives": ()},
    "pocket2d": {"short": "Pocket inside a drawing", "usage": "Clear the inside of a closed contour of a 2D drawing (SVG, DXF, text).",
                 "selection": "One or more closed drawing contours.", "engine": "FreeCAD", "alternatives": ()},
    "profile": {"short": "Contour", "usage": "Follow the outside or the inside of a shape; cut-out with holding tags.",
                "selection": "Nothing (outside of the part), edges, faces or drawing contours.", "engine": "FreeCAD", "alternatives": ()},
    "slot": {"short": "Slot", "usage": "One straight slot between two points or along an edge.",
             "selection": "Two vertices, an edge, or nothing (custom points).", "engine": "FreeCAD", "alternatives": ()},
    "chamfer": {"short": "Chamfer / deburr", "usage": "Break the top edges with a V-bit or a chamfer cutter.",
                "selection": "The edges or faces to chamfer.", "engine": "FreeCAD", "alternatives": ()},
    "drilling": {"short": "Drilling", "usage": "Drill the round holes (G81 / G82 / G83 cycles, peck and dwell).",
                 "selection": "Nothing (every hole larger than the drill), or the holes.", "engine": "FreeCAD", "alternatives": ()},
    "helix": {"short": "Helical boring", "usage": "Open a round hole wider than the tool with a helix.",
              "selection": "Nothing (every round hole wider than the tool), or the holes.", "engine": "FreeCAD", "alternatives": ()},
    "threadmill": {"short": "Thread milling", "usage": "Cut an internal or external thread with a thread mill.",
                   "selection": "The drilled holes (standard table or custom thread).", "engine": "FreeCAD", "alternatives": ()},
    "engrave": {"short": "Engraving", "usage": "Follow drawing lines at a fixed depth (text, lines).",
                "selection": "Drawing vectors or edges.", "engine": "FreeCAD", "alternatives": ()},
    "vcarve": {"short": "V-carving", "usage": "Carve closed shapes with a V-bit, depth following the width (medial axis).",
               "selection": "Closed drawing contours (text, logos).", "engine": "FreeCAD", "alternatives": ()},
    "stockrough": {"short": "2.5D roughing", "usage": "Rough the whole part level by level on the shared stock model; later operations take only what is left.",
                   "selection": "Nothing (whole part).", "engine": "CAM2027", "alternatives": ()},
    "adaptive": {"short": "2D adaptive clearing", "usage": "Clear areas with a controlled engagement (trochoidal paths, full depth of cut).",
                 "selection": "Nothing (pocket floors found automatically), or the floors.", "engine": "FreeCAD", "alternatives": ()},
    "rough3d": {"short": "3D adaptive roughing", "usage": "Rough a 3D shape from the stock down to the model, level by level.",
                "selection": "Nothing (whole part).", "engine": "FreeCAD", "alternatives": ()},
    "surface3d": {"short": "3D parallel finishing", "usage": "Finish a 3D surface with parallel, zigzag or offset passes.",
                  "selection": "Nothing (whole part), or the faces.", "engine": "OpenCamLib", "alternatives": ()},
    "waterline": {"short": "Constant-Z finishing", "usage": "Finish steep walls with passes at constant Z.",
                  "selection": "Nothing (whole part), or the faces.", "engine": "OpenCamLib", "alternatives": ()},
    "scallop": {"short": "Constant scallop finishing", "usage": "Finish with a constant ridge height: constant Z on steep areas, constant step on shallow areas.",
                "selection": "Nothing (whole part), or the faces.", "engine": "OpenCamLib", "alternatives": ()},
    "flat3d": {"short": "Flat areas finishing", "usage": "Finish every flat area of a 3D part at its own height.",
               "selection": "Nothing (every flat area), or the flat faces.", "engine": "CAM2027", "alternatives": ()},
    "pencil": {"short": "Corner rest finishing", "usage": "Take again the corners a larger ball end mill could not reach.",
               "selection": "Nothing (whole part).", "engine": "CAM2027", "alternatives": ()},
}


def family_of(kind):
    """Clé de la famille d'une stratégie (``None`` pour une opération générée hors des stratégies)."""
    for key, _label, _icon, kinds in FAMILIES:
        if kind in kinds:
            return key
    return None


def family_label(key):
    for fkey, label, _icon, _kinds in FAMILIES:
        if fkey == key:
            return label
    return key


def primary_kinds(key):
    """Stratégies présentées dans une famille : celles qui ne sont pas un moteur alternatif d'une autre."""
    secondary = {alt for info in STRATEGY_INFO.values() for alt in info["alternatives"]}
    for fkey, _label, _icon, kinds in FAMILIES:
        if fkey == key:
            return tuple(k for k in kinds if k not in secondary)
    return ()


def info(kind):
    """Nom court, usage, sélection attendue, moteur et alternatives d'une stratégie (libellés anglais)."""
    return STRATEGY_INFO[kind]


def tool_types(kind):
    """Types d'outil compatibles (clés de ``tools.model.TOOL_TYPES``), ordre de préférence."""
    return tuple(TOOLS_FOR.get(kind, ()))


def check():
    """Chaque stratégie dans une famille et une seule, avec sa fiche ; retourne la liste des écarts."""
    problems = []
    seen = {}
    for key, _label, _icon, kinds in FAMILIES:
        for k in kinds:
            if k in seen:
                problems.append("%s in two families: %s, %s" % (k, seen[k], key))
            seen[k] = key
            if k not in STRATEGIES:
                problems.append("%s is not a strategy" % k)
            if k not in STRATEGY_INFO:
                problems.append("%s has no info" % k)
    for k in STRATEGIES:
        if k not in seen:
            problems.append("%s in no family" % k)
    for k, inf in STRATEGY_INFO.items():
        for alt in inf["alternatives"]:
            if family_of(alt) != family_of(k):
                problems.append("%s: alternative %s in another family" % (k, alt))
    return problems
