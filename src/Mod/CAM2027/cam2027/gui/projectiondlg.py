# SPDX-License-Identifier: LGPL-2.1-or-later
"""Dialogue « Projeter sur la pièce » : gravure, contour ou V-carving calculés à plat, reportés sur la surface 3D."""

from ..i18n import tr
from ..project import dressups as dressupmod
from ..project import projection
from . import theme
from .qt import QtWidgets


def candidates(proj):
    """Opérations projetables : (opération de base, déjà projetée ?)."""
    out = []
    for name, rec in sorted(proj.registry.items(), key=lambda kv: kv[1].get("order", 0)):
        op = proj.doc.getObject(name)
        if op is None or rec.get("kind") not in projection.KINDS or rec.get("index_deg") not in (None, 0, 0.0):
            continue
        top = dressupmod.top_of(proj.job, op)
        projected = any(projection.is_projection(d) for d in [top] + dressupmod.dressup_chain(top))
        out.append((op, projected))
    return out


class ProjectionDialog(QtWidgets.QDialog):
    def __init__(self, proj, parent=None, op=None):
        super(ProjectionDialog, self).__init__(parent)
        theme.apply(self)
        self.proj = proj
        self.setWindowTitle(tr("Project on the part"))
        form = QtWidgets.QFormLayout(self)
        self.ops = QtWidgets.QComboBox()
        self.items = candidates(proj)
        for o, projected in self.items:
            self.ops.addItem(tr("{name} (projected)", name=o.Label) if projected else o.Label, o.Name)
        if op is not None:
            self.ops.setCurrentIndex(max(0, self.ops.findData(dressupmod.base_operation(op).Name)))
        form.addRow(tr("Operation"), self.ops)
        self.sample = QtWidgets.QDoubleSpinBox()
        self.sample.setRange(0.01, 5.0)
        self.sample.setDecimals(3)
        self.sample.setValue(projection.DEFAULT_SAMPLE)
        form.addRow(tr("Sample interval (mm)"), self.sample)
        self.tolerance = QtWidgets.QDoubleSpinBox()
        self.tolerance.setRange(0.0001, 1.0)
        self.tolerance.setDecimals(4)
        self.tolerance.setValue(projection.DEFAULT_TOLERANCE)
        form.addRow(tr("Tolerance (mm)"), self.tolerance)
        self.info = QtWidgets.QLabel()
        self.info.setWordWrap(True)
        theme.set_role(self.info, "muted")
        form.addRow(self.info)
        self.buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        form.addRow(self.buttons)
        self.ops.currentIndexChanged.connect(self._update)
        self._update()

    def _projected(self):
        i = self.ops.currentIndex()
        return self.items[i][1] if 0 <= i < len(self.items) else False

    def _update(self):
        ok = self.ops.count() > 0
        if not ok:
            self.info.setText(tr("No engraving, contour or V-carving to project: add one first (it is computed flat, its start depth standing for the part surface)."))
        elif self._projected():
            self.info.setText(tr("This operation is projected on the part: OK puts it back flat."))
        else:
            self.info.setText(tr("Each cut point goes to the part surface (OpenCamLib) minus the depth of the operation below its start depth; steps get finer where the surface bends."))
        for w in (self.sample, self.tolerance):
            w.setEnabled(ok and not self._projected())
        self.buttons.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(ok)

    def apply(self):
        op = self.proj.doc.getObject(self.ops.currentData())
        if self._projected():
            projection.remove_projection(self.proj, op)
            return None
        return projection.add_projection(self.proj, op, self.sample.value(), self.tolerance.value())
