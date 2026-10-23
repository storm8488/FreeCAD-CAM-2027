# SPDX-License-Identifier: LGPL-2.1-or-later
"""Modèles de parcours (Aspire « Toolpath templates », Fusion « Templates »).

Un modèle enregistre les opérations d'un projet 2D : stratégie, outil **par nom** (et préréglage par nom),
paramètres de la stratégie, et pour chaque géométrie le **calque** et le **nom** du vecteur ciblé. Appliqué
à un nouveau dessin, chaque opération est recréée sur les vecteurs du même calque (SVG : calque Inkscape ou
groupe ; DXF : calque), sinon sur le vecteur du même nom, comme Aspire ; une opération sans cible est
rapportée et non créée. Fichier JSON ``.cam2027template``.
"""

import json
import os
import re
import xml.etree.ElementTree as ET

from ..i18n import Msg, UserError
from . import operations as opsmod
from . import sheet as sheetmod

FORMAT = "cam2027-toolpath-template"
VERSION = 1
EXTENSION = ".cam2027template"
LAYER_PROPERTY = "CAM2027Layer"

_INKSCAPE = "{http://www.inkscape.org/namespaces/inkscape}"


# -- calques des vecteurs --------------------------------------------------------------------------------


def svg_layers(path):
    """``{id d'élément: calque}`` d'un SVG : groupe ancêtre le plus proche portant un nom (``inkscape:label``,
    sinon son ``id``) ; éléments hors groupe absents."""
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return {}
    out = {}

    def walk(elem, layer):
        tag = elem.tag.rsplit("}", 1)[-1]
        if tag == "g":
            layer = elem.get(_INKSCAPE + "label") or elem.get("id") or layer
        elif elem.get("id") and layer:
            out[elem.get("id")] = layer
        for child in elem:
            walk(child, layer)

    walk(root, "")
    return out


def tag_layers(path, objects):
    """Après un import : note le calque de chaque vecteur (propriété ``CAM2027Layer``) ; retourne leur nombre."""
    ext = os.path.splitext(path)[1].lower()
    layers = svg_layers(path) if ext == ".svg" else {}
    n = 0
    for obj in objects:
        layer = layers.get(obj.Name) or layers.get(drawing_name(obj)) or _group_layer(obj)
        if layer:
            set_layer(obj, layer)
            n += 1
    return n


def drawing_name(obj):
    """Nom du vecteur dans le fichier : l'import SVG ajoute ``_w`` (contour sans remplissage) et FreeCAD un
    numéro aux doublons (``001``)."""
    return re.sub(r"(_w)?(\d{3})?$", "", obj.Label) or obj.Label


def _group_layer(obj):
    """Calque Draft / groupe qui contient l'objet (import DXF dans l'interface)."""
    for parent in getattr(obj, "InList", []):
        if parent.TypeId == "App::DocumentObjectGroup" or "Layer" in str(getattr(parent, "Proxy", "") or ""):
            return parent.Label
    return ""


def set_layer(obj, layer):
    if LAYER_PROPERTY not in obj.PropertiesList:
        obj.addProperty("App::PropertyString", LAYER_PROPERTY, "CAM2027", "Drawing layer (toolpath templates)")
    setattr(obj, LAYER_PROPERTY, layer)


def layer_of(obj):
    return getattr(obj, LAYER_PROPERTY, "") or _group_layer(obj)


# -- enregistrement --------------------------------------------------------------------------------------


def _source_vector(doc, obj):
    """Vecteur du dessin derrière un clone du job ou une face générée."""
    for attr in ("Objects", "Base"):
        inner = getattr(obj, attr, None)
        if isinstance(inner, list) and len(inner) == 1:
            inner = inner[0]
        if inner is not None and hasattr(inner, "Shape") and hasattr(inner, "Name"):
            obj = inner
            break
    if obj.Name.endswith(sheetmod.FACE_SUFFIX):
        obj = doc.getObject(obj.Name[: -len(sheetmod.FACE_SUFFIX)]) or obj
    return obj


def capture(proj, name="Template"):
    """Modèle (dict) des opérations du projet. Les opérations sans géométrie de dessin (toute la pièce) ou
    générées (fond plat, gravure enroulée) sont ignorées et rapportées dans ``skipped``."""
    lib = proj.library
    reg = proj.registry
    ops, skipped = [], []
    for top in proj.operations():
        op = proj.base_operation(top)
        rec = reg.get(op.Name)
        if rec is None or rec.get("kind") not in opsmod.STRATEGIES:
            skipped.append(op.Label)
            continue
        targets = []
        for obj, _subs in (op.Base or []):
            src = _source_vector(proj.doc, obj)
            if src in sheetmod.vector_objects(proj.doc):
                targets.append({"layer": layer_of(src), "name": drawing_name(src)})
        if not targets:
            skipped.append(op.Label)
            continue
        tool = lib.tool(rec["tool_id"])
        preset = tool.preset(rec["preset_id"])
        params = opsmod.read_params(op, opsmod.STRATEGIES[rec["kind"]]["params"])
        ops.append({
            "kind": rec["kind"],
            "label": op.Label,
            "active": bool(op.Active),
            "tool": tool.name,
            "tool_type": tool.tool_type,
            "diameter": tool.geometry.diameter,
            "preset": preset.name,
            "params": params,
            "targets": targets,
        })
    return {"format": FORMAT, "version": VERSION, "name": name, "operations": ops, "skipped": skipped}


def save(template, path):
    if not path.lower().endswith(EXTENSION):
        path += EXTENSION
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(template, fp, indent=1, ensure_ascii=False)
    return path


def load(path):
    with open(path, encoding="utf-8") as fp:
        data = json.load(fp)
    if data.get("format") != FORMAT:
        raise UserError("{file} is not a CAM2027 toolpath template", file=os.path.basename(path))
    if int(data.get("version", 0)) > VERSION:
        raise UserError("{file} was made by a newer CAM2027 (template version {v})",
                        file=os.path.basename(path), v=data.get("version"))
    return data


# -- application -----------------------------------------------------------------------------------------


def find_tool(lib, entry):
    """Outil du modèle dans la bibliothèque du projet : même nom, sinon même type et même diamètre."""
    tools = list(lib.tools.values())
    for tool in tools:
        if tool.name == entry["tool"]:
            return tool
    for tool in tools:
        if tool.tool_type == entry.get("tool_type") and abs(tool.geometry.diameter - float(entry.get("diameter", -1))) < 1e-6:
            return tool
    return None


def match_targets(doc, targets):
    """Vecteurs du dessin pour les cibles d'une opération : par calque d'abord, puis par nom ;
    retourne ``(vecteurs, comment)`` avec ``comment`` = « layer » / « name » / « »."""
    vectors = sheetmod.vector_objects(doc)
    layers = set(t["layer"] for t in targets if t.get("layer"))
    by_layer = [v for v in vectors if layers and layer_of(v) in layers]
    if by_layer:
        return by_layer, "layer"
    names = set(t["name"] for t in targets)
    by_name = [v for v in vectors if drawing_name(v) in names or v.Label in names]
    return by_name, ("name" if by_name else "")


def apply(proj, template):
    """Recrée les opérations du modèle sur le dessin du projet (job du panneau déjà créé).
    Retourne ``{"created": [(op, comment)], "missing": [Msg]}`` ; ne calcule pas."""
    if not proj.has_job:
        raise UserError("Define the stock and fixture first (this creates the job).")
    lib = proj.library
    created, missing = [], []
    for entry in template.get("operations", []):
        kind = entry["kind"]
        if kind not in opsmod.STRATEGIES:
            missing.append(Msg("{op}: unknown strategy {kind}", op=entry["label"], kind=kind))
            continue
        vectors, how = match_targets(proj.doc, entry["targets"])
        if not vectors:
            missing.append(Msg("{op}: no vector on layer {layer} or named {name}", op=entry["label"],
                               layer=", ".join(sorted(set(t["layer"] for t in entry["targets"] if t.get("layer")))) or "-",
                               name=", ".join(t["name"] for t in entry["targets"])))
            continue
        tool = find_tool(lib, entry)
        if tool is None:
            missing.append(Msg("{op}: tool {tool} not in the project library", op=entry["label"], tool=entry["tool"]))
            continue
        assemblies = lib.assemblies_for_tool(tool.id)
        if not assemblies:
            missing.append(Msg("{op}: tool {tool} not in the project library", op=entry["label"], tool=entry["tool"]))
            continue
        preset = next((p for p in tool.presets if p.name == entry.get("preset")), tool.presets[0])
        if kind in sheetmod.FACE_STRATEGIES:
            vectors = [v for v in vectors if proj.doc.getObject(v.Name + sheetmod.FACE_SUFFIX) is not None]
            if not vectors:
                missing.append(Msg("{op}: the matching vectors are not closed", op=entry["label"]))
                continue
        base = [(v, []) for v in vectors]  # vecteur entier : face ou arêtes selon la stratégie
        op, _rec = proj.add_operation(kind, entry["label"], assemblies[0].id, preset.id, base=base,
                                      params=dict(entry.get("params") or {}))
        op.Active = bool(entry.get("active", True))
        created.append((op, how))
    return {"created": created, "missing": missing}
