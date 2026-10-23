# SPDX-License-Identifier: LGPL-2.1-or-later
"""Usiner > Motif : copies d'opérations en grille ou en cercle (dialogue et commande)."""

from ..i18n import tr, tr_msg
from ..project import dressups as dressupmod, patterns
from . import theme
from .qt import QtWidgets


def _spin(lo, hi, value, decimals=2, suffix=""):
    s = QtWidgets.QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(decimals)
    s.setValue(value)
    if suffix:
        s.setSuffix(suffix)
    return s


def _int(lo, hi, value):
    s = QtWidgets.QSpinBox()
    s.setRange(lo, hi)
    s.setValue(value)
    return s


class PatternDialog(QtWidgets.QDialog):
    """Opérations à répéter (cochées), grille (colonnes, lignes, pas) ou cercle (nombre, centre, angle)."""

    def __init__(self, proj, parent=None, selected=()):
        super(PatternDialog, self).__init__(parent)
        self.proj = proj
        self.setWindowTitle(tr("Toolpath pattern"))
        form = QtWidgets.QFormLayout(self)
        hint = QtWidgets.QLabel(tr("Copies the computed toolpaths of the checked operations on a grid or a circle. The first copy is the operation itself."))
        hint.setWordWrap(True)
        theme.set_role(hint, "muted")
        form.addRow(hint)
        chosen = set(dressupmod.base_operation(o).Name for o in selected)
        self.ops = QtWidgets.QListWidget()
        for o in proj.operations():
            base = dressupmod.base_operation(o)
            if any(dressupmod.dressup_kind(d) == "pattern" for d in dressupmod.dressup_chain(o)):
                continue
            item = QtWidgets.QListWidgetItem(base.Label)
            item.setData(256, base.Name)
            item.setCheckState(theme_checked(base.Name in chosen))
            self.ops.addItem(item)
        form.addRow(tr("Operations"), self.ops)
        self.kind = QtWidgets.QComboBox()
        self.kind.addItem(tr("Grid"), "Grid")
        self.kind.addItem(tr("Circular"), "Circular")
        form.addRow(tr("Pattern"), self.kind)
        self.columns, self.rows = _int(1, 100, 2), _int(1, 100, 1)
        self.step_x, self.step_y = _spin(-10000, 10000, 50.0, suffix=" mm"), _spin(-10000, 10000, 50.0, suffix=" mm")
        self.count = _int(1, patterns.MAX_COPIES, 4)
        self.cx, self.cy = _spin(-10000, 10000, 0.0, suffix=" mm"), _spin(-10000, 10000, 0.0, suffix=" mm")
        self.angle = _spin(-360, 360, 360.0, decimals=1, suffix=" °")
        self.grid_rows = [(tr("Columns (X)"), self.columns), (tr("Rows (Y)"), self.rows),
                          (tr("Distance between columns"), self.step_x), (tr("Distance between rows"), self.step_y)]
        self.circle_rows = [(tr("Number of copies"), self.count), (tr("Centre X"), self.cx), (tr("Centre Y"), self.cy),
                            (tr("Total angle"), self.angle)]
        self._labels = {}
        for text, w in self.grid_rows + self.circle_rows:
            label = QtWidgets.QLabel(text)
            self._labels[w] = label
            form.addRow(label, w)
        bounds = proj.stock_bounds() if proj.has_job else None
        if bounds:
            self.cx.setValue(0.5 * (bounds["xmin"] + bounds["xmax"]))
            self.cy.setValue(0.5 * (bounds["ymin"] + bounds["ymax"]))
        self.minimize = QtWidgets.QCheckBox(tr("Fewer tool changes (group the operations by tool)"))
        self.minimize.setChecked(True)
        form.addRow(self.minimize)
        self.status = QtWidgets.QLabel("")
        self.status.setWordWrap(True)
        form.addRow(self.status)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(self._check_and_accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)
        self.kind.currentIndexChanged.connect(self._show_kind)
        self._show_kind()
        # pas proposé : emprise de la coupe + un diamètre d'outil (copies hors de la pièce), tant que l'utilisateur
        # ne l'a pas saisi
        self._auto_steps = True
        self._suggested = None
        for spin in (self.step_x, self.step_y):
            spin.editingFinished.connect(self._steps_typed)
        self.ops.itemChanged.connect(self._suggest_steps)
        self._suggest_steps()

    def _steps_typed(self):
        if (self.step_x.value(), self.step_y.value()) != self._suggested:
            self._auto_steps = False

    def _suggest_steps(self, *_args):
        steps = [patterns.default_steps(dressupmod.top_of(self.proj.job, o)) for o in self.checked_operations()]
        steps = [s for s in steps if s]
        if not self._auto_steps or not steps:
            return
        self.step_x.setValue(max(s[0] for s in steps))
        self.step_y.setValue(max(s[1] for s in steps))
        self._suggested = (self.step_x.value(), self.step_y.value())

    def _show_kind(self, *_args):
        grid = self.kind.currentData() == "Grid"
        for _t, w in self.grid_rows:
            w.setVisible(grid)
            self._labels[w].setVisible(grid)
        for _t, w in self.circle_rows:
            w.setVisible(not grid)
            self._labels[w].setVisible(not grid)

    def checked_operations(self):
        names = [self.ops.item(i).data(256) for i in range(self.ops.count())
                 if self.ops.item(i).checkState() == theme_checked(True)]
        return [self.proj.doc.getObject(n) for n in names]

    def params(self):
        if self.kind.currentData() == "Grid":
            return {"Kind": "Grid", "Columns": self.columns.value(), "Rows": self.rows.value(),
                    "StepX": self.step_x.value(), "StepY": self.step_y.value()}
        return {"Kind": "Circular", "Count": self.count.value(), "Centre": (self.cx.value(), self.cy.value(), 0.0),
                "Angle": self.angle.value()}

    def _check_and_accept(self):
        try:
            if not self.checked_operations():
                raise patterns.PatternError("Select one or more operations to repeat.")
            patterns.offsets(self.params())
            patterns.check_ops(self.proj, self.checked_operations(), self.params())
        except Exception as exc:
            self.status.setText("<span style='color:%s'>%s</span>" % (theme.status_color("error"), tr_msg(exc)))
            return
        self.accept()

    def apply(self):
        return patterns.add_pattern(self.proj, self.checked_operations(), self.params(),
                                    minimize=self.minimize.isChecked())


def theme_checked(on):
    from .qt import QtCore

    return QtCore.Qt.Checked if on else QtCore.Qt.Unchecked


class PatternCommand(object):
    icon = "CAM2027.svg"
    accel = ""
    atelier = "measure"
    text = "Toolpath pattern"
    tooltip = "Repeat operations on a grid or a circle (Aspire array copy), with fewer tool changes"

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
        if not proj.has_job or not proj.operations():
            commands._warn(tr("Add an operation first."))
            return
        sel = [s.Object for s in FreeCADGui.Selection.getSelectionEx() if s.Object.Document.Name == proj.doc.Name]
        dlg = PatternDialog(proj, FreeCADGui.getMainWindow(), selected=sel)
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
        if made:
            commands._info(tr("{n} operation(s) repeated; tool changes: {t}.", n=len(made),
                              t=patterns.tool_changes(proj)))
