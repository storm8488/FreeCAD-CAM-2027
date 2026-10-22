# SPDX-License-Identifier: LGPL-2.1-or-later
"""Usiner > Perçage intelligent : trous reconnus, séquence proposée (pointage, perçage, chanfrein, filetage)."""

from ..i18n import tr, tr_msg
from ..project import holes as holesmod
from ..project import operations as opsmod
from . import theme
from .qt import QtWidgets


class HoleDialog(QtWidgets.QDialog):
    """Groupes de trous identiques (tableau), étapes à faire, filet par diamètre, aperçu de la séquence."""

    def __init__(self, proj, parent=None):
        super(HoleDialog, self).__init__(parent)
        self.proj = proj
        self.setWindowTitle(tr("Hole recognition and drilling"))
        self.setMinimumWidth(640)
        self.clone = proj.job.Model.Group[0]
        self.holes = holesmod.find_holes(self.clone)
        self.groups = holesmod.groups(self.holes)
        lay = QtWidgets.QVBoxLayout(self)
        hint = QtWidgets.QLabel(tr("Vertical holes found on the part, grouped by size. One operation is made per step and per hole size: spot drilling, drilling (peck drilling deeper than 3 diameters, bore milling without a drill of the size), chamfer, thread milling."))
        hint.setWordWrap(True)
        theme.set_role(hint, "muted")
        lay.addWidget(hint)
        self.table = QtWidgets.QTableWidget(len(self.groups), 5)
        self.table.setHorizontalHeaderLabels([tr("Diameter"), tr("Holes"), tr("Depth"), tr("Type"), tr("Thread")])
        self.thread_boxes = []
        names = [""] + opsmod.thread_names(opsmod.DEFAULT_THREAD_TYPE)
        for row, (model, members) in enumerate(self.groups):
            kind = tr("through hole") if model.through else tr("blind")
            if model.chamfer_diameter:
                kind += ", " + tr("chamfer {d} mm", d="%.2f" % model.chamfer_diameter)
            cells = ("%.2f mm" % model.diameter, str(len(members)), "%.2f mm" % model.depth, kind)
            for col, text in enumerate(cells):
                item = QtWidgets.QTableWidgetItem(text)
                self.table.setItem(row, col, item)
            combo = QtWidgets.QComboBox()
            combo.setEditable(True)
            combo.addItems(names)
            combo.currentTextChanged.connect(self._refresh)
            self.table.setCellWidget(row, 4, combo)
            self.thread_boxes.append(combo)
        self.table.resizeColumnsToContents()
        lay.addWidget(self.table)
        self.spot = QtWidgets.QCheckBox(tr("Spot drill before drilling"))
        self.spot.setChecked(True)
        self.spot.toggled.connect(self._refresh)
        lay.addWidget(self.spot)
        lay.addWidget(QtWidgets.QLabel(tr("Operations to create")))
        self.preview = QtWidgets.QListWidget()
        lay.addWidget(self.preview)
        self.status = QtWidgets.QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(self._check_and_accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._refresh()

    def threads(self):
        out = {}
        for (model, _m), combo in zip(self.groups, self.thread_boxes):
            text = combo.currentText().strip()
            if text:
                out[round(model.diameter, 2)] = text
        return out

    def _refresh(self, *_args):
        self.steps, self.notes = holesmod.plan(self.proj.library, self.holes, threads=self.threads(),
                                               spot=self.spot.isChecked(),
                                               stock_top=self.proj.stock_bounds()["zmax"])
        self.preview.clear()
        for st in self.steps:
            label = tr(holesmod.STEP_LABELS["bore" if st.get("bore") else st["step"]])
            self.preview.addItem("%s Ø%.2f (%d) - %s" % (label, st["model"].diameter, len(st["holes"]),
                                                       st["tool"].name))
        text = [tr_msg(n) for n in self.notes]
        if not self.holes:
            text.insert(0, tr("No vertical hole open at the top was found on the part."))
        self.status.setText("<br>".join(text))

    def _check_and_accept(self):
        if not self.steps:
            self.status.setText("<span style='color:%s'>%s</span>" % (
                theme.status_color("error"), tr("Nothing to drill.")))
            return
        self.accept()

    def apply(self):
        return holesmod.apply_plan(self.proj, self.clone, self.steps)


class HoleCommand(object):
    icon = "CAM2027.svg"
    accel = ""
    atelier = "drill"
    text = "Hole recognition and drilling"
    tooltip = "Find the holes of the part and add spot drilling, drilling, chamfer and thread milling for each size"

    def GetResources(self):
        from . import commands

        return commands._Base.GetResources(self)

    def IsActive(self):
        return True

    def Activated(self):
        import FreeCAD
        import FreeCADGui
        from . import commands
        from ..project import undo

        proj = commands._need_project()
        if proj is None:
            return
        if not proj.has_job:
            commands._warn(tr("Define the stock & fixture first (this creates the job)."))
            return
        dlg = HoleDialog(proj, FreeCADGui.getMainWindow())
        if commands.exec_dialog(dlg) != QtWidgets.QDialog.Accepted:
            return
        try:
            with undo.transaction(FreeCAD.ActiveDocument, tr(self.text)):
                made = dlg.apply()
                with commands.busy(tr("Computing the toolpaths...")):
                    proj.compute()
        except Exception as exc:
            commands._warn(tr("Operation failed: {error}", error=tr_msg(exc)))
            return
        commands._after_change()
        lines = [tr("{n} drilling operation(s) added.", n=len(made))] + [tr_msg(n) for n in dlg.notes]
        commands._info("\n".join(lines))
