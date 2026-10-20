# SPDX-License-Identifier: LGPL-2.1-or-later
"""Import d'une bibliothèque exportée par Autodesk Fusion (``.json`` ou ``.tools``).

État : **partiel, non validé sur un export réel**. La correspondance des champs
repose sur la structure connue des exports Fusion (``{"data": [tool, ...]}``,
clés ``geometry``/``start-values``/``post-process``/``holder``). Tout champ non
reconnu est listé dans le rapport de conversion ; aucun outil n'est inventé.

Un fichier ``.tools`` est une archive ZIP contenant ``tools.json`` (ou tout
fichier ``*.json``) ; le premier fichier JSON trouvé est utilisé.
"""

import json
import zipfile

from .model import ToolDefinition, Holder, ToolAssembly, CuttingPreset

# type Fusion -> (type CAM2027, note)
_TYPE_MAP = {
    "flat end mill": ("endmill", None),
    "ball end mill": ("ballend", None),
    "bull nose end mill": ("bullnose", None),
    "tapered mill": ("taper", None),
    "chamfer mill": ("chamfer", None),
    "face mill": ("facemill", None),
    "thread mill": ("threadmill", None),
    "drill": ("drill", None),
    "spot drill": ("drill", "spot drill imported as drill"),
    "center drill": ("drill", "center drill imported as drill"),
    "engrave/chamfer mill": ("chamfer", None),
    "dovetail mill": ("dovetail", None),
    "lollipop mill": ("lollipop", "lollipop: undercut geometry not used by toolpaths"),
    "slot mill": ("slot", "slot mill: undercut geometry not used by toolpaths"),
    "radius mill": ("radius", None),
    "barrel mill": ("barrel", "barrel mill: no toolpath strategy supports it yet"),
    "lens mill": ("lens", "lens mill: no toolpath strategy supports it yet"),
    "taper barrel mill": ("taperbarrel", "taper barrel mill: no toolpath strategy supports it yet"),
    "ogive mill": ("ogive", "ogive mill: no toolpath strategy supports it yet"),
    "form mill": (None, "form mills need a profile and are not imported"),
    "tap right hand": (None, "taps are not supported yet"),
    "tap left hand": (None, "taps are not supported yet"),
    "reamer": (None, "reamers are not supported yet"),
    "boring bar": (None, "boring bars are not supported yet"),
    "counter bore": (None, "counter bores are not supported yet"),
    "counter sink": ("chamfer", "counter sink imported as chamfer mill"),
}

# Clés vues dans un export réel (Fusion 2.16, version 37) : DC, DCX, SFDM, OAL, LB, LCF, NOF,
# RE, TA (demi-angle), HAND, CSP, assemblyGaugeLength, shoulder-diameter, shoulder-length,
# upper-radius, tip-diameter. Les autres restent des hypothèses.
_KNOWN_GEOMETRY_KEYS = {
    "DC", "SFDM", "OAL", "LCF", "LB", "RE", "TA", "SIG", "NOF", "HAND", "CSP", "shoulder-length",
    "shoulder-diameter", "assemblyGaugeLength", "upper-radius", "lower-radius", "profile-radius",
    "axial-distance", "tip-length", "tip-diameter", "tip-offset", "DCX", "TP", "NT", "tip-angle",
    "taper-angle", "corner-radius", "body-length", "flute-length", "overall-length", "shaft-diameter",
    "diameter", "thread-pitch", "thread-pitch-min", "thread-pitch-max", "thread-profile-angle",
    "TA2", "LU", "LF", "RE2", "number-of-teeth",
}

# « tapered-type » d'un « tapered mill » -> (type CAM2027, pointe)
_TAPERED_TYPES = {
    "tapered_flat": ("taper", "flat"),
    "tapered_bull_nose": ("taper", "bullnose"),
    "tapered_ball": ("taperedball", "ball"),
}


class ConversionReport(object):
    def __init__(self):
        self.imported = []
        self.skipped = []
        self.warnings = []
        self.unknown_fields = {}

    def add_unknown(self, tool_name, keys):
        if keys:
            self.unknown_fields.setdefault(tool_name, set()).update(keys)

    def to_text(self):
        lines = ["Imported: %d tool(s)" % len(self.imported)]
        for name in self.imported:
            lines.append("  + %s" % name)
        lines.append("Skipped: %d" % len(self.skipped))
        for name, why in self.skipped:
            lines.append("  - %s: %s" % (name, why))
        if self.warnings:
            lines.append("Warnings:")
            for w in self.warnings:
                lines.append("  ! %s" % w)
        if self.unknown_fields:
            lines.append("Unmapped fields (kept out of the library):")
            for name, keys in sorted(self.unknown_fields.items()):
                lines.append("  ? %s: %s" % (name, ", ".join(sorted(keys))))
        return "\n".join(lines)


def _read_json(path):
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith(".json")]
            if not names:
                raise ValueError("archive .tools sans fichier JSON")
            names.sort(key=lambda n: (n.lower() != "tools.json", n))
            with zf.open(names[0]) as fp:
                return json.loads(fp.read().decode("utf-8"))
    with open(path, "r", encoding="utf-8") as fp:
        return json.load(fp)


def _coolant(p):
    v = str(p.get("tool-coolant") or ("flood" if p.get("use-coolant") else "disabled")).lower()
    return {"disabled": "none", "flood": "flood", "mist": "mist", "air": "air", "through tool": "through",
            "through": "through"}.get(v, "none")


def _num(d, *keys, default=None):
    for k in keys:
        if k in d and d[k] is not None:
            try:
                return float(d[k])
            except (TypeError, ValueError):
                continue
    return default


def import_fusion_library(path, library, holder_cache=None):
    """Ajoute les outils Fusion du fichier à ``library``. Retourne un ConversionReport."""
    report = ConversionReport()
    data = _read_json(path)
    tools = data.get("data") if isinstance(data, dict) else data
    if not isinstance(tools, list):
        raise ValueError("structure Fusion inattendue (clé 'data' absente)")
    holder_cache = holder_cache if holder_cache is not None else {}
    for raw in tools:
        name = raw.get("description") or raw.get("product-id") or "Fusion tool"
        unit = (raw.get("unit") or "millimeters").lower()
        scale = 25.4 if unit.startswith("inch") else 1.0
        ftype = (raw.get("type") or "").lower()
        mapped = _TYPE_MAP.get(ftype)
        if mapped is None:
            report.skipped.append((name, "unknown Fusion type %r" % ftype))
            continue
        ttype, note = mapped
        if ttype is None:
            report.skipped.append((name, note))
            continue
        if note:
            report.warnings.append("%s: %s" % (name, note))
        taper_tip = None
        if ttype == "taper":
            sub = str(raw.get("tapered-type") or "tapered_flat").lower()
            if sub not in _TAPERED_TYPES:
                report.warnings.append("%s: unknown tapered-type %r, imported as flat taper" % (name, sub))
            ttype, taper_tip = _TAPERED_TYPES.get(sub, ("taper", "flat"))
        g = raw.get("geometry", {}) or {}
        report.add_unknown(name, set(g) - _KNOWN_GEOMETRY_KEYS)
        geom = {
            "diameter": _num(g, "DC", "diameter", default=0) * scale,
            "shank_diameter": _num(g, "SFDM", "shaft-diameter", default=_num(g, "DC", default=0)) * scale,
            "overall_length": _num(g, "OAL", "overall-length", default=0) * scale,
            "flute_length": _num(g, "LCF", "flute-length", default=0) * scale,
            "shoulder_length": _num(g, "shoulder-length", default=None),
            "body_length": _num(g, "LB", "body-length", default=None),
        }
        for key in ("shoulder_length", "body_length"):
            if geom[key] is not None:
                geom[key] *= scale
        if ttype == "bullnose":
            geom["corner_radius"] = _num(g, "RE", "corner-radius", default=0) * scale
        if ttype in ("taper", "taperedball"):
            geom["taper_half_angle_deg"] = _num(g, "TA", "taper-angle", default=0)
            geom["corner_radius"] = _num(g, "RE", "corner-radius", default=0) * scale
            if ttype == "taper":
                geom["taper_tip"] = taper_tip
        if ttype in ("chamfer", "vbit", "engrave"):
            # Fusion stocke le demi-angle (« angle de dépouille », TA) ; l'angle inclus vaut 2 x TA
            half = _num(g, "TA", "taper-angle", default=None)
            if half is not None:
                geom["tip_included_angle_deg"] = 2.0 * half
            else:
                geom["tip_included_angle_deg"] = _num(g, "SIG", "tip-angle", default=90)
            geom["tip_diameter"] = _num(g, "tip-diameter", default=0) * scale
        if ttype == "drill":
            geom["tip_included_angle_deg"] = _num(g, "SIG", "tip-angle", default=118)
        if ttype == "threadmill":
            geom["pitch"] = _num(g, "TP", "thread-pitch", "thread-pitch-max", default=1.0) * scale
            pmin = _num(g, "thread-pitch-min", default=None)
            geom["pitch_min"] = pmin * scale if pmin is not None else None
            geom["thread_teeth"] = int(_num(g, "NT", "number-of-teeth", default=1))
            geom["thread_profile_angle_deg"] = _num(g, "thread-profile-angle", default=60)
        if ttype == "facemill":
            geom["corner_radius"] = _num(g, "RE", default=0) * scale
        if ttype in ("dovetail", "slot", "lens"):
            geom["corner_radius"] = _num(g, "RE", "corner-radius", default=0) * scale
        if ttype == "dovetail":
            geom["taper_half_angle_deg"] = _num(g, "TA", "taper-angle", default=30)
        if ttype == "facemill":
            geom["taper_half_angle_deg"] = _num(g, "TA", "taper-angle", default=0)
        if ttype == "form":
            geom["tip_offset"] = _num(g, "tip-offset", default=0) * scale
        if ttype == "radius":
            geom["corner_radius"] = _num(g, "RE", "corner-radius", default=0) * scale
        if ttype in ("barrel", "ogive", "taperbarrel"):
            geom["barrel_radius"] = _num(g, "profile-radius", "RE2", default=0) * scale
            geom["lower_radius"] = _num(g, "lower-radius", "RE", default=0) * scale
            geom["upper_radius"] = _num(g, "upper-radius", default=0) * scale
            if ttype == "barrel":
                geom["axial_distance"] = _num(g, "axial-distance", default=None)
                if geom["axial_distance"] is not None:
                    geom["axial_distance"] *= scale
            if ttype == "taperbarrel":
                geom["taper_half_angle_deg"] = _num(g, "TA", "taper-angle", default=0)
                geom["tip_diameter"] = _num(g, "tip-diameter", default=0) * scale
        if ttype == "lens":
            geom["lower_radius"] = _num(g, "lower-radius", "profile-radius", default=0) * scale
        if geom["diameter"] <= 0 or geom["overall_length"] <= 0:
            report.skipped.append((name, "missing diameter or overall length"))
            continue
        if geom["flute_length"] <= 0:
            geom["flute_length"] = min(geom["overall_length"], geom["diameter"] * 3)
            report.warnings.append("%s: flute length missing, assumed 3 x D" % name)
        presets = []
        for p in (raw.get("start-values", {}) or {}).get("presets", []) or []:
            try:
                material = p.get("material")
                if isinstance(material, dict):
                    material = material.get("query") or ("" if material.get("category") in (None, "all") else material.get("category"))
                presets.append(
                    CuttingPreset(
                        p.get("name") or "Fusion preset",
                        description=p.get("description", "") or "",
                        material=material or "",
                        spindle_rpm=_num(p, "n"),
                        surface_speed_m_min=_num(p, "v_c"),
                        feed_mm_min=_num(p, "v_f"),
                        feed_per_tooth_mm=_num(p, "f_z"),
                        lead_in_feed_mm_min=_num(p, "v_f_leadIn"),
                        lead_out_feed_mm_min=_num(p, "v_f_leadOut"),
                        ramp_feed_mm_min=_num(p, "v_f_ramp"),
                        ramp_spindle_rpm=_num(p, "n_ramp"),
                        transition_feed_mm_min=_num(p, "v_f_transition"),
                        ramp_angle_deg=_num(p, "ramp-angle"),
                        plunge_feed_mm_min=_num(p, "v_f_plunge"),
                        plunge_feed_per_rev_mm=_num(p, "f_n_plunge"),
                        retract_feed_mm_min=_num(p, "v_f_retract"),
                        feed_per_rev_mm=_num(p, "f_n"),
                        axial_engagement_mm=_num(p, "stepdown") if p.get("use-stepdown", True) else None,
                        radial_engagement_mm=_num(p, "stepover") if p.get("use-stepover", True) else None,
                        coolant=_coolant(p),
                    )
                )
            except ValueError as exc:
                report.warnings.append("%s: preset %r ignored (%s)" % (name, p.get("name"), exc))
        try:
            tool = ToolDefinition(
                name,
                ttype,
                geom,
                flute_count=int(_num(g, "NOF", default=2)),
                rotation="ccw" if (g.get("HAND") is False) else "cw",
                material=(raw.get("BMC") or "carbide").lower(),
                coating=raw.get("GRADE", "") or "",
                vendor=raw.get("vendor", "") or "",
                product_id=raw.get("product-id", "") or "",
                product_url=raw.get("product-link", "") or "",
                description=raw.get("description", "") or "",
                tags=["fusion-import"],
                presets=presets,
            )
        except ValueError as exc:
            report.skipped.append((name, str(exc)))
            continue
        library.add_tool(tool)
        holder_id = None
        hraw = raw.get("holder")
        if isinstance(hraw, dict) and hraw.get("segments"):
            key = json.dumps(hraw.get("segments"), sort_keys=True)
            if key not in holder_cache:
                segs = [
                    {"lower_diameter": _num(s, "lower", default=0) * scale,
                     "upper_diameter": _num(s, "upper", default=0) * scale,
                     "length": _num(s, "height", default=1) * scale}
                    for s in hraw["segments"]
                ]
                try:
                    holder = Holder(hraw.get("description") or "Fusion holder", segs,
                                    vendor=hraw.get("vendor", "") or "", product_id=hraw.get("product-id", "") or "")
                    library.add_holder(holder)
                    holder_cache[key] = holder.id
                except ValueError as exc:
                    report.warnings.append("%s: holder ignored (%s)" % (name, exc))
            holder_id = holder_cache.get(key)
        post = raw.get("post-process", {}) or {}
        gauge = _num(g, "assemblyGaugeLength", default=None)
        asm = ToolAssembly(
            "T%s %s" % (post.get("number", "?"), name),
            tool.id,
            holder_id,
            stickout=geom.get("body_length"),
            gauge_length=gauge * scale if gauge is not None else None,
            output={
                "tool_number": int(post.get("number", 1) or 1),
                "length_offset": post.get("length-offset"),
                "diameter_offset": post.get("diameter-offset"),
                "manual_tool_change": bool(post.get("manual-tool-change", True)),
                "comment": post.get("comment", "") or "",
                "post_properties": {k: v for k, v in post.items()
                                    if k not in ("number", "length-offset", "diameter-offset", "manual-tool-change", "comment")},
            },
        )
        try:
            library.add_assembly(asm)
        except ValueError as exc:
            report.warnings.append("%s: assembly not created (%s)" % (name, exc))
        report.imported.append(name)
    return report
