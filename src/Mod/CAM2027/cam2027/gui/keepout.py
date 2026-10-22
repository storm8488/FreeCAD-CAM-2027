# SPDX-License-Identifier: LGPL-2.1-or-later
"""Dialogue des zones interdites : liste, ajout d'une boîte (vue de dessus + hauteur), brides évitées, marge."""

from ..i18n import tr
from ..project import keepout
from . import theme
from .qt import QtCore, QtWidgets


def _spin(lo, hi, value, decimals=2):
    s = QtWidgets.QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(decimals)
    s.setValue(value)
    return s


class KeepOutDialog(QtWidgets.QDialog):
    def __init__(self, proj, parent=None):
        super(KeepOutDialog, self).__init__(parent)
        theme.apply(self)
        self.proj = proj
        self.setWindowTitle(tr("Keep-out zones"))
        self.pending = []  # zones à créer : (xmin, ymin, xmax, ymax, ztop)
        self.removed = []
        lay = QtWidgets.QVBoxLayout(self)
        self.table = QtWidgets.QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels([tr("Zone"), tr("X Y (mm)"), tr("Top Z (mm)")])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setMinimumHeight(120)
        lay.addWidget(self.table)
        remove = QtWidgets.QPushButton(tr("Remove the selected zone"))
        theme.set_role(remove, "danger")
        remove.clicked.connect(self._remove)
        lay.addWidget(remove)
        box = QtWidgets.QGroupBox(tr("New zone (box seen from above)"))
        form = QtWidgets.QFormLayout(box)
        sb = proj.stock_bounds()
        self.xmin = _spin(-10000, 10000, sb["xmin"])
        self.xmax = _spin(-10000, 10000, sb["xmin"] + min(20.0, sb["length"]))
        self.ymin = _spin(-10000, 10000, sb["ymin"])
        self.ymax = _spin(-10000, 10000, sb["ymax"])
        self.ztop = _spin(-1000, 1000, sb["zmax"] + 10.0)
        form.addRow(tr("X from (mm)"), self.xmin)
        form.addRow(tr("X to (mm)"), self.xmax)
        form.addRow(tr("Y from (mm)"), self.ymin)
        form.addRow(tr("Y to (mm)"), self.ymax)
        form.addRow(tr("Top Z (mm)"), self.ztop)
        add = QtWidgets.QPushButton(tr("Add zone"))
        add.clicked.connect(self._add)
        form.addRow(add)
        lay.addWidget(box)
        opts = QtWidgets.QFormLayout()
        margin, avoid = keepout.settings(proj.doc)
        self.avoid_clamps = QtWidgets.QCheckBox(tr("Rapid moves also avoid the clamps"))
        self.avoid_clamps.setChecked(avoid or keepout._group(proj.doc) is None)  # nouveau réglage : oui
        self.margin = _spin(0.0, 100.0, margin, 1)
        opts.addRow("", self.avoid_clamps)
        opts.addRow(tr("Clearance above and around a zone (mm)"), self.margin)
        lay.addLayout(opts)
        hint = QtWidgets.QLabel(tr("Rapid moves that would pass over a zone lower than its top + clearance go up, across and down again; the cuts are never changed: a cut that enters a zone blocks the export, with its position."))
        hint.setWordWrap(True)
        theme.set_role(hint, "muted")
        lay.addWidget(hint)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._fill()

    def _fill(self):
        self.table.setRowCount(0)
        rows = [(z.Label, z.Shape.BoundBox, z) for z in keepout.zones(self.proj.doc) if z not in self.removed]
        rows += [(tr("(new)"), r, None) for r in self.pending]
        for label, bb, obj in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            if obj is None:
                xmin, ymin, xmax, ymax, ztop = bb
            else:
                xmin, ymin, xmax, ymax, ztop = bb.XMin, bb.YMin, bb.XMax, bb.YMax, bb.ZMax
            item = QtWidgets.QTableWidgetItem(label)
            item.setData(QtCore.Qt.UserRole, obj.Name if obj is not None else "#%d" % (r,))
            self.table.setItem(r, 0, item)
            self.table.setItem(r, 1, QtWidgets.QTableWidgetItem("X %.1f..%.1f  Y %.1f..%.1f" % (xmin, xmax, ymin, ymax)))
            self.table.setItem(r, 2, QtWidgets.QTableWidgetItem("%.2f" % ztop))

    def _add(self):
        x0, x1 = sorted((self.xmin.value(), self.xmax.value()))
        y0, y1 = sorted((self.ymin.value(), self.ymax.value()))
        if x1 - x0 < 0.01 or y1 - y0 < 0.01:
            return
        self.pending.append((x0, y0, x1, y1, self.ztop.value()))
        self._fill()

    def _remove(self):
        row = self.table.currentRow()
        if row < 0:
            return
        key = self.table.item(row, 0).data(QtCore.Qt.UserRole)
        if key.startswith("#"):
            existing = len([z for z in keepout.zones(self.proj.doc) if z not in self.removed])
            del self.pending[int(key[1:]) - existing]
        else:
            self.removed.append(self.proj.doc.getObject(key))
        self._fill()

    def apply(self):
        doc = self.proj.doc
        keepout.configure(doc, margin=self.margin.value(), avoid_clamps=self.avoid_clamps.isChecked())
        for obj in self.removed:
            keepout.remove_zone(doc, obj)
        for xmin, ymin, xmax, ymax, ztop in self.pending:
            keepout.add_zone(doc, xmin, ymin, xmax, ymax, ztop)
        return len(keepout.zones(doc))
