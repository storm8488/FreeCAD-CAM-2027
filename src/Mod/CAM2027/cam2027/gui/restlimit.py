# SPDX-License-Identifier: LGPL-2.1-or-later
"""Onglet « Reprise et zone » de l'éditeur d'opération : reprise de matière depuis les opérations précédentes
(``project/rest.py``) et découpe du parcours dans une zone (``project/trim.py``)."""

from .qt import QtWidgets
from ..i18n import tr


class RestLimitTab(object):
    def __init__(self, editor):
        from ..project import rest, trim

        self.editor = editor
        proj, op = editor.proj, editor.op
        self.widget = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(self.widget)
        self.rest_box = None
        if editor.kind in rest.STRATEGIES:
            current = rest.rest_params(proj, op)
            box = QtWidgets.QGroupBox(tr(rest.LABEL))
            box.setCheckable(True)
            box.setChecked(current is not None)
            form = QtWidgets.QFormLayout(box)
            info = QtWidgets.QLabel(tr("The stock left by the active operations above this one (simulated height map) is the starting stock: only the cuts where the tool meets material are kept, the links between them are recomputed."))
            info.setWordWrap(True)
            info.setProperty("role", "muted")
            form.addRow(info)
            self.ignore = QtWidgets.QDoubleSpinBox()
            self.ignore.setRange(0.0, 50.0)
            self.ignore.setDecimals(3)
            self.ignore.setSuffix(" mm")
            self.ignore.setValue(current["ignore_below"] if current else rest.DEFAULT_IGNORE)
            form.addRow(tr("Ignore stock less than"), self.ignore)
            if current and current.get("report"):
                form.addRow(tr("Last computation"), QtWidgets.QLabel(current["report"]))
            lay.addWidget(box)
            self.rest_box = box

        current = trim.limit_params(proj, op)
        box = QtWidgets.QGroupBox(tr(trim.LABEL))
        box.setCheckable(True)
        box.setChecked(current is not None)
        form = QtWidgets.QFormLayout(box)
        info = QtWidgets.QLabel(tr("Keeps the computed cuts inside (or outside) a rectangle or a closed contour of the drawing, without recomputing the operation; only the links are recomputed (retract, rapid, plunge)."))
        info.setWordWrap(True)
        info.setProperty("role", "muted")
        form.addRow(info)
        self.keep = QtWidgets.QComboBox()
        self.keep.addItem(tr("Keep inside"), True)
        self.keep.addItem(tr("Keep outside"), False)
        self.keep.setCurrentIndex(0 if current is None or current["inside"] else 1)
        form.addRow(tr("Cuts kept"), self.keep)
        try:
            b = proj.stock_bounds()
        except Exception:
            b = {"xmin": 0.0, "ymin": 0.0, "xmax": 100.0, "ymax": 100.0}
        self.rect = {}
        for key, label in (("xmin", "X min"), ("ymin", "Y min"), ("xmax", "X max"), ("ymax", "Y max")):
            spin = QtWidgets.QDoubleSpinBox()
            spin.setRange(-100000.0, 100000.0)
            spin.setDecimals(3)
            spin.setSuffix(" mm")
            spin.setValue(float(b[key]))
            form.addRow(tr(label), spin)
            self.rect[key] = spin
        self.polygon = None  # contour choisi par « Contour sélectionné »
        self.source = QtWidgets.QLabel(tr("Rectangle"))
        if current is not None:
            pts = current["polygon"]
            if current["source"] == "rectangle" and len(pts) == 4:
                xs, ys = [p[0] for p in pts], [p[1] for p in pts]
                for key, v in (("xmin", min(xs)), ("ymin", min(ys)), ("xmax", max(xs)), ("ymax", max(ys))):
                    self.rect[key].setValue(v)
            else:
                self.polygon = pts
                self.source.setText(current["source"] or tr("Selected contour"))
        pick = QtWidgets.QPushButton(tr("Use the selected contour"))
        pick.clicked.connect(self.use_selection)
        clear = QtWidgets.QPushButton(tr("Use the rectangle"))
        clear.clicked.connect(self.use_rectangle)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(pick)
        row.addWidget(clear)
        form.addRow(tr("Boundary"), self.source)
        form.addRow(row)
        lay.addWidget(box)
        self.limit_box = box
        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        lay.addStretch(1)

    def use_selection(self, selection=None):
        """Contour fermé sélectionné (face, fil, objet du dessin) ; ``selection`` : liste d'objets FreeCAD (tests)."""
        from ..project import trim

        if selection is None:
            import FreeCADGui

            selection = []
            for s in FreeCADGui.Selection.getSelectionEx():
                if s.SubObjects:
                    selection.extend(s.SubObjects)
                else:
                    selection.append(s.Object.Shape)
        else:
            selection = [getattr(o, "Shape", o) for o in selection]
        try:
            if not selection:
                raise ValueError(tr("Select a closed contour (a face, a closed wire or a drawing contour) in the 3D view first."))
            import Part

            shape = selection[0] if len(selection) == 1 else Part.Compound(selection)
            self.polygon = trim.polygon_from_shape(shape)
        except Exception as exc:
            from ..i18n import tr_msg

            self.status.setText(tr_msg(exc))
            return False
        self.source.setText(tr("Selected contour ({n} points)", n=len(self.polygon)))
        self.limit_box.setChecked(True)
        self.status.setText("")
        return True

    def use_rectangle(self):
        self.polygon = None
        self.source.setText(tr("Rectangle"))

    def state(self):
        rest_state = (self.rest_box.isChecked(), self.ignore.value()) if self.rest_box is not None else None
        return (rest_state, self.limit_box.isChecked(), self.keep.currentIndex(),
                tuple(s.value() for s in self.rect.values()), tuple(self.polygon or ()))

    def apply(self):
        from ..project import rest, trim

        proj, op = self.editor.proj, self.editor.op
        # la reprise d'abord (plus près de l'opération), la zone par-dessus
        if self.rest_box is not None:
            if self.rest_box.isChecked():
                existing = rest.rest_params(proj, op)
                if existing is None or abs(existing["ignore_below"] - self.ignore.value()) > 1e-9:
                    rest.set_rest(proj, op, True, ignore_below=self.ignore.value())
            elif rest.rest_params(proj, op) is not None:
                rest.set_rest(proj, op, False)
        if self.limit_box.isChecked():
            if self.polygon:
                trim.set_limit(proj, op, self.polygon, inside=self.keep.currentData(), source=self.source.text())
            else:
                r = {k: s.value() for k, s in self.rect.items()}
                trim.set_limit(proj, op, trim.rectangle(r["xmin"], r["ymin"], r["xmax"], r["ymax"]),
                               inside=self.keep.currentData(), source="rectangle")
        elif trim.limit_params(proj, op) is not None:
            trim.set_limit(proj, op, None)


def add_tab(editor):
    """Ajoute l'onglet à l'éditeur (toutes les stratégies sauf la gravure enroulée) ; retourne l'onglet ou None."""
    from ..project import wrap

    if editor.kind == wrap.KIND:
        return None
    tab = RestLimitTab(editor)
    from .opeditor import _scrolled

    editor.tabs.addTab(_scrolled(tab.widget), tr("Rest & area"))
    return tab
