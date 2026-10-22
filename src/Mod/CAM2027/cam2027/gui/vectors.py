# SPDX-License-Identifier: LGPL-2.1-or-later
"""Dessin vectoriel : dialogues et commandes (texte, texte sur courbe, décalage, booléens, miroir, copies
circulaires). La géométrie est dans ``project/vectors.py`` ; chaque commande crée un nouveau vecteur du
dessin (l'original est gardé, masqué pour le décalage et les booléens, comme Aspire)."""

import FreeCAD
import FreeCADGui

from ..i18n import tr, tr_msg
from ..project import sheet as sheetmod
from ..project import vectors as vecmod
from . import commands as base
from . import theme
from .qt import QtWidgets


def _spin(lo, hi, value, decimals=2):
    s = QtWidgets.QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(decimals)
    s.setValue(value)
    return s


def _vector_combo(proj, selected, closed=True):
    combo = QtWidgets.QComboBox()
    names = [o.Name for o in selected]
    rank = lambda o: (names.index(o.Name) if o.Name in names else len(names), o.Label)  # sélection d'abord, dans l'ordre
    for obj in sorted(sheetmod.vector_objects(proj.doc), key=rank):
        if not closed or vecmod.closed_wires_of(obj.Shape):
            combo.addItem(obj.Label, obj.Name)
    return combo


class _VectorDialog(QtWidgets.QDialog):
    title = ""

    def __init__(self, proj, parent=None, selected=()):
        super(_VectorDialog, self).__init__(parent)
        theme.apply(self)
        self.proj = proj
        self.selected = list(selected)
        self.setWindowTitle(tr(self.title))
        self.form = QtWidgets.QFormLayout(self)
        self.build()
        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        theme.set_role(self.status, "muted")
        self.form.addRow(self.status)
        if hasattr(self, "_kind"):
            self._kind()
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        self.form.addRow(bb)
        self.ok = bb.button(QtWidgets.QDialogButtonBox.Ok)

    def build(self):
        pass

    def obj(self, combo):
        return self.proj.doc.getObject(combo.currentData()) if combo.currentData() else None


class TextDialog(_VectorDialog):
    title = "Text"

    def build(self):
        f = self.form
        self.text = QtWidgets.QLineEdit("CAM2027")
        f.addRow(tr("Text"), self.text)
        self.font = QtWidgets.QComboBox()
        for name, path in vecmod.fonts():
            self.font.addItem(name, path)
        f.addRow(tr("Font"), self.font)
        self.size = _spin(0.5, 1000, 10.0)
        f.addRow(tr("Letter height (mm)"), self.size)
        self.spacing = _spin(-50, 200, 0.0)
        f.addRow(tr("Extra letter spacing (mm)"), self.spacing)
        self.layout_kind = QtWidgets.QComboBox()
        self.layout_kind.addItem(tr("Straight line"), "line")
        self.layout_kind.addItem(tr("On an arc"), "arc")
        self.layout_kind.addItem(tr("Along a drawing vector"), "curve")
        f.addRow(tr("Layout"), self.layout_kind)
        self.x = _spin(-10000, 10000, 0.0)
        self.y = _spin(-10000, 10000, 0.0)
        f.addRow(tr("Position X (mm)"), self.x)
        f.addRow(tr("Position Y (mm)"), self.y)
        self.radius = _spin(1, 10000, 40.0)
        self.span = _spin(10, 360, 180.0, 1)
        self.below = QtWidgets.QCheckBox(tr("Text under the arc (reads along the bottom)"))
        f.addRow(tr("Arc radius (mm)"), self.radius)
        f.addRow(tr("Arc angle (°)"), self.span)
        f.addRow("", self.below)
        self.curve = _vector_combo(self.proj, self.selected, closed=False)
        f.addRow(tr("Curve"), self.curve)
        self.layout_kind.currentIndexChanged.connect(self._kind)
        self._kind()

    def _kind(self, *_a):
        k = self.layout_kind.currentData()
        for w in (self.radius, self.span, self.below):
            w.setEnabled(k == "arc")
        self.curve.setEnabled(k == "curve")
        hints = {"line": tr("X, Y: start of the baseline."), "arc": tr("X, Y: centre of the arc; the text is centred on its top."),
                 "curve": tr("The text is centred along the vector, upright on its left side (reverse the vector to flip it).")}
        if hasattr(self, "status"):
            self.status.setText(hints[k])

    def shape(self):
        k = self.layout_kind.currentData()
        font, size, spacing = self.font.currentData(), self.size.value(), self.spacing.value()
        if k == "line":
            return vecmod.text_shape(self.text.text(), font, size, spacing, (self.x.value(), self.y.value()))
        if k == "arc":
            below = self.below.isChecked()
            rail = vecmod.arc_rail((self.x.value(), self.y.value()), self.radius.value(), self.span.value(), top=not below)
            return vecmod.text_on_curve(self.text.text(), rail, font, size, spacing, below=below)
        curve = self.obj(self.curve)
        if curve is None:
            raise ValueError(tr("Choose the curve"))
        return vecmod.text_on_curve(self.text.text(), curve.Shape, font, size, spacing)

    def apply(self):
        return vecmod.add_vector(self.proj, self.shape(), self.text.text())


class OffsetDialog(_VectorDialog):
    title = "Offset vector"

    def build(self):
        self.source = _vector_combo(self.proj, self.selected)
        self.form.addRow(tr("Closed vector"), self.source)
        self.distance = _spin(-500, 500, 2.0, 3)
        self.distance.setToolTip(tr("Positive: outwards; negative: inwards."))
        self.form.addRow(tr("Distance (mm)"), self.distance)
        self.corners = QtWidgets.QComboBox()
        self.corners.addItem(tr("Round corners"), "round")
        self.corners.addItem(tr("Sharp corners"), "sharp")
        self.form.addRow(tr("Corners"), self.corners)

    def apply(self):
        src = self.obj(self.source)
        shape = vecmod.offset(src.Shape, self.distance.value(), self.corners.currentData())
        return vecmod.add_vector(self.proj, shape, tr("{name} offset {d} mm", name=src.Label, d="%g" % self.distance.value()))


class BooleanDialog(_VectorDialog):
    title = "Combine vectors"

    def build(self):
        self.first = _vector_combo(self.proj, self.selected)
        self.second = _vector_combo(self.proj, self.selected[1:] + self.selected[:1])
        self.mode = QtWidgets.QComboBox()
        self.mode.addItem(tr("Union (weld)"), "union")
        self.mode.addItem(tr("Subtract the second from the first"), "subtract")
        self.mode.addItem(tr("Intersection"), "intersect")
        self.form.addRow(tr("First vector"), self.first)
        self.form.addRow(tr("Second vector"), self.second)
        self.form.addRow(tr("Operation"), self.mode)

    def apply(self):
        a, b = self.obj(self.first), self.obj(self.second)
        if a is None or b is None or a.Name == b.Name:
            raise ValueError(tr("Choose two different vectors"))
        shape = vecmod.boolean(a.Shape, b.Shape, self.mode.currentData())
        return vecmod.add_vector(self.proj, shape, "%s %s %s" % (a.Label, {"union": "+", "subtract": "-", "intersect": "x"}[self.mode.currentData()], b.Label))


class MirrorDialog(_VectorDialog):
    title = "Mirror vector"

    def build(self):
        self.source = _vector_combo(self.proj, self.selected, closed=False)
        self.form.addRow(tr("Vector"), self.source)
        self.axis = QtWidgets.QComboBox()
        self.axis.addItem(tr("Left - right (vertical axis)"), "x")
        self.axis.addItem(tr("Top - bottom (horizontal axis)"), "y")
        self.form.addRow(tr("Mirror"), self.axis)

    def apply(self):
        src = self.obj(self.source)
        return vecmod.add_vector(self.proj, vecmod.mirror(src.Shape, self.axis.currentData()), tr("{name} (mirror)", name=src.Label))


class CircularCopiesDialog(_VectorDialog):
    title = "Circular copies"

    def build(self):
        self.source = _vector_combo(self.proj, self.selected, closed=False)
        self.form.addRow(tr("Vector"), self.source)
        self.count = QtWidgets.QSpinBox()
        self.count.setRange(2, 1000)
        self.count.setValue(6)
        self.form.addRow(tr("Number of copies (with the original)"), self.count)
        self.cx = _spin(-10000, 10000, 0.0)
        self.cy = _spin(-10000, 10000, 0.0)
        self.form.addRow(tr("Centre X (mm)"), self.cx)
        self.form.addRow(tr("Centre Y (mm)"), self.cy)
        self.total = _spin(1, 360, 360.0, 1)
        self.form.addRow(tr("Total angle (°)"), self.total)

    def apply(self):
        src = self.obj(self.source)
        shape = vecmod.circular_copies(src.Shape, self.count.value(), (self.cx.value(), self.cy.value()), self.total.value(),
                                       include_original=False)
        return vecmod.add_vector(self.proj, shape, tr("{name} (copies)", name=src.Label))


def _run(dlg_cls, hide_source=False):
    proj = base._need_project()
    if proj is None:
        return None
    sel = [s.Object for s in FreeCADGui.Selection.getSelectionEx() if s.Object.Document.Name == proj.doc.Name]
    dlg = dlg_cls(proj, FreeCADGui.getMainWindow(), selected=sel)
    if dlg_cls is not TextDialog and getattr(dlg, "source", getattr(dlg, "first", None)) is not None \
            and getattr(dlg, "source", getattr(dlg, "first", None)).count() == 0:
        base._warn(tr("No drawing vector in the project: import an SVG / DXF or draw a text first."))
        return None
    if base.exec_dialog(dlg) != QtWidgets.QDialog.Accepted:
        return None
    try:
        obj = dlg.apply()
    except Exception as exc:
        base._warn(tr("Operation failed: {error}", error=tr_msg(exc)))
        return None
    if hide_source and FreeCAD.GuiUp:
        for combo in (getattr(dlg, "source", None), getattr(dlg, "first", None), getattr(dlg, "second", None)):
            src = dlg.obj(combo) if combo is not None else None
            if src is not None and src.ViewObject is not None:
                src.ViewObject.Visibility = False
    FreeCADGui.Selection.clearSelection()
    FreeCADGui.Selection.addSelection(obj)
    base._after_change()
    return obj


class DrawText(base._Base):
    atelier = "engrave"
    text = "Text"
    tooltip = "Draw a text (font, height), straight, on an arc or along a vector"

    @base._undoable
    def Activated(self):
        _run(TextDialog)


class OffsetVector(base._Base):
    atelier = "contour"
    text = "Offset vector"
    tooltip = "Offset a closed vector outwards or inwards (overlapping shapes are welded)"

    @base._undoable
    def Activated(self):
        _run(OffsetDialog)


class CombineVectors(base._Base):
    atelier = "pocket"
    text = "Combine vectors"
    tooltip = "Union, subtraction or intersection of two closed vectors"

    @base._undoable
    def Activated(self):
        _run(BooleanDialog, hide_source=True)


class MirrorVector(base._Base):
    atelier = "measure"
    text = "Mirror vector"
    tooltip = "Mirror copy of a vector (left - right or top - bottom)"

    @base._undoable
    def Activated(self):
        _run(MirrorDialog)


class CircularCopies(base._Base):
    atelier = "drill"
    text = "Circular copies"
    tooltip = "Copies of a vector rotated around a centre"

    @base._undoable
    def Activated(self):
        _run(CircularCopiesDialog)


COMMANDS = [
    ("CAM2027_DrawText", DrawText),
    ("CAM2027_OffsetVector", OffsetVector),
    ("CAM2027_CombineVectors", CombineVectors),
    ("CAM2027_MirrorVector", MirrorVector),
    ("CAM2027_CircularCopies", CircularCopies),
]
TOOLBAR = [name for name, _cls in COMMANDS]
