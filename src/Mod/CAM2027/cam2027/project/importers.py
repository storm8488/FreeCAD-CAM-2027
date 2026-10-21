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

from ..i18n import Msg, UserError, tr


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
            raise UserError("unsupported format: {ext}", ext=ext)
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
        warnings.append(Msg("no object created from {file}", file=os.path.basename(path)))
    if label and len(objects) == 1:
        objects[0].Label = label
    if kind == "mesh":
        objects, mesh_warnings = meshes_to_solids(doc, objects)
        warnings.extend(mesh_warnings)
        if any(getattr(o, "Shape", None) is not None and o.Shape.Solids for o in objects):
            kind = "solid"
        elif any(is_mesh_surface(o) for o in objects):
            kind = "surface"
    if kind == "solid":
        # repères, axes, plans et groupes du fichier STEP : ce ne sont pas des pièces, ne rien en dire
        parts = [o for o in objects if o.TypeId.startswith("Part::")]
        solids = [o for o in parts if getattr(o, "Shape", None) is not None and not o.Shape.isNull() and o.Shape.Solids]
        for o in solids:
            if not o.Shape.isValid():
                warnings.append(Msg("{name}: invalid shape", name=o.Label))
        if not solids:
            warnings.append(Msg("no solid in {file} (surfaces or wires only)", file=os.path.basename(path)))
    return ImportResult(kind, objects, warnings)


#: au-delà, la conversion maillage -> solide est trop lente : le maillage reste un maillage (usinage 3D)
MESH_SOLID_MAX_FACETS = 200000


def meshes_to_solids(doc, objects):
    """Maillages fermés -> solides affinés (faces coplanaires fusionnées : les fonds de poche redeviennent des
    faces planes) ; le maillage d'origine est masqué. Maillage ouvert ou trop gros pour la conversion ->
    **surface 3D** (faces du maillage, non cousues : rapide et exacte) : brut et finitions 3D seulement.
    Un maillage ne peut pas rester la pièce d'un job (son clone FreeCAD n'a pas de forme : le brut bouclait
    jusqu'au plantage, 2026-10-20). Retourne ``(objets, avertissements)``."""
    out, warnings = [], []
    for o in objects:
        mesh = getattr(o, "Mesh", None)
        if mesh is None:
            out.append(o)
            continue
        if mesh.isSolid() and mesh.CountFacets <= MESH_SOLID_MAX_FACETS:
            out.append(mesh_to_solid(doc, o))
            continue
        why = (Msg("open mesh") if not mesh.isSolid()
               else Msg("{n} triangles, too large to convert to a solid", n=mesh.CountFacets))
        try:
            surface = mesh_to_surface(doc, o)
        except TypeError:  # FreeCAD 1.0 : pas de conversion sans couture (trop lente sur un gros maillage)
            warnings.append(Msg("{name}: {why}, kept as a mesh: it cannot be machined with this FreeCAD version",
                                name=o.Label, why=why))
            out.append(o)
            continue
        warnings.append(Msg("{name}: {why}, imported as a 3D surface: only 3D surface finishing (surface, waterline) can machine it",
                            name=o.Label, why=why))
        out.append(surface)
    return out, warnings


#: propriété qui marque une surface issue d'un maillage (pas un solide : finitions 3D seulement)
MESH_SURFACE_PROPERTY = "CAM2027MeshSurface"


def mesh_to_surface(doc, mesh_obj, tolerance=0.05):
    """Faces du maillage dans un ``Part::Feature`` sans couture (14 s pour 215 000 triangles, contre 10 min
    cousu et converti en solide) ; le maillage est masqué. ``TypeError`` sur FreeCAD 1.0 (pas de paramètre
    ``sewShape``)."""
    import Part

    shape = Part.Shape()
    shape.makeShapeFromMesh(mesh_obj.Mesh.Topology, tolerance, False)
    obj = doc.addObject("Part::Feature", mesh_obj.Name + "_surface")
    if FreeCAD.GuiUp and obj.ViewObject is not None:
        # affichage : le maillage d'origine (léger) ; la surface, utilisée pour les calculs, reste masquée
        # (sa triangulation pour la vue 3D prenait 40 à 60 s sur 215 000 faces)
        obj.ViewObject.Visibility = False
    obj.Shape = shape
    obj.addProperty("App::PropertyBool", MESH_SURFACE_PROPERTY, "CAM2027", "3D surface from a mesh: not a solid")
    setattr(obj, MESH_SURFACE_PROPERTY, True)
    name = mesh_obj.Label
    mesh_obj.Label = tr("{name} (mesh)", name=name)
    obj.Label = name
    doc.recompute()
    return obj


def is_mesh_surface(obj):
    return bool(getattr(obj, MESH_SURFACE_PROPERTY, False))


def mesh_to_solid(doc, mesh_obj, tolerance=0.05):
    """Convertit un maillage fermé en solide Part affiné ; le maillage est masqué (lent sur gros maillages)."""
    import Part
    import Mesh  # noqa: F401

    mesh = mesh_obj.Mesh
    if not mesh.isSolid():
        raise ValueError("%s : maillage non fermé, conversion impossible" % mesh_obj.Label)
    shape = Part.Shape()
    shape.makeShapeFromMesh(mesh.Topology, tolerance)
    solid = Part.makeSolid(shape)
    try:
        refined = solid.removeSplitter()
        if refined.isValid() and refined.Solids:
            solid = refined
    except Exception:
        pass
    obj = doc.addObject("Part::Feature", mesh_obj.Name + "_solid")
    obj.Shape = solid
    name = mesh_obj.Label
    mesh_obj.Label = tr("{name} (mesh)", name=name)  # d'abord : le solide reçoit alors le nom exact du fichier
    obj.Label = name
    if FreeCAD.GuiUp and mesh_obj.ViewObject is not None:
        mesh_obj.ViewObject.Visibility = False
    doc.recompute()
    return obj


SUPPORTED_EXTENSIONS = (".step", ".stp", ".brep", ".brp", ".iges", ".igs", ".stl", ".obj", ".svg", ".dxf")
