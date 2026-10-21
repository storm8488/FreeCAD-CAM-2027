# SPDX-License-Identifier: LGPL-2.1-or-later
"""Choix de l'outil d'une opération, comme Fusion : « Outil [Sélectionner…] [Éditer…] ».

« Sélectionner… » ouvre la bibliothèque d'outils (outils compatibles avec la stratégie, recherche, type,
aperçu) où l'on choisit un outil ou en crée un nouveau. Les assemblages (outil + porte-outil + sortie) ne
sont plus montrés : chaque outil a le sien, créé automatiquement (``ToolLibrary.ensure_usable``) ; c'est
lui que l'opération enregistre (contrôle des collisions, numéro d'outil). Un outil choisi qui n'est pas
encore dans l'instantané du projet y est ajouté (``Project.merge_library``).
"""

from .qt import QtCore, QtGui, QtWidgets, exec_dialog
from ..i18n import tr, tr_msg
from ..tools.model import ToolDefinition, TOOL_TYPES
from . import state, theme
from .preview import ToolPreview


def tool_label(tool, number=None):
    """« #1 - Ø6 mm (6 mm flat end mill 2F) » : numéro, diamètre, nom (comme la liste de Fusion)."""
    head = ("#%d - " % number) if number else ""
    return "%sØ%.4g mm (%s)" % (head, tool.geometry.diameter, tool.name)


def _number(lib, tool_id):
    nums = [a.output.tool_number for a in lib.assemblies.values() if a.tool_id == tool_id]
    return min(nums) if nums else None


def _all_tools(proj):
    """Outils de la bibliothèque de l'utilisateur, puis ceux qui ne sont que dans l'instantané du projet
    (projet venu d'un autre poste) : ``[(outil, bibliothèque d'où il vient)]``."""
    user = state.library()
    out = [(t, user) for t in user.tools.values()]
    seen = set(user.tools)
    snap = proj.library
    out += [(t, snap) for t in snap.tools.values() if t.id not in seen]
    return out


def assembly_for(proj, tool_id):
    """Assemblage de l'outil dans l'instantané du projet (l'outil y est ajouté s'il le faut) ; None si
    l'outil est introuvable."""
    user = state.library()
    if tool_id in user.tools:
        if user.ensure_usable(tool_id, tr("New preset")):
            try:
                user.save()
            except (ValueError, OSError):
                pass
        proj.merge_library(user)
    lib = proj.library
    asms = sorted(lib.assemblies_for_tool(tool_id), key=lambda a: a.output.tool_number)
    if not asms and tool_id in lib.tools:
        lib.ensure_usable(tool_id, tr("New preset"))
        proj.update_library_snapshot(lib)
        lib = proj.library
        asms = sorted(lib.assemblies_for_tool(tool_id), key=lambda a: a.output.tool_number)
    return asms[0].id if asms else None


class ToolField(QtWidgets.QWidget):
    """Champ « Outil » d'une opération, comme Fusion : « Sélectionner… » (bibliothèque complète) et
    « Éditer… », puis la liste déroulante des outils déjà utilisés dans ce document (et l'outil choisi).
    ``currentData()`` : assemblage choisi (dans l'instantané du projet)."""

    changed = QtCore.Signal()

    def __init__(self, proj, kind=None, parent=None, accept=None):
        super(ToolField, self).__init__(parent)
        self.proj = proj
        self.kind = kind
        self.accept = accept  # filtre propre au dialogue (fraise plate, V-bit...) ; sinon la stratégie
        self._asm_id = None
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        row = QtWidgets.QHBoxLayout()
        self.select_button = QtWidgets.QPushButton(tr("Select..."))
        self.select_button.setToolTip(tr("Choose a tool in the tool library, or create a new one"))
        self.select_button.clicked.connect(self.select)
        row.addWidget(self.select_button)
        self.edit_button = QtWidgets.QPushButton(tr("Edit..."))
        self.edit_button.setToolTip(tr("Open this tool in the tool library"))
        self.edit_button.clicked.connect(self.edit)
        row.addWidget(self.edit_button)
        row.addStretch(1)
        lay.addLayout(row)
        self.combo = QtWidgets.QComboBox()
        self.combo.setToolTip(tr("Tools already used in this document"))
        self.combo.activated.connect(self._on_combo)
        lay.addWidget(self.combo)

    # -- valeur ------------------------------------------------------------------------------------

    def currentData(self):
        return self._asm_id

    def tool(self):
        if not self._asm_id:
            return None
        lib = self.proj.library
        return lib.tool(lib.assembly(self._asm_id).tool_id)

    def _used(self):
        """Assemblages des opérations du projet (dans l'ordre des numéros d'outil), sans doublon."""
        lib = self.proj.library
        ids = []
        for rec in (self.proj.registry if self.proj.has_job else {}).values():
            aid = rec.get("assembly_id")
            if aid and aid in lib.assemblies and aid not in ids:
                ids.append(aid)
        return sorted(ids, key=lambda aid: lib.assembly(aid).output.tool_number)

    def _fill(self):
        lib = self.proj.library
        ids = self._used()
        if self._asm_id and self._asm_id not in ids:
            ids.insert(0, self._asm_id)
        self.combo.blockSignals(True)
        self.combo.clear()
        for aid in ids:
            a = lib.assembly(aid)
            self.combo.addItem(tool_label(lib.tool(a.tool_id), a.output.tool_number), aid)
        idx = self.combo.findData(self._asm_id)
        self.combo.setCurrentIndex(idx)
        self.combo.blockSignals(False)

    def set_assembly(self, asm_id):
        self._asm_id = asm_id
        self._fill()
        tool = self.tool()
        self.edit_button.setEnabled(tool is not None)
        self.combo.setToolTip("%s - %s" % (tool.name, tr(tool.type_label())) if tool is not None
                              else tr("Tools already used in this document"))
        self.changed.emit()

    def _on_combo(self, index):
        aid = self.combo.itemData(index)
        if aid and aid != self._asm_id:
            self.set_assembly(aid)

    def fits(self, tool):
        from ..project.operations import tool_fits

        if self.accept is not None:
            return bool(self.accept(tool))
        return tool_fits(self.kind, tool) if self.kind else True

    def set_kind(self, kind, pick_default=True):
        """Stratégie changée : garde l'outil s'il convient ; sinon un outil compatible déjà utilisé dans le
        document, à défaut le meilleur outil compatible de la bibliothèque du projet."""
        from ..project.operations import tool_rank

        self.kind = kind
        tool = self.tool()
        if tool is not None and (self.fits(tool) or not pick_default):
            return
        lib = self.proj.library
        used = [aid for aid in self._used() if self.fits(lib.tool(lib.assembly(aid).tool_id))]
        if used:
            self.set_assembly(used[0])
            return
        fitting = [a for a in lib.assemblies.values() if self.fits(lib.tool(a.tool_id))]
        fitting.sort(key=lambda a: (tool_rank(kind, lib.tool(a.tool_id)) if kind else 0, a.output.tool_number))
        self.set_assembly(fitting[0].id if fitting else None)

    # -- boutons -----------------------------------------------------------------------------------

    def select(self):
        current = self.tool()
        dlg = ToolPickerDialog(self.proj, self.kind, current.id if current is not None else None, self, fits=self.fits)
        if exec_dialog(dlg) != QtWidgets.QDialog.Accepted or dlg.selected is None:
            return
        asm_id = assembly_for(self.proj, dlg.selected)
        if asm_id is not None:
            self.set_assembly(asm_id)

    def edit(self):
        tool = self.tool()
        if tool is None:
            return
        from . import panels

        dock = panels.show_tool_library()
        panel = dock.widget() if dock is not None else None
        if panel is not None and hasattr(panel, "show_tool"):
            panel.show_tool(tool.id)


class ToolPickerDialog(QtWidgets.QDialog):
    """« Sélectionner l'outil » : tableau des outils (numéro, Ø, nom, type, rayon de bout, longueur de dent),
    recherche, type, outils compatibles avec la stratégie seulement, aperçu, « Nouvel outil… »."""

    COLUMNS = ("Name", "Type", "Corner radius", "Diameter", "Flute length")

    def __init__(self, proj, kind=None, current_tool_id=None, parent=None, fits=None):
        super(ToolPickerDialog, self).__init__(parent)
        self.fits = fits
        theme.apply(self)
        self.setWindowTitle(tr("Select the tool"))
        self.resize(1160, 600)
        self.proj = proj
        self.kind = kind
        self.selected = None
        lay = QtWidgets.QVBoxLayout(self)
        top = QtWidgets.QHBoxLayout()
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText(tr("Search (name, type, diameter)"))
        self.search.textChanged.connect(self.refresh)
        top.addWidget(self.search, 2)
        self.type_filter = QtWidgets.QComboBox()
        self.type_filter.addItem(tr("All types"), None)
        for key, (label, _f) in TOOL_TYPES.items():
            self.type_filter.addItem(tr(label), key)
        self.type_filter.currentIndexChanged.connect(self.refresh)
        top.addWidget(self.type_filter, 1)
        self.only_fitting = QtWidgets.QCheckBox(tr("Only tools suited to the strategy"))
        self.only_fitting.setChecked(kind is not None or fits is not None)
        self.only_fitting.setEnabled(kind is not None or fits is not None)
        self.only_fitting.toggled.connect(self.refresh)
        top.addWidget(self.only_fitting)
        new_btn = QtWidgets.QPushButton(tr("New tool..."))
        new_btn.clicked.connect(self.new_tool)
        top.addWidget(new_btn)
        lay.addLayout(top)
        split = QtWidgets.QSplitter()
        self.table = QtWidgets.QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels([tr(c) for c in self.COLUMNS])
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        for col in range(1, len(self.COLUMNS)):
            header.setSectionResizeMode(col, QtWidgets.QHeaderView.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._on_select)
        self.table.cellDoubleClicked.connect(lambda _r, _c: self._accept_selected())
        split.addWidget(self.table)
        self.preview = ToolPreview()
        split.addWidget(self.preview)
        split.setSizes([820, 300])
        lay.addWidget(split, 1)
        self.empty = QtWidgets.QLabel()
        theme.set_role(self.empty, "warning")
        lay.addWidget(self.empty)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText(tr("Select"))
        buttons.accepted.connect(self._accept_selected)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.ok_button = buttons.button(QtWidgets.QDialogButtonBox.Ok)
        self.refresh(select=current_tool_id)

    def _rows(self):
        from ..project.operations import tool_fits

        text = self.search.text().strip().lower()
        ttype = self.type_filter.currentData()
        rows = []
        for tool, lib in _all_tools(self.proj):
            if ttype and tool.tool_type != ttype:
                continue
            if self.only_fitting.isChecked():
                ok = self.fits(tool) if self.fits is not None else (not self.kind or tool_fits(self.kind, tool))
                if not ok:
                    continue
            hay = " ".join([tool.name, tr(tool.type_label()), "%.4g" % tool.geometry.diameter]).lower()
            if text and text not in hay:
                continue
            rows.append((_number(lib, tool.id) or 9999, tool, lib))
        rows.sort(key=lambda r: (r[0], r[1].geometry.diameter, r[1].name))
        return rows

    def refresh(self, *_args, select=None):
        keep = select if select is not None else self.selected
        rows = self._rows()
        self.table.setRowCount(len(rows))
        target = -1
        for i, (number, tool, _lib) in enumerate(rows):
            g = tool.geometry
            cells = (tool_label(tool, number if number != 9999 else None), tr(tool.type_label()),
                     "%.4g mm" % g.corner_radius if g.corner_radius else "",
                     "%.4g mm" % g.diameter, "%.4g mm" % g.flute_length)
            for col, value in enumerate(cells):
                item = QtWidgets.QTableWidgetItem(value)
                item.setData(QtCore.Qt.UserRole, tool.id)
                self.table.setItem(i, col, item)
            if tool.id == keep:
                target = i
        self.empty.setText("" if rows else tr("No tool matches: clear the search, untick \"Only tools suited to the strategy\", or create a new tool."))
        self.empty.setVisible(not rows)
        if target < 0 and rows:
            target = 0
        if target >= 0:
            self.table.selectRow(target)
        else:
            self.selected = None
            self.preview.set_tool(None)
        self.ok_button.setEnabled(bool(rows))

    def _on_select(self):
        items = self.table.selectedItems()
        if not items:
            return
        tool_id = items[0].data(QtCore.Qt.UserRole)
        self.selected = tool_id
        for tool, _lib in _all_tools(self.proj):
            if tool.id == tool_id:
                self.preview.set_tool(tool)
                break

    def _accept_selected(self):
        if self.selected is not None:
            self.accept()

    def new_tool(self):
        dlg = NewToolDialog(self.kind, self)
        if exec_dialog(dlg) != QtWidgets.QDialog.Accepted or dlg.tool is None:
            return
        user = state.library()
        user.add_tool(dlg.tool)
        user.ensure_usable(dlg.tool.id, tr("New preset"))
        try:
            user.save()
        except (ValueError, OSError):
            pass
        self.search.clear()
        self.type_filter.setCurrentIndex(0)
        self.refresh(select=dlg.tool.id)


class NewToolDialog(QtWidgets.QDialog):
    """Nouvel outil, l'essentiel seulement (type, nom, diamètre, dents, longueurs, rayon, angle) ; les autres
    champs et les données de coupe se règlent ensuite dans la bibliothèque."""

    def __init__(self, kind=None, parent=None):
        super(NewToolDialog, self).__init__(parent)
        theme.apply(self)
        self.setWindowTitle(tr("New tool"))
        self.tool = None
        from ..project.operations import TOOLS_FOR

        form = QtWidgets.QFormLayout(self)
        self.type = QtWidgets.QComboBox()
        preferred = list(TOOLS_FOR.get(kind, ())) if kind else []
        for key in preferred + [k for k in TOOL_TYPES if k not in preferred]:
            self.type.addItem(tr(TOOL_TYPES[key][0]), key)
        form.addRow(tr("Type"), self.type)
        self.name = QtWidgets.QLineEdit()
        form.addRow(tr("Name"), self.name)

        def spin(value, lo=0.0, hi=1000.0, dec=3):
            w = QtWidgets.QDoubleSpinBox()
            w.setRange(lo, hi)
            w.setDecimals(dec)
            w.setValue(value)
            return w

        self.diameter = spin(6.0, 0.01)
        form.addRow(tr("Diameter (mm)"), self.diameter)
        self.shank = spin(6.0, 0.01)
        form.addRow(tr("Shank diameter (mm)"), self.shank)
        self.flutes = QtWidgets.QSpinBox()
        self.flutes.setRange(1, 64)
        self.flutes.setValue(2)
        form.addRow(tr("Number of flutes"), self.flutes)
        self.flute_length = spin(18.0, 0.01)
        form.addRow(tr("Flute length (mm)"), self.flute_length)
        self.overall = spin(50.0, 0.01)
        form.addRow(tr("Overall length (mm)"), self.overall)
        self.corner = spin(0.0)
        form.addRow(tr("Corner radius (mm)"), self.corner)
        self.angle = spin(60.0, 0.0, 179.0, 2)
        form.addRow(tr("Included angle (deg)"), self.angle)
        self.preview = ToolPreview()
        self.preview.setMinimumHeight(200)
        form.addRow(self.preview)
        self.error = QtWidgets.QLabel()
        theme.set_role(self.error, "warning")
        form.addRow(self.error)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._ok)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.ok_button = buttons.button(QtWidgets.QDialogButtonBox.Ok)
        for w in (self.diameter, self.shank, self.flute_length, self.overall, self.corner, self.angle):
            w.valueChanged.connect(self._update)
        self.flutes.valueChanged.connect(self._update)
        self.type.currentIndexChanged.connect(self._update)
        self.name.textChanged.connect(self._update)
        self.diameter.valueChanged.connect(lambda v: self.shank.setValue(v) if self.shank.value() < v and
                                           self.type.currentData() not in ("facemill",) else None)
        self._update()

    def build(self):
        from ..tools.model import geometry_fields_for

        ttype = self.type.currentData()
        fields = geometry_fields_for(ttype)
        g = {"diameter": self.diameter.value(), "shank_diameter": self.shank.value(),
             "flute_length": self.flute_length.value(), "overall_length": self.overall.value()}
        if "corner_radius" in fields:
            g["corner_radius"] = self.corner.value()
        if "tip_included_angle_deg" in fields:
            g["tip_included_angle_deg"] = self.angle.value()
        if "taper_half_angle_deg" in fields:
            g["taper_half_angle_deg"] = 0.0 if ttype == "facemill" else self.angle.value() / 2.0
        name = self.name.text().strip() or "%s %.4g mm" % (tr(TOOL_TYPES[ttype][0]), self.diameter.value())
        return ToolDefinition(name, ttype, g, flute_count=self.flutes.value())

    def _update(self, *_args):
        from ..tools.model import geometry_fields_for

        fields = geometry_fields_for(self.type.currentData())
        self.corner.setEnabled("corner_radius" in fields)
        self.angle.setEnabled("tip_included_angle_deg" in fields or
                              ("taper_half_angle_deg" in fields and self.type.currentData() != "facemill"))
        try:
            tool = self.build()
        except (ValueError, KeyError, TypeError) as exc:
            self.error.setText(tr_msg(exc) if isinstance(exc, ValueError) else str(exc))
            self.ok_button.setEnabled(False)
            return
        self.error.setText("")
        self.ok_button.setEnabled(True)
        self.preview.set_tool(tool)

    def _ok(self):
        try:
            self.tool = self.build()
        except (ValueError, KeyError, TypeError) as exc:
            self.error.setText(tr_msg(exc) if isinstance(exc, ValueError) else str(exc))
            return
        self.accept()
