# SPDX-License-Identifier: LGPL-2.1-or-later
"""Stockage et manipulation d'une bibliothèque d'outils (fichier JSON ``.cam2027tools``).

Structure du fichier :

    {
      "format": "cam2027-tool-library",
      "data_version": 1,
      "id": "<uuid>", "name": "...", "revision": 12, "updated": "2026-10-20T10:00:00",
      "tools": [...], "holders": [...], "assemblies": [...]
    }

``revision`` est incrémenté à chaque sauvegarde. Un projet conserve un
instantané complet (voir :meth:`ToolLibrary.snapshot`) : une modification
ultérieure de la bibliothèque ne modifie jamais un projet existant.
"""

import copy
import datetime
import json
import os

from ..ids import new_id
from ..version import DATA_VERSION
from .model import ToolDefinition, Holder, ToolAssembly, CuttingPreset, TOOL_TYPES

FORMAT = "cam2027-tool-library"
EXTENSION = ".cam2027tools"


class ToolLibrary(object):
    def __init__(self, name="Library", library_id=None):
        self.id = library_id or new_id()
        self.name = name
        self.revision = 0
        self.updated = None
        self.tools = {}
        self.holders = {}
        self.assemblies = {}
        self.path = None

    # -- accès ---------------------------------------------------------------

    def tool(self, tool_id):
        try:
            return self.tools[tool_id]
        except KeyError:
            raise KeyError("outil %s introuvable" % tool_id)

    def holder(self, holder_id):
        try:
            return self.holders[holder_id]
        except KeyError:
            raise KeyError("porte-outil %s introuvable" % holder_id)

    def assembly(self, assembly_id):
        try:
            return self.assemblies[assembly_id]
        except KeyError:
            raise KeyError("assemblage %s introuvable" % assembly_id)

    def resolve_assembly(self, assembly_id):
        """Retourne (assemblage, outil, porte-outil ou None) après validation."""
        asm = self.assembly(assembly_id)
        tool = self.tool(asm.tool_id)
        holder = self.holder(asm.holder_id) if asm.holder_id else None
        asm.validate_against(tool, holder)
        return asm, tool, holder

    # -- édition -------------------------------------------------------------

    def add_tool(self, tool):
        if tool.id in self.tools:
            raise ValueError("outil déjà présent : %s" % tool.id)
        self.tools[tool.id] = tool
        return tool

    def add_holder(self, holder):
        if holder.id in self.holders:
            raise ValueError("porte-outil déjà présent : %s" % holder.id)
        self.holders[holder.id] = holder
        return holder

    def add_assembly(self, assembly):
        if assembly.id in self.assemblies:
            raise ValueError("assemblage déjà présent : %s" % assembly.id)
        self.resolve_assembly_obj(assembly)
        self.assemblies[assembly.id] = assembly
        return assembly

    def resolve_assembly_obj(self, assembly):
        tool = self.tool(assembly.tool_id)
        holder = self.holder(assembly.holder_id) if assembly.holder_id else None
        assembly.validate_against(tool, holder)

    def remove_tool(self, tool_id):
        users = [a.name for a in self.assemblies.values() if a.tool_id == tool_id]
        if users:
            raise ValueError("outil utilisé par les assemblages : %s" % ", ".join(users))
        del self.tools[tool_id]

    def remove_holder(self, holder_id):
        users = [a.name for a in self.assemblies.values() if a.holder_id == holder_id]
        if users:
            raise ValueError("porte-outil utilisé par les assemblages : %s" % ", ".join(users))
        del self.holders[holder_id]

    def remove_assembly(self, assembly_id):
        del self.assemblies[assembly_id]

    def duplicate_tool(self, tool_id):
        return self.add_tool(self.tool(tool_id).duplicate())

    def duplicate_holder(self, holder_id):
        return self.add_holder(self.holder(holder_id).duplicate())

    def set_favorite(self, tool_id, value=True):
        self.tool(tool_id).favorite = bool(value)

    def bulk_edit(self, tool_ids, **fields):
        """Édition groupée : applique les champs simples (material, coating, vendor,
        tags, flute_count, rotation) ou géométriques (préfixe ``geometry.``) à
        plusieurs outils. Chaque outil est revalidé ; une erreur annule tout."""
        originals = {tid: copy.deepcopy(self.tool(tid).to_dict()) for tid in tool_ids}
        try:
            for tid in tool_ids:
                tool = self.tool(tid)
                for key, value in fields.items():
                    if key.startswith("geometry."):
                        setattr(tool.geometry, key[len("geometry.") :], value)
                    elif key in ("material", "coating", "vendor", "tags", "flute_count", "rotation", "description"):
                        setattr(tool, key, value)
                    else:
                        raise ValueError("édition groupée : champ non autorisé %r" % key)
                tool.validate()
        except Exception:
            for tid, d in originals.items():
                self.tools[tid] = ToolDefinition.from_dict(d)
            raise

    # -- recherche -----------------------------------------------------------

    def search(self, text="", tool_type=None, material=None, favorites_only=False, tags=None):
        """Filtre les outils ; retourne une liste triée par nom."""
        text = (text or "").strip().lower()
        result = []
        for tool in self.tools.values():
            if tool_type and tool.tool_type != tool_type:
                continue
            if material and tool.material.lower() != material.lower():
                continue
            if favorites_only and not tool.favorite:
                continue
            if tags and not set(tags).issubset(set(tool.tags)):
                continue
            if text:
                haystack = " ".join(
                    [tool.name, tool.vendor, tool.product_id, tool.description, tool.tool_type, tool.type_label()]
                    + tool.tags
                ).lower()
                if text not in haystack and not _diameter_match(text, tool):
                    continue
            result.append(tool)
        result.sort(key=lambda t: t.name.lower())
        return result

    def assemblies_for_tool(self, tool_id):
        return [a for a in self.assemblies.values() if a.tool_id == tool_id]

    # -- sérialisation -------------------------------------------------------

    def to_dict(self):
        return {
            "format": FORMAT,
            "data_version": DATA_VERSION,
            "id": self.id,
            "name": self.name,
            "revision": self.revision,
            "updated": self.updated,
            "tools": [t.to_dict() for t in sorted(self.tools.values(), key=lambda t: t.name.lower())],
            "holders": [h.to_dict() for h in sorted(self.holders.values(), key=lambda h: h.name.lower())],
            "assemblies": [
                a.to_dict() for a in sorted(self.assemblies.values(), key=lambda a: a.output.tool_number)
            ],
        }

    @classmethod
    def from_dict(cls, data):
        data = migrate(data)
        if data.get("format") != FORMAT:
            raise ValueError("format de bibliothèque inattendu : %r" % data.get("format"))
        lib = cls(data.get("name", "Library"), data.get("id"))
        lib.revision = int(data.get("revision", 0))
        lib.updated = data.get("updated")
        for d in data.get("tools", []):
            lib.add_tool(ToolDefinition.from_dict(d))
        for d in data.get("holders", []):
            lib.add_holder(Holder.from_dict(d))
        for d in data.get("assemblies", []):
            lib.add_assembly(ToolAssembly.from_dict(d))
        return lib

    def snapshot(self):
        """Copie profonde sérialisable, figée pour un projet."""
        return copy.deepcopy(self.to_dict())

    def save(self, path=None):
        path = path or self.path
        if not path:
            raise ValueError("chemin de sauvegarde manquant")
        self.revision += 1
        self.updated = datetime.datetime.now().replace(microsecond=0).isoformat()
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fp:
            json.dump(self.to_dict(), fp, indent=2, ensure_ascii=False, sort_keys=False)
        os.replace(tmp, path)
        self.path = path
        return path

    @classmethod
    def load(cls, path):
        with open(path, "r", encoding="utf-8") as fp:
            data = json.load(fp)
        lib = cls.from_dict(data)
        lib.path = path
        return lib

    # -- statistiques --------------------------------------------------------

    def summary(self):
        by_type = {}
        for t in self.tools.values():
            by_type[t.tool_type] = by_type.get(t.tool_type, 0) + 1
        return {
            "tools": len(self.tools),
            "holders": len(self.holders),
            "assemblies": len(self.assemblies),
            "by_type": by_type,
        }


def _diameter_match(text, tool):
    """Permet de chercher « 6 » ou « 6mm » et de trouver les outils de 6 mm."""
    t = text.replace("mm", "").replace(",", ".").strip()
    try:
        value = float(t)
    except ValueError:
        return False
    return abs(tool.geometry.diameter - value) < 1e-6


def migrate(data):
    """Migre un dictionnaire de bibliothèque vers DATA_VERSION (sans effet aujourd'hui)."""
    version = int(data.get("data_version", 0))
    if version > DATA_VERSION:
        raise ValueError(
            "bibliothèque écrite par une version plus récente (data_version %d > %d)" % (version, DATA_VERSION)
        )
    if version < 1:
        data = dict(data)
        data["data_version"] = 1
    return data


def default_library_path():
    """Emplacement par défaut de la bibliothèque utilisateur."""
    import FreeCAD

    base = os.path.join(FreeCAD.getUserAppDataDir(), "CAM2027")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "library" + EXTENSION)


def starter_library():
    """Bibliothèque de démarrage : quelques outils courants, un porte-outil ER20.

    Les conditions de coupe sont des points de départ prudents pour une petite
    fraiseuse de bureau ; elles ne constituent pas une recommandation.
    """
    lib = ToolLibrary("CAM2027 starter")
    er20 = lib.add_holder(
        Holder(
            "ER20 collet chuck (generic)",
            [{"lower_diameter": 28.0, "upper_diameter": 28.0, "length": 20.0},
             {"lower_diameter": 28.0, "upper_diameter": 34.0, "length": 15.0}],
            description="Generic ER20 nut + body; replace with the real G-Penny spindle nose dimensions.",
        )
    )
    specs = [
        ("6 mm flat end mill 2F", "endmill", dict(diameter=6, shank_diameter=6, overall_length=50, flute_length=18), 2,
         [("Wood roughing", "roughing", "wood", 18000, 1800, 3.0, 2.4),
          ("Aluminium finishing", "finishing", "aluminium", 16000, 600, 1.0, 0.6)]),
        ("3 mm flat end mill 2F", "endmill", dict(diameter=3, shank_diameter=3.175, overall_length=38, flute_length=12), 2,
         [("Plastic general", "general", "plastic", 18000, 900, 1.5, 1.2)]),
        ("6 mm ball end mill 2F", "ballend", dict(diameter=6, shank_diameter=6, overall_length=50, flute_length=15), 2,
         [("Wood finishing", "finishing", "wood", 18000, 1500, 1.0, 0.5)]),
        ("6 mm compression 2F", "endmill", dict(diameter=6, shank_diameter=6, overall_length=55, flute_length=22, flute_style="compression"), 2,
         [("Plywood through-cut", "slotting", "wood", 18000, 2400, 6.0, 6.0)]),
        ("60° V-bit", "vbit", dict(diameter=12.7, shank_diameter=6.35, overall_length=50, flute_length=11, tip_included_angle_deg=60, tip_diameter=0.1), 2,
         [("Wood V-carve", "engraving", "wood", 18000, 1200, 3.0, 1.0)]),
        ("90° V-bit", "vbit", dict(diameter=12.7, shank_diameter=6.35, overall_length=50, flute_length=6.35, tip_included_angle_deg=90, tip_diameter=0.1), 2,
         [("Wood V-carve", "engraving", "wood", 18000, 1200, 3.0, 1.0)]),
        ("3 mm drill", "drill", dict(diameter=3, shank_diameter=3, overall_length=60, flute_length=30, tip_included_angle_deg=118), 2,
         [("Wood drilling", "drilling", "wood", 12000, 300, 3.0, 3.0)]),
        ("4 mm thread mill (M5-M8, pitch 0.5-1.25)", "threadmill",
         dict(diameter=4, shank_diameter=6, overall_length=60, flute_length=10, shoulder_length=22,
              pitch=1.25, pitch_min=0.5, thread_teeth=6), 3,
         [("Aluminium threading", "general", "aluminium", 12000, 400, 1.25, 0.3)]),
    ]
    number = 1
    for name, ttype, geom, flutes, presets in specs:
        tool = lib.add_tool(ToolDefinition(name, ttype, geom, flute_count=flutes))
        for pname, usage, material, rpm, feed, ap, ae in presets:
            tool.add_preset(
                CuttingPreset(pname, usage=usage, material=material, spindle_rpm=rpm, feed_mm_min=feed,
                              plunge_feed_mm_min=feed / 3.0, axial_engagement_mm=ap, radial_engagement_mm=ae)
            )
        lib.add_assembly(
            ToolAssembly("T%d %s" % (number, name), tool.id, er20.id,
                         stickout=geom["overall_length"] * 0.7,
                         output={"tool_number": number, "manual_tool_change": True})
        )
        number += 1
    return lib


__all__ = ["ToolLibrary", "starter_library", "default_library_path", "migrate", "TOOL_TYPES", "EXTENSION"]
