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
import Path.Main.Job as PathJob

from ..version import __version__, DATA_VERSION
from ..tools.library import ToolLibrary
from ..tools import bridge
from . import docobjects, importers, stock as stockmod, operations as opsmod, export as exportmod
from . import dressups as dressupmod
from . import sheet as sheetmod
from . import indexing
from . import wrap as wrapmod
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

    def import_model(self, path, label=None):
        return importers.import_file(self.doc, path, label)

    def import_relief(self, path, width, relief_height, **options):
        """Relief 3D depuis une image (carte de hauteur), voir ``relief.make_relief``."""
        from . import relief

        obj, warnings = relief.make_relief(self.doc, path, width, relief_height, **options)
        return importers.ImportResult("solid", [obj], warnings)

    # -- job, brut, montage ---------------------------------------------------

    def create_job(self, models, stock=None, fixtures=("G54",), post_processor=None, post_args=None):
        if self.info.Job is not None:
            raise ValueError("le projet a déjà un job")
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

    def create_sheet_job(self, vectors=None, thickness=18.0, margin=10.0, fixtures=("G54",)):
        """Job « dessin 2D dans un panneau » : panneau sous le dessin (dessus à Z = 0), une face par
        vecteur fermé, brut = panneau. ``vectors`` par défaut : tous les vecteurs du document."""
        vectors = list(vectors) if vectors else sheetmod.vector_objects(self.doc)
        if not vectors:
            raise ValueError("aucun dessin 2D dans le projet (importer un SVG ou un DXF)")
        sheet = sheetmod.make_sheet(self.doc, vectors, float(thickness), float(margin))
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
        p = rec["params"]
        cy, cz, sign = indexing.check_machine(self.machine)
        radius = wrapmod.radius_of_stock(self.job)
        wrapmod.check_stock_axis(self.job, (cy, cz))
        base = []
        for name, subs in rec["wrap_base"]:
            obj = self.doc.getObject(name)
            if obj is None:
                raise ValueError("wrapped engraving %s: drawing object %s not found" % (op.Label, name))
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
        obj.Label = "%s (preview)" % op.Label
        obj.Shape = Part.Compound([Part.makePolygon(pts) for pts in polylines]) if polylines else Part.Shape()
        if FreeCAD.GuiUp and obj.ViewObject is not None:
            obj.ViewObject.LineColor = (0.2, 0.55, 1.0)
            obj.ViewObject.LineWidth = 2.0
            if "OnTopWhenSelected" in obj.ViewObject.PropertiesList:  # le trajet est sous la surface
                obj.ViewObject.OnTopWhenSelected = "Enabled"
        return obj

    def material_check(self, resolution=None, tolerance=0.02):
        """Simulation d'enlèvement de matière (Z-map, 3 axes) et comparaison avec la pièce.

        Retourne un dict : volume enlevé, entaille maximale (et position), reste maximal / moyen,
        rapides dans la matière, opérations simulées / non simulées (avec la raison), approximations.
        La carte calculée reste dans ``self.last_zmap`` (affichage).
        """
        from . import sim

        if getattr(self.job.Stock, "Radius", None) is not None:
            raise ValueError("material check: round stock (4th axis) is not supported, only box stock")
        resolution = resolution or sim.DEFAULT_RESOLUTION
        self.compute()
        zmap = sim.ZMap.from_bounds(self.stock_bounds(), resolution)
        simulated, skipped, approximations = [], [], []
        pos = None
        for obj in self.operations():
            if indexing.is_index_op(obj):
                continue
            base = dressupmod.base_operation(obj)
            if getattr(base, "Active", True) is False:
                continue
            rec = self.registry.get(base.Name) or {}
            if wrapmod.is_wrap_op(obj):
                skipped.append((obj.Label, "uses the A axis (wrapped)"))
                pos = None
                continue
            if rec.get("index_deg") not in (None, 0, 0.0):
                skipped.append((obj.Label, "indexed at A%g" % rec["index_deg"]))
                pos = None
                continue
            if not rec.get("tool_id"):
                skipped.append((obj.Label, "unknown tool"))
                continue
            profile, note = sim.ToolProfile.from_library_tool(self.library.tool(rec["tool_id"]))
            if note:
                approximations.append((obj.Label, note))
            segments, pos = sim.path_segments(obj.Path.Commands, pos)
            for rapid, p0, p1 in segments:
                zmap.sweep(p0, p1, profile, rapid=rapid)
            simulated.append(obj.Label)
        heights = sim.model_heights(zmap, [o.Shape for o in self.job.Model.Group if getattr(o, "Shape", None)])
        report = sim.compare(zmap, heights, tolerance)
        report.update(removed_volume=zmap.removed_volume(), rapid_hits=zmap.rapid_hits,
                      rapid_hit_at=zmap.rapid_hit_at, simulated=simulated, skipped=skipped,
                      approximations=approximations, resolution=resolution, tolerance=tolerance,
                      cells=(zmap.nx, zmap.ny))
        self.last_zmap = zmap
        self.last_heights = heights
        return report

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

    def duplicate_operation(self, op):
        """Copie l'opération (mêmes outil, préréglage, géométrie et valeurs courantes ; habillages non copiés)
        juste après l'original."""
        top = dressupmod.top_of(self.job, op)
        op = dressupmod.base_operation(op)
        rec = self.registry.get(op.Name)
        if rec is None:
            raise ValueError("opération %s absente du registre" % op.Label)
        if rec["kind"] == wrapmod.KIND:
            base = [(self.doc.getObject(n), subs) for n, subs in rec["wrap_base"]]
            return self.add_wrapped_engraving(op.Label + " (copy)", rec["assembly_id"], rec["preset_id"], base,
                                              **rec["params"])
        params = opsmod.read_params(op, opsmod.STRATEGIES[rec["kind"]]["params"])
        new, record = self.add_operation(rec["kind"], op.Label + " (copy)", rec["assembly_id"], rec["preset_id"],
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
        issues = exportmod.verify(analysis, self.machine, self.stock_bounds()) + indexing.order_issues(self)
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
            + indexing.order_issues(self)
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
