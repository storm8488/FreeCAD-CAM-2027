# SPDX-License-Identifier: LGPL-2.1-or-later
"""Modèle de données de la bibliothèque d'outils.

Quatre notions distinctes, liées par identifiants (voir ``cam2027.ids``) :

- :class:`ToolDefinition` : la fraise elle-même (géométrie, matière, dents).
- :class:`Holder` : le porte-outil, défini par segments.
- :class:`ToolAssembly` : une fraise montée dans un porte-outil avec une sortie
  donnée, plus les données de sortie (numéro d'outil, correcteurs...).
- :class:`CuttingPreset` : conditions de coupe pour un usage (matière, machine,
  ébauche/finition...). Un préréglage appartient à une définition d'outil.

Les valeurs réellement utilisées par une opération sont copiées au moment de
la création de l'opération (voir ``cam2027.project.operations``) : modifier un
préréglage ne change pas une opération existante.

Conventions d'angles (stockées en degrés) :

- ``tip_included_angle_deg`` : angle **inclus** de la pointe (V-bit 60° = 60,
  foret 118° = 118, fraise à chanfreiner 90° = 90).
- ``taper_half_angle_deg`` : **demi-angle** du cône par rapport à l'axe
  (fraise conique « 5° » = 5), comme le « taper angle » de Fusion.

Unités : voir ``cam2027.units``.
"""

import copy
import math

from ..i18n import UserError, UserKeyError
from ..ids import new_id, is_id
from ..units import to_mm, to_mm_min, to_rpm, to_deg, to_float

# ---------------------------------------------------------------------------
# Types d'outils et champs applicables
# ---------------------------------------------------------------------------

#: type -> (libellé anglais, champs géométriques applicables en plus des communs)
TOOL_TYPES = {
    # (libellé anglais, champs géométriques en plus des champs communs)
    # Les champs suivent l'onglet « Coupant » de Fusion pour chaque type.
    "endmill": ("Flat end mill", ("shoulder_length", "body_length", "flute_style")),
    "ballend": ("Ball end mill", ("shoulder_length", "body_length")),
    "bullnose": ("Bull nose end mill", ("corner_radius", "shoulder_length", "body_length")),
    "chamfer": ("Chamfer / engraving mill", ("tip_diameter", "tip_included_angle_deg", "shoulder_length", "body_length")),
    "vbit": ("V-bit (V-carving)", ("tip_diameter", "tip_included_angle_deg", "shoulder_length", "body_length")),
    "engrave": ("Engraving cutter", ("tip_diameter", "tip_included_angle_deg", "shoulder_length", "body_length")),
    "barrel": ("Barrel mill", ("upper_radius", "barrel_radius", "lower_radius", "axial_distance", "shoulder_length", "body_length")),
    "lens": ("Lens mill", ("corner_radius", "lower_radius", "shoulder_length", "body_length")),
    "ogive": ("Ogive mill", ("barrel_radius", "lower_radius", "shoulder_length", "body_length")),
    "taperbarrel": ("Taper barrel mill", ("taper_half_angle_deg", "upper_radius", "barrel_radius", "lower_radius", "tip_diameter", "shoulder_length", "body_length")),
    "dovetail": ("Dovetail mill", ("corner_radius", "taper_half_angle_deg", "shoulder_length", "body_length")),
    "facemill": ("Face mill", ("corner_radius", "taper_half_angle_deg", "shoulder_length", "body_length")),
    "form": ("Form mill", ("tip_offset", "body_length", "profile")),
    "lollipop": ("Lollipop mill", ("shoulder_length", "body_length")),
    "radius": ("Radius (corner rounding) mill", ("corner_radius", "tip_diameter", "shoulder_length", "body_length")),
    "slot": ("Slot mill", ("corner_radius", "shoulder_length", "body_length")),
    "taper": ("Tapered mill", ("taper_tip", "corner_radius", "taper_half_angle_deg", "shoulder_length", "body_length")),
    "taperedball": ("Tapered ball end mill", ("taper_half_angle_deg", "corner_radius", "shoulder_length", "body_length")),
    "threadmill": ("Thread mill", ("thread_teeth", "thread_profile_angle_deg", "thread_tip_type", "pitch", "pitch_min", "shoulder_length", "body_length")),
    "drill": ("Drill", ("tip_included_angle_deg", "body_length")),
}

#: pointes possibles d'une fraise conique (« Type conique » de Fusion)
TAPER_TIPS = ("flat", "bullnose", "ball")

#: types de pointe de filet
THREAD_TIP_TYPES = ("point", "flat")

#: champs communs à tous les types (longueurs en mm)
COMMON_GEOMETRY_FIELDS = (
    "diameter",
    "shank_diameter",
    "overall_length",
    "flute_length",
)

#: valeurs admises pour flute_style (fraises bois)
FLUTE_STYLES = ("straight", "upcut", "downcut", "compression")

ROTATIONS = ("cw", "ccw")

COOLANTS = ("none", "flood", "mist", "air", "through")

PRESET_USAGES = ("general", "roughing", "finishing", "slotting", "drilling", "engraving", "adaptive")


def geometry_fields_for(tool_type):
    """Champs géométriques pertinents pour un type d'outil (ordre d'affichage)."""
    if tool_type not in TOOL_TYPES:
        raise UserError("unknown tool type: {tool_type}", tool_type=repr(tool_type))
    return COMMON_GEOMETRY_FIELDS + TOOL_TYPES[tool_type][1]


# ---------------------------------------------------------------------------
# Segments (queue et porte-outil)
# ---------------------------------------------------------------------------


class Segment(object):
    """Tronçon de révolution décrit du bas (côté pointe) vers le haut.

    ``lower_diameter`` et ``upper_diameter`` permettent les cônes ; ``length``
    est la hauteur du tronçon. Tous en mm.
    """

    __slots__ = ("lower_diameter", "upper_diameter", "length")

    def __init__(self, lower_diameter, upper_diameter, length):
        self.lower_diameter = to_mm(lower_diameter)
        self.upper_diameter = to_mm(upper_diameter)
        self.length = to_mm(length)
        if self.length <= 0:
            raise UserError("segment: length <= 0")
        if self.lower_diameter < 0 or self.upper_diameter < 0:
            raise UserError("segment: negative diameter")

    def to_dict(self):
        return {
            "lower_diameter": self.lower_diameter,
            "upper_diameter": self.upper_diameter,
            "length": self.length,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(d["lower_diameter"], d["upper_diameter"], d["length"])


# ---------------------------------------------------------------------------
# Préréglage de coupe
# ---------------------------------------------------------------------------


class CuttingPreset(object):
    """Conditions de coupe pour un outil et un usage.

    Relations métriques appliquées par :meth:`resolve` :

        n  = 1000 * Vc / (pi * D)
        Vf = n * z * fz

    ``rpm_source`` indique quelle grandeur pilote (``"rpm"`` ou ``"vc"``) et
    ``feed_source`` de même (``"feed"`` ou ``"fz"``). La grandeur pilotée est
    recalculée ; la valeur saisie est conservée telle quelle. Ces relations
    assurent la cohérence, elles ne recommandent pas des conditions de coupe.
    """

    FIELDS = (
        "name",
        "usage",
        "material",
        "machine_id",
        "description",
        "spindle_rpm",
        "surface_speed_m_min",
        "ramp_spindle_rpm",
        "rpm_source",
        "feed_mm_min",
        "feed_per_tooth_mm",
        "feed_source",
        "lead_in_feed_mm_min",
        "lead_out_feed_mm_min",
        "ramp_feed_mm_min",
        "transition_feed_mm_min",
        "ramp_angle_deg",
        "plunge_feed_mm_min",
        "plunge_feed_per_rev_mm",
        "retract_feed_mm_min",
        "feed_per_rev_mm",
        "axial_engagement_mm",
        "radial_engagement_mm",
        "coolant",
    )

    def __init__(self, name="Default", **kwargs):
        self.id = kwargs.pop("id", None) or new_id()
        self.name = name
        self.usage = kwargs.pop("usage", "general")
        self.material = kwargs.pop("material", "")
        self.machine_id = kwargs.pop("machine_id", None)
        self.description = kwargs.pop("description", "")
        self.spindle_rpm = _opt(kwargs.pop("spindle_rpm", None), to_rpm)
        self.surface_speed_m_min = _opt(kwargs.pop("surface_speed_m_min", None), to_float)
        self.ramp_spindle_rpm = _opt(kwargs.pop("ramp_spindle_rpm", None), to_rpm)
        self.rpm_source = kwargs.pop("rpm_source", "rpm")
        self.feed_mm_min = _opt(kwargs.pop("feed_mm_min", None), to_mm_min)
        self.feed_per_tooth_mm = _opt(kwargs.pop("feed_per_tooth_mm", None), to_mm)
        self.feed_source = kwargs.pop("feed_source", "feed")
        self.lead_in_feed_mm_min = _opt(kwargs.pop("lead_in_feed_mm_min", None), to_mm_min)
        self.lead_out_feed_mm_min = _opt(kwargs.pop("lead_out_feed_mm_min", None), to_mm_min)
        self.ramp_feed_mm_min = _opt(kwargs.pop("ramp_feed_mm_min", None), to_mm_min)
        self.transition_feed_mm_min = _opt(kwargs.pop("transition_feed_mm_min", None), to_mm_min)
        self.ramp_angle_deg = _opt(kwargs.pop("ramp_angle_deg", None), to_deg)
        self.plunge_feed_mm_min = _opt(kwargs.pop("plunge_feed_mm_min", None), to_mm_min)
        self.plunge_feed_per_rev_mm = _opt(kwargs.pop("plunge_feed_per_rev_mm", None), to_mm)
        self.retract_feed_mm_min = _opt(kwargs.pop("retract_feed_mm_min", None), to_mm_min)
        self.feed_per_rev_mm = _opt(kwargs.pop("feed_per_rev_mm", None), to_mm)
        self.axial_engagement_mm = _opt(kwargs.pop("axial_engagement_mm", None), to_mm)
        self.radial_engagement_mm = _opt(kwargs.pop("radial_engagement_mm", None), to_mm)
        self.coolant = kwargs.pop("coolant", "none")
        if kwargs:
            raise UserError("preset: unknown fields {fields}", fields=sorted(kwargs))
        self.validate()

    def validate(self):
        if self.usage not in PRESET_USAGES:
            raise UserError("preset {name}: unknown use {usage}", name=self.name, usage=repr(self.usage))
        if self.rpm_source not in ("rpm", "vc"):
            raise UserError("preset {name}: invalid rpm_source", name=self.name)
        if self.feed_source not in ("feed", "fz"):
            raise UserError("preset {name}: invalid feed_source", name=self.name)
        if self.coolant not in COOLANTS:
            raise UserError("preset {name}: unknown coolant {coolant}", name=self.name, coolant=repr(self.coolant))
        for f in ("spindle_rpm", "feed_mm_min", "feed_per_tooth_mm", "surface_speed_m_min"):
            v = getattr(self, f)
            if v is not None and v < 0:
                raise UserError("preset {name}: negative {field}", name=self.name, field=f)

    def resolve(self, tool):
        """Retourne un dict complet (rpm, vc, feed, fz, avances annexes) cohérent.

        Les avances annexes absentes héritent de l'avance de coupe (entrée,
        sortie, rampe) ou de la moitié de celle-ci (plongée), comme valeur de
        repli explicitement signalée par ``"derived"``.
        """
        d = max(tool.geometry.diameter, 1e-9)
        z = max(int(tool.flute_count or 1), 1)
        derived = []
        rpm = self.spindle_rpm
        vc = self.surface_speed_m_min
        if self.rpm_source == "vc":
            if vc is None:
                raise UserError("preset {name}: Vc missing", name=self.name)
            rpm = 1000.0 * vc / (math.pi * d)
            derived.append("spindle_rpm")
        else:
            if rpm is None:
                raise UserError("preset {name}: spindle speed missing", name=self.name)
            vc = math.pi * d * rpm / 1000.0
            derived.append("surface_speed_m_min")
        feed = self.feed_mm_min
        fz = self.feed_per_tooth_mm
        if self.feed_source == "fz":
            if fz is None:
                raise UserError("preset {name}: fz missing", name=self.name)
            feed = rpm * z * fz
            derived.append("feed_mm_min")
        else:
            if feed is None:
                raise UserError("preset {name}: feed rate missing", name=self.name)
            fz = feed / (rpm * z) if rpm > 0 else 0.0
            derived.append("feed_per_tooth_mm")

        def fallback(name, default):
            v = getattr(self, name)
            if v is None:
                derived.append(name)
                return default
            return v

        plunge = fallback("plunge_feed_mm_min", feed / 3.0)
        return {
            "preset_id": self.id,
            "preset_name": self.name,
            "spindle_rpm": rpm,
            "surface_speed_m_min": vc,
            "ramp_spindle_rpm": fallback("ramp_spindle_rpm", rpm),
            "feed_mm_min": feed,
            "feed_per_tooth_mm": fz,
            "lead_in_feed_mm_min": fallback("lead_in_feed_mm_min", feed),
            "lead_out_feed_mm_min": fallback("lead_out_feed_mm_min", feed),
            "transition_feed_mm_min": fallback("transition_feed_mm_min", feed),
            "ramp_feed_mm_min": fallback("ramp_feed_mm_min", feed / 3.0),
            "ramp_angle_deg": fallback("ramp_angle_deg", 2.0),
            "plunge_feed_mm_min": plunge,
            "plunge_feed_per_rev_mm": fallback("plunge_feed_per_rev_mm", plunge / rpm if rpm > 0 else 0.0),
            "retract_feed_mm_min": fallback("retract_feed_mm_min", feed),
            "feed_per_rev_mm": self.feed_per_rev_mm,
            "axial_engagement_mm": fallback("axial_engagement_mm", tool.geometry.diameter),
            "radial_engagement_mm": fallback("radial_engagement_mm", tool.geometry.diameter * 0.4),
            "coolant": self.coolant,
            "derived": derived,
        }

    def to_dict(self):
        d = {"id": self.id}
        for f in self.FIELDS:
            d[f] = getattr(self, f)
        return d

    @classmethod
    def from_dict(cls, d):
        d = dict(d)
        name = d.pop("name", "Default")
        return cls(name, **d)

    def duplicate(self):
        d = self.to_dict()
        d["id"] = new_id()
        d["name"] = self.name + " (copy)"
        return CuttingPreset.from_dict(d)


def _opt(value, conv):
    if value is None or value == "":
        return None
    return conv(value)


# ---------------------------------------------------------------------------
# Géométrie d'outil
# ---------------------------------------------------------------------------


class ToolGeometry(object):
    """Géométrie de coupe. Les champs non pertinents pour le type restent ``None``."""

    ALL_FIELDS = (
        "diameter",
        "shank_diameter",
        "overall_length",
        "flute_length",
        "shoulder_length",
        "body_length",
        "corner_radius",
        "tip_diameter",
        "tip_included_angle_deg",
        "taper_half_angle_deg",
        "taper_tip",
        "barrel_radius",
        "upper_radius",
        "lower_radius",
        "axial_distance",
        "tip_offset",
        "pitch",
        "pitch_min",
        "thread_teeth",
        "thread_profile_angle_deg",
        "thread_tip_type",
        "flute_style",
        "profile",
    )
    _LENGTHS = (
        "diameter",
        "shank_diameter",
        "overall_length",
        "flute_length",
        "shoulder_length",
        "body_length",
        "corner_radius",
        "tip_diameter",
        "barrel_radius",
        "upper_radius",
        "lower_radius",
        "axial_distance",
        "tip_offset",
        "pitch",
        "pitch_min",
    )
    _ANGLES = ("tip_included_angle_deg", "taper_half_angle_deg", "thread_profile_angle_deg")
    _ENUMS = {"flute_style": FLUTE_STYLES, "taper_tip": TAPER_TIPS, "thread_tip_type": THREAD_TIP_TYPES}

    def __init__(self, **kwargs):
        for f in self.ALL_FIELDS:
            setattr(self, f, None)
        for k, v in kwargs.items():
            if k not in self.ALL_FIELDS:
                raise UserError("geometry: unknown field {field}", field=repr(k))
            if v is None or v == "":
                continue
            if k in self._LENGTHS:
                v = to_mm(v)
            elif k in self._ANGLES:
                v = to_deg(v)
            elif k in self._ENUMS:
                if v not in self._ENUMS[k]:
                    raise UserError("unknown {key} {value}", key=k, value=repr(v))
            elif k == "thread_teeth":
                v = int(to_float(v))
            elif k == "profile":
                v = [Segment.from_dict(s) if isinstance(s, dict) else s for s in v]
            setattr(self, k, v)

    def validate(self, tool_type):
        fields = geometry_fields_for(tool_type)
        for f in ("diameter", "overall_length"):
            if getattr(self, f) is None or getattr(self, f) <= 0:
                raise UserError("geometry: {field} required and > 0", field=f)
        if self.shank_diameter is None:
            self.shank_diameter = self.diameter
        if self.flute_length is None:
            self.flute_length = min(self.overall_length, self.diameter * 3)
        if self.flute_length > self.overall_length:
            raise UserError("geometry: flute length > overall length")
        if self.shoulder_length is not None and self.shoulder_length < self.flute_length:
            raise UserError("geometry: shoulder length < flute length")
        if "corner_radius" in fields and self.corner_radius is None:
            self.corner_radius = self.diameter / 2.0 if tool_type == "taperedball" else 0.0
        if (
            self.corner_radius is not None
            and tool_type not in ("barrel", "lens", "ogive", "taperbarrel")
            and self.corner_radius > self.diameter / 2.0 + 1e-9
        ):
            raise UserError("geometry: corner radius > tool radius")
        if "tip_included_angle_deg" in fields:
            if self.tip_included_angle_deg is None:
                self.tip_included_angle_deg = 118.0 if tool_type == "drill" else 90.0
            if not 0 < self.tip_included_angle_deg < 180:
                raise UserError("geometry: included tip angle outside ]0, 180[")
        if "tip_diameter" in fields and self.tip_diameter is None:
            self.tip_diameter = 0.0
        if "taper_half_angle_deg" in fields:
            if self.taper_half_angle_deg is None:
                raise UserError("geometry: taper half-angle required")
            if not 0 <= self.taper_half_angle_deg < 90:
                raise UserError("geometry: taper half-angle outside [0, 90[")
        if self.body_length is not None and self.body_length > self.overall_length:
            raise UserError("geometry: length below holder > overall length")
        if "barrel_radius" in fields and (self.barrel_radius is None or self.barrel_radius <= 0):
            raise UserError("geometry: profile radius required and > 0")
        for f in ("upper_radius", "lower_radius"):
            if f in fields and getattr(self, f) is None:
                setattr(self, f, 0.0)
        if "axial_distance" in fields and self.axial_distance is None:
            self.axial_distance = self.flute_length
        if "tip_offset" in fields and self.tip_offset is None:
            self.tip_offset = 0.0
        if "flute_style" in fields and self.flute_style is None:
            self.flute_style = "straight"
        if "taper_tip" in fields and self.taper_tip is None:
            self.taper_tip = "bullnose" if self.corner_radius else "flat"
        if tool_type == "threadmill":
            if not self.pitch:
                raise UserError("geometry: (maximum) thread pitch required")
            if self.pitch_min is None:
                self.pitch_min = self.pitch
            if self.pitch_min > self.pitch:
                raise UserError("geometry: minimum pitch > maximum pitch")
            if self.thread_teeth is None:
                self.thread_teeth = 1
            if self.thread_profile_angle_deg is None:
                self.thread_profile_angle_deg = 60.0
            if self.thread_tip_type is None:
                self.thread_tip_type = "point"

    def to_dict(self):
        d = {}
        for f in self.ALL_FIELDS:
            v = getattr(self, f)
            if v is None:
                continue
            if f == "profile":
                v = [s.to_dict() for s in v]
            d[f] = v
        return d

    @classmethod
    def from_dict(cls, d):
        return cls(**d)


class ToolDefinition(object):
    """Définition d'une fraise (indépendante du porte-outil et de la machine)."""

    def __init__(self, name, tool_type, geometry, **kwargs):
        self.id = kwargs.pop("id", None) or new_id()
        self.name = name
        if tool_type not in TOOL_TYPES:
            raise UserError("unknown tool type: {tool_type}", tool_type=repr(tool_type))
        self.tool_type = tool_type
        self.geometry = geometry if isinstance(geometry, ToolGeometry) else ToolGeometry.from_dict(geometry)
        self.flute_count = int(to_float(kwargs.pop("flute_count", 2)))
        self.rotation = kwargs.pop("rotation", "cw")
        self.material = kwargs.pop("material", "carbide")
        self.coating = kwargs.pop("coating", "")
        self.vendor = kwargs.pop("vendor", "")
        self.product_id = kwargs.pop("product_id", "")
        self.product_url = kwargs.pop("product_url", "")
        self.description = kwargs.pop("description", "")
        self.tags = list(kwargs.pop("tags", []))
        self.favorite = bool(kwargs.pop("favorite", False))
        self.shank_segments = [
            Segment.from_dict(s) if isinstance(s, dict) else s for s in kwargs.pop("shank_segments", [])
        ]
        self.presets = [
            CuttingPreset.from_dict(p) if isinstance(p, dict) else p for p in kwargs.pop("presets", [])
        ]
        if kwargs:
            raise UserError("tool {name}: unknown fields {fields}", name=name, fields=sorted(kwargs))
        self.validate()

    def validate(self):
        if not self.name:
            raise UserError("tool: name required")
        if self.flute_count < 1:
            raise UserError("tool {name}: number of flutes < 1", name=self.name)
        if self.rotation not in ROTATIONS:
            raise UserError("tool {name}: invalid rotation direction", name=self.name)
        self.geometry.validate(self.tool_type)
        if not self.shank_segments:
            shank_len = self.geometry.overall_length - (
                self.geometry.shoulder_length or self.geometry.flute_length
            )
            if shank_len > 0:
                self.shank_segments = [
                    Segment(self.geometry.shank_diameter, self.geometry.shank_diameter, shank_len)
                ]
        seen = set()
        for p in self.presets:
            if p.id in seen:
                raise UserError("tool {name}: duplicate preset id", name=self.name)
            seen.add(p.id)

    def preset(self, preset_id):
        for p in self.presets:
            if p.id == preset_id:
                return p
        raise UserKeyError("preset {preset} not found on tool {tool}", preset=preset_id, tool=self.name)

    def add_preset(self, preset):
        self.presets.append(preset)
        self.validate()
        return preset

    def type_label(self):
        return TOOL_TYPES[self.tool_type][0]

    def silhouette(self):
        """Profil de révolution simplifié (liste de segments bas->haut) pour l'aperçu.

        Approximation : la partie taillée est un cylindre (ou un cône pour les
        pointes), suivie de l'épaulement puis des segments de queue.
        """
        g = self.geometry
        segs = []
        if self.tool_type in ("vbit", "engrave", "chamfer", "drill"):
            half = math.radians(g.tip_included_angle_deg / 2.0)
            tip = g.tip_diameter or 0.0
            cone_h = (g.diameter - tip) / 2.0 / math.tan(half) if half > 0 else 0.0
            cone_h = min(max(cone_h, 1e-3), g.overall_length)
            segs.append(Segment(tip, g.diameter, cone_h))
            rest = g.flute_length - cone_h
            if rest > 1e-6:
                segs.append(Segment(g.diameter, g.diameter, rest))
        elif self.tool_type in ("taper", "taperedball", "taperbarrel"):
            # le diamètre saisi est celui de la pointe ; le cône s'élargit vers le haut
            half = math.radians(g.taper_half_angle_deg)
            tip = g.diameter if self.tool_type != "taperbarrel" else (g.tip_diameter or g.diameter)
            top = tip + 2.0 * g.flute_length * math.tan(half)
            segs.append(Segment(tip, top, g.flute_length))
        elif self.tool_type in ("dovetail",):
            half = math.radians(g.taper_half_angle_deg)
            top = max(g.diameter - 2.0 * g.flute_length * math.tan(math.radians(90) - half), g.shank_diameter * 0.5)
            segs.append(Segment(g.diameter, top, g.flute_length))
        else:
            segs.append(Segment(g.diameter, g.diameter, g.flute_length))
        used = sum(s.length for s in segs)
        if g.shoulder_length and g.shoulder_length > used:
            segs.append(Segment(g.diameter, g.diameter, g.shoulder_length - used))
            used = g.shoulder_length
        for s in self.shank_segments:
            segs.append(s)
            used += s.length
        if used < g.overall_length - 1e-6:
            segs.append(Segment(g.shank_diameter, g.shank_diameter, g.overall_length - used))
        return segs

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "tool_type": self.tool_type,
            "geometry": self.geometry.to_dict(),
            "flute_count": self.flute_count,
            "rotation": self.rotation,
            "material": self.material,
            "coating": self.coating,
            "vendor": self.vendor,
            "product_id": self.product_id,
            "product_url": self.product_url,
            "description": self.description,
            "tags": list(self.tags),
            "favorite": self.favorite,
            "shank_segments": [s.to_dict() for s in self.shank_segments],
            "presets": [p.to_dict() for p in self.presets],
        }

    @classmethod
    def from_dict(cls, d):
        d = dict(d)
        return cls(d.pop("name"), d.pop("tool_type"), d.pop("geometry"), **d)

    def duplicate(self):
        d = copy.deepcopy(self.to_dict())
        d["id"] = new_id()
        d["name"] = self.name + " (copy)"
        for p in d["presets"]:
            p["id"] = new_id()
        d["favorite"] = False
        return ToolDefinition.from_dict(d)


# ---------------------------------------------------------------------------
# Porte-outil et assemblage
# ---------------------------------------------------------------------------


class Holder(object):
    """Porte-outil décrit par segments du nez (bas) vers la broche (haut)."""

    def __init__(self, name, segments, **kwargs):
        self.id = kwargs.pop("id", None) or new_id()
        self.name = name
        self.segments = [Segment.from_dict(s) if isinstance(s, dict) else s for s in segments]
        self.vendor = kwargs.pop("vendor", "")
        self.product_id = kwargs.pop("product_id", "")
        self.description = kwargs.pop("description", "")
        self.bore_diameter = _opt(kwargs.pop("bore_diameter", None), to_mm)
        if kwargs:
            raise UserError("holder {name}: unknown fields {fields}", name=name, fields=sorted(kwargs))
        if not self.segments:
            raise UserError("holder {name}: at least one segment required", name=name)

    @property
    def length(self):
        return sum(s.length for s in self.segments)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "segments": [s.to_dict() for s in self.segments],
            "vendor": self.vendor,
            "product_id": self.product_id,
            "description": self.description,
            "bore_diameter": self.bore_diameter,
        }

    @classmethod
    def from_dict(cls, d):
        d = dict(d)
        return cls(d.pop("name"), d.pop("segments"), **d)

    def duplicate(self):
        d = copy.deepcopy(self.to_dict())
        d["id"] = new_id()
        d["name"] = self.name + " (copy)"
        return Holder.from_dict(d)


class OutputData(object):
    """Données utilisées à l'export (postprocesseur)."""

    def __init__(
        self,
        tool_number=1,
        length_offset=None,
        diameter_offset=None,
        manual_tool_change=True,
        post_properties=None,
        comment="",
    ):
        self.tool_number = int(tool_number)
        self.length_offset = int(length_offset) if length_offset is not None else self.tool_number
        self.diameter_offset = int(diameter_offset) if diameter_offset is not None else self.tool_number
        self.manual_tool_change = bool(manual_tool_change)
        self.post_properties = dict(post_properties or {})
        self.comment = comment
        if self.tool_number < 0:
            raise UserError("negative tool number")

    def to_dict(self):
        return {
            "tool_number": self.tool_number,
            "length_offset": self.length_offset,
            "diameter_offset": self.diameter_offset,
            "manual_tool_change": self.manual_tool_change,
            "post_properties": dict(self.post_properties),
            "comment": self.comment,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(**d)


class ToolAssembly(object):
    """Fraise + porte-outil + sortie (stickout) + données de sortie."""

    def __init__(self, name, tool_id, holder_id=None, stickout=None, output=None, **kwargs):
        self.id = kwargs.pop("id", None) or new_id()
        self.name = name
        if not is_id(tool_id):
            raise UserError("assembly {name}: invalid tool_id", name=name)
        self.tool_id = tool_id
        self.holder_id = holder_id
        self.stickout = _opt(stickout, to_mm)
        self.gauge_length = _opt(kwargs.pop("gauge_length", None), to_mm)
        if isinstance(output, dict):
            output = OutputData.from_dict(output)
        self.output = output or OutputData()
        self.description = kwargs.pop("description", "")
        if kwargs:
            raise UserError("assembly {name}: unknown fields {fields}", name=name, fields=sorted(kwargs))

    def validate_against(self, tool, holder):
        """Vérifie la cohérence géométrique avec l'outil et le porte-outil."""
        if self.stickout is None:
            self.stickout = tool.geometry.body_length or tool.geometry.overall_length * 0.7
        if self.gauge_length is None:
            # longueur de jauge = sortie + longueur du porte-outil (nez -> référence broche)
            self.gauge_length = self.stickout + (holder.length if holder is not None else 0.0)
        if self.stickout > tool.geometry.overall_length:
            raise UserError("assembly {name}: stickout > overall tool length", name=self.name)
        if self.stickout < (tool.geometry.shoulder_length or tool.geometry.flute_length):
            raise UserError("assembly {name}: the fluted part goes into the holder", name=self.name)
        if holder is not None and holder.bore_diameter is not None:
            if abs(holder.bore_diameter - tool.geometry.shank_diameter) > 1e-6:
                raise UserError("assembly {name}: holder bore ({bore:.3f}) != shank ({shank:.3f})",
                                name=self.name, bore=holder.bore_diameter, shank=tool.geometry.shank_diameter)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "tool_id": self.tool_id,
            "holder_id": self.holder_id,
            "stickout": self.stickout,
            "gauge_length": self.gauge_length,
            "output": self.output.to_dict(),
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, d):
        d = dict(d)
        return cls(d.pop("name"), d.pop("tool_id"), **d)
