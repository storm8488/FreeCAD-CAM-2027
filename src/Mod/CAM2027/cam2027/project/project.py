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

    def set_stock(self, spec):
        return stockmod.set_stock(self.job, spec)

    def stock_bounds(self):
        return stockmod.stock_bounds(self.job)

    def add_clamp(self, name, length, width, height, origin):
        return stockmod.add_clamp(self.job, name, length, width, height, origin)

    # -- opérations -----------------------------------------------------------

    def add_operation(self, kind, name, assembly_id, preset_id, base=None, params=None):
        """Crée une opération avec un ToolController dédié issu de (assemblage, préréglage).

        Retourne ``(op, record)`` où ``record`` contient les valeurs copiées et
        les avertissements (approximations de forme, paramètres ignorés).
        """
        job = self.job
        asm, tool, holder = self.library.resolve_assembly(assembly_id)
        preset = tool.preset(preset_id)
        values = preset.resolve(tool)
        params = opsmod.resolve_params(kind, tool, params)
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
        }
        reg[op.Name] = record
        self._save_registry(reg)
        return op, record

    def operations(self):
        return list(self.job.Operations.Group)

    def compute(self):
        """Recalcule le document et retourne un résumé par opération."""
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
        issues = exportmod.verify(analysis, self.machine, self.stock_bounds())
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
        sections = exportmod.postprocess(self.job, post_processor, post_args)
        text = "\n".join(g for _n, g in sections)
        analysis = exportmod.analyze_gcode(text)
        issues = exportmod.verify(analysis, self.machine, self.stock_bounds() if self.has_job else None)
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
