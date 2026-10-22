# SPDX-License-Identifier: LGPL-2.1-or-later
"""Classe :class:`Project` : parcours complet dans un document FreeCAD.

    Projet → Dessin/Modèle → Brut et bridage → Opérations → (Simulation) → Export

Un projet est un document ``.FCStd`` contenant :

- l'objet ``CAM2027Project`` (instantané de bibliothèque, machine, registre) ;
- un ``Job`` CAM FreeCAD (modèle cloné, brut, feuille de réglage, outils, opérations).

Les parcours calculés sont stockés dans le document par FreeCAD ; ils sont
recalculés à la réouverture si une dépendance a changé.
"""

import json
import os

import FreeCAD

from ..i18n import Msg, UserError, tr
import Path.Main.Job as PathJob

from ..version import __version__, DATA_VERSION
from ..tools.library import ToolLibrary
from ..tools import bridge
from . import docobjects, importers, stock as stockmod, operations as opsmod, export as exportmod
from . import dressups as dressupmod
from . import holes as holesmod
from . import sheet as sheetmod
from . import indexing
from . import wrap as wrapmod
from . import rest as restmod
from . import keepout  # zones interdites : complète le calcul de chaque opération (rapides relevés)
#: mouvements de coupe balayés d'un coup par le contrôle matière (paquets vectorisés)
PENDING_SEGMENTS = 4096
#: en dessous, un niveau de profondeur n'est pas balayé seul (fraise plate)
LEVEL_BATCH_MIN = 64
#: strategies qui acceptent une surface 3D issue d'un maillage (pas un solide)
SURFACE_STRATEGIES = ("surface3d", "waterline", "millface", "scallop")  # surfaçage : le dessus du brut (voir commands)
from .machine import MachineProfile, lunyee_4040_nova


class Project(object):
    def __init__(self, doc, info):
        self.doc = doc
        self.info = info
        self._library = None
        self._machine = None

    # -- création / ouverture -------------------------------------------------

    @classmethod
    def create(cls, name, library, machine=None):
        """Nouveau document avec instantané de ``library`` (ToolLibrary ou dict) et profil machine."""
        doc = FreeCAD.newDocument(_safe_doc_name(name))
        doc.Label = name
        info = docobjects.create_info(doc)
        snapshot = library.snapshot() if hasattr(library, "snapshot") else dict(library)
        docobjects.ProjectInfo.set_json(info, "LibrarySnapshot", snapshot)
        machine = machine or lunyee_4040_nova()
        docobjects.ProjectInfo.set_json(info, "Machine", machine.to_dict())
        docobjects.ProjectInfo.set_json(info, "OperationRegistry", {})
        doc.recompute()
        return cls(doc, info)

    @classmethod
    def open(cls, path):
        doc = FreeCAD.openDocument(path)
        return cls.from_document(doc)

    @classmethod
    def from_document(cls, doc):
        info = docobjects.find_info(doc)
        if info is None:
            raise ValueError("%s : ce document n'est pas un projet CAM2027" % doc.Label)
        if int(info.DataVersion) > DATA_VERSION:
            raise ValueError("projet écrit par une version plus récente (data_version %d)" % info.DataVersion)
        return cls(doc, info)

    # -- propriétés -----------------------------------------------------------

    @property
    def app_version(self):
        return self.info.AppVersion

    @property
    def library(self):
        if self._library is None:
            self._library = ToolLibrary.from_dict(docobjects.ProjectInfo.get_json(self.info, "LibrarySnapshot"))
        return self._library

    def merge_library(self, library):
        """Ajoute à l'instantané du projet les outils de ``library`` créés depuis (les outils déjà présents et
        les opérations existantes ne changent pas). Retourne le nombre d'assemblages ajoutés."""
        snap = self.library
        added = snap.merge_new_from(library)
        if added:
            docobjects.ProjectInfo.set_json(self.info, "LibrarySnapshot", snap.snapshot())
            self._library = None
        return added

    def update_library_snapshot(self, library):
        """Remplace volontairement l'instantané (action explicite de l'utilisateur)."""
        docobjects.ProjectInfo.set_json(self.info, "LibrarySnapshot", library.snapshot())
        self._library = None

    @property
    def machine(self):
        if self._machine is None:
            self._machine = MachineProfile.from_dict(docobjects.ProjectInfo.get_json(self.info, "Machine"))
        return self._machine

    def set_machine(self, machine):
        docobjects.ProjectInfo.set_json(self.info, "Machine", machine.to_dict())
        self._machine = machine

    @property
    def registry(self):
        return docobjects.ProjectInfo.get_json(self.info, "OperationRegistry")

    def _save_registry(self, reg):
        docobjects.ProjectInfo.set_json(self.info, "OperationRegistry", reg)

    @property
    def job(self):
        job = self.info.Job
        if job is None:
            raise ValueError("le projet n'a pas encore de job (appeler create_job)")
        return job

    @property
    def has_job(self):
        return self.info.Job is not None

    # -- modèle ---------------------------------------------------------------

    def surface_models(self):
        """Modeles du job qui sont des surfaces 3D issues d'un maillage (clones -> objets d'origine)."""
        if not self.has_job:
            return []
        out = []
        for clone in self.job.Model.Group:
            for src in getattr(clone, "Objects", None) or []:
                if importers.is_mesh_surface(src):
                    out.append(clone)
                    break
        return out

    def model_candidates(self):
        """Ce que « Brut et montage » usine sans sélection : solides et maillages importés, hors objets techniques
        (brut, clones du job, brides, panneau, copies tournées, aperçus) ; un maillage converti en solide ne
        compte pas deux fois."""
        from . import stock as stockmod

        technical = {o.Name for o in stockmod.clamps(self.doc)}  # clones, copies tournées : par leur nom
        if self.has_job and getattr(self.job, "Stock", None) is not None:
            technical.add(self.job.Stock.Name)
        out = []
        for o in self.doc.Objects:
            if o.Name in technical or o.Name in ("Stock", sheetmod.SHEET_NAME) or o.Name.startswith(("Clone", "Job")):
                continue
            if o.Name.endswith(("_Preview", "_FlatArea", sheetmod.FACE_SUFFIX)) or "_A" in o.Name and o.Name.rsplit("_A", 1)[0] \
                    and self.doc.getObject(o.Name.rsplit("_A", 1)[0]) is not None:
                continue
            if o.TypeId.startswith("Mesh::"):
                if o.Mesh.CountFacets and self.doc.getObject(o.Name + "_solid") is None                         and self.doc.getObject(o.Name + "_surface") is None:
                    out.append(o)
            elif (o.TypeId.startswith("Part::") and getattr(o, "Shape", None) is not None and not o.Shape.isNull()
                  and (o.Shape.Solids or importers.is_mesh_surface(o) and o.Shape.Faces)):
                out.append(o)
        return out

    def import_model(self, path, label=None):
        key = os.path.normcase(os.path.abspath(path))
        done = json.loads(getattr(self.info, "ImportedFiles", "") or "[]")
        res = importers.import_file(self.doc, path, label)
        if res.kind == "vector":
            from . import templates

            templates.tag_layers(path, res.objects)  # calques : correspondance des modèles de parcours
        if key in done:
            res.warnings.insert(0, Msg("{file} was already imported: the project now contains it twice",
                                       file=os.path.basename(path)))
        else:
            done.append(key)
            if "ImportedFiles" not in self.info.PropertiesList:
                self.info.addProperty("App::PropertyString", "ImportedFiles", "CAM2027", "Imported files (JSON)")
                self.info.setEditorMode("ImportedFiles", 1)
            self.info.ImportedFiles = json.dumps(done)
        return res

    def import_relief(self, path, width, relief_height, **options):
        """Relief 3D depuis une image (carte de hauteur), voir ``relief.make_relief``."""
        from . import relief

        obj, warnings = relief.make_relief(self.doc, path, width, relief_height, **options)
        return importers.ImportResult("solid", [obj], warnings)

    # -- job, brut, montage ---------------------------------------------------

    def create_job(self, models, stock=None, fixtures=("G54",), post_processor=None, post_args=None):
        if self.info.Job is not None:
            raise ValueError("le projet a déjà un job")
        for m in models:  # une boîte invalide fait boucler le brut de FreeCAD (Stock.execute) jusqu'au plantage
            if m.TypeId.startswith("Mesh::"):
                # le clone du job n'a pas de forme pour un maillage : brut sans boite (plantage du 2026-10-20)
                raise UserError("{name}: mesh not converted to a solid ({n} triangles), it cannot be the part of a job: import it again (closed meshes are converted, large or open ones become a 3D surface)",
                                name=m.Label, n=m.Mesh.CountFacets)
            geom = getattr(m, "Shape", None)
            bb = geom.BoundBox if geom is not None else None
            if geom is None or geom.isNull() or bb is None or not bb.isValid() or (bb.XLength <= 0 and bb.YLength <= 0):
                raise UserError("{name}: empty shape, it cannot be machined", name=m.Label)
        previous = FreeCAD.ActiveDocument
        FreeCAD.setActiveDocument(self.doc.Name)
        try:
            job = PathJob.Create("Job", list(models), None)
        finally:
            if previous is not None and previous.Name != self.doc.Name:
                try:
                    FreeCAD.setActiveDocument(previous.Name)
                except Exception:
                    pass
        job.Label = "Job"
        self.info.Job = job
        if FreeCAD.GuiUp:
            # surface 3D issue d'un gros maillage : le clone du job reste masqué (avant le recalcul : sinon il
            # est triangulé pour la vue), le maillage d'origine s'affiche
            for clone in self.surface_models():
                if clone.ViewObject is not None:
                    clone.ViewObject.Visibility = False
                for src in getattr(clone, "Objects", None) or []:
                    mesh = self.doc.getObject(src.Name[:-len("_surface")]) if src.Name.endswith("_surface") else None
                    if mesh is not None and mesh.ViewObject is not None:
                        mesh.ViewObject.Visibility = True
        # Job.Create ajoute un « TC: Default Tool » (fraise 5 mm) sans rapport avec la
        # bibliothèque : les contrôleurs sont créés par add_operation uniquement.
        for tc in list(job.Tools.Group):
            tool = getattr(tc, "Tool", None)
            job.Tools.Group = [t for t in job.Tools.Group if t.Name != tc.Name]
            self.doc.removeObject(tc.Name)
            if tool is not None:
                self.doc.removeObject(tool.Name)
        self.doc.recompute()
        stockmod.set_stock(job, stock or {"kind": "box_margins", "xy": 0.0, "z_top": 0.0, "z_bottom": 0.0})
        stockmod.set_fixtures(job, list(fixtures))
        post = post_processor or self.machine.post_processor
        if post:
            if post not in job.getEnumerationsOfProperty("PostProcessor"):
                raise ValueError("postprocesseur %r non disponible (activer dans les préférences CAM)" % post)
            job.PostProcessor = post
        job.PostProcessorArgs = post_args if post_args is not None else (self.machine.post_processor_args or "")
        self.doc.recompute()
        return job

    def create_sheet_job(self, vectors=None, thickness=18.0, margin=10.0, fixtures=("G54",), sheet_rect=None):
        """Job « dessin 2D dans un panneau » : panneau sous le dessin (dessus à Z = 0), une face par
        vecteur fermé, brut = panneau. ``vectors`` par défaut : tous les vecteurs du document."""
        vectors = list(vectors) if vectors else sheetmod.vector_objects(self.doc)
        if not vectors:
            raise ValueError("aucun dessin 2D dans le projet (importer un SVG ou un DXF)")
        if sheet_rect is None and getattr(self.info, "NestedSheet", ""):
            sheet_rect = json.loads(self.info.NestedSheet)  # panneau choisi à l'imbrication
        sheet = sheetmod.make_sheet(self.doc, vectors, float(thickness), float(margin), rect=sheet_rect)
        faces = sheetmod.make_faces(self.doc, vectors)
        self.doc.recompute()
        return self.create_job([sheet] + vectors + faces,
                               stock={"kind": "box_margins", "xy": 0.0, "z_top": 0.0, "z_bottom": 0.0},
                               fixtures=fixtures)

    def drawing_clone(self, source, face=False):
        """Clone du job d'un vecteur source (``face=True`` : clone de sa face générée)."""
        name = source.Name + (sheetmod.FACE_SUFFIX if face else "")
        target = self.doc.getObject(name)
        if target is None:
            raise ValueError("pas de %s pour %s" % ("face" if face else "vecteur", source.Label))
        return opsmod.model_clone(self.job, target)

    def set_stock(self, spec):
        return stockmod.set_stock(self.job, spec)

    def stock_bounds(self):
        return stockmod.stock_bounds(self.job)

    def add_clamp(self, name, length, width, height, origin):
        return stockmod.add_clamp(self.job, name, length, width, height, origin)

    # -- opérations -----------------------------------------------------------

    def add_operation(self, kind, name, assembly_id, preset_id, base=None, params=None, index_deg=None):
        """Crée une opération avec un ToolController dédié issu de (assemblage, préréglage).

        ``index_deg`` : angle A de l'index (4e axe 3+1) ; ``None`` = projet 3 axes / A0 implicite.
        Retourne ``(op, record)`` où ``record`` contient les valeurs copiées et
        les avertissements (approximations de forme, paramètres ignorés).
        """
        job = self.job
        if kind not in SURFACE_STRATEGIES and self.surface_models():
            raise UserError("{op}: the part is a 3D surface from a mesh (not a solid): only 3D surface finishing (surface, waterline) can machine it",
                            op=Msg(opsmod.STRATEGIES[kind]["label"]))
        if self.surface_models():
            # BaseBoundBox : FreeCAD calcule l'enveloppe (booleen) de la forme, 18 Go et des heures sur 215 000 faces
            params = dict(params or {})
            params.setdefault("BoundBox", "Stock")
        asm, tool, holder = self.library.resolve_assembly(assembly_id)
        preset = tool.preset(preset_id)
        values = preset.resolve(tool)
        params = opsmod.resolve_params(kind, tool, params)
        base = sheetmod.expand_drawing_base(self.doc, kind, base)
        if index_deg is not None:
            index_deg = float(index_deg)
            indexing.check_machine(self.machine)
            indexing.check_angle(self.machine, index_deg)
            if abs(index_deg) > 1e-9:
                base = indexing.index_base(self, kind, base, index_deg, tool.geometry.diameter)
        toolbit, bit_warnings = bridge.create_toolbit(self.doc, tool, label="%s (T%d)" % (tool.name, asm.output.tool_number))
        tc, _ = bridge.create_tool_controller(self.doc, asm, tool, values, toolbit=toolbit, label="TC: %s" % name)
        job.Proxy.addToolController(tc)
        op, ignored = opsmod.create_operation(job, kind, name, tc, base=base, params=params)
        job.Proxy.addOperation(op)
        if kind == "threadmill" and not any(subs for _o, subs in (base or [])):
            try:
                params, kept, others = opsmod.fit_thread_to_holes(op, tool, params)
            except Exception:  # aucun trou à fileter : ne rien laisser dans le job
                job.Operations.Group = [o for o in job.Operations.Group if o.Name != op.Name]
                job.Tools.Group = [t for t in job.Tools.Group if t.Name != tc.Name]
                for obj in (op, tc, toolbit):
                    self.doc.removeObject(obj.Name)
                raise
            if kept:
                bit_warnings = list(bit_warnings) + [Msg("Thread {name} on the {n} hole(s) drilled for it", name=params["ThreadName"], n=kept)]
                if others:
                    bit_warnings.append(Msg("Holes of other diameters left out of the thread milling: {d} mm",
                                            d=", ".join("%.2f" % d for d in others)))
        reg = self.registry
        record = {
            "kind": kind,
            "label": name,
            "order": len(reg),
            "assembly_id": asm.id,
            "tool_id": tool.id,
            "holder_id": holder.id if holder else None,
            "preset_id": preset.id,
            "values": values,
            "tool_controller": tc.Name,
            "toolbit": toolbit.Name,
            "params": _jsonable(params),
            "ignored_params": ignored,
            "warnings": bit_warnings,
            "index_deg": index_deg,
        }
        reg[op.Name] = record
        self._save_registry(reg)
        if index_deg is not None or self.index_angles():
            indexing.sync(self)
            self._renumber()
        return op, record

    def add_wrapped_engraving(self, name, assembly_id, preset_id, base, depth, step_down, safe_margin=5.0):
        """4e axe continu : gravure des contours d'un dessin déroulé, enroulée sur le brut rond (G93).

        ``base`` : ``[(objet, sous-éléments)]`` du dessin dans le repère déroulé (X le long de l'axe,
        Y = longueur d'arc, Y 0 à A 0) ; ``depth`` < 0 sous la surface. Retourne ``(op, record)``.
        """
        import Path.Op.Custom as Custom

        indexing.check_machine(self.machine)
        job = self.job
        asm, tool, holder = self.library.resolve_assembly(assembly_id)
        preset = tool.preset(preset_id)
        values = preset.resolve(tool)
        toolbit, bit_warnings = bridge.create_toolbit(self.doc, tool, label="%s (T%d)" % (tool.name, asm.output.tool_number))
        tc, _ = bridge.create_tool_controller(self.doc, asm, tool, values, toolbit=toolbit, label="TC: %s" % name)
        job.Proxy.addToolController(tc)
        previous = FreeCAD.ActiveDocument
        FreeCAD.setActiveDocument(self.doc.Name)
        try:
            op = Custom.Create(wrapmod.WRAP_PREFIX, parentJob=job)
        finally:
            if previous is not None and previous.Name != self.doc.Name:
                FreeCAD.setActiveDocument(previous.Name)
        op.Label = name
        op.ToolController = tc
        op.Source = "Text"
        if FreeCAD.GuiUp and op.ViewObject is not None:
            op.ViewObject.Visibility = False  # la vue des parcours ignore A : l'aperçu « (preview) » le remplace
        reg = self.registry
        record = {
            "kind": wrapmod.KIND,
            "label": name,
            "order": len(reg),
            "assembly_id": asm.id,
            "tool_id": tool.id,
            "holder_id": holder.id if holder else None,
            "preset_id": preset.id,
            "values": values,
            "tool_controller": tc.Name,
            "toolbit": toolbit.Name,
            "params": {"depth": float(depth), "step_down": float(step_down), "safe_margin": float(safe_margin)},
            "wrap_base": [[obj.Name, list(subs)] for obj, subs in base],
            "ignored_params": [],
            "warnings": bit_warnings,
            "index_deg": None,
        }
        reg[op.Name] = record
        self._save_registry(reg)
        try:
            self._generate_wrap(op)
        except Exception:
            self.remove_operation(op)
            raise
        indexing.sync(self)
        self._renumber()
        return op, self.registry[op.Name]

    def update_wrapped_engraving(self, op, depth=None, step_down=None, safe_margin=None):
        reg = self.registry
        params = reg[op.Name]["params"]
        for key, value in (("depth", depth), ("step_down", step_down), ("safe_margin", safe_margin)):
            if value is not None:
                params[key] = float(value)
        self._save_registry(reg)
        self._generate_wrap(op)

    def _generate_wrap(self, op):
        """(Re)calcule le G-code enroulé depuis le dessin, le brut rond et le profil machine."""
        reg = self.registry
        rec = reg[op.Name]
        if rec["kind"] != wrapmod.KIND:  # contour, poche et finition 3D enroulés
            from . import rotary
            return rotary.generate(self, op)[0]
        p = rec["params"]
        cy, cz, sign = indexing.check_machine(self.machine)
        radius = wrapmod.radius_of_stock(self.job)
        wrapmod.check_stock_axis(self.job, (cy, cz))
        base = []
        for name, subs in rec["wrap_base"]:
            obj = self.doc.getObject(name)
            if obj is None:
                raise UserError("wrapped engraving {op}: drawing object {name} not found", op=op.Label, name=name)
            base.append((obj, subs))
        wires = wrapmod.drawing_wires(base)
        warnings = wrapmod.check_layout(wires, radius)
        moves = wrapmod.flat_engrave_moves(wires, p["depth"], p["step_down"], p["safe_margin"])
        values = rec["values"]
        lines = wrapmod.wrap_moves(moves, radius, (cy, cz), sign, values["feed_mm_min"], values["plunge_feed_mm_min"])
        op.Gcode = wrapmod.path_gcode(lines)
        self._wrap_preview(op, wrapmod.preview_polylines(moves, radius, (cy, cz)))
        rec["warnings"] = [w for w in rec.get("warnings", []) if not w.startswith("drawing Y")] + warnings
        self._save_registry(reg)
        self.doc.recompute()
        return lines

    def _wrap_preview(self, op, polylines):
        """Objet d'aperçu (hors job) : trajet réel de la fraise autour de la pièce."""
        import Part

        name = op.Name + "_Preview"
        obj = self.doc.getObject(name) or self.doc.addObject("Part::Feature", name)
        obj.Label = tr("{name} (preview)", name=op.Label)
        obj.Shape = Part.Compound([Part.makePolygon(pts) for pts in polylines]) if polylines else Part.Shape()
        if FreeCAD.GuiUp and obj.ViewObject is not None:
            obj.ViewObject.LineColor = (0.2, 0.55, 1.0)
            obj.ViewObject.LineWidth = 2.0
            if "OnTopWhenSelected" in obj.ViewObject.PropertiesList:  # le trajet est sous la surface
                obj.ViewObject.OnTopWhenSelected = "Enabled"
        return obj

    def add_flat_clearing(self, vcarve_op, assembly_id, preset_id, name=None, params=None):
        """Fond plat d'un V-carving limité en profondeur (« flat depth » d'Aspire), deux opérations placées
        juste avant le V-carving :

        1. poche 2D à la profondeur finale avec la fraise plate ``assembly_id`` dans la zone plate
           (face décalée vers l'intérieur de la portée du V-bit) ;
        2. contour de la zone plate suivi par le V-bit du V-carving à cette profondeur : ses flancs
           taillent les parois jusqu'au bord (le V-carving limité ne suit que l'axe médian).

        Retourne ``(poche, contour)``."""
        from . import inlay

        vcarve_op = dressupmod.base_operation(vcarve_op)
        reg = self.registry
        vrec = reg.get(vcarve_op.Name)
        if not vrec or vrec["kind"] != "vcarve":
            raise UserError("flat depth clearing applies to a V-carve operation")
        start = float(vcarve_op.StartDepth.getValueAs("mm"))
        final = float(vcarve_op.FinalDepth.getValueAs("mm"))
        depth = start - final
        if depth <= 1e-6:
            raise UserError("the V-carve has no depth limit (final depth = start depth)")
        reach = inlay.vbit_reach(self.library.tool(vrec["tool_id"]), depth)
        faces = inlay.flat_area(inlay.operation_faces(vcarve_op), reach)
        if not faces:
            raise UserError("no flat area: the V-bit reaches {d:.2f} mm everywhere in this shape", d=depth)
        import Part

        area = self.doc.getObject(vcarve_op.Name + inlay.FLAT_SUFFIX)             or self.doc.addObject("Part::Feature", vcarve_op.Name + inlay.FLAT_SUFFIX)
        area.Label = tr("{name} (flat area)", name=vcarve_op.Label)
        area.Shape = Part.Compound(faces) if len(faces) > 1 else faces[0]
        if FreeCAD.GuiUp and area.ViewObject is not None:
            area.ViewObject.Visibility = False
        label = name or vcarve_op.Label
        values = {"StartDepth": start, "FinalDepth": final, "StepOver": 40}
        values.update(params or {})
        pocket, _r1 = self.add_operation("pocket2d", tr("{name} - flat", name=label), assembly_id, preset_id,
                                         base=[(area, ["Face%d" % (i + 1) for i in range(len(area.Shape.Faces))])],
                                         params=values)
        outline, _r2 = self.add_operation("engrave", tr("{name} - flat outline", name=label), vrec["assembly_id"],
                                          vrec["preset_id"],
                                          base=[(area, ["Edge%d" % (i + 1) for i in range(len(area.Shape.Edges))])],
                                          params={"StartDepth": start, "FinalDepth": final, "StepDown": depth})
        corners = self._vcarve_corners(vcarve_op, vrec, tr("{name} - sharp corners", name=label), start, depth)
        reg = self.registry
        for op in (pocket, outline, corners):
            if op is not None:
                reg[op.Name]["flat_for"] = vcarve_op.Name
                reg[op.Name]["flat_reach"] = reach
        self._save_registry(reg)
        for op in (pocket, outline, corners):  # avant le V-carving, dans cet ordre
            if op is None:
                continue
            group = [o for o in self.job.Operations.Group if not indexing.is_index_op(o)]
            self.move_operation(op, group.index(dressupmod.top_of(self.job, vcarve_op)) - group.index(op))
        return pocket, outline, corners

    def _vcarve_corners(self, vcarve_op, vrec, label, z_top, depth):
        """Angles vifs d'un V-carving limité (le V-carving de FreeCAD les laisse trop peu profonds) :
        opération « Custom » avec le V-bit du V-carving ; None s'il n'y a aucun angle saillant."""
        import Path.Op.Custom as Custom
        from . import inlay

        tool = self.library.tool(vrec["tool_id"])
        spurs = [s for f in inlay.operation_faces(vcarve_op) for s in inlay.corner_spurs(f, tool, depth)]
        if not spurs:
            return None
        safe = float(vcarve_op.SafeHeight.getValueAs("mm"))
        values = vrec["values"]
        previous = FreeCAD.ActiveDocument
        FreeCAD.setActiveDocument(self.doc.Name)
        try:
            op = Custom.Create(inlay.CORNERS_PREFIX, parentJob=self.job)
        finally:
            if previous is not None and previous.Name != self.doc.Name:
                FreeCAD.setActiveDocument(previous.Name)
        op.Label = label
        op.ToolController = vcarve_op.ToolController  # même outil : pas de changement d'outil
        op.Source = "Text"
        op.Gcode = inlay.spur_gcode(spurs, z_top, depth, safe, values["feed_mm_min"], values["plunge_feed_mm_min"])
        reg = self.registry
        rec = dict(vrec)
        rec.update(kind=inlay.CORNERS_KIND, label=label, order=len(reg), params={"corners": len(spurs)},
                   ignored_params=[], warnings=[], tool_controller=None, toolbit=None, index_deg=None)
        reg[op.Name] = rec
        self._save_registry(reg)
        self.doc.recompute()
        return op

    def create_inlay(self, drawing, vbit_assembly_id, vbit_preset_id, flat_assembly_id, flat_preset_id,
                     female_depth, male_start_depth, male_flat_depth, margin=None, male_thickness=12.0,
                     name=None):
        """Incrustation en V (mâle / femelle) d'un dessin fermé du projet (flux 2D, panneau).

        Femelle (ce projet) : V-carving de la forme à ``female_depth`` + fond plat. Mâle : **nouveau
        projet** (autre planche) avec le dessin miroir réduit de la profondeur de départ, zone autour
        taillée en V à ``male_flat_depth`` + fond plat. Retourne un dict : opérations femelles, projet
        mâle et ses opérations, jeux attendus (colle au fond, écart entre planches), notes.
        """
        from . import inlay

        gaps = inlay.check_inlay_depths(female_depth, male_start_depth, male_flat_depth)
        _asm, vbit, _h = self.library.resolve_assembly(vbit_assembly_id)
        label = name or drawing.Label
        notes = []
        face_clone = self.drawing_clone(drawing, face=True)
        fv, _r = self.add_operation("vcarve", tr("{name} - female V-carve", name=label), vbit_assembly_id, vbit_preset_id,
                                    base=[(face_clone, ["Face1"])],
                                    params={"StartDepth": 0.0, "FinalDepth": -float(female_depth)})
        female = [fv]
        try:
            female[:0] = [o for o in self.add_flat_clearing(fv, flat_assembly_id, flat_preset_id) if o is not None]
        except ValueError as exc:
            notes.append(Msg("female: {why}", why=exc))
        source_face = face_clone.Shape.Faces[0]
        if margin is None:
            # la bande autour du bouchon doit recevoir la fraise plate entre les deux flancs en V
            _fa, flat_tool, _fh = self.library.resolve_assembly(flat_assembly_id)
            margin = 2 * inlay.vbit_reach(vbit, male_flat_depth) + flat_tool.geometry.diameter + 3.0
        outline, mirror_x = inlay.male_outline(source_face, vbit, male_start_depth, margin)
        male = Project.create(tr("{name} - male", name=label), self.library, self.machine)
        mobj = male.doc.addObject("Part::Feature", "InlayMale")
        mobj.Label = tr("{name} (male, mirrored)", name=label)
        mobj.Shape = outline
        male.doc.recompute()
        male.create_sheet_job([mobj], thickness=male_thickness, margin=5.0)
        mv, _r = male.add_operation("vcarve", tr("{name} - male V-carve", name=label), vbit_assembly_id, vbit_preset_id,
                                    base=[(male.drawing_clone(mobj, face=True), ["Face1"])],
                                    params={"StartDepth": 0.0, "FinalDepth": -float(male_flat_depth)})
        male_ops = [mv]
        try:
            male_ops[:0] = [o for o in male.add_flat_clearing(mv, flat_assembly_id, flat_preset_id) if o is not None]
        except ValueError as exc:
            notes.append(Msg("male: {why}", why=exc))
        return {"female_ops": female, "male_project": male, "male_ops": male_ops, "mirror_x": mirror_x,
                "notes": notes, **gaps}

    def nest_drawings(self, drawings, sheet_width, sheet_length, spacing=5.0, margin=10.0, rotate=True, copies=None,
                      true_shape=True, angle_step=15.0, max_sheets=1):
        """Imbrication des dessins 2D sur un panneau ``sheet_width × sheet_length`` (origine 0, 0), avant
        « Brut et montage > panneau ». ``copies`` : ``{objet: nombre}`` (copies créées). Les dessins placés
        sont déplacés ; ceux qui ne tiennent pas restent où ils sont et sont rapportés.

        ``true_shape`` : silhouettes réelles (rotations par pas de ``angle_step`` si ``rotate``), sinon rectangles
        englobants (rotation de 90°). ``max_sheets`` > 1 : les panneaux suivants sont posés à droite du premier,
        à ``nesting.SHEET_GAP`` mm ; le job reprend le premier.

        Retourne un dict : placés ``[(libellé, x, y, angle)]``, non placés, taux d'utilisation, panneaux."""
        from . import nesting

        if self.has_job:
            raise UserError("nesting must be done before the sheet job is created")
        objs = []
        for obj in drawings:
            objs.append(obj)
            for k in range(2, int((copies or {}).get(obj, 1)) + 1):
                dup = self.doc.addObject("Part::Feature", obj.Name + "_Copy")
                dup.Shape = obj.Shape.copy()
                dup.Label = "%s (%d)" % (obj.Label, k)
                objs.append(dup)
        self.doc.recompute()
        report = {"placed": [], "unplaced": [], "sheet": (sheet_width, sheet_length), "sheet_of": {}}
        used = 0.0
        width, length = sheet_width - 2 * margin, sheet_length - 2 * margin
        if true_shape:
            items = [(o.Name, nesting.silhouette(o.Shape)) for o in objs]
            placed, unplaced, res = nesting.shape_pack(items, width, length, spacing,
                                                       angle_step if rotate else 0.0, max_sheets)
            report["resolution"] = res
        else:
            items = [(o.Name, o.Shape.BoundBox.XLength, o.Shape.BoundBox.YLength) for o in objs]
            placed, unplaced = nesting.skyline_pack(items, width, length, spacing, rotate)
        sheets = 1
        for o in objs:
            if o.Name not in placed:
                report["unplaced"].append(o.Label)
                continue
            if true_shape:
                sheet, angle, dx, dy = placed[o.Name]
                shift = sheet * (sheet_width + nesting.SHEET_GAP)
                nesting.place_shape(o, angle, margin + dx + shift, margin + dy)
                sheets = max(sheets, sheet + 1)
                report["sheet_of"][o.Label] = sheet
            else:
                x, y, rot = placed[o.Name]
                nesting.move_to(o, margin + x, margin + y, rot)
                angle = 90.0 if rot else 0.0
            bb = o.Shape.BoundBox
            report["placed"].append((o.Label, bb.XMin, bb.YMin, angle))
            used += nesting.outline_area(o)
        if "NestedSheet" not in self.info.PropertiesList:
            self.info.addProperty("App::PropertyString", "NestedSheet", "CAM2027", "Sheet chosen when nesting (JSON)")
        self.info.NestedSheet = json.dumps([0.0, 0.0, float(sheet_width), float(sheet_length)])
        self.doc.recompute()
        report["sheets"] = sheets
        report["utilization"] = used / (sheets * sheet_width * sheet_length)
        report["objects"] = [o for o in objs if o.Name in placed]
        return report

    def material_check(self, resolution=None, tolerance=0.02, start_zmap=None):
        """Simulation d'enlèvement de matière (Z-map, 3 axes) et comparaison avec la pièce.

        Retourne un dict : volume enlevé, entaille maximale (et position), reste maximal / moyen,
        rapides dans la matière, opérations simulées / non simulées (avec la raison), approximations.
        La carte calculée reste dans ``self.last_zmap`` (affichage). ``start_zmap`` : carte de départ (face B
        d'un recto-verso) ; ``False`` = brut neuf même en recto-verso.
        """
        from . import sim
        from . import twosided

        if start_zmap is None and twosided.is_two_sided(self):
            return twosided.material_check(self, resolution, tolerance)

        if getattr(self.job.Stock, "Radius", None) is not None:
            raise UserError("material check: round stock (4th axis) is not supported, only box stock")
        resolution = resolution or sim.DEFAULT_RESOLUTION
        self.compute()
        zmap = start_zmap or sim.ZMap.from_bounds(self.stock_bounds(), resolution)
        simulated, skipped, approximations = [], [], []
        from . import stock as stockmod

        boxes = [(c.Label, c.Shape.BoundBox) for c in stockmod.clamps(self.doc) if getattr(c, "Shape", None)] \
            + keepout.zone_boxes(self.doc)
        events = []  # (type, opération, n° de commande, position, valeur)
        no_holder = []
        pos = None
        for obj in self.operations():
            if indexing.is_index_op(obj):
                continue
            base = dressupmod.base_operation(obj)
            if getattr(base, "Active", True) is False:
                continue
            rec = self.registry.get(base.Name) or {}
            if wrapmod.is_wrap_op(obj):
                skipped.append((obj.Label, Msg("uses the A axis (wrapped)")))
                pos = None
                continue
            if rec.get("index_deg") not in (None, 0, 0.0):
                skipped.append((obj.Label, Msg("indexed at A{a:g}", a=rec["index_deg"])))
                pos = None
                continue
            if rec.get("kind") == "probe":  # palpage : aucune coupe, position inconnue ensuite
                skipped.append((obj.Label, Msg("probing (no cut)")))
                pos = None
                continue
            if not rec.get("tool_id"):
                skipped.append((obj.Label, Msg("unknown tool")))
                continue
            asm, tool, holder = self.library.resolve_assembly(rec["assembly_id"])
            profile, note = sim.ToolProfile.from_library_tool(tool)
            if note:
                approximations.append((obj.Label, note))
            envelope = sim.Envelope.from_assembly(asm, tool, holder)
            if holder is None:
                no_holder.append(obj.Label)
            seen = set()
            # filetage dans la matière (trou pas encore percé) : un seul message qui dit quoi faire
            threading = rec.get("kind") == "threadmill"
            commands = obj.Path.Commands
            if rec.get("kind") == "drilling" and holesmod.has_cycles(commands):  # cycles : mouvements équivalents
                commands = holesmod.expand_cycles(commands)
            segments, pos = sim.path_segments(commands, pos, with_index=True)
            top_max = float(zmap.top.max())  # la matière ne fait que baisser pendant l'opération
            clamp_top = max([bb.ZMax for _n, bb in boxes] or [-float("inf")])
            def excess_events(p0, p1, index, z_low):
                # avant d'enlever la matière de ce mouvement : ce qui est devant la fraise est encore là
                for lo, _hi, r, role in envelope.parts:
                    if role == "cutter" or (role, "material") in seen or z_low + lo >= top_max:
                        continue
                    excess, at = sim.material_excess(zmap, p0, p1, r, lo)
                    if excess > tolerance + 0.03:
                        seen.add((role, "material"))
                        if not threading:
                            events.append(("holder" if role == "holder" else "flute_length", obj.Label, index, at, excess))
                        elif "undrilled" not in seen:
                            events.append(("undrilled", obj.Label, index, at, excess))
                            seen.add("undrilled")

            def sweep_one(rapid, p0, p1, index):
                before = zmap.rapid_hits
                zmap.sweep(p0, p1, profile, rapid=rapid)
                if zmap.rapid_hits > before and "rapid" not in seen and not (threading and "undrilled" in seen):
                    events.append(("undrilled" if threading else "rapid", obj.Label, index, tuple(p1), 0.0))
                    seen.add("undrilled" if threading else "rapid")

            pending = []  # mouvements en attente : balayés par paquets vectorisés

            def flush():
                if not pending:
                    return
                np = sim._np()
                P0 = np.array([q[0] for q in pending], dtype=float)
                P1 = np.array([q[1] for q in pending], dtype=float)
                rapids = np.array([q[3] for q in pending], dtype=bool)
                # pré-contrôles sur l'état avant le paquet (queue / porte-outil dans la matière, rapides dans
                # la matière) : la matière ne fait que baisser, donc rien ici = rien en séquentiel ; sinon
                # le paquet est repris en séquentiel (queue / porte-outil, rare) ou jusqu'au rapide signalé
                parts = [(lo, r, role) for lo, _hi, r, role in envelope.parts
                         if role != "cutter" and (role, "material") not in seen
                         and float(np.minimum(P0[:, 2], P1[:, 2]).min()) + lo < top_max]
                for lo, r, _role in parts:
                    # queue et porte-outil : disques plats quel que soit le profil de la fraise
                    if zmap.excess_any(P0, P1, r, lo, tolerance + 0.03, True):
                        for q0, q1, idx, rapid in pending:
                            excess_events(q0, q1, idx, min(q0[2], q1[2]))
                            sweep_one(rapid, q0, q1, idx)
                        del pending[:]
                        return
                sel = np.nonzero(rapids)[0]
                flagged = []  # rapides à vérifier sur l'état réel, dans l'ordre
                if len(sel):
                    R0, R1 = P0[sel], P1[sel]
                    for start, stop in sim.chunk_bounds(R0, R1, zmap.res, profile.radius):
                        hits = zmap.rapid_hits_many(R0[start:stop], R1[start:stop], profile)
                        flagged.extend(sel[start:stop][hits].tolist())
                cursor = 0
                for m in flagged:
                    zmap.sweep_arrays(P0[cursor:m], P1[cursor:m], profile)  # ce qui le précède, d'un coup
                    q0, q1, idx, _rapid = pending[m]
                    sweep_one(True, q0, q1, idx)  # lui seul, sur l'état réel
                    cursor = m + 1
                zmap.sweep_arrays(P0[cursor:], P1[cursor:], profile)
                del pending[:]

            level = None  # Z des mouvements de coupe horizontaux en attente (fraise plate)
            for rapid, p0, p1, index in segments:
                z_low = min(p0[2], p1[2])
                for name, role, depth, at in (sim.clamp_contacts(p0, p1, envelope, boxes) if z_low < clamp_top else ()):
                    if ("clamp", name) not in seen:
                        events.append(("clamp", obj.Label, index, at, depth, name, role))
                        seen.add(("clamp", name))
                if not rapid and profile.kind == "flat" and p0[2] == p1[2]:
                    # un paquet par niveau de profondeur : les liaisons rapides et la queue du niveau suivant
                    # trouvent alors le niveau précédent déjà usiné dans l'état d'avant le paquet (sinon le
                    # pré-contrôle renvoie le paquet au séquentiel). Les plongées et pentes entre deux niveaux
                    # ne comptent pas ; un niveau minuscule rejoint le suivant.
                    if level is not None and p0[2] != level and len(pending) >= LEVEL_BATCH_MIN:
                        flush()
                    level = p0[2]
                pending.append((p0, p1, index, rapid))
                if len(pending) >= PENDING_SEGMENTS:
                    flush()
            flush()
            simulated.append(obj.Label)
        heights, low = sim.model_heights(zmap, [o.Shape for o in self.job.Model.Group if getattr(o, "Shape", None)],
                                         lateral=sim.WALL_TOLERANCE)
        self._thread_the_holes(zmap, heights)
        self._thread_the_holes(zmap, low)
        # entailles vérifiées en 3D : vraie pénétration au lieu de la hauteur de paroi (trous filetés déjà
        # écartés : ils ne sont plus candidats)
        low = sim.refine_gouges(zmap, [o.Shape for o in self.job.Model.Group if getattr(o, "Shape", None)], low, tolerance)
        report = sim.compare(zmap, heights, tolerance, gouge_heights=low)
        checked = bool(simulated)
        not_run = [label for label, _r in skipped]

        def status(kind, extra_unchecked=()):
            if any(e[0] == kind or (e[0] == "undrilled" and kind in ("rapid", "flute_length")) for e in events):
                return "collision"
            if not checked or extra_unchecked or not_run:
                return "not_checked"
            return "ok"

        report["collisions"] = {
            "events": events,
            "flute_length": status("flute_length"),
            "holder": status("holder", no_holder),
            "clamps": status("clamp", () if boxes else ("no clamp",)),
            "rapids": status("rapid"),
            "no_holder": no_holder,
            "clamps_defined": [name for name, _bb in boxes],
            "not_run": not_run,
        }
        report.update(removed_volume=zmap.removed_volume(), rapid_hits=zmap.rapid_hits,
                      rapid_hit_at=zmap.rapid_hit_at, simulated=simulated, skipped=skipped,
                      approximations=approximations, resolution=resolution, tolerance=tolerance,
                      cells=(zmap.nx, zmap.ny))
        self.last_zmap = zmap
        self.last_heights = low  # affichage des entailles (gouge_mask)
        self._store_check(report)
        return report

    def _thread_the_holes(self, zmap, heights):
        """La pièce montre l'avant-trou lisse : un filetage enlève forcément la matière jusqu'à son diamètre
        majeur. Les trous filetés sont creusés à ce diamètre dans la hauteur de référence (sinon chaque
        filet compte comme une entaille)."""
        import numpy as np

        for obj in self.operations():
            base = dressupmod.base_operation(obj)
            if (self.registry.get(base.Name) or {}).get("kind") != "threadmill" or not base.Active:
                continue
            r = float(base.MajorDiameter.Value) / 2.0 + zmap.res
            bottom = float(base.FinalDepth.Value)
            for b, subs in base.Base:
                for sub in subs:
                    c = base.Proxy.holePosition(base, b, sub)
                    win = zmap._window(c.x - r, c.x + r, c.y - r, c.y + r)
                    if win is None:
                        continue
                    i0, i1, j0, j1, (X, Y) = win
                    inside = np.hypot(X - c.x, Y - c.y) <= r
                    block = heights[i0:i1, j0:j1]
                    block[inside] = np.minimum(block[inside], bottom)

    def _store_check(self, report):
        """Dernier contrôle matière / collisions, enregistré dans le document (chaque commande de l'interface
        relit le projet depuis le document : un attribut Python serait perdu)."""
        col = report["collisions"]
        data = {"fingerprint": self._paths_fingerprint(),
                "events": [[e[0], e[1], e[2], list(e[3]) if e[3] else None, e[4]] + list(e[5:]) for e in col["events"]],
                "status": {k: col[k] for k in ("flute_length", "holder", "clamps", "rapids")},
                "no_holder": col["no_holder"], "clamps_defined": col["clamps_defined"],
                "not_run": [str(x) for x in col["not_run"]],
                "gouge_max": report["gouge_max"], "gouge_at": list(report["gouge_at"]) if report["gouge_at"] else None,
                "tolerance": report["tolerance"]}
        if "MaterialCheck" not in self.info.PropertiesList:
            self.info.addProperty("App::PropertyString", "MaterialCheck", "CAM2027", "Last material / collision check (JSON)")
            self.info.setEditorMode("MaterialCheck", 1)
        self.info.MaterialCheck = json.dumps(data)

    def last_check(self):
        raw = getattr(self.info, "MaterialCheck", "")
        return json.loads(raw) if raw else None

    @staticmethod
    def unique_bodies(objects):
        """Corps sans doublon (même volume, même boîte, même centre : fichier importé deux fois)."""
        out = []
        for o in objects:
            s = o.Shape
            key = (s.Volume, s.BoundBox, s.CenterOfMass if s.Solids else None)
            dup = False
            for u in out:
                t = u.Shape
                if abs(t.Volume - key[0]) <= 1e-6 * max(1.0, abs(key[0])) and t.BoundBox.isValid() and \
                        key[1].isValid() and (t.BoundBox.Center - key[1].Center).Length < 1e-6 and \
                        abs(t.BoundBox.DiagonalLength - key[1].DiagonalLength) < 1e-6 and \
                        (key[2] is None or (t.CenterOfMass - key[2]).Length < 1e-6):
                    dup = True
                    break
            if not dup:
                out.append(o)
        return out

    def merge_models(self, objects, label=None):
        """Fusionne plusieurs corps en une seule pièce à usiner (assemblage empilé : sans cela, chaque corps
        est contourné jusqu'au fond du modèle, à travers les autres). Les corps d'origine sont masqués.

        Retourne None si la fusion ne donne pas un solide plausible (forme vide, volume perdu) : les corps
        restent alors séparés (une forme vide fait boucler le brut de FreeCAD jusqu'au plantage)."""
        shapes = [o.Shape for o in objects]
        try:
            fused = shapes[0].fuse(shapes[1:])
        except Exception:
            return None
        try:
            refined = fused.removeSplitter()
            if refined.isValid():
                fused = refined
        except Exception:
            pass
        biggest = max(s.Volume for s in shapes)
        if fused.isNull() or not fused.Solids or not fused.BoundBox.isValid() or fused.Volume < 0.5 * biggest:
            return None
        obj = self.doc.addObject("Part::Feature", "MergedPart")
        obj.Shape = fused
        obj.Label = label or Msg("{n} bodies merged", n=len(objects))
        if FreeCAD.GuiUp:
            for o in objects:
                if o.ViewObject is not None:
                    o.ViewObject.Visibility = False
        self.doc.recompute()
        return obj

    def _paths_fingerprint(self):
        """Empreinte des parcours actifs (un contrôle de collisions ne vaut que pour ces parcours-là)."""
        import hashlib

        from . import twosided

        h = hashlib.sha1()
        for obj in twosided.all_operations(self):  # recto-verso : le contrôle enchaîné vaut pour les deux faces
            base = dressupmod.base_operation(obj)
            h.update(obj.Name.encode())
            h.update(b"1" if getattr(base, "Active", True) else b"0")
            h.update(obj.Path.toGCode().encode())
        return h.hexdigest()

    def collision_issues(self):
        """Contrôles d'export issus du dernier contrôle de collisions : erreur si collision ; « non vérifiable »
        si le contrôle n'a pas été lancé, si les parcours ont changé depuis, ou pour ce qu'il n'a pas pu contrôler."""
        last = self.last_check()
        if last is None or last["fingerprint"] != self._paths_fingerprint():
            return [("unverifiable", Msg("collisions not checked for these toolpaths: run Simulate > Material and collision check"))]
        col = dict(last["status"], events=last["events"], no_holder=last["no_holder"],
                   clamps_defined=last["clamps_defined"], not_run=last["not_run"])
        issues = []
        if last["gouge_max"] > last["tolerance"] and last["gouge_at"]:
            rep = last
            x, y, _z = rep["gouge_at"]
            issues.append(("error", Msg("material check: the tool cuts {d:.2f} mm into the part (worst at X {x:.1f} Y {y:.1f})",
                                        d=rep["gouge_max"], x=x, y=y)))
        for event in col["events"]:
            kind, label, index, at = event[0], event[1], event[2], event[3]
            where = "X%.2f Y%.2f Z%.2f" % tuple(at) if at else "?"
            what = {"flute_length": Msg("material above the flute length (shank rubbing)"),
                    "holder": Msg("tool holder touches the material"),
                    "clamp": Msg("collision with clamp {name} ({part})", name=event[5], part=Msg(event[6]))
                    if kind == "clamp" else "",
                    "rapid": Msg("rapid move into the material"),
                    "undrilled": Msg("thread milling in a hole that is not drilled: add a drilling operation at the tap drill size before it")}[kind]
            issues.append(("error", Msg("{op}: {what}, command {n}, tip at {where}", op=label, what=what, n=index,
                                        where=where)))
        for key, label in (("flute_length", Msg("flute length")), ("holder", Msg("tool holder")),
                           ("clamps", Msg("clamps")), ("rapids", Msg("rapid moves"))):
            if col[key] == "not_checked":
                reason = []
                if key == "holder" and col["no_holder"]:
                    reason.append(Msg("no holder in the assembly of {ops}", ops=", ".join(col["no_holder"])))
                if key == "clamps" and not col["clamps_defined"]:
                    reason.append(Msg("no clamp defined"))
                if col["not_run"]:
                    reason.append(Msg("not simulated: {ops}", ops=", ".join(col["not_run"])))
                issues.append(("unverifiable", Msg("{what} collisions not checked ({why})", what=label,
                                                   why=_JoinedMsg(reason) if reason else "-")))
        return issues

    def wrapped_operations(self):
        return [o for o in self.operations() if wrapmod.is_wrap_op(o)]

    def index_angles(self):
        """Angles A utilisés par les opérations (triés)."""
        return sorted({rec["index_deg"] for rec in self.registry.values() if rec.get("index_deg") is not None})

    def set_operation_index(self, op, index_deg):
        """Change l'angle d'index d'une opération existante dont la géométrie est sélectionnée."""
        op = dressupmod.base_operation(op)
        reg = self.registry
        rec = reg[op.Name]
        if index_deg is not None:
            index_deg = float(index_deg)
            indexing.check_machine(self.machine)
            indexing.check_angle(self.machine, index_deg)
        base = [(indexing.source_of_rotated(self.doc, o), list(subs)) for o, subs in (op.Base or [])]
        tool = self.library.tool(rec["tool_id"])
        if index_deg is not None and abs(index_deg) > 1e-9:
            base = indexing.index_base(self, rec["kind"], base, index_deg, tool.geometry.diameter)
        self.set_operation_base(op, base)
        rec["index_deg"] = index_deg
        self._save_registry(reg)
        indexing.sync(self)
        self._renumber()

    def operations(self):
        return list(self.job.Operations.Group)

    def operation_state(self, obj):
        """État de calcul normalisé de l'objet du groupe Operations (voir ``operations.compute_state``)."""
        if indexing.is_index_op(obj):
            return "computed" if obj.Path.Commands and "Touched" not in (obj.State or []) else "todo"
        base = dressupmod.base_operation(obj)
        return opsmod.compute_state(obj, base, self.registry.get(base.Name))

    def update_operation(self, op, params):
        """Modifie des propriétés d'une opération existante (registre mis à jour) ; retourne les noms ignorés.

        Filetage : un nouveau ``ThreadName`` est résolu en diamètres/pas comme à la création.
        """
        reg = self.registry
        rec = reg.get(op.Name)
        params = dict(params or {})
        if rec and rec.get("kind") == "threadmill":
            tool = self.library.tool(rec["tool_id"])
            if params.get("ThreadName") and params["ThreadName"] != rec.get("params", {}).get("ThreadName"):
                for key in ("MajorDiameter", "MinorDiameter", "Pitch", "TPI"):
                    params.pop(key, None)
            params = opsmod.resolve_params("threadmill", tool, params)
        ignored = opsmod.set_params(op, params)
        if rec is not None:
            merged = dict(rec.get("params", {}))
            merged.update({k: v for k, v in params.items() if k not in ignored})
            rec["params"] = _jsonable(merged)
            rec["ignored_params"] = ignored
            rec["label"] = op.Label
            self._save_registry(reg)
        return ignored

    def change_operation_tool(self, op, assembly_id, preset_id):
        """Change l'assemblage et/ou le préréglage d'une opération existante.

        Même outil : le ToolController reçoit les nouvelles valeurs. Autre outil : un nouveau
        ToolBit + ToolController remplacent les anciens (supprimés). Les réglages de stratégie
        sont conservés ; pour un filetage, le pas est revérifié contre le nouvel outil.
        """
        op = dressupmod.base_operation(op)
        reg = self.registry
        rec = reg.get(op.Name)
        if rec is None:
            raise ValueError("opération %s absente du registre" % op.Label)
        asm, tool, holder = self.library.resolve_assembly(assembly_id)
        preset = tool.preset(preset_id)
        values = preset.resolve(tool)
        if rec["kind"] == "threadmill":
            opsmod.resolve_params("threadmill", tool, rec.get("params", {}))
        warnings = list(rec.get("warnings", []))
        if tool.id != rec["tool_id"]:
            old_tc = self.doc.getObject(rec.get("tool_controller") or "")
            old_bit = self.doc.getObject(rec.get("toolbit") or "")
            toolbit, warnings = bridge.create_toolbit(self.doc, tool, label="%s (T%d)" % (tool.name, asm.output.tool_number))
            tc, _ = bridge.create_tool_controller(self.doc, asm, tool, values, toolbit=toolbit, label="TC: %s" % op.Label)
            self.job.Proxy.addToolController(tc)
            op.ToolController = tc
            if old_tc is not None:
                self.job.Tools.Group = [t for t in self.job.Tools.Group if t.Name != old_tc.Name]
                self.doc.removeObject(old_tc.Name)
            if old_bit is not None:
                self.doc.removeObject(old_bit.Name)
            rec["tool_controller"], rec["toolbit"] = tc.Name, toolbit.Name
        else:
            tc = self.doc.getObject(rec["tool_controller"])
            bridge.apply_preset_to_controller(tc, tool, values)
        rec.update({"assembly_id": asm.id, "tool_id": tool.id, "holder_id": holder.id if holder else None,
                    "preset_id": preset.id, "values": values, "warnings": warnings})
        self._save_registry(reg)
        return rec

    def set_operation_base(self, op, base):
        """Géométrie de l'opération : liste de ``(objet, [sous-éléments])`` ; vide = tout le modèle."""
        op.Base = [(opsmod.model_clone(self.job, obj), list(subs)) for obj, subs in (base or [])]

    def set_operation_active(self, op, active):
        dressupmod.base_operation(op).Active = bool(active)

    def move_operation(self, op, delta):
        """Déplace l'opération de ``delta`` rangs dans l'ordre d'usinage ; retourne son nouvel indice."""
        group = [o for o in self.job.Operations.Group if not indexing.is_index_op(o)]  # positionnements A recréés
        i = group.index(op)
        j = max(0, min(len(group) - 1, i + delta))
        if j != i:
            group.insert(j, group.pop(i))
            self.job.Operations.Group = group
            indexing.sync(self)
            self._renumber()
        return j

    def move_operation_to(self, op, index):
        """Place l'opération au rang ``index`` de l'ordre d'usinage (positionnements A non comptés) ; retourne
        son rang."""
        group = [o for o in self.job.Operations.Group if not indexing.is_index_op(o)]
        return self.move_operation(op, int(index) - group.index(op))

    def duplicate_operation(self, op):
        """Copie l'opération (mêmes outil, préréglage, géométrie et valeurs courantes ; habillages non copiés)
        juste après l'original."""
        top = dressupmod.top_of(self.job, op)
        op = dressupmod.base_operation(op)
        rec = self.registry.get(op.Name)
        if rec is None:
            raise ValueError("opération %s absente du registre" % op.Label)
        if rec["kind"] not in opsmod.STRATEGIES and rec["kind"] != wrapmod.KIND:
            raise UserError("{op} is generated (flat depth clearing): it cannot be duplicated", op=op.Label)
        if rec["kind"] == wrapmod.KIND:
            base = [(self.doc.getObject(n), subs) for n, subs in rec["wrap_base"]]
            return self.add_wrapped_engraving(tr("{name} (copy)", name=op.Label), rec["assembly_id"], rec["preset_id"], base,
                                              **rec["params"])
        params = opsmod.read_params(op, opsmod.STRATEGIES[rec["kind"]]["params"])
        new, record = self.add_operation(rec["kind"], tr("{name} (copy)", name=op.Label), rec["assembly_id"], rec["preset_id"],
                                         base=[(obj, list(subs)) for obj, subs in (op.Base or [])], params=params)
        new.Active = op.Active
        if rec.get("index_deg") is not None:  # la géométrie copiée est déjà celle de l'index
            reg = self.registry
            reg[new.Name]["index_deg"] = rec["index_deg"]
            self._save_registry(reg)
            record = reg[new.Name]
        group = [o for o in self.job.Operations.Group if not indexing.is_index_op(o)]
        group.remove(new)
        group.insert(group.index(top) + 1, new)
        self.job.Operations.Group = group
        indexing.sync(self)
        self._renumber()
        return new, record

    def remove_operation(self, op):
        """Supprime l'opération (et ses habillages), son ToolController et son ToolBit, et l'entrée de registre."""
        op = dressupmod.base_operation(op)
        if indexing.is_index_op(op):
            raise ValueError("les positionnements A sont gérés automatiquement : supprimer ou réindexer les opérations")
        self.job.Operations.Group = [o for o in self.job.Operations.Group if not indexing.is_index_op(o)]
        for idx in [o for o in self.doc.Objects if indexing.is_index_op(o)]:
            idx.Label = "CAM2027IndexRemoved"
            self.doc.removeObject(idx.Name)  # libère les contrôleurs d'outil référencés
        for d in self.dressups(op):
            dressupmod.remove_dressup(self.job, d)
        reg = self.registry
        rec = reg.pop(op.Name, None)
        self.job.Operations.Group = [o for o in self.job.Operations.Group if o.Name != op.Name]
        if self.doc.getObject(op.Name + "_Preview") is not None:
            self.doc.removeObject(op.Name + "_Preview")
        self.doc.removeObject(op.Name)
        if rec:
            tc = self.doc.getObject(rec.get("tool_controller") or "")
            if tc is not None:
                self.job.Tools.Group = [t for t in self.job.Tools.Group if t.Name != tc.Name]
                self.doc.removeObject(tc.Name)
            bit_name = rec.get("toolbit") or ""
            if bit_name and self.doc.getObject(bit_name) is not None:
                self.doc.removeObject(bit_name)
        self._save_registry(reg)
        indexing.sync(self)
        self._renumber()

    def _renumber(self):
        reg = self.registry
        for i, o in enumerate(self.job.Operations.Group):
            name = dressupmod.base_operation(o).Name
            if name in reg:
                reg[name]["order"] = i
        self._save_registry(reg)

    # -- habillages (attaches, rampe) ------------------------------------------

    def base_operation(self, obj):
        return dressupmod.base_operation(obj)

    def dressups(self, op):
        """Habillages (objets FreeCAD) empilés sur ``op``, du plus haut au plus proche."""
        return dressupmod.dressup_chain(dressupmod.top_of(self.job, op))

    def add_dressup(self, op, kind, params=None, count=None):
        """Ajoute un habillage (``tags`` ou ``ramp``) à l'opération ; retourne (objet, paramètres ignorés)."""
        base = dressupmod.base_operation(op)
        obj, ignored = dressupmod.add_dressup(self.job, base, kind, params=params, count=count)
        reg = self.registry
        rec = reg.get(base.Name)
        if rec is not None:
            rec.setdefault("dressups", [])
            rec["dressups"] = [d for d in rec["dressups"] if d["kind"] != kind]
            rec["dressups"].append({"kind": kind, "name": obj.Name, "params": _jsonable(params or {}),
                                    "count": count})
            self._save_registry(reg)
        self._renumber()
        return obj, ignored

    def remove_dressup(self, op, kind):
        """Retire l'habillage ``kind`` de l'opération (sans effet s'il n'existe pas)."""
        base = dressupmod.base_operation(op)
        for d in self.dressups(base):
            if dressupmod.dressup_kind(d) == kind:
                dressupmod.remove_dressup(self.job, d)
                break
        reg = self.registry
        rec = reg.get(base.Name)
        if rec is not None and rec.get("dressups"):
            rec["dressups"] = [d for d in rec["dressups"] if d["kind"] != kind]
            self._save_registry(reg)
        self._renumber()

    def compute(self):
        """Recalcule le document et retourne un résumé par opération."""
        for op in self.wrapped_operations():
            self._generate_wrap(op)  # le dessin ou le brut ont pu changer
        opsmod.patch_adaptive_slicing()  # projet rouvert : l'adaptative n'est pas encore passée par strategy_module
        opsmod.patch_surface_keepalive()
        opsmod.patch_pocket()
        restmod.sync(self)  # reprise de matière : opérations précédentes à jour (ordre, activation)
        self.doc.recompute()
        results = []
        for op in self.operations():
            summary = opsmod.toolpath_summary(op)
            summary["valid"] = op.isValid()
            results.append(summary)
        return results

    # -- export ---------------------------------------------------------------

    def export_gcode(self, path, post_processor=None, post_args=None, write_sheet=True):
        """Postprocesse, analyse, vérifie, écrit le G-code et la fiche. Retourne un dict."""
        job = self.job
        if not self.operations():
            raise ValueError("aucune opération à exporter")
        self.doc.recompute()
        sections = exportmod.postprocess(job, post_processor, post_args)
        text = "\n".join(g for _n, g in sections)
        analysis = exportmod.analyze_gcode(text)
        issues = exportmod.verify(analysis, self.machine, self.stock_bounds()) + indexing.order_issues(self) \
            + self.collision_issues() + keepout.issues(self)
        if any(level == "error" for level, _m in issues):
            raise ExportBlocked(issues, sections, analysis)
        written = exportmod.write_gcode(sections, path)
        job.PostProcessorOutputFile = path
        sheet_path = None
        sheet = exportmod.prep_sheet(self, sections, analysis, issues, written)
        if write_sheet:
            sheet_path = os.path.splitext(path)[0] + "-setup.md"
            with open(sheet_path, "w", encoding="utf-8") as fp:
                fp.write(sheet)
        return {
            "files": written,
            "sheet": sheet_path,
            "sheet_text": sheet,
            "analysis": analysis,
            "issues": issues,
            "gcode": text,
        }

    def preview_gcode(self, post_processor=None, post_args=None):
        self.doc.recompute()  # jamais d'aperçu construit sur des parcours périmés
        sections = exportmod.postprocess(self.job, post_processor, post_args)
        text = "\n".join(g for _n, g in sections)
        analysis = exportmod.analyze_gcode(text)
        issues = exportmod.verify(analysis, self.machine, self.stock_bounds() if self.has_job else None) \
            + indexing.order_issues(self) + (self.collision_issues() if self.has_job else []) + keepout.issues(self)
        return text, analysis, issues

    # -- sauvegarde -----------------------------------------------------------

    def save(self, path=None):
        if path:
            self.doc.saveAs(path)
        else:
            if not self.doc.FileName:
                raise ValueError("chemin requis pour la première sauvegarde")
            self.doc.save()
        return self.doc.FileName

    def close(self):
        FreeCAD.closeDocument(self.doc.Name)


class _JoinedMsg(Msg):
    """Plusieurs messages joints par « ; », traduits chacun à l'affichage."""

    def __new__(cls, parts):
        obj = Msg.__new__(cls, "; ".join(str(p) for p in parts))
        obj.template = "{0}"
        obj.parts = list(parts)
        obj.params = {}
        return obj


class ExportBlocked(Exception):
    """Levée quand la vérification du G-code trouve une erreur bloquante."""

    def __init__(self, issues, sections, analysis):
        self.issues = issues
        self.sections = sections
        self.analysis = analysis
        Exception.__init__(self, "; ".join(m for level, m in issues if level == "error"))


def _safe_doc_name(name):
    out = "".join(ch if ch.isalnum() else "_" for ch in name)
    if not out or out[0].isdigit():
        out = "P" + out
    return out


def _jsonable(value):
    try:
        json.dumps(value)
        return value
    except TypeError:
        if isinstance(value, dict):
            return {k: _jsonable(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [_jsonable(v) for v in value]
        return str(value)
