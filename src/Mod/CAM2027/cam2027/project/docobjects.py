# SPDX-License-Identifier: LGPL-2.1-or-later
"""Objet de document ``CAM2027Project`` : porte l'instantané de bibliothèque,
le profil machine et le registre des opérations du projet.

Les données sont stockées en JSON dans des propriétés chaîne pour rester
lisibles dans le fichier ``.FCStd`` et survivre aux versions de FreeCAD.
"""

import json

import FreeCAD

from ..version import __version__, DATA_VERSION

OBJECT_NAME = "CAM2027Project"


class ProjectInfo(object):
    def __init__(self, obj):
        obj.Proxy = self
        self.setup(obj)

    def setup(self, obj):
        props = obj.PropertiesList
        if "DataVersion" not in props:
            obj.addProperty("App::PropertyInteger", "DataVersion", "CAM2027", "Data schema version")
            obj.DataVersion = DATA_VERSION
        if "AppVersion" not in props:
            obj.addProperty("App::PropertyString", "AppVersion", "CAM2027", "CAM2027 version that wrote the file")
            obj.AppVersion = __version__
        if "LibrarySnapshot" not in props:
            obj.addProperty("App::PropertyString", "LibrarySnapshot", "CAM2027", "Frozen tool library (JSON)")
            obj.LibrarySnapshot = "{}"
        if "Machine" not in props:
            obj.addProperty("App::PropertyString", "Machine", "CAM2027", "Machine profile (JSON)")
            obj.Machine = "{}"
        if "OperationRegistry" not in props:
            obj.addProperty(
                "App::PropertyString", "OperationRegistry", "CAM2027", "Per-operation tool/preset record (JSON)"
            )
            obj.OperationRegistry = "{}"
        if "Job" not in props:
            obj.addProperty("App::PropertyLink", "Job", "CAM2027", "CAM job of this project")
        for name in ("LibrarySnapshot", "Machine", "OperationRegistry"):
            obj.setEditorMode(name, 1)

    def onDocumentRestored(self, obj):
        self.setup(obj)

    def execute(self, obj):
        pass

    def dumps(self):
        return None

    def loads(self, state):
        return None

    # -- accès JSON ------------------------------------------------------------

    @staticmethod
    def get_json(obj, prop):
        raw = getattr(obj, prop) or "{}"
        return json.loads(raw)

    @staticmethod
    def set_json(obj, prop, value):
        setattr(obj, prop, json.dumps(value, ensure_ascii=False, sort_keys=True))


def create_info(doc):
    obj = doc.addObject("App::FeaturePython", OBJECT_NAME)
    ProjectInfo(obj)
    if FreeCAD.GuiUp and obj.ViewObject:
        obj.ViewObject.Proxy = 0
    return obj


def find_info(doc):
    for obj in doc.Objects:
        if hasattr(obj, "Proxy") and isinstance(getattr(obj, "Proxy", None), ProjectInfo):
            return obj
    obj = doc.getObject(OBJECT_NAME)
    if obj is not None and hasattr(obj, "LibrarySnapshot"):
        return obj
    return None
