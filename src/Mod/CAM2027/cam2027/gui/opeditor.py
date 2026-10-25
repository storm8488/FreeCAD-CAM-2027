# SPDX-License-Identifier: LGPL-2.1-or-later
"""Éditeur d'opération : une page du panneau contextuel, en sections dépliables dans l'ordre du métier.

1. géométrie ciblée (résumé, surbrillance dans la vue) ; 2. outil et préréglage ; 3. profondeurs, passes,
surépaisseur ; 4. avances et vitesses ; 5. entrées, sorties, dégagements, attaches ; 6. réglages spécialisés de
la stratégie (section repliée) ; 7. filetage ; 8. reprise et zone. Un bandeau garde visibles le diamètre, la
broche, les avances, la profondeur finale, la passe axiale et les hauteurs de sécurité ; un résumé concret
précède le calcul (« 2 contours — fraise Ø 6 mm — profondeur 8 mm — passes 2 mm »).

Travaille toujours sur une opération FreeCAD existante : les genres de propriétés, les énumérations et les
valeurs courantes sont lus sur l'objet (``operations.param_kind`` / ``read_params``), les libellés, groupes et
aides viennent de ``project.paramspec``. La même page sert à la création (ouverte juste après « Ajouter une
opération ») et à la modification. ``tabs`` reste une façade sur les sections (scripts et scénarios).
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
from .inspector import Page


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

#: paramètres toujours visibles dans le bandeau (nom FreeCAD -> libellé court)
_KEY_PARAMS = (("FinalDepth", "Depth"), ("StepDown", "Step down"), ("SafeHeight", "Safe"), ("ClearanceHeight", "Clearance"))


class Section(QtWidgets.QWidget):
    """Section dépliable : en-tête (flèche + titre) et corps."""

    def __init__(self, title, body, expanded=True, parent=None):
        super(Section, self).__init__(parent)
        self.title_text = title
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.header = QtWidgets.QToolButton()
        self.header.setObjectName("sectionHeader")
        self.header.setText(title)
        self.header.setCheckable(True)
        self.header.setChecked(expanded)
        self.header.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.header.setArrowType(QtCore.Qt.DownArrow if expanded else QtCore.Qt.RightArrow)
        self.header.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.header.toggled.connect(self._toggled)
        lay.addWidget(self.header)
        self.body = body
        body.setContentsMargins(8, 4, 8, 8)
        body.setVisible(expanded)
        lay.addWidget(body)

    def _toggled(self, on):
        self.header.setArrowType(QtCore.Qt.DownArrow if on else QtCore.Qt.RightArrow)
        self.body.setVisible(on)

    def set_expanded(self, on):
        self.header.setChecked(bool(on))

    def expanded(self):
        return self.header.isChecked()


class _Sections(object):
    """Façade « onglets » sur les sections : ``count`` / ``tabText`` / ``setCurrentIndex`` / ``currentWidget`` /
    ``addTab`` comme un ``QTabWidget`` (scripts, scénarios, modules qui ajoutent une section)."""

    def __init__(self, editor):
        self.editor = editor
        self.sections = []
        self._current = 0

    def addTab(self, widget, title, expanded=False):
        section = Section(title, widget, expanded)
        self.editor.sections_layout.addWidget(section)
        self.sections.append(section)
        return len(self.sections) - 1

    def count(self):
        return len(self.sections)

    def tabText(self, index):
        return self.sections[index].title_text

    def widget(self, index):
        return self.sections[index].body

    def currentIndex(self):
        return self._current

    def currentWidget(self):
        return self.sections[self._current].body if self.sections else None

    def setCurrentIndex(self, index):
        if index < 0 or index >= len(self.sections):
            return
        self._current = index
        section = self.sections[index]
        section.set_expanded(True)
        area = getattr(self.editor, "scroll_area", None)
        if area is not None:
            QtWidgets.QApplication.processEvents()
            area.ensureWidgetVisible(section.header)

    def section(self, index):
        return self.sections[index]


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


class OperationEditor(Page):
    """Page non modale ; ``on_close(accepted)`` est appelé à la fermeture."""

    dialog_like = False

    def __init__(self, proj, op, parent=None, on_close=None, title=None):
        super(OperationEditor, self).__init__(title or tr("Operation: {name}", name=op.Label), parent)
        self.proj = proj
        self.op = op
        self.op_key = (proj.doc.Name, op.Name)  # lisible même quand l'objet n'existe plus
        self.rec = proj.registry.get(op.Name, {})
        self.kind = self.rec.get("kind", "?")
        self.on_close = on_close
        self.widgets = {}
        self._build()
        theme.apply(self)
        self._snapshot = self._current_state()
        self._refresh_key_values()
        # clavier : Ctrl+Entrée = appliquer ; le nom a le focus à l'ouverture
        shortcut_cls = getattr(QtGui, "QShortcut", None) or QtWidgets.QShortcut  # Qt6 : QtGui, Qt5 : QtWidgets
        self._shortcuts = []
        for seq in ("Ctrl+Return", "Ctrl+Enter"):
            sc = shortcut_cls(QtGui.QKeySequence(seq), self)
            sc.setContext(QtCore.Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(self.apply)
            self._shortcuts.append(sc)
        self.name.setFocus()
        self.name.selectAll()

    # -- construction ----------------------------------------------------------

    def _build(self):
        meta = STRATEGIES.get(self.kind, {"label": extra_label(self.kind), "limits": ""})
        from ..project import families

        info = families.STRATEGY_INFO.get(self.kind)
        head_w = QtWidgets.QWidget()
        head_w.setObjectName("editorHead")
        head = QtWidgets.QFormLayout(head_w)
        head.setContentsMargins(10, 8, 10, 4)
        head.setFieldGrowthPolicy(QtWidgets.QFormLayout.ExpandingFieldsGrow)
        self.name = QtWidgets.QLineEdit(self.op.Label)
        head.addRow(tr("Name"), self.name)
        strategy = QtWidgets.QLabel("<b>%s</b>" % tr(info["short"] if info else meta["label"]))
        strategy.setToolTip(tr(meta["label"]) + ((" - " + tr("engine: {name}", name=info["engine"])) if info else ""))
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
        self.outer.addWidget(head_w)
        # bandeau des valeurs clés (toujours visible) et résumé avant calcul
        self.key_strip = QtWidgets.QLabel()
        self.key_strip.setObjectName("keyStrip")
        self.key_strip.setWordWrap(True)
        self.key_strip.setContentsMargins(10, 2, 10, 2)
        self.key_strip.setTextFormat(QtCore.Qt.RichText)
        self.outer.addWidget(self.key_strip)
        self.summary = QtWidgets.QLabel()
        self.summary.setWordWrap(True)
        self.summary.setContentsMargins(10, 0, 10, 6)
        theme.set_role(self.summary, "muted")
        self.outer.addWidget(self.summary)

        body = self.scrolled_body()
        self.sections_layout = QtWidgets.QVBoxLayout(body)
        self.sections_layout.setContentsMargins(0, 0, 0, 0)
        self.sections_layout.setSpacing(2)
        self.tabs = _Sections(self)
        # ordre du métier : géométrie, outil, profondeurs et passes, avances, liaisons, spécialisé, filetage
        self.tabs.addTab(self._geometry_tab(), tr("Geometry"), expanded=True)
        self.tabs.addTab(self._tool_tab(), tr("Tool"), expanded=True)
        names = list(meta.get("params", ()))
        by_group = {}
        for n in names:
            if n not in self.op.PropertiesList:
                continue
            _label, group, _help = paramspec.spec(n)
            by_group.setdefault(group, []).append(n)
        depth_names = by_group.get("heights", []) + by_group.get("passes", [])
        if depth_names:
            self.tabs.addTab(self._params_tab(depth_names), tr("Depths and passes"), expanded=True)
        self.tabs.addTab(self._feeds_tab(), tr("Feeds and speeds"), expanded=False)
        self.dressup_boxes = {}
        entry_names = by_group.get("entry", [])
        if self.kind in _DRESSUP_KINDS or entry_names:
            self.tabs.addTab(self._dressup_tab(entry_names), tr("Entry, exit and tabs"), expanded=False)
        if by_group.get("strategy"):
            self.tabs.addTab(self._params_tab(by_group["strategy"]), tr("Strategy settings"), expanded=False)
        if by_group.get("thread"):
            self.tabs.addTab(self._params_tab(by_group["thread"]), tr("Thread"), expanded=True)
        from . import restlimit

        self.rest_limit = restlimit.add_tab(self)  # reprise de matière, limiter à une zone
        if meta.get("limits"):
            limits = QtWidgets.QLabel(tr(meta["limits"]))
            limits.setWordWrap(True)
            limits.setContentsMargins(10, 6, 10, 6)
            limits.setProperty("role", "muted")
            self.sections_layout.addWidget(limits)
        self.sections_layout.addStretch(1)

        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        self.status.setContentsMargins(10, 4, 10, 0)
        self.outer.addWidget(self.status)
        self.add_buttons(tr("Apply and compute"), tr("Close"), extra=((tr("Discard changes"), self.revert),))
        self.primary_button.clicked.disconnect()
        self.primary_button.clicked.connect(self.apply)
        self.cancel_button.clicked.disconnect()
        self.cancel_button.clicked.connect(self.close_requested)
        self.revert_button = self.extra_buttons[tr("Discard changes")]
        self.revert_button.setEnabled(False)
        self._watch_changes()

    def _watch_changes(self):
        """Chaque champ signale sa modification : bandeau, résumé et bouton « Annuler les modifications »."""
        for w in self.findChildren(QtWidgets.QWidget):
            for sig in ("valueChanged", "currentIndexChanged", "toggled", "textChanged"):
                signal = getattr(w, sig, None)
                if signal is not None and not isinstance(w, (QtWidgets.QScrollBar, QtWidgets.QAbstractScrollArea)):
                    try:
                        signal.connect(self._on_change)
                    except (TypeError, RuntimeError):
                        pass

    def _on_change(self, *_a):
        if not hasattr(self, "revert_button") or not hasattr(self, "_snapshot"):
            return  # page en construction
        self._refresh_key_values()
        self.revert_button.setEnabled(self.has_unsaved_changes())

    def _tool_tab(self):
        w = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(w)
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.ExpandingFieldsGrow)
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
        box = QtWidgets.QGroupBox(tr("Values of the cutting preset"))
        box.setLayout(self.values_grid)
        form.addRow(box)
        note = QtWidgets.QLabel(tr("Values are copied at creation time: a later change of the library never alters this operation. Choosing another tool or preset here and applying copies the new values (another cutter replaces the tool controller; strategy settings are kept). Spindle speed and feeds can be changed for this operation only in the Feeds and speeds section."))
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
        self._preset_values = values
        self._preset_name = preset_label(tool.preset(preset_id))
        if hasattr(self, "feed_widgets"):
            # autre outil ou préréglage : ses valeurs remplacent les surcharges de l'ancien
            same = (asm_id, preset_id) == (self.rec.get("assembly_id"), self.rec.get("preset_id"))
            self._load_feeds(self.proj.effective_values(self.rec) if same else values)
        if hasattr(self, "key_strip"):
            self._refresh_key_values()

    # -- avances et vitesses ----------------------------------------------------

    FEEDS = (("spindle_rpm", "Spindle speed", "rpm"), ("feed_mm_min", "Cutting feed", "mm/min"),
             ("plunge_feed_mm_min", "Plunge feed", "mm/min"))

    def _feeds_tab(self):
        """Broche, avance, plongée : valeur du préréglage ou surcharge propre à l'opération, source affichée."""
        w = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(w)
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.ExpandingFieldsGrow)
        self.feed_widgets = {}
        for key, label, unit in self.FEEDS:
            spin = QtWidgets.QDoubleSpinBox()
            spin.setRange(0.1, 1000000.0)
            spin.setDecimals(0)
            spin.setSuffix(" " + unit)
            source = QtWidgets.QLabel()
            source.setProperty("role", "muted")
            source.setWordWrap(True)
            col = QtWidgets.QVBoxLayout()
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(0)
            col.addWidget(spin)
            col.addWidget(source)
            form.addRow(tr(label), col)
            self.feed_widgets[key] = (spin, source)
            spin.valueChanged.connect(lambda _v: self._refresh_feed_sources())
        reset = QtWidgets.QPushButton(tr("Back to the preset values"))
        reset.clicked.connect(lambda: self._load_feeds(getattr(self, "_preset_values", None) or self.rec.get("values") or {}))
        form.addRow(reset)
        note = QtWidgets.QLabel(tr("Values copied from the cutting preset when the operation was created. A value changed here is kept for this operation only and shown as overridden; choosing another tool or preset puts the preset values back. Engagements (step down, step over) are in the Depths and passes section."))
        note.setWordWrap(True)
        note.setProperty("role", "muted")
        form.addRow(note)
        self._load_feeds(self.proj.effective_values(self.rec))
        return w

    def _load_feeds(self, values):
        for key, (spin, _src) in self.feed_widgets.items():
            spin.blockSignals(True)
            spin.setValue(float(values.get(key, spin.value())))
            spin.blockSignals(False)
        self._refresh_feed_sources()
        if hasattr(self, "key_strip"):
            self._on_change()

    def _refresh_feed_sources(self):
        preset = getattr(self, "_preset_values", None) or self.rec.get("values") or {}
        name = getattr(self, "_preset_name", "") or ""
        for key, (spin, source) in self.feed_widgets.items():
            base = preset.get(key)
            if base is None:
                source.setText("")
            elif abs(spin.value() - float(base)) > 1e-9:
                source.setText(tr("Overridden for this operation (preset: {v})", v="%.0f" % float(base)))
                source.setProperty("role", "warning")
            else:
                source.setText(tr("From the preset: {name}", name=name))
                source.setProperty("role", "muted")
            source.style().unpolish(source)
            source.style().polish(source)

    def _feed_overrides(self):
        return {key: spin.value() for key, (spin, _src) in self.feed_widgets.items()}

    def _apply_tool(self):
        asm_id, preset_id = self.asm_combo.currentData(), self.preset_combo.currentData()
        if asm_id and preset_id and (asm_id, preset_id) != (self.rec.get("assembly_id"), self.rec.get("preset_id")):
            self.rec = self.proj.change_operation_tool(self.op, asm_id, preset_id)

    # -- géométrie -----------------------------------------------------------------

    def _geometry_tab(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        hint = QtWidgets.QLabel(tr("Faces, edges or vertices of the model the operation works on. Select them in the 3D view, then use the buttons below. No geometry = whole model."))
        hint.setWordWrap(True)
        theme.set_role(hint, "muted")
        lay.addWidget(hint)
        self.base_list = QtWidgets.QListWidget()
        self.base_list.setMaximumHeight(110)
        self.base_list.setToolTip(tr("Click an item to highlight it in the 3D view"))
        self.base_list.itemClicked.connect(self._highlight)
        lay.addWidget(self.base_list)
        row = QtWidgets.QGridLayout()
        row.setSpacing(4)
        b_replace = QtWidgets.QPushButton(tr("Use the 3D selection"))
        b_add = QtWidgets.QPushButton(tr("Add the 3D selection"))
        b_clear = QtWidgets.QPushButton(tr("Whole model"))
        b_replace.clicked.connect(lambda: self._take_selection(replace=True))
        b_add.clicked.connect(lambda: self._take_selection(replace=False))
        b_clear.clicked.connect(self._clear_base)
        row.addWidget(b_replace, 0, 0)
        row.addWidget(b_add, 0, 1)
        row.addWidget(b_clear, 1, 0, 1, 2)
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
            item = QtWidgets.QListWidgetItem("%s: %s" % (obj.Label, " ".join(subs) or tr("whole")))
            item.setData(QtCore.Qt.UserRole, (obj.Name, list(subs)))
            self.base_list.addItem(item)
        if hasattr(self, "key_strip"):
            self._on_change()

    def _highlight(self, item):
        """Surbrillance dans la vue 3D de la géométrie cliquée dans la liste."""
        data = item.data(QtCore.Qt.UserRole)
        if not data:
            return
        name, subs = data
        try:
            FreeCADGui.Selection.clearSelection()
            for sub in subs or [""]:
                FreeCADGui.Selection.addSelection(self.proj.doc.Name, name, sub)
        except Exception:
            pass

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

    def geometry_summary(self):
        """« 2 contours selected » / « whole part » / « 3 faces (Plate) »."""
        if self._base is None:
            return tr("generated geometry")
        if not self._base:
            return tr("whole part")
        subs = [s for _o, ss in self._base for s in ss]
        if not subs:
            return tr("{n} object(s)", n=len(self._base))
        kinds = {"Face": tr("face(s)"), "Edge": tr("edge(s)"), "Vertex": tr("vertex/vertices")}
        counts = {}
        for s in subs:
            key = next((k for k in kinds if s.startswith(k)), "?")
            counts[key] = counts.get(key, 0) + 1
        return ", ".join("%d %s" % (n, kinds.get(k, k)) for k, n in counts.items())

    # -- paramètres ----------------------------------------------------------------

    def _params_tab(self, names):
        w = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(w)
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.ExpandingFieldsGrow)
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

    def _dressup_tab(self, entry_names=()):
        from ..project import dressups as dressupmod

        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        if entry_names:
            lay.addWidget(self._params_tab(entry_names))
        if self.kind in _DRESSUP_KINDS:
            info = QtWidgets.QLabel(tr("Dressups transform the computed toolpath: holding tags keep the part attached to the stock on a profile cut, a ramp entry replaces vertical plunges. 0 = FreeCAD default value."))
            info.setWordWrap(True)
            theme.set_role(info, "muted")
            lay.addWidget(info)
        existing = {dressupmod.dressup_kind(d): d for d in self.proj.dressups(self.op)}
        for key in ("tags", "ramp", "dogbone", "leads"):
            if self.kind not in _DRESSUP_KINDS:
                break
            if key == "tags" and self.kind != "profile":
                continue
            if key == "leads" and self.kind not in ("profile", "slot"):
                continue
            if key == "dogbone" and (self.kind not in ("profile", "pocket", "adaptive")
                                     or not dressupmod.dogbone_possible(self.op)):
                continue
            meta = dressupmod.DRESSUPS[key]
            box = QtWidgets.QGroupBox(tr(meta["label"]))
            box.setCheckable(True)
            box.setChecked(key in existing)
            form = QtWidgets.QFormLayout(box)
            form.setFieldGrowthPolicy(QtWidgets.QFormLayout.ExpandingFieldsGrow)
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

    # -- bandeau et résumé ------------------------------------------------------------

    def _refresh_key_values(self):
        """Diamètre, broche, avance, plongée, profondeur finale, passe axiale, hauteurs : toujours lisibles."""
        parts = []
        tool = self.asm_combo.tool() if hasattr(self, "asm_combo") else None
        if tool is not None:
            parts.append("Ø <b>%.4g</b> mm" % tool.geometry.diameter)
        if hasattr(self, "feed_widgets"):
            f = {k: spin.value() for k, (spin, _s) in self.feed_widgets.items()}
            parts.append("S <b>%.0f</b>" % f.get("spindle_rpm", 0))
            parts.append("F <b>%.0f</b>" % f.get("feed_mm_min", 0))
            parts.append(tr("plunge") + " <b>%.0f</b>" % f.get("plunge_feed_mm_min", 0))
        for name, label in _KEY_PARAMS:
            if name in self.widgets:
                kind, w = self.widgets[name]
                parts.append("%s <b>%.3g</b> mm" % (tr(label), w.value()))
        self.key_strip.setText(" &nbsp;·&nbsp; ".join(parts))
        # résumé concret avant calcul
        summary = [self.geometry_summary()]
        if tool is not None:
            summary.append(tr("tool Ø {d} mm", d="%.4g" % tool.geometry.diameter))
        if "FinalDepth" in self.widgets:
            summary.append(tr("depth {z} mm", z="%.3g" % self.widgets["FinalDepth"][1].value()))
        if "StepDown" in self.widgets:
            summary.append(tr("step down {s} mm", s="%.3g" % self.widgets["StepDown"][1].value()))
        self.summary.setText(" — ".join(summary))

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
            self.rec = self.proj.set_operation_feeds(self.op, self._feed_overrides())
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
        self.setWindowTitle(tr("Operation: {name}", name=self.op.Label))
        panels.refresh_project_panel()
        return True

    def _current_state(self):
        """Valeurs affichées (nom, outil, géométrie, paramètres, habillages) pour détecter une modification non appliquée."""
        dressups = {}
        for key, (box, widgets) in getattr(self, "dressup_boxes", {}).items():
            dressups[key] = (box.isChecked(), tuple(sorted(self._widget_values(widgets).items())))
        return (self.name.text(), self.index.value(), self.asm_combo.currentData(), self.preset_combo.currentData(),
                tuple(sorted(self._feed_overrides().items())) if hasattr(self, "feed_widgets") else (),
                tuple((o.Name, tuple(subs)) for o, subs in (self._base or ())),
                tuple(sorted((k, repr(v)) for k, v in self.params().items())), tuple(sorted(dressups.items())),
                self.rest_limit.state() if getattr(self, "rest_limit", None) is not None else None)

    def has_unsaved_changes(self):
        return self._current_state() != self._snapshot

    def apply(self):
        ok = self._apply()
        if ok:
            self._snapshot = self._current_state()
            self.revert_button.setEnabled(False)
        return ok

    def revert(self):
        """Annule les modifications non appliquées : la page est reconstruite depuis l'opération."""
        if not self.has_unsaved_changes():
            return
        cb, self.on_close = self.on_close, None
        self.done(0)
        open_editor(self.proj, self.op, on_close=cb)

    def accept(self):
        if not self.has_unsaved_changes() or self.apply():  # rien à appliquer : pas d'étape d'annulation vide
            self.done(1)

    def reject(self):
        # Échap / fermeture : ne pas perdre en silence des modifications non appliquées
        if self.has_unsaved_changes():
            answer = QtWidgets.QMessageBox.question(
                self, "CAM2027", tr("Discard the changes that were not applied?"),
                QtWidgets.QMessageBox.Discard | QtWidgets.QMessageBox.Cancel, QtWidgets.QMessageBox.Cancel)
            if answer != QtWidgets.QMessageBox.Discard:
                return
        self.done(0)

    def close_requested(self):
        """Bouton « Fermer » : applique d'abord s'il reste des modifications (question explicite)."""
        if self.has_unsaved_changes():
            box = QtWidgets.QMessageBox(self.window())
            box.setWindowTitle("CAM2027")
            box.setText(tr("Changes not applied yet."))
            box.setInformativeText(tr("Apply them, discard them, or stay on this panel?"))
            apply_b = box.addButton(tr("Apply"), QtWidgets.QMessageBox.AcceptRole)
            discard = box.addButton(tr("Discard"), QtWidgets.QMessageBox.DestructiveRole)
            stay = box.addButton(tr("Stay"), QtWidgets.QMessageBox.RejectRole)
            box.setDefaultButton(stay)
            from .inspector import _ask

            answer = _ask(box)
            if answer is stay:
                return
            if answer is apply_b:
                self.accept()
                return
            if answer is discard:
                self.done(0)
                return
        self.accept()

    def done(self, code):
        if self.is_done():
            return
        super(OperationEditor, self).done(code)
        cb, self.on_close = self.on_close, None
        if cb:
            cb(bool(code))


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
    except RuntimeError:
        pass


def open_editor(proj, op, on_close=None, title=None):
    """Ouvre l'éditeur de l'opération ``op`` dans le panneau contextuel et le retourne."""
    global _observer
    if _observer is None:
        _observer = _DocumentObserver()
        FreeCAD.addDocumentObserver(_observer)
    editor = OperationEditor(proj, op, on_close=on_close, title=title)
    _open_editors.append(editor)
    editor.finished.connect(lambda _r: _open_editors.remove(editor) if editor in _open_editors else None)
    from . import shell

    shown = shell.inspector().show_page(editor)
    if shown is None:
        return editor  # la page précédente a gardé la place ; l'éditeur est déjà terminé
    shell.show_space("machine")
    return editor
