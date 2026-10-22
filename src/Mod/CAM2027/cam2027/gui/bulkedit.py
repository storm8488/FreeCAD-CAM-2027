# SPDX-License-Identifier: LGPL-2.1-or-later
"""Dialogue « Comparer et modifier des opérations » : colonnes = opérations, lignes = paramètres communs.

La dernière colonne reçoit une nouvelle valeur, appliquée à toutes les opérations cochées ; « Différences
seulement » masque les paramètres identiques partout."""

from ..i18n import tr
from ..project import bulkedit
from . import theme
from .qt import QtCore, QtGui, QtWidgets


def _text(kind, value):
    if kind == "bool":
        return tr("yes") if value else tr("no")
    if kind in ("length", "angle", "float"):
        return ("%.4f" % value).rstrip("0").rstrip(".")
    return str(value)


class BulkEditDialog(QtWidgets.QDialog):
    def __init__(self, proj, selected=None, parent=None):
        super(BulkEditDialog, self).__init__(parent)
        theme.apply(self)
        self.proj = proj
        self.setWindowTitle(tr("Compare and edit operations"))
        self.resize(900, 600)
        lay = QtWidgets.QVBoxLayout(self)
        self.all_ops = bulkedit.editable_operations(proj)
        chosen = set(o.Name for o in bulkedit.editable_operations(proj, selected)) if selected else None
        self.op_list = QtWidgets.QListWidget()
        self.op_list.setMaximumHeight(110)
        for op in self.all_ops:
            item = QtWidgets.QListWidgetItem(op.Label)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Checked if chosen is None or op.Name in chosen else QtCore.Qt.Unchecked)
            item.setData(QtCore.Qt.UserRole, op.Name)
            self.op_list.addItem(item)
        lay.addWidget(QtWidgets.QLabel(tr("Operations to compare")))
        lay.addWidget(self.op_list)
        self.diff_only = QtWidgets.QCheckBox(tr("Differences only"))
        lay.addWidget(self.diff_only)
        self.table = QtWidgets.QTableWidget()
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        lay.addWidget(self.table, 1)
        hint = QtWidgets.QLabel(tr("Type a value in the last column: it is written to every checked operation, which is then recomputed. Rows in bold differ between the operations."))
        hint.setWordWrap(True)
        theme.set_role(hint, "muted")
        lay.addWidget(hint)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.editors = {}
        self.op_list.itemChanged.connect(lambda _i: self._build())
        self.diff_only.toggled.connect(self._filter)
        self._build()

    def operations(self):
        names = [self.op_list.item(i).data(QtCore.Qt.UserRole) for i in range(self.op_list.count())
                 if self.op_list.item(i).checkState() == QtCore.Qt.Checked]
        return [op for op in self.all_ops if op.Name in names]

    def _build(self):
        pending = {name: self.value_text(name) for name in self.editors}  # saisies gardées si la sélection change
        ops = self.operations()
        self.rows = bulkedit.compare(self.proj, ops) if ops else []
        self.table.clear()
        self.table.setColumnCount(len(ops) + 2)
        self.table.setRowCount(len(self.rows))
        self.table.setHorizontalHeaderLabels([tr("Parameter")] + [op.Label for op in ops] + [tr("New value (all)")])
        self.editors = {}
        bold = QtGui.QFont()
        bold.setBold(True)
        for r, row in enumerate(self.rows):
            head = QtWidgets.QTableWidgetItem(tr(row["label"]))
            head.setToolTip(tr(row["help"]) if row["help"] else "")
            if row["differs"]:
                head.setFont(bold)
            self.table.setItem(r, 0, head)
            for c, value in enumerate(row["values"], 1):
                self.table.setItem(r, c, QtWidgets.QTableWidgetItem(_text(row["kind"], value)))
            if row["kind"] in ("enum", "bool"):
                editor = QtWidgets.QComboBox()
                editor.addItem(tr("(unchanged)"), None)
                if row["kind"] == "bool":
                    editor.addItem(tr("yes"), "true")
                    editor.addItem(tr("no"), "false")
                else:
                    for choice in row["choices"]:
                        editor.addItem(tr(choice), choice)
                if pending.get(row["name"]):
                    editor.setCurrentIndex(max(0, editor.findData(pending[row["name"]])))
            else:
                editor = QtWidgets.QLineEdit(pending.get(row["name"]) or "")
                editor.setPlaceholderText(tr("(unchanged)"))
            self.table.setCellWidget(r, len(ops) + 1, editor)
            self.editors[row["name"]] = editor
        self.table.resizeColumnsToContents()
        self._filter()

    def _filter(self, *_a):
        for r, row in enumerate(self.rows):
            self.table.setRowHidden(r, self.diff_only.isChecked() and not row["differs"])

    def value_text(self, name):
        editor = self.editors.get(name)
        if editor is None:
            return None
        if isinstance(editor, QtWidgets.QComboBox):
            return editor.currentData()
        return editor.text().strip() or None

    def set_value(self, name, text):
        """Saisie dans la colonne « Nouvelle valeur » (pilote des scénarios)."""
        editor = self.editors[name]
        if isinstance(editor, QtWidgets.QComboBox):
            editor.setCurrentIndex(editor.findData(text))
        else:
            editor.setText(text)

    def changes(self):
        """``{paramètre: valeur}`` saisis ; ValueError (libellé, texte) sur une saisie illisible."""
        out = {}
        for row in self.rows:
            text = self.value_text(row["name"])
            if text is None:
                continue
            try:
                out[row["name"]] = bulkedit.parse(row["kind"], text, row["choices"])
            except ValueError:
                raise ValueError(tr("{param}: invalid value {value}", param=tr(row["label"]), value=text))
        return out

    def apply(self):
        ops = self.operations()
        changes = self.changes()
        if not ops or not changes:
            return {}
        return bulkedit.apply(self.proj, ops, changes)
