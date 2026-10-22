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


COMMANDS = [
    ("CAM2027_SaveTemplate", SaveTemplate),
    ("CAM2027_ApplyTemplate", ApplyTemplate),
]
#: entrées du menu Usiner
MACHINING_MENU = ["Separator", "CAM2027_SaveTemplate", "CAM2027_ApplyTemplate"]
