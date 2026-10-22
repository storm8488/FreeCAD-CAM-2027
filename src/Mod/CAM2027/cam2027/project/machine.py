# SPDX-License-Identifier: LGPL-2.1-or-later
"""Profil machine.

Toute donnée inconnue vaut ``None`` et est affichée « à renseigner ». Aucune
course, avance maximale, plage de broche ni caractéristique de l'axe A n'est
déduite du modèle de machine : elles proviennent uniquement de l'utilisateur.
"""

from ..ids import new_id
from ..version import DATA_VERSION

CONTROLLERS = ("grbl", "linuxcnc", "mach3", "marlin", "smoothie", "unknown")


class RotaryAxis(object):
    """Axe rotatif A (par convention autour de X)."""

    FIELDS = (
        "name",
        "about",
        "positive_direction",
        "center_offset_mm",
        "min_deg",
        "max_deg",
        "max_feed_deg_min",
        "angle_mode",
        "chuck_diameter_mm",
        "chuck_length_mm",
        "jaw_count",
        "tailstock",
        "present",
    )

    def __init__(self, **kwargs):
        self.name = kwargs.pop("name", "A")
        self.about = kwargs.pop("about", "X")
        self.positive_direction = kwargs.pop("positive_direction", None)  # "ccw_looking_from_plus_x" ...
        self.center_offset_mm = kwargs.pop("center_offset_mm", None)  # (y, z) du centre de rotation
        self.min_deg = kwargs.pop("min_deg", None)
        self.max_deg = kwargs.pop("max_deg", None)
        self.max_feed_deg_min = kwargs.pop("max_feed_deg_min", None)
        self.angle_mode = kwargs.pop("angle_mode", None)  # "continuous" | "wrap_360" | "limited"
        self.chuck_diameter_mm = kwargs.pop("chuck_diameter_mm", None)
        self.chuck_length_mm = kwargs.pop("chuck_length_mm", None)
        self.jaw_count = kwargs.pop("jaw_count", None)
        self.tailstock = kwargs.pop("tailstock", None)  # bool ou None
        self.present = kwargs.pop("present", False)
        if kwargs:
            raise ValueError("axe rotatif : champs inconnus %s" % sorted(kwargs))

    def to_dict(self):
        return {f: getattr(self, f) for f in self.FIELDS}

    @classmethod
    def from_dict(cls, d):
        return cls(**d)


#: libellés anglais (traduits par l'interface) des champs machine, y compris ceux de l'axe A
FIELD_LABELS = {
    "name": "Name", "vendor": "Vendor", "model": "Model", "controller": "Controller",
    "post_processor": "Post processor", "post_processor_args": "Post arguments",
    "travel_x_mm": "Travel X (mm)", "travel_y_mm": "Travel Y (mm)", "travel_z_mm": "Travel Z (mm)",
    "max_feed_xy_mm_min": "Max feed XY (mm/min)", "max_feed_z_mm_min": "Max feed Z (mm/min)",
    "spindle_min_rpm": "Spindle min (rpm)", "spindle_max_rpm": "Spindle max (rpm)",
    "spindle_power_w": "Spindle power (W)", "collet": "Collet", "notes": "Notes",
    "tool_change": "Tool change", "coolant_options": "Coolant options", "feed_mode_rotary": "Rotary feed mode (G93/G94)",
    "rotary.positive_direction": "A axis positive direction", "rotary.center_offset_mm": "A axis centre offset (mm)",
    "rotary.min_deg": "A axis min (deg)", "rotary.max_deg": "A axis max (deg)",
    "rotary.max_feed_deg_min": "A axis max feed (deg/min)", "rotary.angle_mode": "A axis angle mode",
    "rotary.chuck_diameter_mm": "Chuck diameter (mm)", "rotary.chuck_length_mm": "Chuck length (mm)",
    "rotary.jaw_count": "Jaw count", "rotary.tailstock": "Tailstock",
}


class MachineProfile(object):
    FIELDS = (
        "name",
        "vendor",
        "model",
        "controller",
        "post_processor",
        "post_processor_args",
        "travel_x_mm",
        "travel_y_mm",
        "travel_z_mm",
        "max_feed_xy_mm_min",
        "max_feed_z_mm_min",
        "spindle_min_rpm",
        "spindle_max_rpm",
        "spindle_power_w",
        "collet",
        "tool_change",
        "coolant_options",
        "feed_mode_rotary",
        "notes",
    )

    def __init__(self, name, **kwargs):
        self.id = kwargs.pop("id", None) or new_id()
        self.name = name
        self.vendor = kwargs.pop("vendor", "")
        self.model = kwargs.pop("model", "")
        self.controller = kwargs.pop("controller", "unknown")
        self.post_processor = kwargs.pop("post_processor", None)
        self.post_processor_args = kwargs.pop("post_processor_args", "")
        self.travel_x_mm = kwargs.pop("travel_x_mm", None)
        self.travel_y_mm = kwargs.pop("travel_y_mm", None)
        self.travel_z_mm = kwargs.pop("travel_z_mm", None)
        self.max_feed_xy_mm_min = kwargs.pop("max_feed_xy_mm_min", None)
        self.max_feed_z_mm_min = kwargs.pop("max_feed_z_mm_min", None)
        self.spindle_min_rpm = kwargs.pop("spindle_min_rpm", None)
        self.spindle_max_rpm = kwargs.pop("spindle_max_rpm", None)
        self.spindle_power_w = kwargs.pop("spindle_power_w", None)
        self.collet = kwargs.pop("collet", None)
        self.tool_change = kwargs.pop("tool_change", "manual")
        self.coolant_options = list(kwargs.pop("coolant_options", ["none"]))
        self.feed_mode_rotary = kwargs.pop("feed_mode_rotary", None)  # "G93" | "G94" | None
        self.notes = kwargs.pop("notes", "")
        # palpeur : present, tip_diameter_mm, plate_thickness_mm, feed_mm_min, travel_mm, tool_number (project/probe.py)
        self.probe = dict(kwargs.pop("probe", None) or {})
        rotary = kwargs.pop("rotary", None)
        self.rotary = RotaryAxis.from_dict(rotary) if isinstance(rotary, dict) else (rotary or RotaryAxis())
        if kwargs:
            raise ValueError("machine : champs inconnus %s" % sorted(kwargs))
        if self.controller not in CONTROLLERS:
            raise ValueError("machine : contrôleur inconnu %r" % (self.controller,))

    def unknown_fields(self):
        """Champs encore à renseigner (None)."""
        missing = [f for f in self.FIELDS if getattr(self, f) is None]
        if self.rotary.present:
            missing += ["rotary.%s" % f for f in RotaryAxis.FIELDS if getattr(self.rotary, f) is None]
        return missing

    def to_dict(self):
        d = {"id": self.id, "data_version": DATA_VERSION}
        for f in self.FIELDS:
            d[f] = getattr(self, f)
        d["rotary"] = self.rotary.to_dict()
        d["probe"] = dict(self.probe)
        return d

    @classmethod
    def from_dict(cls, d):
        d = dict(d)
        d.pop("data_version", None)
        return cls(d.pop("name"), **d)


def lunyee_4040_nova():
    """Profil de la machine de l'utilisateur ; les valeurs inconnues restent None.

    Seuls le nom, le fournisseur, la broche G-Penny 1,5 kW (puissance) et le
    pilotage par CNCjs sont connus. Le contrôleur et le postprocesseur sont
    des hypothèses signalées dans ``notes`` et doivent être confirmés.
    """
    return MachineProfile(
        "LUNYEE 4040 Nova",
        vendor="LUNYEE",
        model="4040 Nova",
        controller="grbl",
        post_processor="grbl",
        post_processor_args="--no-show-editor --precision=3",
        spindle_power_w=1500,
        tool_change="manual",
        coolant_options=["none"],
        notes=(
            "Contrôleur supposé GRBL (piloté par CNCjs) : à confirmer. "
            "Courses, avances maximales, plage de broche, pince et axe A : à renseigner."
        ),
    )
