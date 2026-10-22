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
from ..i18n import tr, tr_msg
from .labels import preset_label
from ..tools import bridge
from ..project.operations import STRATEGIES, param_kind, read_params, thread_names
from ..project import paramspec, undo
from ..project import leads as _leads
from . import state, panels, theme


_DRESSUP_KINDS = ("profile", "pocket", "adaptive", "slot", "millface")
_DRESSUP_CHOICES = {
    "Method": ("RampMethod1", "RampMethod2", "RampMethod3", "Helix"),
    "RampFeedRate": ("Horizontal Feed Rate", "Vertical Feed Rate", "Ramp Feed Rate", "Custom"),
    "Style": ("Dogbone", "T-bone horizontal", "T-bone vertical", "T-bone long edge", "T-bone short edge"),
    "Side": ("Left", "Right"),
    "Incision": ("adaptive", "fixed", "custom"),
    "StyleIn": _leads.styles(),
    "StyleOut": _leads.styles(),
}
_DRESSUP_LABELS = {
    "Style": "Bone style",
    "Side": "Side of the path",
    "Incision": "Bone length",
    "Custom": "Custom length",
    "Width": "Tag width",
    "Height": "Tag height",
    "Angle": "Angle",
    "Radius": "Fillet radius",
    "Method": "Ramp method",
    "RampFeedRate": "Ramp feed rate",
    "UseStartDepth": "Only below a start depth",
    "DressupStartDepth": "Ramp start depth",
    "StyleIn": "Lead-in style",
    "RadiusIn": "Lead-in radius",
    "AngleIn": "Lead-in sweep angle",
    "StyleOut": "Lead-out style",
    "RadiusOut": "Lead-out radius",
    "AngleOut": "Lead-out sweep angle",
}


def _scrolled(widget):
    """Onglet dans une zone défilante : la boîte reste à la taille de l'écran (150 %, 200 %)."""
    area = QtWidgets.QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QtWidgets.QFrame.NoFrame)
    area.setWidget(widget)
    return area


class _VectorWidget(QtWidgets.QWidget):
    """Trois champs X / Y / Z en mm pour une propriété vecteur."""

    def __init__(self, value=None, parent=None):
        super(_VectorWidget, self).__init__(parent)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.boxes = []
        for i, axis in enumerate(("X", "Y", "Z")):
            lay.addWidget(QtWidgets.QLabel(axis))
            box = QtWidgets.QDoubleSpinBox()
            box.setRange(-100000, 100000)
            box.setDecimals(3)
            box.setValue(float(value[i]) if value else 0.0)
            lay.addWidget(box)
            self.boxes.append(box)

    def value(self):
        return tuple(b.value() for b in self.boxes)


class OperationEditor(QtWidgets.QDialog):
    """Dialogue non modal ; ``on_close(accepted)`` est appelé à la fermeture."""

    def __init__(self, proj, op, parent=None, on_close=None, title=None):
        super(OperationEditor, self).__init__(parent or FreeCADGui.getMainWindow())
        self.proj = proj
        self.op = op
        self.op_key = (proj.doc.Name, op.Name)  # lisible même quand l'objet n'existe plus
        self.rec = proj.registry.get(op.Name, {})
        self.kind = self.rec.get("kind", "?")
        self.on_close = on_close
        self.widgets = {}
        self.setWindowTitle(title or tr("Operation: {name}", name=op.Label))
        self.setMinimumWidth(720)
        self._build()
        theme.apply(self)
        self._snapshot = self._current_state()
        # clavier : Ctrl+Entrée = OK ; le nom a le focus à l'ouverture
        shortcut_cls = getattr(QtGui, "QShortcut", None) or QtWidgets.QShortcut  # Qt6 : QtGui, Qt5 : QtWidgets
        self._shortcuts = []
        for seq in ("Ctrl+Return", "Ctrl+Enter"):
            sc = shortcut_cls(QtGui.QKeySequence(seq), self)
            sc.activated.connect(self.accept)
            self._shortcuts.append(sc)
        self.name.setFocus()
        self.name.selectAll()
        # jamais plus haut que 85 % de l'écran disponible (mise à l'échelle 150 / 200 %)
        screen = self.screen() if hasattr(self, "screen") else None
        if screen is None:
            screen = QtWidgets.QApplication.primaryScreen()
        if screen is not None:
            limit = int(screen.availableGeometry().height() * 0.85)
            self.resize(max(self.minimumWidth(), self.sizeHint().width()), min(self.sizeHint().height(), limit))

    # -- construction ----------------------------------------------------------

    def _build(self):
        lay = QtWidgets.QVBoxLayout(self)
        head = QtWidgets.QFormLayout()
        self.name = QtWidgets.QLineEdit(self.op.Label)
        head.addRow(tr("Name"), self.name)
        meta = STRATEGIES.get(self.kind, {"label": extra_label(self.kind), "limits": ""})
        strategy = QtWidgets.QLabel("<b>%s</b>" % tr(meta["label"]))
        head.addRow(tr("Strategy"), strategy)
        self.index = QtWidgets.QDoubleSpinBox()
        self.index.setRange(-361.0, 360.0)
        self.index.setDecimals(3)
        self.index.setSuffix(" °")
        self.index.setSpecialValueText(tr("(none: 3 axes)"))
        current = self.rec.get("index_deg")
        self.index.setValue(self.index.minimum() if current is None else float(current))
        self.index.setToolTip(tr("Indexed 4th axis: the part is turned to this A angle, then machined in 3 axes. Select the faces or edges on the part as it is shown."))
        if self.proj.machine.rotary.present or current is not None:
            head.addRow(tr("A index (deg)"), self.index)
        else:
            self.index.setVisible(False)
        if meta.get("limits"):
            limits = QtWidgets.QLabel(tr(meta["limits"]))
            limits.setWordWrap(True)
            limits.setProperty("role", "muted")
            head.addRow(tr("Known limits"), limits)
        lay.addLayout(head)

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(_scrolled(self._tool_tab()), tr("Tool"))
        self.tabs.addTab(_scrolled(self._geometry_tab()), tr("Geometry"))
        names = list(meta.get("params", ()))
        by_group = {}
        for n in names:
            if n not in self.op.PropertiesList:
                continue
            _label, group, _help = paramspec.spec(n)
            by_group.setdefault(group, []).append(n)
        for key, label in paramspec.GROUPS:
            if by_group.get(key):
                self.tabs.addTab(_scrolled(self._params_tab(by_group[key])), tr(label))
        self.dressup_boxes = {}
        if self.kind in _DRESSUP_KINDS:
            self.tabs.addTab(_scrolled(self._dressup_tab()), tr("Entry, exit & tabs"))
        from . import restlimit

        self.rest_limit = restlimit.add_tab(self)  # reprise de matière, limiter à une zone
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
        from .toolpicker import ToolField

        # comme Fusion : Sélectionner… (bibliothèque) / Éditer…, outils du document en liste déroulante
        self.asm_combo = ToolField(self.proj, self.rec.get("kind"))
        self.asm_combo.set_assembly(self.rec.get("assembly_id"))
        form.addRow(tr("Tool"), self.asm_combo)
        self.cutter_label = QtWidgets.QLabel()
        self.cutter_label.setWordWrap(True)
        form.addRow(tr("Cutter"), self.cutter_label)
        self.preset_combo = QtWidgets.QComboBox()
        form.addRow(tr("Cutting preset"), self.preset_combo)
        self.values_grid = QtWidgets.QGridLayout()
        box = QtWidgets.QGroupBox(tr("Values used by this operation (copied from the preset)"))
        box.setLayout(self.values_grid)
        form.addRow(box)
        tc = getattr(self.op, "ToolController", None)
        if tc is not None:
            v = bridge.tool_controller_values(tc)
            form.addRow(tr("Tool controller"), QtWidgets.QLabel("%s (T%d, F%.0f, S%.0f)" % (
                tc.Label, v["tool_number"], v["feed_mm_min"], v["spindle_rpm"])))
        note = QtWidgets.QLabel(tr("Values are frozen at creation time: a later change of the library never alters this operation. Choosing another tool or preset here and applying copies the new values (another cutter replaces the tool controller; strategy settings are kept)."))
        note.setWordWrap(True)
        note.setProperty("role", "muted")
        form.addRow(note)
        self.asm_combo.changed.connect(self._fill_presets)
        self.preset_combo.currentIndexChanged.connect(lambda _i: self._show_values())
        self._fill_presets(select=self.rec.get("preset_id"))
        return w

    def _fill_presets(self, select=None):
        lib = self.proj.library
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        asm_id = self.asm_combo.currentData()
        tool = lib.tool(lib.assembly(asm_id).tool_id) if asm_id else None
        if tool is not None:
            self.cutter_label.setText("%s - %s, D %.3g mm, %d %s" % (
                tool.name, tr(tool.type_label()), tool.geometry.diameter, tool.flute_count, tr("flutes")))
            for p in tool.presets:
                self.preset_combo.addItem(preset_label(p), p.id)
            idx = self.preset_combo.findData(select) if select else -1
            self.preset_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.preset_combo.blockSignals(False)
        self._show_values()

    def _show_values(self):
        while self.values_grid.count():
            item = self.values_grid.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        lib = self.proj.library
        asm_id, preset_id = self.asm_combo.currentData(), self.preset_combo.currentData()
        if not asm_id or not preset_id:
            return
        tool = lib.tool(lib.assembly(asm_id).tool_id)
        try:
            values = tool.preset(preset_id).resolve(tool)
        except (KeyError, ValueError) as exc:
            self.values_grid.addWidget(QtWidgets.QLabel(tr_msg(exc)), 0, 0)
            return
        rows = (
            (tr("Spindle speed"), "%.0f rpm" % values["spindle_rpm"]),
            (tr("Surface speed"), "%.1f m/min" % values["surface_speed_m_min"]),
            (tr("Cutting feed"), "%.0f mm/min" % values["feed_mm_min"]),
            (tr("Feed per tooth"), "%.4f mm" % values["feed_per_tooth_mm"]),
            (tr("Plunge feed"), "%.0f mm/min" % values["plunge_feed_mm_min"]),
            (tr("Axial / radial engagement"), "%.2f / %.2f mm" % (values["axial_engagement_mm"], values["radial_engagement_mm"])),
        )
        for i, (k, v) in enumerate(rows):
            self.values_grid.addWidget(QtWidgets.QLabel(k), i, 0)
            self.values_grid.addWidget(QtWidgets.QLabel("<b>%s</b>" % v), i, 1)

    def _apply_tool(self):
        asm_id, preset_id = self.asm_combo.currentData(), self.preset_combo.currentData()
        if asm_id and preset_id and (asm_id, preset_id) != (self.rec.get("assembly_id"), self.rec.get("preset_id")):
            self.rec = self.proj.change_operation_tool(self.op, asm_id, preset_id)

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
        if "Base" not in self.op.PropertiesList:
            # opération générée par sa commande (angles vifs du V-carving...) : pas de géométrie à choisir ici
            self._base = None
            hint.setText(tr("This operation is generated by its command: it has no geometry to choose here."))
            for b in (b_replace, b_add, b_clear):
                b.setEnabled(False)
            self.base_list.setVisible(False)
            return w
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
        if kind == "vector":
            return _VectorWidget(value)
        return None

    def _dressup_tab(self):
        from ..project import dressups as dressupmod

        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        info = QtWidgets.QLabel(tr("Dressups transform the computed toolpath: holding tags keep the part attached to the stock on a profile cut, a ramp entry replaces vertical plunges. 0 = FreeCAD default value."))
        info.setWordWrap(True)
        lay.addWidget(info)
        existing = {dressupmod.dressup_kind(d): d for d in self.proj.dressups(self.op)}
        for key in ("tags", "ramp", "dogbone", "leads"):
            if key == "tags" and self.kind != "profile":
                continue
            if key == "leads" and self.kind not in ("profile", "slot"):
                continue
            if key == "dogbone" and self.kind not in ("profile", "pocket", "adaptive"):
                continue
            meta = dressupmod.DRESSUPS[key]
            box = QtWidgets.QGroupBox(tr(meta["label"]))
            box.setCheckable(True)
            box.setChecked(key in existing)
            form = QtWidgets.QFormLayout(box)
            limits = QtWidgets.QLabel(tr(meta["limits"]))
            limits.setWordWrap(True)
            limits.setProperty("role", "muted")
            form.addRow(limits)
            widgets = {}
            values = dressupmod.dressup_params(existing[key]) if key in existing else {}
            if key == "tags":
                count = QtWidgets.QSpinBox()
                count.setRange(0, 50)
                count.setValue(int(values.get("Count", 4)))
                form.addRow(tr("Number of tags"), count)
                widgets["Count"] = ("int", count)
            for name, pkind in meta["params"]:
                widget = self._make_widget(name, pkind, _DRESSUP_CHOICES.get(name, ()), values.get(name))
                if widget is None:
                    continue
                if pkind in ("length", "angle"):
                    widget.setRange(0, 10000)
                    widget.setSpecialValueText(tr("(automatic)"))
                    widget.setValue(float(values.get(name) or 0.0))
                form.addRow(tr(_DRESSUP_LABELS.get(name, name)), widget)
                widgets[name] = (pkind, widget)
            lay.addWidget(box)
            self.dressup_boxes[key] = (box, widgets)
        lay.addStretch(1)
        return w

    def _apply_dressups(self):
        from ..project import dressups as dressupmod

        existing = {dressupmod.dressup_kind(d): d for d in self.proj.dressups(self.op)}
        for key, (box, widgets) in self.dressup_boxes.items():
            wanted = box.isChecked()
            vals = self._widget_values(widgets)
            count = vals.pop("Count", None)
            params = {k: v for k, v in vals.items()
                      if not (isinstance(v, float) and v == 0.0)}  # 0 = valeur par défaut FreeCAD
            if wanted and key not in existing:
                self.proj.add_dressup(self.op, key, params=params or None, count=count)
            elif wanted:
                obj = existing[key]
                dressupmod.set_dressup_params(obj, params)
                if key == "tags" and count is not None and (count != len(obj.Positions) or params):
                    obj.Proxy.generateTags(obj, int(count))
            elif key in existing:
                self.proj.remove_dressup(self.op, key)

    # -- lecture / application -------------------------------------------------

    def params(self):
        return self._widget_values(self.widgets)

    @staticmethod
    def _widget_values(widgets):
        out = {}
        for n, (kind, w) in widgets.items():
            if isinstance(w, _VectorWidget):
                out[n] = w.value()
            elif isinstance(w, QtWidgets.QComboBox):
                data = w.currentData()
                out[n] = data if data is not None else w.currentText()
            elif isinstance(w, QtWidgets.QCheckBox):
                out[n] = w.isChecked()
            elif isinstance(w, (QtWidgets.QDoubleSpinBox, QtWidgets.QSpinBox)):
                out[n] = w.value()
            elif isinstance(w, QtWidgets.QLineEdit):
                out[n] = w.text()
        return out

    def _apply(self):
        with undo.transaction(self.proj.doc, tr("Edit the operation")):
            return self._apply_changes()

    def _apply_changes(self):
        try:
            label = self.name.text().strip()
            if label:
                self.op.Label = label
            if self._base is not None:
                self.proj.set_operation_base(self.op, self._base)
            self._apply_tool()
            wanted = self.index.value() if self.index.value() > self.index.minimum() else None
            if wanted != self.rec.get("index_deg"):
                self.proj.set_operation_index(self.op, wanted)
                self.rec = self.proj.registry.get(self.op.Name, self.rec)
                self._base = [(o, list(subs)) for o, subs in (self.op.Base or [])]
                self._refresh_base_list()
            ignored = self.proj.update_operation(self.op, self.params())
            self._apply_dressups()
            if self.rest_limit is not None:
                self.rest_limit.apply()
            from .commands import busy

            with busy(tr("Computing the toolpaths..."), stoppable=self.proj):
                self.proj.compute()
            from ..project import dressups as dressupmod
            from ..project.operations import toolpath_summary

            top = dressupmod.top_of(self.proj.job, self.op)
            summary = toolpath_summary(top)
            summary["valid"] = top.isValid()
        except Exception as exc:
            self.status.setText("<span style='color:%s'>%s</span>" % (theme.status_color("error"), tr("Operation failed: {error}", error=tr_msg(exc))))
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

    def _current_state(self):
        """Valeurs affichées (nom, outil, géométrie, paramètres, habillages) pour détecter une modification non appliquée."""
        dressups = {}
        for key, (box, widgets) in getattr(self, "dressup_boxes", {}).items():
            dressups[key] = (box.isChecked(), tuple(sorted(self._widget_values(widgets).items())))
        return (self.name.text(), self.index.value(), self.asm_combo.currentData(), self.preset_combo.currentData(),
                tuple((o.Name, tuple(subs)) for o, subs in (self._base or ())),
                tuple(sorted((k, repr(v)) for k, v in self.params().items())), tuple(sorted(dressups.items())),
                self.rest_limit.state() if getattr(self, "rest_limit", None) is not None else None)

    def has_unsaved_changes(self):
        return self._current_state() != self._snapshot

    def apply(self):
        ok = self._apply()
        if ok:
            self._snapshot = self._current_state()
        return ok

    def accept(self):
        if not self.has_unsaved_changes() or self.apply():  # rien à appliquer : pas d'étape d'annulation vide
            super(OperationEditor, self).accept()
            self._finish(True)

    def reject(self):
        # Échap / Annuler : ne pas perdre en silence des modifications non appliquées
        if self.has_unsaved_changes():
            answer = QtWidgets.QMessageBox.question(
                self, "CAM2027", tr("Discard the changes that were not applied?"),
                QtWidgets.QMessageBox.Discard | QtWidgets.QMessageBox.Cancel, QtWidgets.QMessageBox.Cancel)
            if answer != QtWidgets.QMessageBox.Discard:
                return
        super(OperationEditor, self).reject()
        self._finish(False)

    def _finish(self, accepted):
        cb, self.on_close = self.on_close, None
        if cb:
            cb(accepted)
        self.deleteLater()  # non modal, enfant de la fenêtre principale : sinon gardé jusqu'à la fin de la session


def extra_label(kind):
    """Libellé (anglais, traduit par ``tr``) d'une opération CAM2027 hors des stratégies : sinon l'identifiant
    interne (``vcarve_corners``...) s'affichait."""
    from ..project import inlay, probe, wrap
    from ..project.bitmap import KIND_LABELS

    labels = dict(KIND_LABELS, **{inlay.CORNERS_KIND: inlay.CORNERS_LABEL, wrap.KIND: wrap.LABEL,
                                  probe.KIND: "Probe the origin"})
    return labels.get(kind, kind)


_open_editors = []
_observer = None


class _DocumentObserver(object):
    """Ferme les éditeurs d'un document qui se ferme, et celui d'une opération qui disparaît (Ctrl+Z juste après
    l'ajout, suppression) : OK sur l'opération retirée donnait « Access violation »."""

    def slotDeletedObject(self, obj):
        try:
            key = (obj.Document.Name, obj.Name)
        except Exception:
            return
        for ed in list(_open_editors):
            if getattr(ed, "op_key", None) == key:
                QtCore.QTimer.singleShot(0, lambda ed=ed: _close_orphan(ed))

    def slotUndoDocument(self, doc):
        # l'annulation retire l'objet sans signaler sa suppression
        for ed in list(_open_editors):
            if getattr(ed, "op_key", (None,))[0] == doc.Name:
                QtCore.QTimer.singleShot(0, lambda ed=ed: _close_orphan(ed))

    def slotDeletedDocument(self, doc):
        for ed in list(_open_editors):
            try:
                same = ed.proj.doc.Name == doc.Name
            except Exception:
                same = True  # objets déjà détruits
            if same:
                ed.on_close = None
                _open_editors.remove(ed)
                try:
                    ed.done(0)
                    ed.deleteLater()
                except RuntimeError:
                    pass


def _close_orphan(ed):
    """Éditeur dont l'opération a été retirée du document : fermé sans rien appliquer ni rappeler ``on_close``
    (l'ajout est déjà annulé). Rien si l'opération est revenue entre-temps (Ctrl+Y)."""
    if ed not in _open_editors:
        return
    doc = FreeCAD.getDocument(ed.op_key[0]) if ed.op_key[0] in FreeCAD.listDocuments() else None
    if doc is not None and doc.getObject(ed.op_key[1]) is not None:
        return
    ed.on_close = None
    _open_editors.remove(ed)
    try:
        ed.done(0)
        ed.deleteLater()
    except RuntimeError:
        pass


def open_editor(proj, op, on_close=None, title=None):
    """Ouvre (non modal) l'éditeur de l'opération ``op`` et le retourne."""
    global _observer
    if _observer is None:
        _observer = _DocumentObserver()
        FreeCAD.addDocumentObserver(_observer)
    dlg = OperationEditor(proj, op, on_close=on_close, title=title)
    _open_editors.append(dlg)
    dlg.finished.connect(lambda _r: _open_editors.remove(dlg) if dlg in _open_editors else None)
    dlg.show()
    dlg.raise_()
    return dlg
