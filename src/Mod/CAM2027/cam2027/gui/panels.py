# SPDX-License-Identifier: LGPL-2.1-or-later
"""Panneaux ancrés : bibliothèque d'outils et projet."""

import os

import FreeCAD
import FreeCADGui

from .qt import QtCore, QtGui, QtWidgets, exec_dialog
from ..i18n import tr, tr_msg
from .labels import asm_label, preset_label
from ..tools.model import (
    ToolDefinition, ToolGeometry, CuttingPreset, Holder, ToolAssembly, TOOL_TYPES, geometry_fields_for,
    FLUTE_STYLES, ROTATIONS, COOLANTS, PRESET_USAGES, TAPER_TIPS, THREAD_TIP_TYPES,
)
from ..tools.fusion_import import import_fusion_library
from ..tools import bridge
from ..project import undo
from . import state, theme
from .preview import ToolPreview

_FIELD_LABELS = {
    "diameter": "Diameter (mm)",
    "shank_diameter": "Shank diameter (mm)",
    "overall_length": "Overall length (mm)",
    "flute_length": "Flute length (mm)",
    "shoulder_length": "Shoulder length (mm)",
    "body_length": "Length below holder (mm)",
    "corner_radius": "Corner radius (mm)",
    "tip_diameter": "Tip diameter (mm)",
    "tip_included_angle_deg": "Tip included angle (deg)",
    "taper_half_angle_deg": "Taper half-angle (deg)",
    "taper_tip": "Taper tip type",
    "barrel_radius": "Profile radius (mm)",
    "upper_radius": "Upper radius (mm)",
    "lower_radius": "Lower radius (mm)",
    "axial_distance": "Axial distance (mm)",
    "tip_offset": "Tip offset (mm)",
    "pitch": "Maximum thread pitch (mm)",
    "pitch_min": "Minimum thread pitch (mm)",
    "thread_teeth": "Number of thread teeth",
    "thread_profile_angle_deg": "Thread profile angle (deg)",
    "thread_tip_type": "Thread tip type",
    "flute_style": "Flute style",
}
_ENUM_FIELDS = {"flute_style": FLUTE_STYLES, "taper_tip": TAPER_TIPS, "thread_tip_type": THREAD_TIP_TYPES}
_ADVANCED_FIELDS = ("shoulder_length", "body_length", "neck_diameter", "neck_length")

_PRESET_FIELDS = (
    ("spindle_rpm", "Spindle speed (rpm)"),
    ("surface_speed_m_min", "Surface speed (m/min)"),
    ("ramp_spindle_rpm", "Ramp spindle speed (rpm)"),
    ("feed_mm_min", "Cutting feed (mm/min)"),
    ("feed_per_tooth_mm", "Feed per tooth (mm)"),
    ("lead_in_feed_mm_min", "Lead-in feed (mm/min)"),
    ("lead_out_feed_mm_min", "Lead-out feed (mm/min)"),
    ("transition_feed_mm_min", "Transition feed (mm/min)"),
    ("ramp_feed_mm_min", "Ramp feed (mm/min)"),
    ("ramp_angle_deg", "Ramp angle (deg)"),
    ("plunge_feed_mm_min", "Plunge feed (mm/min)"),
    ("plunge_feed_per_rev_mm", "Plunge feed per revolution (mm)"),
    ("retract_feed_mm_min", "Retract feed (mm/min)"),
    ("feed_per_rev_mm", "Feed per revolution (mm)"),
    ("axial_engagement_mm", "Axial engagement / stepdown (mm)"),
    ("radial_engagement_mm", "Radial engagement / stepover (mm)"),
)


def _warn(text):
    QtWidgets.QMessageBox.warning(FreeCADGui.getMainWindow(), "CAM2027", text)


def _info(text):
    QtWidgets.QMessageBox.information(FreeCADGui.getMainWindow(), "CAM2027", text)


# ---------------------------------------------------------------------------
# Bibliothèque d'outils
# ---------------------------------------------------------------------------


#: type d'outil -> icône « Atelier » (silhouette la plus proche)
TOOL_TYPE_ICONS = {
    "endmill": "endmill-flat", "bullnose": "endmill-flat", "facemill": "endmill-flat", "slot": "endmill-flat",
    "taper": "endmill-flat", "form": "endmill-flat", "dovetail": "endmill-flat",
    "ballend": "endmill-ball", "taperedball": "endmill-ball", "lollipop": "endmill-ball", "radius": "endmill-ball",
    "barrel": "endmill-ball", "lens": "endmill-ball", "ogive": "endmill-ball", "taperbarrel": "endmill-ball",
    "drill": "drill", "threadmill": "drill",
    "vbit": "engrave", "chamfer": "engrave", "engrave": "engrave",
}


class ToolLibraryPanel(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super(ToolLibraryPanel, self).__init__(parent)
        self.lib = state.library()
        self.current = None
        self._building = False
        self._build()
        self.refresh_list()

    # -- construction -----------------------------------------------------

    def _build(self):
        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        splitter = QtWidgets.QSplitter()
        root.addWidget(splitter)

        # colonne gauche : recherche + liste
        left = QtWidgets.QWidget()
        ll = QtWidgets.QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        filt = QtWidgets.QHBoxLayout()
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText(tr("Search (name, vendor, diameter...)"))
        self.search.textChanged.connect(self.refresh_list)
        filt.addWidget(self.search)
        self.type_filter = QtWidgets.QComboBox()
        self.type_filter.addItem(tr("All types"), None)
        for key, (label, _f) in TOOL_TYPES.items():
            self.type_filter.addItem(tr(label), key)
        self.type_filter.currentIndexChanged.connect(self.refresh_list)
        filt.addWidget(self.type_filter)
        self.fav_only = QtWidgets.QCheckBox(tr("Favorites"))
        self.fav_only.toggled.connect(self.refresh_list)
        filt.addWidget(self.fav_only)
        ll.addLayout(filt)
        self.table = QtWidgets.QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(["★", "T", tr("Name"), tr("Type"), "D (mm)", "Lc (mm)", "z", tr("Material")])
        self.table.horizontalHeaderItem(5).setToolTip(tr("Flute length (mm)"))
        self.table.horizontalHeaderItem(1).setToolTip(tr("Tool number of the first assembly (output data)"))
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self.on_select)
        self.table.horizontalHeader().setSortIndicator(1, QtCore.Qt.AscendingOrder)  # tri par numéro T
        ll.addWidget(self.table)
        # actions principales visibles (texte + icône), le reste dans deux menus : lisible à 1280 px
        row1 = QtWidgets.QHBoxLayout()
        for label, slot, icon_name in ((tr("New"), self.new_tool, "new-project"),
                                       (tr("Duplicate"), self.duplicate_tool, "redo"),
                                       (tr("Delete"), self.delete_tool, "delete")):
            b = QtWidgets.QPushButton(theme.icon(icon_name), label)
            if slot == self.delete_tool:
                theme.set_role(b, "danger")
            b.clicked.connect(slot)
            row1.addWidget(b)
        ll.addLayout(row1)
        row2 = QtWidgets.QHBoxLayout()
        self.menus = {}
        for key, label, icon_name, actions in (
            ("tool", tr("More..."), "settings", ((tr("Favorite"), self.toggle_favorite),
                                                 (tr("Bulk edit"), self.bulk_edit))),
            ("library", tr("Library..."), "tool-library", (
                (tr("Save library"), self.save_library), (tr("Import Fusion..."), self.import_fusion),
                (tr("Export library..."), self.export_library), (tr("Import library..."), self.import_library),
                (tr("Add missing starter tools"), self.add_starter_tools))),
        ):
            btn = QtWidgets.QToolButton()
            btn.setText(label)
            btn.setIcon(theme.icon(icon_name))
            btn.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
            btn.setPopupMode(QtWidgets.QToolButton.InstantPopup)
            btn.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            menu = QtWidgets.QMenu(btn)
            for text, slot in actions:
                menu.addAction(text).triggered.connect(lambda _c=False, f=slot: f())
            btn.setMenu(menu)
            row2.addWidget(btn)
            self.menus[key] = menu
        ll.addLayout(row2)
        self.status = QtWidgets.QLabel()
        ll.addWidget(self.status)
        splitter.addWidget(left)

        # colonne centrale : fiche outil (onglets)
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(self._build_cutter_tab(), tr("Cutter"))
        self.tabs.addTab(self._build_presets_tab(), tr("Cutting data"))
        self.tabs.addTab(self._build_assembly_tab(), tr("Holder"))
        self.tabs.tabBar().setElideMode(QtCore.Qt.ElideRight)  # jamais un onglet coupé au début du mot
        self.tabs.setMinimumWidth(self.tabs.tabBar().sizeHint().width() + 8)
        splitter.addWidget(self.tabs)

        # colonne droite : aperçu
        right = QtWidgets.QWidget()
        rl = QtWidgets.QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self.preview = ToolPreview()
        rl.addWidget(self.preview)
        show3d = QtWidgets.QPushButton(tr("Show in 3D (active document)"))
        show3d.clicked.connect(self.show_in_3d)
        rl.addWidget(show3d)
        splitter.addWidget(right)
        splitter.setSizes([420, 420, 280])
        for index, factor in enumerate((3, 3, 2)):  # la table garde sa part quand la fenêtre rétrécit
            splitter.setStretchFactor(index, factor)

    def _build_cutter_tab(self):
        w = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(w)
        self.f_name = QtWidgets.QLineEdit()
        form.addRow(tr("Name"), self.f_name)
        self.f_type = QtWidgets.QComboBox()
        for key, (label, _f) in TOOL_TYPES.items():
            self.f_type.addItem(tr(label), key)
        self.f_type.currentIndexChanged.connect(self.on_type_changed)
        form.addRow(tr("Type"), self.f_type)
        self.f_flutes = QtWidgets.QSpinBox()
        self.f_flutes.setRange(1, 64)
        form.addRow(tr("Number of flutes"), self.f_flutes)
        self.f_rotation = QtWidgets.QComboBox()
        self.f_rotation.addItem(tr("Clockwise (M3)"), "cw")
        self.f_rotation.addItem(tr("Counter-clockwise (M4)"), "ccw")
        form.addRow(tr("Spindle rotation"), self.f_rotation)
        self.f_material = QtWidgets.QComboBox()
        self.f_material.setEditable(True)
        self.f_material.addItems(["carbide", "hss", "ceramic", "diamond", "cobalt"])
        form.addRow(tr("Material"), self.f_material)
        self.f_coating = QtWidgets.QLineEdit()
        form.addRow(tr("Coating"), self.f_coating)
        self.geom_widgets = {}
        self.geom_rows = {}
        for key in ToolGeometry.ALL_FIELDS:
            if key == "profile":
                continue
            if key in _ENUM_FIELDS:
                wdg = QtWidgets.QComboBox()
                for fs in _ENUM_FIELDS[key]:
                    wdg.addItem(tr(fs), fs)
            elif key == "thread_teeth":
                wdg = QtWidgets.QSpinBox()
                wdg.setRange(0, 200)
                wdg.setSpecialValueText(tr("(not set)"))
            else:
                wdg = QtWidgets.QDoubleSpinBox()
                wdg.setDecimals(3)
                wdg.setRange(0.0, 10000.0)
                wdg.setSpecialValueText(tr("(not set)"))
            lab = QtWidgets.QLabel(tr(_FIELD_LABELS[key]))
            form.addRow(lab, wdg)
            self.geom_widgets[key] = wdg
            self.geom_rows[key] = lab
        self.f_vendor = QtWidgets.QLineEdit()
        form.addRow(tr("Vendor"), self.f_vendor)
        self.f_product = QtWidgets.QLineEdit()
        form.addRow(tr("Product id"), self.f_product)
        self.f_url = QtWidgets.QLineEdit()
        form.addRow(tr("Product link"), self.f_url)
        self.f_desc = QtWidgets.QLineEdit()
        form.addRow(tr("Description"), self.f_desc)
        self.f_tags = QtWidgets.QLineEdit()
        self.f_tags.setPlaceholderText(tr("comma separated"))
        form.addRow(tr("Tags"), self.f_tags)
        self.advanced = QtWidgets.QCheckBox(tr("Advanced mode (all fields)"))
        self.advanced.toggled.connect(self.on_type_changed)
        form.addRow(self.advanced)
        apply_btn = QtWidgets.QPushButton(tr("Apply changes"))
        apply_btn.clicked.connect(self.apply_tool)
        form.addRow(apply_btn)
        # aperçu dynamique (comme Fusion) : chaque saisie redessine l'outil à partir des champs, sans l'enregistrer
        self.f_name.textChanged.connect(self._live_preview)
        self.f_type.currentIndexChanged.connect(self._live_preview)
        self.f_flutes.valueChanged.connect(self._live_preview)
        for wdg in self.geom_widgets.values():
            signal = wdg.currentIndexChanged if isinstance(wdg, QtWidgets.QComboBox) else wdg.valueChanged
            signal.connect(self._live_preview)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(w)
        return scroll

    def _build_presets_tab(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        self.preset_list = QtWidgets.QListWidget()
        self.preset_list.currentRowChanged.connect(self.on_preset_selected)
        lay.addWidget(self.preset_list)
        pb = QtWidgets.QHBoxLayout()
        for label, slot in ((tr("New preset"), self.new_preset), (tr("Duplicate"), self.duplicate_preset),
                            (tr("Delete"), self.delete_preset)):
            b = QtWidgets.QPushButton(label)
            b.clicked.connect(slot)
            pb.addWidget(b)
        lay.addLayout(pb)
        form = QtWidgets.QFormLayout()
        self.p_name = QtWidgets.QLineEdit()
        form.addRow(tr("Preset name"), self.p_name)
        self.p_usage = QtWidgets.QComboBox()
        for u in PRESET_USAGES:
            self.p_usage.addItem(tr(u), u)
        form.addRow(tr("Usage"), self.p_usage)
        self.p_material = QtWidgets.QLineEdit()
        form.addRow(tr("Workpiece material"), self.p_material)
        self.p_rpm_source = QtWidgets.QComboBox()
        self.p_rpm_source.addItem(tr("Spindle speed drives surface speed"), "rpm")
        self.p_rpm_source.addItem(tr("Surface speed drives spindle speed"), "vc")
        form.addRow(tr("Speed source"), self.p_rpm_source)
        self.p_feed_source = QtWidgets.QComboBox()
        self.p_feed_source.addItem(tr("Cutting feed drives feed per tooth"), "feed")
        self.p_feed_source.addItem(tr("Feed per tooth drives cutting feed"), "fz")
        form.addRow(tr("Feed source"), self.p_feed_source)
        self.p_widgets = {}
        for key, label in _PRESET_FIELDS:
            wdg = QtWidgets.QDoubleSpinBox()
            wdg.setDecimals(4)
            wdg.setRange(0.0, 1e6)
            wdg.setSpecialValueText(tr("(not set)"))
            form.addRow(tr(label), wdg)
            self.p_widgets[key] = wdg
        self.p_coolant = QtWidgets.QComboBox()
        for c in COOLANTS:
            self.p_coolant.addItem(tr(c), c)
        form.addRow(tr("Coolant"), self.p_coolant)
        self.p_resolved = QtWidgets.QLabel()
        self.p_resolved.setWordWrap(True)
        form.addRow(tr("Resolved values"), self.p_resolved)
        apply_btn = QtWidgets.QPushButton(tr("Apply preset"))
        apply_btn.clicked.connect(self.apply_preset)
        form.addRow(apply_btn)
        lay.addLayout(form)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(w)
        return scroll

    def _build_assembly_tab(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        # comme Fusion : l'outil a son porte-outil et sa sortie, sans liste d'« assemblages » à gérer (un seul
        # par outil, créé automatiquement ; la liste reste interne)
        self.asm_list = QtWidgets.QListWidget()
        self.asm_list.currentRowChanged.connect(self.on_assembly_selected)
        self.asm_list.setVisible(False)
        lay.addWidget(self.asm_list)
        form = QtWidgets.QFormLayout()
        self.a_name = QtWidgets.QLineEdit()  # nom interne, non affiché
        self.a_holder = QtWidgets.QComboBox()
        form.addRow(tr("Holder"), self.a_holder)
        self.a_stickout = QtWidgets.QDoubleSpinBox()
        self.a_stickout.setRange(0.0, 1000.0)
        self.a_stickout.setDecimals(2)
        form.addRow(tr("Length below the holder (mm)"), self.a_stickout)
        self.a_gauge = QtWidgets.QLabel()
        form.addRow(tr("Gauge length (mm)"), self.a_gauge)
        self.a_number = QtWidgets.QSpinBox()
        self.a_number.setRange(0, 999)
        form.addRow(tr("Tool number"), self.a_number)
        self.a_len_off = QtWidgets.QSpinBox()
        self.a_len_off.setRange(0, 999)
        form.addRow(tr("Length offset"), self.a_len_off)
        self.a_dia_off = QtWidgets.QSpinBox()
        self.a_dia_off.setRange(0, 999)
        form.addRow(tr("Diameter offset"), self.a_dia_off)
        self.a_manual = QtWidgets.QCheckBox(tr("Manual tool change"))
        form.addRow(self.a_manual)
        self.a_comment = QtWidgets.QLineEdit()
        form.addRow(tr("Comment"), self.a_comment)
        lay.addLayout(form)
        ab = QtWidgets.QHBoxLayout()
        for label, slot in ((tr("Apply"), self.apply_assembly), (tr("New holder..."), self.new_holder)):
            b = QtWidgets.QPushButton(label)
            b.clicked.connect(slot)
            ab.addWidget(b)
        lay.addLayout(ab)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(w)
        return scroll

    # -- liste ------------------------------------------------------------

    def refresh_list(self, *_args):
        tools = self.lib.search(self.search.text(), tool_type=self.type_filter.currentData(),
                                favorites_only=self.fav_only.isChecked())
        self._building = True
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(tools))
        for row, t in enumerate(tools):
            numbers = sorted(a.output.tool_number for a in self.lib.assemblies_for_tool(t.id))
            items = ["★" if t.favorite else "", numbers[0] if numbers else None, t.name, tr(t.type_label()),
                     t.geometry.diameter, t.geometry.flute_length, t.flute_count, t.material]
            for col, value in enumerate(items):
                item = QtWidgets.QTableWidgetItem()
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    item.setData(QtCore.Qt.DisplayRole, value)  # tri numérique
                    item.setTextAlignment(int(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter))
                else:
                    item.setText(value or "")
                item.setData(QtCore.Qt.UserRole, t.id)
                if col == 2:
                    item.setIcon(theme.icon(TOOL_TYPE_ICONS.get(t.tool_type, "endmill-flat")))
                self.table.setItem(row, col, item)
        self.table.setSortingEnabled(True)
        self.table.resizeColumnsToContents()
        self._building = False
        s = self.lib.summary()
        self.status.setText(tr("{tools} tools, {holders} holders, {assemblies} assemblies - revision {rev}",
                               tools=s["tools"], holders=s["holders"], assemblies=s["assemblies"], rev=self.lib.revision))
        if self.current and self.current.id in self.lib.tools:
            for row in range(self.table.rowCount()):
                if self.table.item(row, 2).data(QtCore.Qt.UserRole) == self.current.id:
                    self.table.selectRow(row)
                    break

    def show_tool(self, tool_id):
        """Ouvre l'outil ``tool_id`` dans la fiche (bouton « Éditer… » d'une opération)."""
        if tool_id not in self.lib.tools:
            return
        self.search.clear()
        self.type_filter.setCurrentIndex(0)
        self.current = self.lib.tool(tool_id)
        self.refresh_list()
        self.load_tool(self.current)

    def selected_ids(self):
        ids = []
        for item in self.table.selectedItems():
            if item.column() == 1:
                ids.append(item.data(QtCore.Qt.UserRole))
        return ids

    def on_select(self):
        if self._building:
            return
        ids = self.selected_ids()
        if not ids:
            return
        self.current = self.lib.tool(ids[0])
        self.load_tool(self.current)

    # -- fiche outil --------------------------------------------------------

    def load_tool(self, tool):
        self._building = True
        self.f_name.setText(tool.name)
        self.f_type.setCurrentIndex(self.f_type.findData(tool.tool_type))
        self.f_flutes.setValue(tool.flute_count)
        self.f_rotation.setCurrentIndex(self.f_rotation.findData(tool.rotation))
        self.f_material.setEditText(tool.material)
        self.f_coating.setText(tool.coating)
        self.f_vendor.setText(tool.vendor)
        self.f_product.setText(tool.product_id)
        self.f_url.setText(tool.product_url)
        self.f_desc.setText(tool.description)
        self.f_tags.setText(", ".join(tool.tags))
        for key, wdg in self.geom_widgets.items():
            v = getattr(tool.geometry, key)
            if key in _ENUM_FIELDS:
                wdg.setCurrentIndex(max(wdg.findData(v), 0))
            elif key == "thread_teeth":
                wdg.setValue(int(v) if v is not None else 0)
            else:
                wdg.setValue(float(v) if v is not None else 0.0)
        self._building = False
        self.on_type_changed()
        self.load_presets(tool)
        self.load_assemblies(tool)
        self.update_preview()

    def on_type_changed(self, *_args):
        ttype = self.f_type.currentData()
        fields = geometry_fields_for(ttype)
        advanced = self.advanced.isChecked()
        for key, wdg in self.geom_widgets.items():
            visible = key in fields and (advanced or key not in _ADVANCED_FIELDS)
            wdg.setVisible(visible)
            self.geom_rows[key].setVisible(visible)
        for wdg in (self.f_coating, self.f_vendor, self.f_product, self.f_url, self.f_tags):
            wdg.setVisible(advanced)
            lab = self.tabs.widget(0).widget().layout().labelForField(wdg)
            if lab:
                lab.setVisible(advanced)

    def _geometry_from_form(self):
        ttype = self.f_type.currentData()
        fields = geometry_fields_for(ttype)
        g = {}
        for key, wdg in self.geom_widgets.items():
            if key not in fields:
                continue
            if key in _ENUM_FIELDS:
                g[key] = wdg.currentData()
            elif wdg.value() > 0:
                g[key] = wdg.value()
            elif key in ("upper_radius", "lower_radius", "tip_offset", "tip_diameter", "corner_radius")                     or (key == "taper_half_angle_deg" and ttype == "facemill"):  # dépouille 0° : fraise à surfacer droite
                g[key] = 0.0
        if self.current is not None and ttype == "form":
            g["profile"] = [s.to_dict() for s in (self.current.geometry.profile or [])]
        return g

    def _tool_from_form(self):
        """Outil tel que saisi dans la fiche (non enregistré) ; ``ValueError`` si une valeur est incohérente."""
        data = self.current.to_dict()
        data.update({
            "name": self.f_name.text().strip(),
            "tool_type": self.f_type.currentData(),
            "geometry": self._geometry_from_form(),
            "flute_count": self.f_flutes.value(),
            "shank_segments": [],
        })
        return ToolDefinition.from_dict(data)

    def _live_preview(self, *_args):
        if self._building or self.current is None:
            return
        a = self.current_assembly()
        holder = self.lib.holders.get(a.holder_id) if a and a.holder_id else None
        try:
            tool = self._tool_from_form()
        except (ValueError, KeyError, TypeError) as exc:
            self.preview.set_error(tr_msg(exc) if isinstance(exc, ValueError) else str(exc))
            return
        self.preview.set_tool(tool, holder, a.stickout if a else None)

    def apply_tool(self):
        if self.current is None:
            return
        try:
            data = self.current.to_dict()
            data.update({
                "name": self.f_name.text().strip(),
                "tool_type": self.f_type.currentData(),
                "geometry": self._geometry_from_form(),
                "flute_count": self.f_flutes.value(),
                "rotation": self.f_rotation.currentData(),
                "material": self.f_material.currentText().strip(),
                "coating": self.f_coating.text().strip(),
                "vendor": self.f_vendor.text().strip(),
                "product_id": self.f_product.text().strip(),
                "product_url": self.f_url.text().strip(),
                "description": self.f_desc.text().strip(),
                "tags": [t.strip() for t in self.f_tags.text().split(",") if t.strip()],
                "shank_segments": [],
            })
            new = ToolDefinition.from_dict(data)
        except ValueError as exc:
            _warn(tr_msg(exc))
            return
        self.lib.tools[new.id] = new
        self.lib.ensure_usable(new.id, tr("New preset"))
        self.current = new
        self.refresh_list()
        self.load_tool(new)

    def new_tool(self):
        tool = ToolDefinition(tr("New tool"), "endmill", dict(diameter=6, overall_length=50, flute_length=18))
        self.lib.add_tool(tool)
        self.lib.ensure_usable(tool.id, tr("New preset"))  # préréglage et assemblage : proposé à l'opération
        self.current = tool
        self.refresh_list()
        self.load_tool(tool)

    def duplicate_tool(self):
        if self.current is None:
            return
        copy = self.lib.duplicate_tool(self.current.id)
        self.lib.ensure_usable(copy.id, tr("New preset"))
        self.current = copy
        self.refresh_list()
        self.load_tool(copy)

    def delete_tool(self):
        ids = self.selected_ids()
        if not ids:
            return
        try:
            for tid in ids:
                self.lib.remove_tool(tid)
        except ValueError as exc:
            _warn(tr_msg(exc))
        self.current = None
        self.refresh_list()

    def toggle_favorite(self):
        for tid in self.selected_ids():
            t = self.lib.tool(tid)
            self.lib.set_favorite(tid, not t.favorite)
        self.refresh_list()

    def bulk_edit(self):
        ids = self.selected_ids()
        if len(ids) < 2:
            _warn(tr("Select at least two tools for bulk edit."))
            return
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(tr("Bulk edit"))
        form = QtWidgets.QFormLayout(dlg)
        material = QtWidgets.QLineEdit()
        coating = QtWidgets.QLineEdit()
        vendor = QtWidgets.QLineEdit()
        flutes = QtWidgets.QSpinBox()
        flutes.setRange(0, 64)
        flutes.setSpecialValueText(tr("(unchanged)"))
        form.addRow(tr("Material (empty = unchanged)"), material)
        form.addRow(tr("Coating (empty = unchanged)"), coating)
        form.addRow(tr("Vendor (empty = unchanged)"), vendor)
        form.addRow(tr("Number of flutes"), flutes)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        if exec_dialog(dlg) != QtWidgets.QDialog.Accepted:
            return
        fields = {}
        if material.text().strip():
            fields["material"] = material.text().strip()
        if coating.text().strip():
            fields["coating"] = coating.text().strip()
        if vendor.text().strip():
            fields["vendor"] = vendor.text().strip()
        if flutes.value() > 0:
            fields["flute_count"] = flutes.value()
        try:
            self.lib.bulk_edit(ids, **fields)
        except ValueError as exc:
            _warn(tr_msg(exc))
        self.refresh_list()

    # -- préréglages --------------------------------------------------------

    def load_presets(self, tool):
        self.preset_list.clear()
        for p in tool.presets:
            self.preset_list.addItem("%s (%s)" % (p.name, tr(p.usage)))
        if tool.presets:
            self.preset_list.setCurrentRow(0)
        else:
            self.p_resolved.setText("")

    def current_preset(self):
        row = self.preset_list.currentRow()
        if self.current is None or row < 0 or row >= len(self.current.presets):
            return None
        return self.current.presets[row]

    def on_preset_selected(self, _row):
        p = self.current_preset()
        if p is None:
            return
        self._building = True
        self.p_name.setText(p.name)
        self.p_usage.setCurrentIndex(self.p_usage.findData(p.usage))
        self.p_material.setText(p.material)
        self.p_rpm_source.setCurrentIndex(self.p_rpm_source.findData(p.rpm_source))
        self.p_feed_source.setCurrentIndex(self.p_feed_source.findData(p.feed_source))
        for key, wdg in self.p_widgets.items():
            v = getattr(p, key)
            wdg.setValue(float(v) if v is not None else 0.0)
        self.p_coolant.setCurrentIndex(self.p_coolant.findData(p.coolant))
        self._building = False
        self.show_resolved(p)

    def show_resolved(self, p):
        try:
            r = p.resolve(self.current)
            self.p_resolved.setText(
                "n = %.0f rpm, Vc = %.1f m/min, Vf = %.0f mm/min, fz = %.4f mm, plunge = %.0f mm/min (%s: %s)"
                % (r["spindle_rpm"], r["surface_speed_m_min"], r["feed_mm_min"], r["feed_per_tooth_mm"],
                   r["plunge_feed_mm_min"], tr("derived"), ", ".join(r["derived"]) or "-"))
        except ValueError as exc:
            self.p_resolved.setText(tr("Incomplete: {error}", error=tr_msg(exc)))

    def _preset_from_form(self, preset_id=None):
        kwargs = {"id": preset_id, "usage": self.p_usage.currentData(), "material": self.p_material.text().strip(),
                  "rpm_source": self.p_rpm_source.currentData(), "feed_source": self.p_feed_source.currentData(),
                  "coolant": self.p_coolant.currentData()}
        for key, wdg in self.p_widgets.items():
            kwargs[key] = wdg.value() if wdg.value() > 0 else None
        return CuttingPreset(self.p_name.text().strip() or "Preset", **kwargs)

    def apply_preset(self):
        p = self.current_preset()
        if p is None:
            return
        try:
            new = self._preset_from_form(p.id)
        except ValueError as exc:
            _warn(tr_msg(exc))
            return
        row = self.current.presets.index(p)
        self.current.presets[row] = new
        self.load_presets(self.current)
        self.preset_list.setCurrentRow(row)

    def new_preset(self):
        if self.current is None:
            return
        self.current.add_preset(CuttingPreset(tr("New preset"), spindle_rpm=12000, feed_mm_min=600))
        self.load_presets(self.current)
        self.preset_list.setCurrentRow(len(self.current.presets) - 1)

    def duplicate_preset(self):
        p = self.current_preset()
        if p is None:
            return
        self.current.add_preset(p.duplicate())
        self.load_presets(self.current)

    def delete_preset(self):
        p = self.current_preset()
        if p is None:
            return
        self.current.presets.remove(p)
        self.load_presets(self.current)

    # -- assemblages --------------------------------------------------------

    def load_assemblies(self, tool):
        self.a_holder.clear()
        self.a_holder.addItem(tr("(no holder)"), None)
        for h in sorted(self.lib.holders.values(), key=lambda h: h.name):
            self.a_holder.addItem(h.name, h.id)
        self.asm_list.clear()
        self._assemblies = self.lib.assemblies_for_tool(tool.id)
        for a in self._assemblies:
            self.asm_list.addItem(asm_label(a))
        if self._assemblies:
            self.asm_list.setCurrentRow(0)

    def current_assembly(self):
        row = self.asm_list.currentRow()
        if row < 0 or row >= len(self._assemblies):
            return None
        return self._assemblies[row]

    def on_assembly_selected(self, _row):
        a = self.current_assembly()
        if a is None:
            return
        self.a_name.setText(a.name)
        self.a_holder.setCurrentIndex(max(self.a_holder.findData(a.holder_id), 0))
        self.a_stickout.setValue(a.stickout or 0.0)
        self.a_gauge.setText("%.2f" % a.gauge_length if a.gauge_length else "-")
        self.a_number.setValue(a.output.tool_number)
        self.a_len_off.setValue(a.output.length_offset)
        self.a_dia_off.setValue(a.output.diameter_offset)
        self.a_manual.setChecked(a.output.manual_tool_change)
        self.a_comment.setText(a.output.comment)
        self.update_preview()

    def apply_assembly(self):
        a = self.current_assembly()
        if a is None:
            return
        d = a.to_dict()
        d.update({"name": self.a_name.text().strip() or a.name, "holder_id": self.a_holder.currentData(),
                  "stickout": self.a_stickout.value() or None, "gauge_length": None})
        d["output"].update({"tool_number": self.a_number.value(), "length_offset": self.a_len_off.value(),
                            "diameter_offset": self.a_dia_off.value(), "manual_tool_change": self.a_manual.isChecked(),
                            "comment": self.a_comment.text()})
        try:
            new = ToolAssembly.from_dict(d)
            self.lib.resolve_assembly_obj(new)
        except (ValueError, KeyError) as exc:
            _warn(tr_msg(exc))
            return
        self.lib.assemblies[new.id] = new
        self.load_assemblies(self.current)
        self.update_preview()

    def new_assembly(self):
        if self.current is None:
            return
        number = max([a.output.tool_number for a in self.lib.assemblies.values()] + [0]) + 1
        holder_id = next(iter(self.lib.holders), None)
        asm = ToolAssembly("T%d %s" % (number, self.current.name), self.current.id, holder_id,
                           output={"tool_number": number})
        try:
            self.lib.add_assembly(asm)
        except ValueError as exc:
            _warn(tr_msg(exc))
            return
        self.load_assemblies(self.current)
        self.asm_list.setCurrentRow(len(self._assemblies) - 1)

    def delete_assembly(self):
        a = self.current_assembly()
        if a is None:
            return
        self.lib.remove_assembly(a.id)
        self.load_assemblies(self.current)

    def new_holder(self):
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(tr("New holder"))
        form = QtWidgets.QFormLayout(dlg)
        name = QtWidgets.QLineEdit("ER20")
        form.addRow(tr("Name"), name)
        segs = QtWidgets.QPlainTextEdit("28 28 20\n28 34 15")
        form.addRow(tr("Segments (lower upper length, one per line, from nose up)"), segs)
        bore = QtWidgets.QDoubleSpinBox()
        bore.setRange(0, 100)
        bore.setSpecialValueText(tr("(any)"))
        form.addRow(tr("Bore diameter (mm)"), bore)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        if exec_dialog(dlg) != QtWidgets.QDialog.Accepted:
            return
        try:
            segments = []
            for line in segs.toPlainText().splitlines():
                parts = line.replace(",", ".").split()
                if len(parts) != 3:
                    raise ValueError(tr("Each segment line needs three numbers"))
                segments.append({"lower_diameter": float(parts[0]), "upper_diameter": float(parts[1]), "length": float(parts[2])})
            holder = Holder(name.text().strip() or "Holder", segments, bore_diameter=bore.value() or None)
            self.lib.add_holder(holder)
        except ValueError as exc:
            _warn(tr_msg(exc))
            return
        if self.current is not None:
            self.load_assemblies(self.current)

    # -- aperçu / 3D ----------------------------------------------------------

    def update_preview(self):
        a = self.current_assembly()
        holder = self.lib.holders.get(a.holder_id) if a and a.holder_id else None
        self.preview.set_tool(self.current, holder, a.stickout if a else None)

    def show_in_3d(self):
        if self.current is None:
            return
        doc = FreeCAD.ActiveDocument or FreeCAD.newDocument("ToolPreview")
        obj, warnings = bridge.create_toolbit(doc, self.current)
        if obj.ViewObject:
            obj.ViewObject.Visibility = True
        doc.recompute()
        FreeCADGui.SendMsgToActiveView("ViewFit")
        if warnings:
            _info("\n".join(warnings))

    # -- fichiers -----------------------------------------------------------

    def save_library(self):
        try:
            path = self.lib.save()
        except (ValueError, OSError) as exc:
            _warn(tr_msg(exc))
            return
        self.refresh_list()
        self.status.setText(tr("Library saved: {path} (revision {rev})", path=path, rev=self.lib.revision))

    def add_starter_tools(self):
        from ..tools.library import merge_starter_tools

        added = merge_starter_tools(self.lib)
        self.refresh_list()
        if added:
            self.status.setText(tr("Added starter tools: {names} (not saved yet)", names=", ".join(added)))
        else:
            self.status.setText(tr("No starter tool missing."))

    def import_fusion(self):
        path, _f = QtWidgets.QFileDialog.getOpenFileName(self, tr("Import a Fusion tool library"), "",
                                                         "Fusion (*.json *.tools);;All (*.*)")
        if not path:
            return
        try:
            report = import_fusion_library(path, self.lib)
        except (ValueError, OSError) as exc:
            _warn(tr_msg(exc))
            return
        self.refresh_list()
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle(tr("Fusion import report"))
        box.setText(tr("Imported {n} tool(s), skipped {s} (details below).", n=len(report.imported), s=len(report.skipped)))
        box.setDetailedText(report.to_text())
        exec_dialog(box)

    def export_library(self):
        path, _f = QtWidgets.QFileDialog.getSaveFileName(self, tr("Export the library"), "library.cam2027tools",
                                                         "CAM2027 (*.cam2027tools)")
        if path:
            self.lib.save(path)
            self.lib.path = state.library().path

    def import_library(self):
        from ..tools.library import ToolLibrary

        path, _f = QtWidgets.QFileDialog.getOpenFileName(self, tr("Open a library"), "", "CAM2027 (*.cam2027tools)")
        if not path:
            return
        try:
            lib = ToolLibrary.load(path)
        except (ValueError, OSError, KeyError) as exc:
            _warn(tr_msg(exc))
            return
        state.set_library(lib)
        self.lib = lib
        self.current = None
        self.refresh_list()


def _seconds(cycle_time):
    """Durée FreeCAD « HH:MM:SS » (ou vide) en secondes."""
    try:
        parts = [int(p) for p in str(cycle_time or "").split(":")]
    except ValueError:
        return 0
    if len(parts) != 3:
        return 0
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def _hms(seconds):
    return "%02d:%02d:%02d" % (seconds // 3600, (seconds % 3600) // 60, seconds % 60)


_docks = {}


def _dock(key, title, factory, area=QtCore.Qt.RightDockWidgetArea):
    mw = FreeCADGui.getMainWindow()
    dock = _docks.get(key)
    if dock is None or not _is_alive(dock):
        dock = QtWidgets.QDockWidget(title, mw)
        dock.setObjectName("CAM2027_" + key)
        widget = factory()
        theme.apply(widget)
        dock.setWidget(widget)
        mw.addDockWidget(area, dock)
        mw.restoreDockWidget(dock)  # position mémorisée par FreeCAD à la fermeture (état de la fenêtre)
        _docks[key] = dock
    dock.show()
    dock.raise_()
    return dock


def _is_alive(widget):
    try:
        widget.objectName()
        return True
    except RuntimeError:
        return False


def restyle_all():
    """Réapplique le thème courant aux panneaux CAM2027 ouverts (après changement de thème)."""
    for dock in list(_docks.values()):
        if _is_alive(dock) and dock.widget() is not None:
            theme.apply(dock.widget())
    from . import shell

    if shell._shell is not None:
        shell._shell.restyle()
    refresh_project_panel()


def show_tool_library():
    return _dock("ToolLibrary", tr("CAM2027 tool library"), ToolLibraryPanel, QtCore.Qt.BottomDockWidgetArea)


class _UndoObserver(object):
    """Annuler / Rétablir (Ctrl+Z, Ctrl+Y) : la liste des opérations suit le document. Chaque action CAM2027
    finit par le calcul des parcours, donc l'état rétabli est un état calculé ; FreeCAD marque pourtant les
    objets rétablis « modifiés » (« à recalculer » dans la liste) : la marque est retirée."""

    def slotUndoDocument(self, doc):
        self._restored(doc)

    def slotRedoDocument(self, doc):
        self._restored(doc)

    def _restored(self, doc):
        from ..project import docobjects

        if docobjects.find_info(doc) is not None:
            for obj in doc.Objects:
                if "Touched" in obj.State:
                    obj.purgeTouched()
        QtCore.QTimer.singleShot(0, refresh_project_panel)

    # Le panneau montrait encore l'ancien projet après un changement d'onglet, l'ouverture d'un fichier ou la
    # fermeture du document (différé : à l'ouverture, les fournisseurs de vue sont relus après le document).

    def slotActivateDocument(self, doc):
        QtCore.QTimer.singleShot(0, _document_activated)

    def slotDeletedDocument(self, doc):
        QtCore.QTimer.singleShot(0, refresh_project_panel)
        QtCore.QTimer.singleShot(250, refresh_project_panel)  # le document est encore listé pendant le signal


def _document_activated():
    proj = state.active_project()
    if proj is not None and proj.has_job:
        from ..project.project import attach_job_view

        attach_job_view(proj.job)  # projet enregistré avant que le job ait son fournisseur de vue
    from . import shell

    shell.document_activated(FreeCAD.ActiveDocument)
    refresh_project_panel()


_undo_observer = None


def ensure_project_panel():
    """Navigateur métier (dock « CAM2027_Project » de la coquille) ; l'observateur du document est posé une fois."""
    global _undo_observer
    if _undo_observer is None:
        _undo_observer = _UndoObserver()
        FreeCAD.addDocumentObserver(_undo_observer)
    from . import shell

    s = shell.install()
    return s.nav_dock if s is not None else None


class _OperationTree(QtWidgets.QTreeWidget):
    """Liste des opérations : ordre d'usinage changé par glisser-déposer (ou Alt+Haut / Alt+Bas). Qt ne
    déplace rien lui-même : le rang visé est transmis au projet, qui réordonne le job puis la liste est
    reconstruite (positionnements A recréés)."""

    def __init__(self, on_move):
        super(_OperationTree, self).__init__()
        self.on_move = on_move
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
        self.setDefaultDropAction(QtCore.Qt.MoveAction)

    def _op_rank(self, row):
        """Rang parmi les opérations (lignes de positionnement A non comptées) de la ligne ``row``."""
        rank = 0
        for i in range(min(row, self.topLevelItemCount())):
            if self.topLevelItem(i).flags() & QtCore.Qt.ItemIsDragEnabled:
                rank += 1
        return rank

    def drop_rank(self, src_row, target_row, where):
        """Rang visé (parmi les opérations) quand la ligne ``src_row`` est déposée ``where`` (« above »,
        « below », « on », « end ») la ligne ``target_row`` (None : sous la dernière)."""
        if target_row is None or where == "end":
            row = self.topLevelItemCount()
        else:
            row = target_row
            if where == "below" or (where == "on" and target_row > src_row):  # sur une ligne : prend sa place
                row += 1
        rank = self._op_rank(row)
        if row > src_row:
            rank -= 1  # la ligne déplacée libère sa place
        return max(0, rank)

    def dropEvent(self, event):
        source = self.currentItem()
        if source is None:
            event.ignore()
            return
        target = self.itemAt(_event_pos(event))
        pos = self.dropIndicatorPosition()
        where = {QtWidgets.QAbstractItemView.AboveItem: "above", QtWidgets.QAbstractItemView.BelowItem: "below",
                 QtWidgets.QAbstractItemView.OnItem: "on"}.get(pos, "end")
        rank = self.drop_rank(self.indexOfTopLevelItem(source),
                              None if target is None else self.indexOfTopLevelItem(target), where)
        event.setDropAction(QtCore.Qt.IgnoreAction)
        event.accept()
        name = source.data(0, QtCore.Qt.UserRole)
        QtCore.QTimer.singleShot(0, lambda: self.on_move(name, rank))

    def keyPressEvent(self, event):
        if event.modifiers() & QtCore.Qt.AltModifier and event.key() in (QtCore.Qt.Key_Up, QtCore.Qt.Key_Down):
            item = self.currentItem()
            if item is not None and item.flags() & QtCore.Qt.ItemIsDragEnabled:
                row = self.indexOfTopLevelItem(item)
                rank = self._op_rank(row) + (-1 if event.key() == QtCore.Qt.Key_Up else 1)
                self.on_move(item.data(0, QtCore.Qt.UserRole), max(0, rank))
            event.accept()
            return
        super(_OperationTree, self).keyPressEvent(event)


def _event_pos(event):
    pos = event.position() if hasattr(event, "position") else event.pos()
    return pos.toPoint() if hasattr(pos, "toPoint") else pos


def refresh_project_panel():
    from ..project import operations as opsmod

    if opsmod.GuiTicker.defer(refresh_project_panel):  # calcul en cours : une fois à la fin
        return
    from . import shell

    shell.refresh()
