# SPDX-License-Identifier: LGPL-2.1-or-later
"""Commandes du flux « à la Aspire » (nuit 2, S5) : modèles de parcours, dessin, images, fiche, décors.

Enregistrées par ``commands.COMMANDS`` (accroche en fin de liste) ; les aides de ``commands`` sont lues au
moment de l'appel (les scénarios d'interface les remplacent par leur pilote).
"""

import os

import FreeCAD
import FreeCADGui

from ..i18n import tr, tr_msg
from .qt import QtWidgets
from . import commands as base


def _templates_dir():
    from ..tools.library import default_library_path

    folder = os.path.join(os.path.dirname(default_library_path()), "templates")
    os.makedirs(folder, exist_ok=True)
    return folder


class SaveTemplate(base._Base):
    atelier = "open-project"
    text = "Save toolpath template"
    tooltip = "Save the operations of this project (strategy, tool, settings, target layer / vector) to apply them to another drawing"

    def Activated(self):
        from ..project import templates

        proj = base._need_project()
        if proj is None:
            return
        if not proj.has_job or not proj.operations():
            base._warn(tr("No operation to save: create the operations on the drawing first."))
            return
        path, _f = QtWidgets.QFileDialog.getSaveFileName(
            FreeCADGui.getMainWindow(), tr("Save toolpath template"), os.path.join(_templates_dir(), proj.doc.Label),
            tr("Toolpath templates") + " (*%s)" % templates.EXTENSION)
        if not path:
            return
        tpl = templates.capture(proj, os.path.splitext(os.path.basename(path))[0])
        if not tpl["operations"]:
            base._warn(tr("No operation on a 2D drawing vector: nothing to save in a template."))
            return
        path = templates.save(tpl, path)
        lines = [tr("Template saved: {n} operation(s) in {file}.", n=len(tpl["operations"]), file=os.path.basename(path))]
        if tpl["skipped"]:
            lines.append(tr("Not in the template (whole part or generated): {ops}", ops=", ".join(tpl["skipped"])))
        base._info("\n".join(lines))


class ApplyTemplate(base._Base):
    atelier = "recalculate"
    text = "Apply toolpath template"
    tooltip = "Create the operations of a template on this drawing: vectors matched by layer, then by name, then computed"

    @base._undoable
    def Activated(self):
        from ..project import templates

        proj = base._need_project()
        if proj is None:
            return
        if not proj.has_job:
            base._warn(tr("Define the stock & fixture first (this creates the job)."))
            return
        path, _f = QtWidgets.QFileDialog.getOpenFileName(
            FreeCADGui.getMainWindow(), tr("Apply toolpath template"), _templates_dir(),
            tr("Toolpath templates") + " (*%s)" % templates.EXTENSION)
        if not path:
            return
        try:
            rep = templates.apply(proj, templates.load(path))
            with base.busy(tr("Computing the toolpaths..."), stoppable=proj):
                proj.compute()
        except Exception as exc:
            base._warn(tr("Operation failed: {error}", error=tr_msg(exc)))
            return
        base._after_change()
        how = {"layer": tr("by layer"), "name": tr("by name")}
        lines = [tr("{n} operation(s) created:", n=len(rep["created"]))]
        lines += ["- %s (%s)" % (op.Label, how.get(h, h)) for op, h in rep["created"]]
        failed = [op.Label for op, _h in rep["created"] if proj.operation_state(op) == "failed"]
        if rep["missing"]:
            lines.append(tr("Not created:"))
            lines += ["- " + tr_msg(m) for m in rep["missing"]]
        if failed:
            lines.append(tr("Operations without a valid toolpath: {names}", names=", ".join(failed)))
        (base._warn if rep["missing"] or failed else base._info)("\n".join(lines))


def _image_path(title):
    from ..project import relief

    filt = tr("Images") + " (" + " ".join("*" + e for e in relief.IMAGE_EXTENSIONS) + ")"
    path, _f = QtWidgets.QFileDialog.getOpenFileName(FreeCADGui.getMainWindow(), title, "", filt)
    return path


class TraceBitmap(base._Base):
    atelier = "contour"
    text = "Trace bitmap"
    tooltip = "Turn the dark (or light) areas of an image into closed drawing vectors"

    @base._undoable
    def Activated(self):
        proj = base._need_project()
        if proj is None:
            return
        path = _image_path(tr("Trace bitmap"))
        if not path:
            return
        res = base._sheet_dialog(proj, "TraceBitmapDialog", path=path)
        if res:
            obj, n = res
            base._info(tr("{n} closed outline(s) traced in {name}.", n=n, name=obj.Label))
            FreeCADGui.SendMsgToActiveView("ViewFit")


class PhotoVCarve(base._Base):
    atelier = "engrave"
    text = "Photo V-carve"
    tooltip = "Engrave a photo with a V-bit: parallel lines, deeper where the image is darker"

    @base._undoable
    def Activated(self):
        proj = base._need_project()
        if proj is None:
            return
        if not proj.has_job:
            base._warn(tr("Define the stock & fixture first (this creates the job)."))
            return
        path = _image_path(tr("Photo V-carve"))
        if not path:
            return
        op = base._sheet_dialog(proj, "PhotoVCarveDialog", path=path)
        if op:
            op, rec = op
            base._info(tr("{name}: {n} moves, lines every {s} mm.", name=op.Label, n=len(op.Path.Commands),
                          s="%.3f" % rec["params"]["spacing"]))


class SetupSheetPdf(base._Base):
    atelier = "open-project"
    text = "Setup sheet (PDF)"
    tooltip = "Write the setup sheet (tools, operations, estimated time with acceleration, checks) as a PDF file"

    def Activated(self):
        from ..project import export as exportmod

        proj = base._need_project()
        if proj is None:
            return
        if not proj.has_job or not proj.operations():
            base._warn(tr("No operation to export: add an operation first."))
            return
        path, _f = QtWidgets.QFileDialog.getSaveFileName(FreeCADGui.getMainWindow(), tr("Setup sheet (PDF)"),
                                                         proj.doc.Label + "-setup.pdf", "PDF (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        try:
            with base.busy(tr("Computing the toolpaths...")):
                _text, analysis, issues = proj.preview_gcode()
                sheet = exportmod.prep_sheet(proj, [], analysis, issues, [path])
                exportmod.write_pdf(sheet, path, title=proj.doc.Label)
        except Exception as exc:
            base._warn(tr("Operation failed: {error}", error=tr_msg(exc)))
            return
        base._info(tr("Setup sheet written: {file}", file=path))


from . import vectors  # noqa: E402

COMMANDS = [
    ("CAM2027_SaveTemplate", SaveTemplate),
    ("CAM2027_ApplyTemplate", ApplyTemplate),
    ("CAM2027_TraceBitmap", TraceBitmap),
    ("CAM2027_PhotoVCarve", PhotoVCarve),
    ("CAM2027_SetupSheetPdf", SetupSheetPdf),
] + vectors.COMMANDS
#: menu et barre d'outils Dessin
DRAWING_MENU = vectors.TOOLBAR + ["Separator", "CAM2027_TraceBitmap"]
#: entrées du menu Usiner
MACHINING_MENU = ["Separator", "CAM2027_PhotoVCarve", "Separator", "CAM2027_SaveTemplate", "CAM2027_ApplyTemplate"]
#: entrées du menu Exporter
EXPORT_MENU = ["CAM2027_SetupSheetPdf"]
