# SPDX-License-Identifier: LGPL-2.1-or-later
"""Éditeur d'opération à onglets (Outil / Géométrie / Hauteurs / Passes / Stratégie / Filetage).

Travaille toujours sur une opération FreeCAD existante : les genres de
propriétés, les énumérations et les valeurs courantes sont lus sur l'objet
(``operations.param_kind`` / ``read_params``), les libellés, groupes et aides
viennent de ``project.paramspec``. Le dialogue est non modal pour laisser la
sélection dans la vue 3D possible (onglet Géométrie).
"""

import FreeCAD
import FreeCADGui

from .qt import QtCore, QtGui, QtWidgets
from ..i18n import tr
from ..tools import bridge
from ..project.operations import STRATEGIES, param_kind, read_params, thread_names
from ..project import paramspec
from . import state, panels


class OperationEditor(QtWidgets.QDialog):
    """Dialogue non modal ; ``on_close(accepted)`` est appelé à la fermeture."""

    def __init__(self, proj, op, parent=None, on_close=None, title=None):
        super(OperationEditor, self).__init__(parent or FreeCADGui.getMainWindow())
        self.proj = proj
        self.op = op
        self.rec = proj.registry.get(op.Name, {})
        self.kind = self.rec.get("kind", "?")
        self.on_close = on_close
        self.widgets = {}
        self.setWindowTitle(title or tr("Operation: {name}", name=op.Label))
        self.setMinimumWidth(560)
        self._build()

    # -- construction ----------------------------------------------------------

    def _build(self):
        lay = QtWidgets.QVBoxLayout(self)
        head = QtWidgets.QFormLayout()
        self.name = QtWidgets.QLineEdit(self.op.Label)
        head.addRow(tr("Name"), self.name)
        meta = STRATEGIES.get(self.kind, {"label": self.kind, "limits": ""})
        strategy = QtWidgets.QLabel("<b>%s</b>" % tr(meta["label"]))
        head.addRow(tr("Strategy"), strategy)
        if meta.get("limits"):
            limits = QtWidgets.QLabel(tr(meta["limits"]))
            limits.setWordWrap(True)
            limits.setStyleSheet("color: #9aa7b8;")
            head.addRow(tr("Known limits"), limits)
        lay.addLayout(head)

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(self._tool_tab(), tr("Tool"))
        self.tabs.addTab(self._geometry_tab(), tr("Geometry"))
        names = list(meta.get("params", ()))
        by_group = {}
        for n in names:
            if n not in self.op.PropertiesList:
                continue
            _label, group, _help = paramspec.spec(n)
            by_group.setdefault(group, []).append(n)
        for key, label in paramspec.GROUPS:
            if by_group.get(key):
                self.tabs.addTab(self._params_tab(by_group[key]), tr(label))
        lay.addWidget(self.tabs)

        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Apply
                                             | QtWidgets.QDialogButtonBox.Cancel)
        buttons.button(QtWidgets.QDialogButtonBox.Apply).clicked.connect(self.apply)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _tool_tab(self):
        w = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(w)
        lib = self.proj.library
        tool = lib.tools.get(self.rec.get("tool_id"))
        asm = lib.assemblies.get(self.rec.get("assembly_id"))
        values = self.rec.get("values", {})
        form.addRow(tr("Tool assembly"), QtWidgets.QLabel(
            "T%d - %s" % (asm.output.tool_number, asm.name) if asm else tr("(unknown)")))
        if tool:
            form.addRow(tr("Cutter"), QtWidgets.QLabel("%s - %s, D %.3g mm, %d %s" % (
                tool.name, tr(tool.type_label()), tool.geometry.diameter, tool.flute_count, tr("flutes"))))
        form.addRow(tr("Cutting preset"), QtWidgets.QLabel(values.get("preset_name", tr("(unknown)"))))
        if values:
            grid = QtWidgets.QGridLayout()
            rows = (
                (tr("Spindle speed"), "%.0f rpm" % values["spindle_rpm"]),
                (tr("Surface speed"), "%.1f m/min" % values["surface_speed_m_min"]),
                (tr("Cutting feed"), "%.0f mm/min" % values["feed_mm_min"]),
                (tr("Feed per tooth"), "%.4f mm" % values["feed_per_tooth_mm"]),
                (tr("Plunge feed"), "%.0f mm/min" % values["plunge_feed_mm_min"]),
                (tr("Axial / radial engagement"), "%.2f / %.2f mm" % (values["axial_engagement_mm"], values["radial_engagement_mm"])),
            )
            for i, (k, v) in enumerate(rows):
                grid.addWidget(QtWidgets.QLabel(k), i, 0)
                grid.addWidget(QtWidgets.QLabel("<b>%s</b>" % v), i, 1)
            box = QtWidgets.QGroupBox(tr("Values used by this operation (copied from the preset)"))
            box.setLayout(grid)
            form.addRow(box)
        tc = getattr(self.op, "ToolController", None)
        if tc is not None:
            v = bridge.tool_controller_values(tc)
            form.addRow(tr("Tool controller"), QtWidgets.QLabel("%s (T%d, F%.0f, S%.0f)" % (
                tc.Label, v["tool_number"], v["feed_mm_min"], v["spindle_rpm"])))
        note = QtWidgets.QLabel(tr("To use another tool or preset, create a new operation: the values above are frozen at creation time so that library changes never alter an existing operation."))
        note.setWordWrap(True)
        note.setStyleSheet("color: #9aa7b8;")
        form.addRow(note)
        return w

    def _geometry_tab(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        hint = QtWidgets.QLabel(tr("Faces, edges or vertices of the model the operation works on. Select them in the 3D view, then use the buttons below. No geometry = whole model."))
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.base_list = QtWidgets.QListWidget()
        lay.addWidget(self.base_list)
        row = QtWidgets.QHBoxLayout()
        b_replace = QtWidgets.QPushButton(tr("Use the 3D selection"))
        b_add = QtWidgets.QPushButton(tr("Add the 3D selection"))
        b_clear = QtWidgets.QPushButton(tr("Whole model"))
        b_replace.clicked.connect(lambda: self._take_selection(replace=True))
        b_add.clicked.connect(lambda: self._take_selection(replace=False))
        b_clear.clicked.connect(self._clear_base)
        for b in (b_replace, b_add, b_clear):
            row.addWidget(b)
        lay.addLayout(row)
        self._base = [(obj, list(subs)) for obj, subs in (self.op.Base or [])]
        self._refresh_base_list()
        return w

    def _refresh_base_list(self):
        self.base_list.clear()
        if not self._base:
            self.base_list.addItem(tr("(whole model)"))
        for obj, subs in self._base:
            self.base_list.addItem("%s: %s" % (obj.Label, " ".join(subs) or tr("whole")))

    def _take_selection(self, replace):
        picked = []
        for s in FreeCADGui.Selection.getSelectionEx():
            if s.Object.Document.Name == self.proj.doc.Name and getattr(s.Object, "Shape", None):
                picked.append((s.Object, list(s.SubElementNames)))
        if not picked:
            self.status.setText(tr("Nothing selected in the 3D view."))
            return
        self._base = picked if replace else self._base + picked
        self._refresh_base_list()
        self.status.setText("")

    def _clear_base(self):
        self._base = []
        self._refresh_base_list()

    def _params_tab(self, names):
        w = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(w)
        current = read_params(self.op, names)
        for n in names:
            label, _group, help_text = paramspec.spec(n)
            kind, choices = param_kind(self.op, n)
            widget = self._make_widget(n, kind, choices, current.get(n))
            if widget is None:
                continue
            if help_text:
                widget.setToolTip(tr(help_text))
            lbl = QtWidgets.QLabel(tr(label))
            lbl.setToolTip(tr(help_text) if help_text else "")
            form.addRow(lbl, widget)
            self.widgets[n] = (kind, widget)
        return w

    def _make_widget(self, name, kind, choices, value):
        if name == "ThreadName" and self.kind == "threadmill":
            w = QtWidgets.QComboBox()
            w.setEditable(True)
            try:
                w.addItems(thread_names(getattr(self.op, "ThreadType", "MetricInternal6H")))
            except Exception:
                pass
            w.setCurrentText(value or "")
            return w
        if kind in ("length", "angle", "float"):
            w = QtWidgets.QDoubleSpinBox()
            w.setRange(-100000, 100000)
            w.setDecimals(3 if kind != "float" else 4)
            w.setSuffix(" mm" if kind == "length" else (" °" if kind == "angle" else ""))
            w.setValue(float(value or 0.0))
            return w
        if kind == "percent":
            w = QtWidgets.QSpinBox()
            w.setRange(0, 100)
            w.setSuffix(" %")
            w.setValue(int(value or 0))
            return w
        if kind == "int":
            w = QtWidgets.QSpinBox()
            w.setRange(-100000, 100000)
            w.setValue(int(value or 0))
            return w
        if kind == "bool":
            w = QtWidgets.QCheckBox()
            w.setChecked(bool(value))
            return w
        if kind == "enum":
            w = QtWidgets.QComboBox()
            for c in choices:
                w.addItem(tr(c), c)
            if value in choices:
                w.setCurrentIndex(list(choices).index(value))
            return w
        if kind == "string":
            return QtWidgets.QLineEdit(value or "")
        return None

    # -- lecture / application -------------------------------------------------

    def params(self):
        out = {}
        for n, (kind, w) in self.widgets.items():
            if isinstance(w, QtWidgets.QComboBox):
                data = w.currentData()
                out[n] = data if data is not None else w.currentText()
            elif isinstance(w, QtWidgets.QCheckBox):
                out[n] = w.isChecked()
            elif isinstance(w, (QtWidgets.QDoubleSpinBox, QtWidgets.QSpinBox)):
                out[n] = w.value()
            elif isinstance(w, QtWidgets.QLineEdit):
                out[n] = w.text()
        return out

    def apply(self):
        try:
            label = self.name.text().strip()
            if label:
                self.op.Label = label
            self.proj.set_operation_base(self.op, self._base)
            ignored = self.proj.update_operation(self.op, self.params())
            results = self.proj.compute()
            mine = [r for r in results if r["name"] == self.op.Label]
            summary = mine[0] if mine else None
        except Exception as exc:
            self.status.setText("<span style='color:#e06060'>%s</span>" % tr("Operation failed: {error}", error=str(exc)))
            return False
        text = []
        if summary:
            text.append(tr("{n} commands, {length:.0f} mm, Z {zmin:.2f} to {zmax:.2f}",
                           n=summary["commands"], length=summary["length_mm"],
                           zmin=summary["zmin"] or 0.0, zmax=summary["zmax"] or 0.0))
            if not summary["valid"] or summary["commands"] == 0:
                text.append(tr("No valid toolpath: check the geometry and the depths."))
        if ignored:
            text.append(tr("Ignored parameters: {p}", p=", ".join(ignored)))
        self.status.setText("<br>".join(text))
        panels.refresh_project_panel()
        return True

    def accept(self):
        if self.apply():
            super(OperationEditor, self).accept()
            self._finish(True)

    def reject(self):
        super(OperationEditor, self).reject()
        self._finish(False)

    def _finish(self, accepted):
        cb, self.on_close = self.on_close, None
        if cb:
            cb(accepted)


_open_editors = []


def open_editor(proj, op, on_close=None, title=None):
    """Ouvre (non modal) l'éditeur de l'opération ``op`` et le retourne."""
    dlg = OperationEditor(proj, op, on_close=on_close, title=title)
    _open_editors.append(dlg)
    dlg.finished.connect(lambda _r: _open_editors.remove(dlg) if dlg in _open_editors else None)
    dlg.show()
    dlg.raise_()
    return dlg
