# SPDX-License-Identifier: LGPL-2.1-or-later
"""Profil « FAO seule » : préférences FreeCAD appliquées au profil du lanceur.

Appliqué uniquement quand FreeCAD a été démarré par ``scripts/cam2027.cmd``
(variable d'environnement ``CAM2027_HOME``), donc jamais au profil FreeCAD
habituel de l'utilisateur. Idempotent : chaque version du profil n'est
appliquée qu'une fois (``CAM2027/ProfileVersion``), ce qui laisse ensuite
l'utilisateur libre de changer ses préférences. Désactivable avec le
paramètre booléen ``CAM2027/CamOnly``.

Le thème sombre est le pack de préférences « FreeCAD Dark » livré avec
FreeCAD (fichier XML de paramètres), lu et recopié clé par clé.
"""

import os
import xml.etree.ElementTree as ET

import FreeCAD

PROFILE_VERSION = 1
WORKBENCH = "CAM2027Workbench"
DARK_PACK = ("Gui", "PreferencePacks", "FreeCAD Dark", "FreeCAD Dark.cfg")

_SETTERS = {
    "FCText": ("SetString", str),
    "FCBool": ("SetBool", lambda v: v not in ("0", "false", "False")),
    "FCInt": ("SetInt", int),
    "FCUInt": ("SetUnsigned", int),
    "FCFloat": ("SetFloat", float),
}


def launched_by_cam2027():
    return bool(os.environ.get("CAM2027_HOME"))


def apply_preference_pack(path, root="User parameter:"):
    """Recopie les paramètres d'un pack FreeCAD (XML) sous ``root`` ; retourne le nombre de clés."""
    tree = ET.parse(path)
    count = 0

    def walk(node, groups):
        nonlocal count
        for child in node:
            if child.tag == "FCParamGroup":
                walk(child, groups + [child.get("Name")])
            elif child.tag in _SETTERS:
                if not groups:
                    continue
                grp = FreeCAD.ParamGet(root + "/".join(groups))
                setter, conv = _SETTERS[child.tag]
                raw = child.get("Value") if child.get("Value") is not None else (child.text or "")
                getattr(grp, setter)(child.get("Name"), conv(raw))
                count += 1

    document = tree.getroot()
    # le fichier commence par <FCParameters><FCParamGroup Name="Root"> : « Root » n'est pas un chemin
    top = document.find("FCParamGroup")
    walk(top if top is not None and top.get("Name") == "Root" else document, [])
    return count


def hide_other_workbenches(keep=(WORKBENCH,)):
    """Masque tous les ateliers FreeCAD sauf ``keep`` (préférence Workbenches/Disabled)."""
    import FreeCADGui

    names = sorted(n for n in FreeCADGui.listWorkbenches() if n not in keep and n != "NoneWorkbench")
    grp = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Workbenches")
    grp.SetString("Disabled", ",".join(names))
    grp.SetString("Enabled", ",".join(keep))
    return names


def apply_cam_only_profile(force=False):
    """Applique le profil FAO seule ; retourne un dict décrivant ce qui a été fait (ou ``None``)."""
    if not force and not launched_by_cam2027():
        return None
    grp = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/CAM2027")
    if not grp.GetBool("CamOnly", True):
        return None
    if not force and grp.GetInt("ProfileVersion", 0) >= PROFILE_VERSION:
        return None
    done = {"dark_pack": 0, "hidden": []}
    pack = os.path.join(FreeCAD.getResourceDir(), *DARK_PACK)
    if os.path.isfile(pack):
        done["dark_pack"] = apply_preference_pack(pack)
    general = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/General")
    general.SetString("AutoloadModule", WORKBENCH)
    general.SetInt("ToolbarIconSize", 32)
    general.SetBool("ShowSplasher", False)
    FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Mod/Start").SetBool("closeStart", True)
    done["hidden"] = hide_other_workbenches()
    grp.SetInt("ProfileVersion", PROFILE_VERSION)
    return done
