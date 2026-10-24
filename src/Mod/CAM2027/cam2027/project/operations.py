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
import math
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
        "params": ("CutMode", "StepOver", "ZigZagAngle", "OffsetPattern", "ClearingPattern", "StartAt", "ExtraOffset",
                   "KeepToolDown", "MinTravel", "UseOutline", "StepDown", "StartDepth", "FinalDepth",
                   "FinishDepth", "ClearanceHeight", "SafeHeight", "HelixAngle", "HelixDiameterLimit"),
        "limits": "Offset/zigzag/spiral patterns are NOT adaptive (no engagement control); use 'adaptive'.",
    },
    "offsetpocket": {
        "module": "cam2027.project.offsetpocket",
        "label": "2D pocket (offset passes, every floor in one operation, helical entry)",
        "params": ("StepDown", "StepOver", "StockToLeave", "HelixAngle", "HelixDiameterLimit", "StartDepth", "FinalDepth",
                   "ClearanceHeight", "SafeHeight"),
        "limits": "Flat horizontal faces (drawing faces, pocket floors), vertical walls; offset passes from the inside "
                  "out, the last one along the walls; a pocket floor of a solid is cut down to its own height, a "
                  "drawing face down to the final depth; zones narrower than the tool are skipped and reported.",
    },
    "pocket2d": {
        "module": "Path.Op.PocketShape",
        "label": "2D pocket (inside a drawing contour)",
        "params": ("CutMode", "StepOver", "ZigZagAngle", "OffsetPattern", "ClearingPattern", "StartAt", "ExtraOffset",
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
        "params": ("BoundaryShape", "StepOver", "CutMode", "ZigZagAngle", "OffsetPattern", "ClearingPattern", "StepDown",
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
    "stockrough": {
        "module": "cam2027.project.stockrough",
        "label": "2.5D roughing on the stock model (all depths, every body protected)",
        "params": ("StepDown", "StepOver", "StockToLeave", "RestMachining", "Resolution", "HelixAngle", "HelixDiameterLimit",
                   "WallPass", "StartDepth", "FinalDepth", "ClearanceHeight", "SafeHeight"),
        "limits": "Flat end mill; clears the whole stock above the part level by level on a height map shared with the "
                  "material check (pocket floors at every depth in one operation, other bodies never cut); helical "
                  "entries, raster passes then a wall pass; steps remain on slopes (use a 3D finishing).",
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
    },    "scallop": {
        "module": "cam2027.project.scallop",
        "label": "3D constant scallop finishing (steep and shallow, OpenCamLib)",
        "params": ("ScallopHeight", "SteepShallow", "ThresholdAngle", "SampleInterval", "DepthOffset", "BoundBox",
                   "LinearDeflection", "StartDepth", "FinalDepth", "ClearanceHeight", "SafeHeight"),
        "limits": "Ball or bull nose mill; passes offset along the surface from the boundary (constant 3D step); "
                  "steep-and-shallow mode cuts at constant Z above the threshold angle; no rest machining.",
    },
    "flat3d": {
        "module": "cam2027.project.flatfinish",
        "label": "3D flat areas finishing (offset passes at each flat height)",
        "params": ("StepOver", "StockToLeave", "DepthOffset", "ClearanceHeight", "SafeHeight"),
        "limits": "Horizontal flat faces reachable from above (part top, pocket floors), each at its exact height, "
                  "tool kept inside the flat area; run it after roughing (plunges straight down at the start of "
                  "each area).",
    },
    "pencil": {
        "module": "cam2027.project.pencil",
        "label": "3D corner rest finishing (pencil, ball end mill)",
        "params": ("ReferenceDiameter", "StepOver", "Threshold", "MaxSlope", "ClearanceHeight", "SafeHeight"),
        "limits": "Passes along the inner corners left by a larger reference ball (fillets smaller than its "
                  "radius), heights by OpenCamLib on the triangulated part; every pass starts from the safe height.",
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
#: types d'outil de la bibliothèque proposés pour chaque stratégie, dans l'ordre de préférence (le premier
#: présent est présélectionné), d'après l'usage de chaque fraise dans Fusion, limités aux formes que FreeCAD
#: sait calculer et simuler :
#: - surfaçage : fraise à surfacer (son usage), puis fraise deux tailles ou torique ;
#: - contour 2D : fraises deux tailles / torique / boule, et queue d'aronde, à rainurer, lollipop pour les
#:   contre-dépouilles et rainures latérales ;
#: - poches, adaptative, hélice : fraises qui coupent au centre (pas de fraise à surfacer ni à rainurer) ;
#: - ébauche 3D : deux tailles, torique, boule (Fusion accepte la boule en ébauche adaptative) ;
#: - finitions 3D : boule d'abord, torique, conique à bout rond, deux tailles ;
#: - perçage : foret, ou fraise deux tailles en plongée ; filetage : fraise à fileter ;
#: - V-carving, chanfrein : outils à pointe en V ; gravure : en V, boule ou deux tailles.
TOOLS_FOR = {
    "profile": _MILLS + ("dovetail", "slot", "lollipop"), "pocket": _MILLS, "pocket2d": _MILLS,
    "adaptive": ("endmill", "bullnose"), "millface": ("facemill", "endmill", "bullnose"),
    "slot": _MILLS + ("slot",), "helix": ("endmill", "bullnose"),
    "rough3d": ("endmill", "bullnose", "ballend"), "surface3d": ("ballend", "bullnose", "taperedball", "endmill"),
    "waterline": ("ballend", "bullnose", "endmill"), "drilling": ("drill", "endmill"), "threadmill": ("threadmill",),
    "vcarve": ("vbit", "engrave", "chamfer"), "engrave": ("vbit", "engrave", "chamfer", "ballend", "endmill"),
    "chamfer": ("chamfer", "vbit", "engrave"),
    "flat3d": ("endmill", "bullnose", "facemill"),
    "stockrough": ("endmill",),
    "offsetpocket": ("endmill", "bullnose"),
    "pencil": ("ballend",),
    "scallop": ("ballend", "bullnose"),
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


def pocket_floor_faces(obj, tol=1e-6, others=()):
    """Fonds de poche d'un solide : faces planes horizontales strictement entre le dessous et le dessus, sans
    matière au-dessus d'elles. Un fond sous un surplomb n'est pas accessible par le dessus : la poche FreeCAD
    l'extrude vers le haut et usine à travers le surplomb. ``others`` : formes des autres corps du job, dont la
    matière compte aussi (cavité du socle du chauffage Vz330 fermée par le couvercle, un autre corps)."""
    import FreeCAD

    shape = obj.Shape
    bb = shape.BoundBox
    shapes = [shape] + [o for o in others if o is not None and not o.isNull() and o.Solids]
    top = max(s.BoundBox.ZMax for s in shapes)
    # Matière dans la colonne au-dessus du fond ⇔ une face non verticale de la pièce y entre (en montant depuis
    # un point de matière, on sort par une telle face, toujours dans la colonne). Le test face à face sur les
    # seules faces voisines (boîtes englobantes) écarte vite les fonds dégagés ; l'intersection complète avec
    # la pièce (lente : 1553 faces → 9 s pour 135 fonds) ne tranche plus que les fonds douteux.
    tilted = []
    for g in (g for s in shapes for g in s.Faces):
        try:
            vertical = g.Surface.__class__.__name__ == "Plane" and abs(g.normalAt(0, 0).z) < 1e-9
        except Exception:
            vertical = False
        if not vertical:
            tilted.append((g, g.BoundBox))
    out = []
    for i, f in _horizontal_planes(shape, tol):
        if not bb.ZMin + 1e-3 < f.BoundBox.ZMin < bb.ZMax - 1e-3:
            continue
        above = f.copy()
        above.translate(FreeCAD.Vector(0, 0, 1e-3))
        column = above.extrude(FreeCAD.Vector(0, 0, top - f.BoundBox.ZMin + 1.0))
        if _column_touched(column, tilted) and any(column.common(s).Volume > 1e-3 for s in shapes):
            continue
        out.append("Face%d" % i)
    return out


def _column_touched(column, faces, eps=1e-6):
    cb = column.BoundBox
    for g, gb in faces:
        if (gb.XMax <= cb.XMin + eps or gb.XMin >= cb.XMax - eps or gb.YMax <= cb.YMin + eps
                or gb.YMin >= cb.YMax - eps or gb.ZMax <= cb.ZMin + eps):
            continue
        if g.common(column).Area > eps:
            return True
    return False


def top_faces(obj, tol=1e-6):
    """Faces planes horizontales au sommet du solide (surfaçage)."""
    top = obj.Shape.BoundBox.ZMax
    return ["Face%d" % i for i, f in _horizontal_planes(obj.Shape, tol) if abs(f.BoundBox.ZMax - top) < 1e-3]


def stock_top_face(stock):
    """Nom de la face du dessus du brut (surfaçage sans face plane au sommet de la pièce)."""
    faces = stock.Shape.Faces
    k = max(range(len(faces)), key=lambda i: (faces[i].BoundBox.ZMin, faces[i].Area))
    return "Face%d" % (k + 1)


def auto_geometry(kind, models):
    """Géométrie choisie sans sélection : ``[(objet, sous-éléments)]``, ``[]`` si rien de pertinent, ``None``
    quand la stratégie travaille sur la pièce entière."""
    if kind in ("pocket", "pocket2d", "adaptive", "offsetpocket"):  # poche 2D : faces planes (fonds trouvés, comme la poche)
        finder = pocket_floor_faces
    elif kind == "millface":
        finder = top_faces
    elif kind == "flat3d":
        from .flatfinish import flat_faces as finder
    else:
        return None
    out = []
    for obj in models:
        shape = getattr(obj, "Shape", None)
        if shape is None or not shape.Solids:
            continue
        if finder is pocket_floor_faces:
            subs = finder(obj, others=[getattr(o, "Shape", None) for o in models if o is not obj])
        else:
            subs = finder(obj)
        if subs:
            out.append((obj, subs))
    return out


def floor_groups(base, tol=1e-3):
    """Fonds de poche de ``base`` regroupés par hauteur, du plus haut au plus bas : ``[(z, base)]`` ; None si
    ``base`` contient autre chose que des faces planes horizontales. FreeCAD usine des fonds sélectionnés
    ensemble jusqu'au plus haut d'entre eux (disque WobbleRing : logements d'écrou à 141,57 laissés à 142,58)."""
    import Part

    groups = {}
    for obj, subs in base or []:
        for sub in subs:
            if not sub.startswith("Face"):
                return None
            face = obj.Shape.getElement(sub)
            if not isinstance(face.Surface, Part.Plane) or face.BoundBox.ZLength > 1e-6:
                return None
            z = face.BoundBox.ZMin
            key = next((k for k in groups if abs(k - z) <= tol), z)
            group = groups.setdefault(key, [])
            entry = next((e for e in group if e[0] is obj), None)
            if entry is None:
                group.append((obj, [sub]))
            else:
                entry[1].append(sub)
    return [(z, groups[z]) for z in sorted(groups, reverse=True)] if groups else None


def floors_have_islands(base):
    """True si un fond de ``base`` entoure de la matière (îlot, tube autour d'un trou...) ; False si ses trous
    sont vides sur toute la hauteur (trou débouchant d'un logement d'écrou du disque WobbleRing). Sans îlot, la
    poche 2D et l'adaptative peuvent usiner le contour extérieur seul (``UseOutline``), comme Fusion qui laisse
    ouvert un trou : le fond seul y est un anneau de 1,1 mm où une fraise de 3 mm ne passe pas. La colonne
    entière au-dessus du trou est testée (un îlot en anneau est vide en son centre : entaille de 1,6 mm sur le
    chauffage avec le seul centre)."""
    import FreeCAD
    import Part

    for obj, subs in base or []:
        shape = obj.Shape
        top = shape.BoundBox.ZMax
        for sub in subs:
            face = shape.getElement(sub)
            z = face.BoundBox.ZMax
            for w in face.Wires:
                if w.isSame(face.OuterWire):
                    continue
                inner = Part.Face(w)
                inner.translate(FreeCAD.Vector(0, 0, 1e-3))
                column = inner.extrude(FreeCAD.Vector(0, 0, top - z + 1.0))
                if column.common(shape).Volume > 1e-6:
                    return True
    return False


def largest_tool_for(base, precision=0.05):
    """Plus grand diamètre de fraise qui entre dans au moins une des faces de ``base`` (fonds de poche trouvés
    automatiquement), à ``precision`` près ; None sans face plane. Sert à dire pourquoi une poche ne donne
    aucun parcours (disque WobbleRing : logements de 26,5 mm², fraise de 6 mm proposée par défaut)."""
    best = None
    for obj, subs in base or []:
        for sub in subs:
            face = obj.Shape.getElement(sub)
            lo, hi = 0.0, max(face.BoundBox.XLength, face.BoundBox.YLength)

            def fits(d):
                try:
                    return bool(face.makeOffset2D(-d / 2.0).Faces)
                except Exception:
                    return False

            while hi - lo > precision:
                mid = (lo + hi) / 2.0
                if fits(mid):
                    lo = mid
                else:
                    hi = mid
            best = lo if best is None else max(best, lo)
    return best


def thread_table(thread_type):
    """Lignes (dict) de la table FreeCAD des filets standard ``Mod/CAM/Data/Threads``."""
    import FreeCAD

    mod = strategy_module("threadmill")
    filename = mod.ThreadTypeData.get(thread_type)
    if filename is None:
        raise UserError("thread type without a standard table: {thread_type}", thread_type=repr(thread_type))
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
        raise UserError("thread {name} not in the {table} table", name=repr(name), table=thread_type)
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
        raise UserError("thread milling needs a “threadmill” tool (tool: {tool_type})", tool_type=tool.tool_type)
    g = tool.geometry
    if "ThreadName" in params and "MajorDiameter" not in params:
        params.setdefault("ThreadType", DEFAULT_THREAD_TYPE)
        params.update(thread_spec(params["ThreadType"], params["ThreadName"], params.get("ThreadFit", 50)))
    if not params.get("TPI") and "Pitch" not in params:
        params["Pitch"] = g.pitch
    pitch = 25.4 / params["TPI"] if params.get("TPI") else float(params["Pitch"])
    if pitch < (g.pitch_min or 0.0) - 1e-6 or pitch > g.pitch + 1e-6:
        raise UserError("thread pitch {pitch:.3f} mm outside the range of tool {tool} ({low:.3f}-{high:.3f} mm)",
                        pitch=pitch, tool=tool.name, low=g.pitch_min or 0.0, high=g.pitch)
    return params


def _own_strategy_resources(strategy, kind):
    """Ressources de vue d'une stratégie propre à CAM2027 : les siennes (``gui_resources()``, finition à crête
    constante) sinon une page FreeCAD vide, comme elle (l'éditeur CAM2027 porte les réglages). Sans cela,
    les finitions des plats et des angles échouaient à l'ajout (« gui_resources »)."""
    if hasattr(strategy, "gui_resources"):
        return strategy.gui_resources()
    import Path.Op.Gui.Base as PathOpGui

    page = getattr(strategy, "TaskPanelOpPage", None)
    if page is None:
        class TaskPanelOpPage(PathOpGui.TaskPanelPage):
            def getForm(self):
                from ..gui.qt import QtWidgets

                return QtWidgets.QWidget()

            def getFields(self, obj):
                pass

            def setFields(self, obj):
                pass

            def getSignalsForUpdate(self, obj):
                return []

        TaskPanelOpPage.__module__ = strategy.__name__  # retrouvée à la réouverture du document
        strategy.TaskPanelOpPage = page = TaskPanelOpPage
    label = STRATEGIES[kind]["label"]
    return PathOpGui.CommandResources(kind, strategy.Create, page, "CAM_3DSurface", label, None, label)


def strategy_module(kind):
    if kind not in STRATEGIES:
        raise UserError("unknown strategy: {kind} (available: {available})",
                        kind=repr(kind), available=", ".join(sorted(STRATEGIES)))
    mod = importlib.import_module(STRATEGIES[kind]["module"])
    if kind in ("adaptive", "rough3d"):
        patch_adaptive_slicing(mod)
    if kind == "surface3d":
        patch_surface_keepalive()
    if kind in ("surface3d", "waterline"):
        patch_surface_models()
    if kind == "waterline":
        from . import parallel_waterline

        parallel_waterline.install(mod)
    if kind == "pocket":
        patch_pocket(mod)
    if kind in ("pocket2d", "adaptive"):
        patch_combine_faces()
    if kind == "pocket2d":
        patch_pocket2d(mod)
    if kind == "vcarve":
        patch_vcarve(mod)
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
        if len(line) < SIMPLIFY_NUMPY_MIN:
            return original(line, tolerance=tolerance)
        return simplify_3d_line(line, tolerance)

    simplify.cam2027_patched = True
    PathUtils.simplify3dLine = simplify
    _patch_pattern_edges()


#: en dessous (points d'une ligne ou d'une plage), Douglas-Peucker en Python comme FreeCAD : numpy y coûte plus
SIMPLIFY_NUMPY_MIN = 64


def simplify_3d_line(line, tolerance=1e-4):
    """``PathUtils.simplify3dLine`` de FreeCAD (Douglas-Peucker, mêmes points gardés) avec les distances des
    longues plages calculées par numpy : 13 millions d'appels à ``distanceToLineSegment`` (7,5 s) sur la
    finition 3D du chauffage Vz330."""
    import numpy as np

    n = len(line)
    pts = np.array([(v.x, v.y, v.z) for v in line], dtype=float)
    keep = []
    stack = [(0, n - 1)]
    while stack:
        start, end = stack.pop()
        if end - start < 2:
            keep.extend(range(start, end))
            continue
        if end - start < SIMPLIFY_NUMPY_MIN:
            index, distance = 0, 0.0
            a, b = line[start], line[end]
            for i in range(start + 1, end):
                d = line[i].distanceToLineSegment(a, b).Length
                if d > distance:
                    index, distance = i, d
        else:
            a, b = pts[start], pts[end]
            seg = b - a
            q = pts[start + 1:end]
            l2 = float(seg.dot(seg))
            if l2 == 0.0:
                closest = a
            else:
                t = np.clip((q - a).dot(seg) / l2, 0.0, 1.0)
                closest = a + t[:, None] * seg
            d = np.sqrt(((closest - q) ** 2).sum(axis=1))
            k = int(np.argmax(d))
            index, distance = start + 1 + k, float(d[k])
        if distance > tolerance:
            stack.append((index, end))
            stack.append((start, index))
        else:
            keep.append(start)
    keep.append(n - 1)
    return [line[i] for i in keep]


class _CachedEdges(object):
    """Composé de passes vu par les fonctions de motif de FreeCAD : ``compGeoShp.Edges[i]`` dans leur boucle
    reconstruit à chaque fois la liste de toutes les arêtes (coût quadratique : 5,2 s sur le chauffage Vz330) ;
    la liste est lue une fois."""

    def __init__(self, shape):
        self._shape = shape
        self.Edges = shape.Edges

    def __getattr__(self, name):
        return getattr(self._shape, name)


def _patch_pattern_edges():
    import Path.Op.SurfaceSupport as support

    for name in ("pathGeomToLinesPointSet", "pathGeomToZigzagPointSet", "pathGeomToCircularPointSet",
                 "pathGeomToSpiralPointSet"):
        original = getattr(support, name, None)
        if original is None or getattr(original, "cam2027_patched", False):
            continue

        def wrapper(*args, _original=original):
            if args and hasattr(args[-1], "Edges") and not isinstance(args[-1], _CachedEdges):
                args = args[:-1] + (_CachedEdges(args[-1]),)
            return _original(*args)

        wrapper.cam2027_patched = True
        setattr(support, name, wrapper)


def _all_models_stl(group, types, obj, ocl):
    """Triangles de tous les corps du job dans un seul modèle OpenCamLib (même triangulation que FreeCAD,
    ``SurfaceSupport._makeSTL``)."""
    stl = ocl.STLSurf()
    for model, model_type in zip(group, types):
        if model_type == "M":
            facets = model.Mesh.Facets.Points
        else:
            vertices, indices = model.Shape.tessellate(obj.LinearDeflection.Value)
            facets = ((vertices[f[0]], vertices[f[1]], vertices[f[2]]) for f in indices)
        for v1, v2, v3 in facets:
            stl.addTriangle(ocl.Triangle(ocl.Point(v1[0], v1[1], v1[2]), ocl.Point(v2[0], v2[1], v2[2]),
                                         ocl.Point(v3[0], v3[1], v3[2])))
    return stl


def _merge_whole_models(psf, faces, voids):
    """Zones des corps usinés entiers réunies dans celle du premier (les autres : rien à faire). Avec un seul
    modèle OpenCamLib pour tous les corps, chaque corps referait sinon la zone commune (couvercle du chauffage
    usiné deux fois)."""
    group = psf.JOB.Model.Group
    with_faces = {base.Name for base, subs in (psf.obj.Base or []) if any(subs)}
    whole = [m for m, model in enumerate(group)
             if isinstance(faces[m], list) and faces[m] and voids[m] is False and model.Name not in with_faces]
    if len(whole) < 2 or psf.profileEdges != "None":
        return
    shapes = [s for m in whole for s in faces[m]]
    try:
        merged = shapes[0].fuse(shapes[1:]).removeSplitter()
    except Exception:
        return
    if merged.isNull() or not merged.Faces:
        return
    faces[whole[0]] = [merged]
    for m in whole[1:]:
        faces[m] = False


def patch_surface_models():
    """Finition 3D et Z constant sur une pièce à plusieurs corps : FreeCAD calcule corps par corps avec un modèle
    OpenCamLib de ce seul corps. Sur le socle du chauffage Vz330, la boule descendait dans la cavité à travers
    le couvercle posé dessus (entaille de 41 mm). Chaque corps est ici calculé contre tous les corps du job, et
    les corps usinés entiers ne font qu'une zone."""
    import Path.Op.SurfaceSupport as support

    original = support._prepareModelSTLs
    if getattr(original, "cam2027_patched", False):
        return

    def prepare(self, JOB, obj, m, ocl):
        group = JOB.Model.Group
        if len(group) < 2 or self.modelSTLs[m] is not True:
            return original(self, JOB, obj, m, ocl)
        # un seul modèle pour tous les corps à calculer (FreeCAD libère la liste à la fin du calcul)
        stl = _all_models_stl(group, self.modelTypes, obj, ocl)
        for k, flag in enumerate(self.modelSTLs):
            if flag is True:
                self.modelSTLs[k] = stl

    prepare.cam2027_patched = True
    support._prepareModelSTLs = prepare

    pre_original = support.ProcessSelectedFaces.preProcessModel

    def pre_process(self, module):
        result = pre_original(self, module)
        if result:
            _merge_whole_models(self, result[0], result[1])
        return result

    support.ProcessSelectedFaces.preProcessModel = pre_process


#: écart de la triangulation d'une face dont FreeCAD ne sait pas projeter les fils (mm)
SHADOW_DEFLECTION = 0.01


def _face_shadow(face):
    """Ombre sur XY d'une face que FreeCAD ne sait pas projeter seule (disque WobbleRing : fonds plats,
    cylindres des rainures, « Wire is not closed ») : face plane -> polygone de son bord discrétisé (trous
    compris, exact) ; face courbe -> réunion des triangles de sa triangulation (le bord seul sous-estimait
    l'ombre d'un cylindre qui se replie vu de dessus : 2,0 mm² au lieu de 2,9, entaille de 1,5 mm).
    None si la face n'a pas d'ombre (face verticale)."""
    import FreeCAD
    import Part

    outer = _polygon(face.OuterWire, SHADOW_DEFLECTION) if isinstance(face.Surface, Part.Plane) else None
    if outer is not None:
        holes = [h for h in (_polygon(w, SHADOW_DEFLECTION) for w in face.Wires if not w.isSame(face.OuterWire))
                 if h is not None]
        try:
            shadow = Part.makeFace([outer] + holes, "Part::FaceMakerBullseye")
            if shadow.isValid() and shadow.Area > 1e-6:
                return shadow
        except Exception:
            pass
    points, triangles = face.tessellate(SHADOW_DEFLECTION)
    flat = [FreeCAD.Vector(p.x, p.y, 0.0) for p in points]
    faces = []
    for i, j, k in triangles:
        a, b, c = flat[i], flat[j], flat[k]
        if abs((b - a).cross(c - a).z) > 1e-9:
            faces.append(Part.Face(Part.makePolygon([a, b, c, a])))
    if not faces:
        return None
    return faces[0].fuse(faces[1:]).removeSplitter() if len(faces) > 1 else faces[0]


def _polygon(wire, deflection):
    import FreeCAD
    import Part

    pts = []
    for p in wire.discretize(Deflection=deflection):
        p = FreeCAD.Vector(p.x, p.y, 0.0)
        if not pts or (p - pts[-1]).Length > 1e-5:
            pts.append(p)
    if len(pts) > 1 and (pts[0] - pts[-1]).Length <= 1e-5:
        pts.pop()
    return Part.makePolygon(pts + [pts[0]]) if len(pts) >= 3 else None


def _patch_discretize(mod):
    """Discrétisation des régions de l'adaptative : sur le disque WobbleRing une région garde une lamelle
    ouverte (une ligne de 6,4 mm et une courbe de 0,03 mm, aire nulle) et ``Wire.discretize`` plante
    (« Access violation »), toute l'ébauche 3D échoue. Chaque arête se discrétise pourtant seule : ses points
    sont alors mis bout à bout (polygone d'aire nulle, sans effet sur le parcours)."""
    original = getattr(mod, "discretize", None)
    if original is None or getattr(original, "cam2027_patched", False):
        return

    def discretize(edge, flipDirection=False):
        try:
            return original(edge, flipDirection)
        except Exception:
            pts = []
            for e in getattr(edge, "OrderedEdges", None) or edge.Edges:
                for p in e.discretize(Deflection=0.002):
                    if not pts or (p - pts[-1]).Length > 1e-9:
                        pts.append(p)
            if flipDirection:
                pts.reverse()
            return pts

    discretize.cam2027_patched = True
    mod.discretize = discretize


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
            parts = []
            for f in faces:
                try:
                    parts.append(original([f], *args, **kwargs))
                except Exception:
                    parts.append(_face_shadow(f))
            parts = [p for p in parts if p is not None and not p.isNull() and p.Faces]
            if not parts:
                raise
            return parts[0].fuse(parts[1:]).removeSplitter() if len(parts) > 1 else parts[0]

    projection.cam2027_patched = True
    mod.projectFacesToXY = projection
    _patch_discretize(mod)
    _patch_roughing_regions(mod)
    from . import parallel_adaptive

    parallel_adaptive.install(mod)


#: intervalle de l'horloge qui rend la main à l'interface pendant un calcul (``GuiTicker``)
TICK_S = 0.1


#: rendus de main à l'interface : nombre et durée totale (mesure de leur coût, scénarios C2)
GUI_STATS = {"calls": 0, "seconds": 0.0, "stops": []}


def keep_gui_alive(_state={"t": 0.0, "inside": False}):
    """Rend la main à l'interface (au plus toutes les ``TICK_S``) pendant un calcul long en Python : sans cela
    Windows marque CAM2027 « Ne répond pas » et « Arrêter le calcul » reste sans effet. La fenêtre de
    progression est modale : seuls son bouton et le rafraîchissement passent."""
    import time

    now = time.time()
    if now - _state["t"] < TICK_S or _state["inside"]:
        return
    _state["t"] = now
    _state["inside"] = True  # appel venu d'un événement traité ici : pas de traitement imbriqué
    try:
        import FreeCAD

        if FreeCAD.GuiUp:
            import FreeCADGui

            FreeCADGui.updateGui()
    except Exception:
        pass
    finally:
        _state["inside"] = False
        GUI_STATS["calls"] += 1
        GUI_STATS["seconds"] += time.time() - now


class ComputationStopped(BaseException):
    """« Arrêter le calcul » : levée dans le calcul en cours, comme Ctrl+C. Dérive de ``BaseException`` : les
    ``except Exception`` de FreeCAD et de CAM2027 ne la retiennent pas."""


class GuiTicker(object):
    """Pendant un calcul lancé de l'interface (``busy``), rend la main à l'interface toutes les ``TICK_S``,
    quel que soit le code Python qui calcule (FreeCAD ou CAM2027) : un fil d'horloge simule un signal
    (``PyErr_SetInterruptEx``) dont le gestionnaire Python tourne dans le fil principal entre deux
    instructions Python et appelle ``keep_gui_alive``. Un appel C++ long (OpenCascade, libarea) n'est pas
    interrompu : la main revient à sa fin.

    ``stop()`` (bouton « Arrêter le calcul ») : le gestionnaire lève ``ComputationStopped`` dans le calcul en
    cours, comme Ctrl+C, jamais pendant le rendu de la main ni la fermeture du bloc (``PROTECTED``) ; de
    nouveau toutes les ``RESTOP_S`` tant que le calcul continue (une opération FreeCAD qui échoue n'arrête pas
    le recalcul du document : la suivante est arrêtée à son tour). Rien hors de l'interface ; les blocs
    imbriqués partagent la même horloge."""

    SIGNAL = "SIGBREAK"  # Windows ; SIGUSR1 ailleurs
    RESTOP_S = 0.3
    #: fonctions (noms de code) dans lesquelles l'arrêt n'est jamais levé
    PROTECTED = {"keep_gui_alive", "__exit__"}

    _depth = 0
    _deferred = []
    _flushing = False
    _thread = None
    _halt = None
    _stop = False
    _stopped_at = 0.0
    _old = None
    _signum = None

    def __enter__(self):
        import signal
        import threading

        cls = GuiTicker
        cls._depth += 1
        if cls._depth > 1 or not _gui_up() or threading.current_thread() is not threading.main_thread():
            return self
        signum = getattr(signal, cls.SIGNAL, None) or getattr(signal, "SIGUSR1", None)
        if signum is None:
            return self
        try:
            cls._old = signal.signal(signum, cls._handler)
        except (ValueError, OSError):
            return self
        cls._signum = signum
        cls._stop = False
        cls._stopped_at = 0.0
        cls._halt = threading.Event()
        cls._thread = threading.Thread(target=cls._run, args=(cls._halt, signum), name="CAM2027-gui-ticker",
                                       daemon=True)
        cls._thread.start()
        return self

    def __exit__(self, *_exc):
        import signal

        cls = GuiTicker
        cls._depth -= 1
        if cls._depth > 0 or cls._thread is None:
            return False
        # rafraîchissements différés : maintenant, horloge encore active (panneau Projet : lecture des parcours
        # neufs, 0,5 s pour 21 000 commandes)
        deferred, cls._deferred = cls._deferred, []
        cls._flushing = True
        try:
            for fn in deferred:
                try:
                    fn()
                except Exception:
                    pass
        finally:
            cls._flushing = False
        cls._halt.set()
        cls._thread.join(2.0)
        cls._thread = None
        cls._stop = False
        try:
            signal.signal(cls._signum, cls._old if cls._old is not None else signal.SIG_DFL)
        except (ValueError, OSError, TypeError):
            pass
        return False

    @classmethod
    def stop(cls):
        cls._stop = True

    @classmethod
    def active(cls):
        return cls._thread is not None

    @classmethod
    def defer(cls, fn):
        """Pendant le calcul, ``fn`` (rafraîchissement d'un panneau : 0,5 s pour 21 000 commandes) est appelée
        une seule fois, à la fin, au lieu de chaque rendu de main. Vrai si différée."""
        if cls._thread is None or cls._flushing:
            return False
        if fn not in cls._deferred:
            cls._deferred.append(fn)
        return True

    @classmethod
    def _handler(cls, _signum, frame):
        import time

        if cls._thread is None:
            return
        if cls._stop:
            f, protected = frame, False
            while f is not None:
                if f.f_code.co_name in cls.PROTECTED:
                    protected = True
                    break
                f = f.f_back
            now = time.time()
            if not protected and now - cls._stopped_at >= cls.RESTOP_S:
                cls._stopped_at = now
                GUI_STATS["stops"].append("%s:%d" % (frame.f_code.co_name, frame.f_lineno))
                raise ComputationStopped()
            return
        keep_gui_alive()  # jamais imbriqué (garde de keep_gui_alive)

    @classmethod
    def _run(cls, halt, signum):
        import ctypes

        trip = ctypes.pythonapi.PyErr_SetInterruptEx
        trip.argtypes = [ctypes.c_int]
        trip.restype = ctypes.c_int
        while not halt.wait(TICK_S):
            trip(signum)


def hold_stopped(doc):
    """Après « Arrêter le calcul » : les objets en échec restent « à recalculer » pour FreeCAD, et le premier
    recalcul venu (même hors calcul, sans fenêtre de progression) referait tout ce qui vient d'être arrêté
    (7 s figées sur le plateau). Leur état « à recalculer » est retiré ; ``Project.compute`` les reprend."""
    for o in doc.Objects:
        if "Invalid" in o.State and "Touched" in o.State:
            o.purgeTouched()


def _gui_up():
    try:
        import FreeCAD

        return bool(FreeCAD.GuiUp)
    except Exception:
        return False


#: empreinte SHA-1 de ``_workingEdgeHelperRoughing`` de FreeCAD 1.1.4 (le remplacement n'est installé que sur
#: cette version exacte du code)
ROUGHING_HELPER_SHA1 = "dba8a4f537de339e8a419ff74a3291e9e5447226"


def _clean_region(face):
    """Poche d'un niveau de l'ébauche 3D, débarrassée de ce que la découpe booléenne laisse sur une pièce aux
    nombreuses petites faces (disque WobbleRing) : fils ouverts ou d'aire nulle (lamelles), et faces aux fils
    mal orientés. Une poche d'aire -32,55 mm² (= -(1,98 + 30,58)) avait pour second fil le bossage voisin :
    l'adaptative vidait le bossage, entaille de 1,5 mm. Une face saine a pour aire son contour moins ses trous ;
    sinon seul son plus petit contour est gardé (au pire de la matière reste pour la finition, jamais
    d'entaille). None si rien ne reste."""
    import Part

    def area(w):
        try:
            return abs(Part.Face(w).Area)
        except Exception:
            return 0.0

    wires = [(w, area(w)) for w in face.Wires if w.isClosed()]
    wires = [(w, a) for w, a in wires if a > 1e-6]
    if not wires:
        return None
    outer = face.OuterWire
    outer_area = area(outer)
    holes = [(w, a) for w, a in wires if not w.isSame(outer)]
    expected = outer_area - sum(a for _w, a in holes)
    consistent = (face.Area > 0 and abs(face.Area - expected) <= 1e-3 * max(1.0, outer_area)
                  and all(a < outer_area and outer.BoundBox.isInside(w.BoundBox) for w, a in holes))
    if consistent and len(wires) == len(face.Wires):
        return face
    if consistent:
        return Part.makeFace([outer] + [w for w, _a in holes], "Part::FaceMakerBullseye")
    smallest = min(wires, key=lambda wa: wa[1])[0]
    return Part.makeFace([smallest], "Part::FaceMakerBullseye")


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
                    f = _clean_region(f)  # CAM2027 : poche retournée ou lamelle (disque WobbleRing)
                    if f is None:
                        continue
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


#: empreinte SHA-1 de ``Path.Geom.combineHorizontalFaces`` (même code en 1.0.2 et 1.1.4)
COMBINE_FACES_SHA1 = "429f00578adaff3be8ec5abb57e8048345d1fbdd"


def patch_combine_faces():
    """Poche 2D et adaptative sur des fonds choisis automatiquement : FreeCAD (``combineHorizontalFaces``) réunit
    les fonds en fusionnant leurs extrusions une à une, chaque fusion reprenant tout le résultat précédent
    (5,4 s pour les 135 alvéoles du plateau). Copie de la fonction de FreeCAD où la boîte est découpée par toutes
    les extrusions d'un coup (même région), installée seulement si le code d'origine est exactement celui
    attendu."""
    import Path.Geom as geom

    original = getattr(geom, "combineHorizontalFaces", None)
    if original is None or getattr(original, "cam2027_patched", False) or _sha1(original) != COMBINE_FACES_SHA1:
        return
    import FreeCAD
    import Part

    def combine(faces):
        if len(faces) < 3:
            return original(faces)
        horizontal = list()
        offset = 10.0
        topFace = None
        innerFaces = list()
        for f in faces:
            if f.BoundBox.ZMin != 0.0:
                f.translate(FreeCAD.Vector(0.0, 0.0, 0.0 - f.BoundBox.ZMin))
        allFaces = Part.makeCompound(faces)
        if hasattr(allFaces, "Area") and geom.isRoughly(allFaces.Area, 0.0):
            geom.Path.Log.info(geom.translate("PathGeom", "Zero working area to process. Check your selection and settings."))
            return horizontal
        afbb = allFaces.BoundBox
        bboxFace = geom.makeBoundBoxFace(afbb, offset, -5.0)
        bboxSolid = bboxFace.extrude(FreeCAD.Vector(0.0, 0.0, 10.0))
        extrudedFaces = [f.extrude(FreeCAD.Vector(0.0, 0.0, 6.0)) for f in faces]
        cut = bboxSolid.cut(extrudedFaces)  # CAM2027 : une découpe, au lieu de fusionner les extrusions une à une
        for f in cut.Faces:
            fbb = f.BoundBox
            if geom.isRoughly(fbb.ZMin, 5.0) and geom.isRoughly(fbb.ZMax, 5.0):
                if (geom.isRoughly(afbb.XMin - offset, fbb.XMin) and geom.isRoughly(afbb.XMax + offset, fbb.XMax)
                        and geom.isRoughly(afbb.YMin - offset, fbb.YMin) and geom.isRoughly(afbb.YMax + offset, fbb.YMax)):
                    topFace = f
                else:
                    innerFaces.append(f)
        if not topFace:
            return horizontal
        outer = [Part.Face(w) for w in topFace.Wires[1:]]
        if outer:
            for f in outer:
                f.translate(FreeCAD.Vector(0.0, 0.0, 0.0 - f.BoundBox.ZMin))
            if innerFaces:
                inner = innerFaces
                for f in inner:
                    f.translate(FreeCAD.Vector(0.0, 0.0, 0.0 - f.BoundBox.ZMin))
                cut = Part.makeCompound(outer).cut(Part.makeCompound(inner))
                for f in cut.Faces:
                    horizontal.append(f)
            else:
                horizontal = outer
        return horizontal

    combine.cam2027_patched = True
    geom.combineHorizontalFaces = combine


#: empreinte SHA-1 de ``ObjectVcarve.buildMedialWires`` (FreeCAD 1.1.4)
VCARVE_MEDIAL_SHA1 = "683dd0b61d57a4f77e67c38515bec448c2c30180"
#: empreinte SHA-1 de ``Path.Op.Vcarve._getPartEdges`` (FreeCAD 1.1.4)
VCARVE_EDGES_SHA1 = "268676f93eb4a95dda49d9cfa232a22393a3348d"
#: pas (mm) des points où la profondeur du V-carving est recalculée le long d'une arête qui touche un coin
VCARVE_EXACT_STEP = 0.2


def _site_distance(cell, p):
    """Distance de ``p`` à la source d'une cellule de Voronoï (point ou segment du dessin)."""
    src = cell.getSource(0.0)
    if cell.containsPoint():
        return math.hypot(p.x - src.x, p.y - src.y)
    (a, b) = src
    dx, dy = b.x - a.x, b.y - a.y
    n = dx * dx + dy * dy
    t = 0.0 if n < 1e-24 else min(max(((p.x - a.x) * dx + (p.y - a.y) * dy) / n, 0.0), 1.0)
    return math.hypot(a.x + t * dx - p.x, a.y + t * dy - p.y)


class _FaceDomain:
    """Point dans une face plane horizontale, d'après les segments donnés au diagramme de Voronoï (pair-impair,
    trous compris) ; un point sur un bord (à 1e-7 près) est dans la face, comme pour ``isPartOfDomain``."""

    def __init__(self, loops):
        import numpy as np

        seg = np.array([(a.x, a.y, b.x, b.y) for ptv in loops for a, b in zip(ptv[:-1], ptv[1:])], dtype=float)
        self.x0, self.y0, self.x1, self.y1 = seg.T if len(seg) else (np.zeros(0),) * 4
        self.dx, self.dy = self.x1 - self.x0, self.y1 - self.y0
        self.len2 = np.maximum(self.dx * self.dx + self.dy * self.dy, 1e-300)

    def exterior(self, x, y):
        import numpy as np

        t = np.clip(((x - self.x0) * self.dx + (y - self.y0) * self.dy) / self.len2, 0.0, 1.0)
        d2 = (self.x0 + t * self.dx - x) ** 2 + (self.y0 + t * self.dy - y) ** 2
        if len(d2) and d2.min() <= 1e-14:
            return False
        span = (self.y0 > y) != (self.y1 > y)
        xs = self.x0[span] + (y - self.y0[span]) * self.dx[span] / self.dy[span]
        return int(np.count_nonzero(xs > x)) % 2 == 0


def patch_vcarve(mod):
    """V-carving : FreeCAD classe chaque sommet du diagramme de Voronoï (dedans / dehors) avec
    ``Face.isPartOfDomain``, qui reconstruit son classificateur à chaque appel : 56 ms par sommet sur une face de
    milliers d'arêtes, 25 min pour un dessin vectorisé (dragon : 20 000 sommets). Copie de ``buildMedialWires``
    où les faces planes horizontales sont classées sur les segments mêmes du diagramme (numpy) ; les autres
    gardent le test de FreeCAD.

    Profondeur : FreeCAD la calcule aux deux bouts de chaque arête du diagramme et l'interpole en ligne droite.
    Le long d'une arête qui touche un coin du dessin (arc de parabole, ou médiatrice de deux coins), la distance
    au bord est plus petite au milieu qu'aux bouts : le V-bit descendait trop et mordait le bord (0,83 mm sur le
    dragon vectorisé, fait de milliers de coins). Ces arêtes sont découpées tous les ``VCARVE_EXACT_STEP`` mm,
    profondeur calculée à chaque point d'après la distance au coin ; les arêtes entre deux segments (distance
    linéaire) restent celles de FreeCAD. Installée seulement si le code d'origine est exactement celui attendu."""
    _patch_vcarve_depth(mod)
    cls = getattr(mod, "ObjectVcarve", None)
    original = getattr(cls, "buildMedialWires", None)
    if original is None or getattr(original, "cam2027_patched", False) or _sha1(original) != VCARVE_MEDIAL_SHA1:
        return
    import FreeCAD
    import Path

    def buildMedialWires(self, obj, faces):
        wires_by_face = dict()
        self.voronoiDebugCache = dict()

        def is_exterior(vertex, face):
            vector = FreeCAD.Vector(vertex.toPoint(face.BoundBox.ZMin))
            (u, v) = face.Surface.parameter(vector)
            return not face.isPartOfDomain(u, v)

        def insert_many_wires(vd, wires):
            loops = []
            for wire in wires:
                pts = wire.discretize(QuasiDeflection=obj.Discretize)
                ptv = [FreeCAD.Vector(p.x, p.y) for p in pts]
                if len(ptv) > 0:
                    dist = ptv[-1].distanceToPoint(ptv[0])
                    if dist < FreeCAD.Base.Precision.confusion():
                        del ptv[-1]
                ptv.append(ptv[0])
                for i in range(len(ptv) - 1):
                    vd.addSegment(ptv[i], ptv[i + 1])
                loops.append(ptv)
            return loops

        for f in faces:
            voronoiWires = []
            vd = Path.Voronoi.Diagram()
            loops = insert_many_wires(vd, f.Wires)
            vd.construct()
            for e in vd.Edges:
                if e.isPrimary():
                    e.Color = mod.BORDERLINE if e.isBorderline() else mod.PRIMARY
                else:
                    e.Color = mod.SECONDARY
            vd.colorColinear(mod.COLINEAR, obj.Colinear)
            vd.colorExterior(mod.EXTERIOR1)
            normal = getattr(f.Surface, "Axis", None)
            if normal is not None and abs(abs(normal.z) - 1.0) < 1e-9:  # CAM2027 : face plane horizontale
                domain = _FaceDomain(loops)
                vd.colorExterior(mod.EXTERIOR2, lambda v: domain.exterior(v.toPoint(0.0).x, v.toPoint(0.0).y))
            else:
                vd.colorExterior(mod.EXTERIOR2, lambda v: is_exterior(v, f))
            vd.colorTwins(mod.TWIN)
            wires = mod._collectVoronoiWires(vd)
            wires = mod._sortVoronoiWires(wires)
            voronoiWires.extend(wires)
            wires_by_face[f] = voronoiWires
            self.voronoiDebugCache = wires_by_face
        return wires_by_face

    buildMedialWires.cam2027_patched = True
    buildMedialWires.cam2027_original = original
    cls.buildMedialWires = buildMedialWires


def _patch_vcarve_depth(mod):
    original = getattr(mod, "_getPartEdges", None)
    if original is None or getattr(original, "cam2027_patched", False) or _sha1(original) != VCARVE_EDGES_SHA1:
        return
    import FreeCAD
    import Part

    def exact_edges(e, geom):
        flat = e.toShape(0.0, 0.0)
        cell = e.Cell if e.Cell.containsPoint() else e.Twin.Cell
        n = max(2, int(math.ceil(flat.Length / VCARVE_EXACT_STEP)))
        params = [flat.FirstParameter + k * (flat.LastParameter - flat.FirstParameter) / n for k in range(n + 1)]
        d0, d1 = e.getDistances()
        pts = []
        for k, u in enumerate(params):
            p = flat.valueAt(u)
            d = d0 if k == 0 else d1 if k == n else _site_distance(cell, p)
            pts.append(FreeCAD.Vector(p.x, p.y, mod._calculate_depth(d, geom)))
        return [Part.Edge(Part.LineSegment(a, b)) for a, b in zip(pts[:-1], pts[1:]) if (b - a).Length > 1e-9]

    def _getPartEdges(obj, vWire, geom):
        edges = []
        for e in vWire:
            if e.Cell.containsSegment() and e.Twin.Cell.containsSegment():
                edges.append(mod._getPartEdge(e, geom))  # entre deux segments : distance linéaire, exacte
            else:
                edges.extend(exact_edges(e, geom) or [mod._getPartEdge(e, geom)])
        return edges

    _getPartEdges.cam2027_patched = True
    _getPartEdges.cam2027_original = original
    mod._getPartEdges = _getPartEdges


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


def patch_pocket2d(mod=None):
    """Poche 2D sur de nombreux fonds (alvéoles d'un plateau) : les niveaux de chaque fond sont découpés dans des
    processus avant que FreeCAD ne les demande un par un (``parallel_pocket.precompute_face_sections``), repris
    seulement si la zone est exactement celle préparée. Installé seulement si ``_buildPathArea`` est le code
    attendu."""
    if mod is None:
        mod = importlib.import_module("Path.Op.PocketShape")
    cls = getattr(mod, "ObjectPocket", None)
    original = getattr(cls, "areaOpShapes", None)
    if original is None or getattr(original, "cam2027_patched", False):
        return
    import Path.Op.Area as area_mod

    build = area_mod.ObjectOp._buildPathArea
    if _sha1(build) not in AREA_BUILD_SHA1:
        return
    from . import parallel_pocket

    def area_op_shapes(self, obj):
        shapes = original(self, obj)
        try:
            self._cam2027_face_sections = parallel_pocket.precompute_face_sections(self, obj, shapes)
        except Exception:
            self._cam2027_face_sections = {}
        return shapes

    def build_path_area(self, obj, baseobject, isHole, start, getsim):
        return parallel_pocket.build_face_path_area(area_mod, build, self, obj, baseobject, isHole, start, getsim)

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

        module = STRATEGIES[kind]["module"]
        if module.startswith("cam2027."):  # stratégie propre à CAM2027
            res = _own_strategy_resources(importlib.import_module(module), kind)
        else:
            res = importlib.import_module(module.replace("Path.Op.", "Path.Op.Gui.")).Command.res
        op.ViewObject.Proxy = PathOpGui.ViewProvider(op.ViewObject, res)
        op.ViewObject.Proxy.deleteOnReject = False  # opération déjà créée : Annuler sur sa page ne la supprime pas
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
    hit = _PATH_STATS.pop(key, None)
    if hit is not None:
        _PATH_STATS[key] = hit  # la plus récemment lue : gardée le plus longtemps
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
        # la plus ancienne seulement : tout vider faisait relire tous les parcours au rafraîchissement suivant du
        # panneau (0,5 s pour 21 000 commandes, hors de toute fenêtre de progression)
        _PATH_STATS.pop(next(iter(_PATH_STATS)))
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
