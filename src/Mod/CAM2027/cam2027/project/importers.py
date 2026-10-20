# SPDX-License-Identifier: LGPL-2.1-or-later
"""Import de pièces et de dessins dans le document du projet.

Formats et état :

- STEP (``.step``/``.stp``) : solides via ``Part`` — testé automatiquement.
- STL / OBJ : maillage via ``Mesh`` — testé automatiquement (STL). Un maillage
  n'est pas un solide : seules les opérations 3D sur maillage (Surface, OCL)
  peuvent l'utiliser ; la conversion en solide est proposée pour les petits
  maillages fermés.
- SVG : vecteurs via ``importSVG`` (module Draft) — testé automatiquement.
- DXF : vecteurs via ``importDXF`` (module Draft) — testé automatiquement.
- BRep / FCStd : via ``Part`` / ``FreeCAD.openDocument`` (copie des objets).
"""

import os

import FreeCAD


class ImportResult(object):
    def __init__(self, kind, objects, warnings=None):
        self.kind = kind  # "solid" | "mesh" | "vector"
        self.objects = list(objects)
        self.warnings = list(warnings or [])

    def __repr__(self):
        return "ImportResult(%s, %d objects)" % (self.kind, len(self.objects))


def _new_objects(doc, before):
    names = set(o.Name for o in before)
    return [o for o in doc.Objects if o.Name not in names]


def import_file(doc, path, label=None):
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    ext = os.path.splitext(path)[1].lower()
    before = list(doc.Objects)
    previous = FreeCAD.ActiveDocument
    FreeCAD.setActiveDocument(doc.Name)
    try:
        if ext in (".step", ".stp", ".iges", ".igs"):
            # module Import (sans interface) : lecteur STEP/IGES commun aux deux versions,
            # Part.insert est déprécié pour STEP depuis 1.1
            import Import

            Import.insert(path, doc.Name)
            kind = "solid"
        elif ext in (".brep", ".brp"):
            import Part

            Part.insert(path, doc.Name)
            kind = "solid"
        elif ext in (".stl", ".obj", ".ast", ".ply", ".off"):
            import Mesh

            Mesh.insert(path, doc.Name)
            kind = "mesh"
        elif ext == ".svg":
            import importSVG

            importSVG.insert(path, doc.Name)
            kind = "vector"
        elif ext == ".dxf":
            if FreeCAD.GuiUp:
                import importDXF

                importDXF.insert(path, doc.Name)
            else:
                # importDXF.insert exige ImportGui ; en console, le lecteur C++ suffit.
                # Contournement (FreeCAD 1.0.2) : readDXF laisse une exception pendante
                # tant qu'aucun Part::Feature n'existe dans le document.
                import Import

                placeholder = None
                if not any(o.isDerivedFrom("Part::Feature") for o in doc.Objects):
                    placeholder = doc.addObject("Part::Feature", "CAM2027DxfPlaceholder")
                try:
                    Import.readDXF(path, doc.Name)
                finally:
                    if placeholder is not None:
                        doc.removeObject(placeholder.Name)
            kind = "vector"
        else:
            raise ValueError("format non pris en charge : %s" % ext)
    finally:
        if previous is not None and previous.Name != doc.Name:
            try:
                FreeCAD.setActiveDocument(previous.Name)
            except Exception:
                pass
    doc.recompute()
    objects = _new_objects(doc, before)
    warnings = []
    if not objects:
        warnings.append("no object created from %s" % os.path.basename(path))
    if label and len(objects) == 1:
        objects[0].Label = label
    if kind == "solid":
        for o in objects:
            shape = getattr(o, "Shape", None)
            if shape is None or shape.isNull():
                warnings.append("%s: empty shape" % o.Label)
            elif not shape.Solids:
                warnings.append("%s: no solid (surfaces/wires only)" % o.Label)
            elif not shape.isValid():
                warnings.append("%s: invalid shape" % o.Label)
    return ImportResult(kind, objects, warnings)


def mesh_to_solid(doc, mesh_obj, tolerance=0.1):
    """Convertit un maillage fermé en solide Part (lent sur gros maillages)."""
    import Part
    import Mesh  # noqa: F401

    mesh = mesh_obj.Mesh
    if not mesh.isSolid():
        raise ValueError("%s : maillage non fermé, conversion impossible" % mesh_obj.Label)
    shape = Part.Shape()
    shape.makeShapeFromMesh(mesh.Topology, tolerance)
    solid = Part.makeSolid(shape)
    obj = doc.addObject("Part::Feature", mesh_obj.Name + "_solid")
    obj.Shape = solid
    obj.Label = mesh_obj.Label + " (solid)"
    doc.recompute()
    return obj


SUPPORTED_EXTENSIONS = (".step", ".stp", ".brep", ".brp", ".iges", ".igs", ".stl", ".obj", ".svg", ".dxf")
