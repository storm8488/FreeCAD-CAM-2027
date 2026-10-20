# SPDX-License-Identifier: LGPL-2.1-or-later
"""Pont entre la bibliothèque CAM2027 et les objets CAM de FreeCAD.

Produit, à partir d'un :class:`ToolAssembly` et d'un préréglage résolu :

- un objet ``ToolBit`` FreeCAD (forme paramétrique du module CAM) ;
- un ``ToolController`` portant les avances et la vitesse de broche.

Les correspondances de formes sont approximatives pour certains types (voir
``SHAPE_MAP``) : le ToolBit FreeCAD sert aux calculs de parcours 2D/2,5D qui
n'utilisent que le diamètre, l'angle de pointe et la longueur. Les
approximations sont signalées dans ``warnings``.
"""

import FreeCAD

from ..compat import tool_api

# type CAM2027 -> (fichier de forme FreeCAD, avertissement éventuel)
SHAPE_MAP = {
    "endmill": ("endmill.fcstd", None),
    "facemill": ("endmill.fcstd", "face mill represented as a flat end mill"),
    "ballend": ("ballend.fcstd", None),
    "bullnose": ("bullnose.fcstd", None),
    "taper": ("endmill.fcstd", "tapered flat end mill represented by its tip diameter as a flat end mill"),
    "taperedball": ("taperedballnose.fcstd", None),  # 1.1+ ; repli ballend sur 1.0
    "vbit": ("v-bit.fcstd", None),
    "engrave": ("v-bit.fcstd", None),
    "chamfer": ("chamfer.fcstd", None),
    "threadmill": ("thread-mill.fcstd", None),
    "drill": ("drill.fcstd", None),
    "form": ("endmill.fcstd", "form cutter represented as a flat end mill (profile ignored)"),
    "dovetail": ("dovetail.fcstd", None),
    "lollipop": ("ballend.fcstd", "lollipop mill represented as a ball end mill (undercut ignored)"),
    "radius": ("radius.fcstd", None),  # 1.1+ ; repli endmill sur 1.0
    "slot": ("endmill.fcstd", "slot mill represented as a flat end mill (undercut ignored)"),
    "barrel": ("endmill.fcstd", "barrel mill represented as a flat end mill: no toolpath strategy supports it yet"),
    "lens": ("endmill.fcstd", "lens mill represented as a flat end mill: no toolpath strategy supports it yet"),
    "ogive": ("endmill.fcstd", "ogive mill represented as a flat end mill: no toolpath strategy supports it yet"),
    "taperbarrel": ("endmill.fcstd", "taper barrel mill represented as a flat end mill: no toolpath strategy supports it yet"),
}


def shape_parameters(tool):
    """Retourne (nom de forme, paramètres FreeCAD en chaînes avec unités, avertissements)."""
    g = tool.geometry
    shape, warn = SHAPE_MAP[tool.tool_type]
    warnings = [warn] if warn else []
    p = {
        "Diameter": _mm(g.diameter),
        "Length": _mm(g.overall_length),
        "ShankDiameter": _mm(g.shank_diameter),
        "CuttingEdgeHeight": _mm(g.flute_length),
    }
    if tool.tool_type in ("bullnose", "facemill"):
        p["FlatRadius"] = _mm(max(g.diameter / 2.0 - (g.corner_radius or 0.0), 0.0))
    if tool.tool_type in ("vbit", "engrave", "chamfer"):
        p["CuttingEdgeAngle"] = _deg(g.tip_included_angle_deg)
        p["TipDiameter"] = _mm(g.tip_diameter or 0.0)
    if tool.tool_type == "drill":
        p = {"Diameter": _mm(g.diameter), "Length": _mm(g.overall_length), "TipAngle": _deg(g.tip_included_angle_deg)}
    if tool.tool_type == "threadmill":
        p = {
            "Diameter": _mm(g.diameter),
            "Length": _mm(g.overall_length),
            "ShankDiameter": _mm(g.shank_diameter),
            "Crest": _mm(0.0),
            # l'esquisse FreeCAD exige un col plus étroit que le diamètre de coupe
            "NeckDiameter": _mm(min(g.shank_diameter, 0.8 * g.diameter)),
            "NeckLength": _mm(max((g.shoulder_length or g.flute_length) - g.flute_length, 0.0)),
        }
    if tool.tool_type == "dovetail":
        p["CuttingEdgeAngle"] = _deg(2.0 * g.taper_half_angle_deg)
        p["NeckDiameter"] = _mm(g.shank_diameter)
        p["NeckHeight"] = _mm(max((g.shoulder_length or g.flute_length) - g.flute_length, 0.0))
        p["TipDiameter"] = _mm(g.diameter)
    if tool.tool_type == "radius":
        if tool_api() == "legacy":
            shape = "endmill.fcstd"
            warnings.append("radius mill represented as a flat end mill on FreeCAD 1.0")
        else:
            p["FlatRadius"] = _mm(max(g.diameter / 2.0 - (g.corner_radius or 0.0), 0.0))
    if tool.tool_type == "taperedball":
        if tool_api() == "legacy":
            shape = "ballend.fcstd"
            warnings.append("tapered ball nose represented as a ball end mill on FreeCAD 1.0")
        else:
            p["TaperAngle"] = _deg(g.taper_half_angle_deg)
            p["Diameter"] = _mm(2.0 * g.corner_radius)
    return shape, p, warnings


def _mm(v):
    return "%.4f mm" % float(v)


def _deg(v):
    return "%.2f °" % float(v)


def create_toolbit(doc, tool, label=None):
    """Crée l'objet ToolBit FreeCAD dans ``doc`` ; retourne (objet, avertissements)."""
    shape, params, warnings = shape_parameters(tool)
    attrs = {
        "version": 2,
        "name": label or tool.name,
        "shape": shape,
        "parameter": params,
        "attribute": {
            "Flutes": int(tool.flute_count),
            "Material": _freecad_material(tool.material),
            "SpindleDirection": "Forward" if tool.rotation == "cw" else "Reverse",
        },
    }
    previous = FreeCAD.ActiveDocument
    FreeCAD.setActiveDocument(doc.Name)
    try:
        if tool_api() == "assets":
            from Path.Tool.toolbit import ToolBit

            attrs = dict(attrs)
            attrs["attribute"] = dict(attrs["attribute"])
            bit = ToolBit.from_dict(attrs)
            obj = bit.attach_to_doc(doc=doc, label=attrs["name"])
        else:
            import Path.Tool.Bit as PathToolBit

            obj = PathToolBit.Factory.CreateFromAttrs(attrs, name=_safe_name(attrs["name"]))
    finally:
        if previous is not None and previous.Name != doc.Name:
            try:
                FreeCAD.setActiveDocument(previous.Name)
            except Exception:
                pass
    if obj.ViewObject:
        obj.ViewObject.Visibility = False
    return obj, warnings


def _freecad_material(material):
    m = (material or "").lower()
    if "hss" in m:
        return "HSS"
    if "carb" in m:
        return "Carbide"
    return "Carbide"


def _safe_name(name):
    out = "".join(ch if ch.isalnum() else "_" for ch in name)
    return out or "ToolBit"


def create_tool_controller(doc, assembly, tool, resolved_preset, toolbit=None, label=None):
    """Crée un ToolController FreeCAD à partir de l'assemblage et du préréglage résolu.

    Les valeurs copiées dans le contrôleur sont celles « utilisées dans
    l'opération » ; elles ne suivent plus le préréglage ensuite.
    """
    import Path.Tool.Controller as PathToolController

    warnings = []
    if toolbit is None:
        toolbit, warnings = create_toolbit(doc, tool)
    previous = FreeCAD.ActiveDocument
    FreeCAD.setActiveDocument(doc.Name)
    try:
        tc = PathToolController.Create(
            label or ("TC: %s" % assembly.name),
            tool=toolbit,
            toolNumber=assembly.output.tool_number,
            assignViewProvider=bool(FreeCAD.GuiUp),
        )
    finally:
        if previous is not None and previous.Name != doc.Name:
            try:
                FreeCAD.setActiveDocument(previous.Name)
            except Exception:
                pass
    tc.HorizFeed = "%.3f mm/min" % resolved_preset["feed_mm_min"]
    tc.VertFeed = "%.3f mm/min" % resolved_preset["plunge_feed_mm_min"]
    tc.SpindleSpeed = float(resolved_preset["spindle_rpm"])
    tc.SpindleDir = "Forward" if tool.rotation == "cw" else "Reverse"
    tc.HorizRapid = "0 mm/min"
    tc.VertRapid = "0 mm/min"
    return tc, warnings


def tool_controller_values(tc):
    """Valeurs effectivement portées par un ToolController (pour la fiche et les tests)."""
    return {
        "tool_number": int(tc.ToolNumber),
        "feed_mm_min": float(tc.HorizFeed.getValueAs("mm/min")),
        "plunge_feed_mm_min": float(tc.VertFeed.getValueAs("mm/min")),
        "spindle_rpm": float(tc.SpindleSpeed),
        "spindle_dir": str(tc.SpindleDir),
        "diameter_mm": float(tc.Tool.Diameter.getValueAs("mm")) if hasattr(tc.Tool, "Diameter") else None,
    }
