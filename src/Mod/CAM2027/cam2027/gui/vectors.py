# SPDX-License-Identifier: LGPL-2.1-or-later
"""Dessin vectoriel : dialogues et commandes (texte, texte sur courbe, rectangle, cercle, polygone, nœuds,
décalage, booléens, miroir, copies circulaires). La géométrie est dans ``project/vectors.py`` ; chaque commande
crée un nouveau vecteur du dessin (l'original est gardé, masqué pour le décalage et les booléens, comme Aspire).

[C4] Texte, rectangle, cercle et polygone sont des vecteurs paramétriques : « Modifier le vecteur » (ou double-clic
dans l'arborescence) rouvre leur dialogue, « Modifier les nœuds » déplace / supprime les nœuds d'une forme à côtés
droits ; les opérations qui les usinent sont recalculées."""

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

    def __init__(self, proj, parent=None, selected=(), edit=None):
        super(_VectorDialog, self).__init__(parent)
        theme.apply(self)
        self.proj = proj
        self.selected = list(selected)
        self.edit = edit  # vecteur paramétrique modifié (None : création)
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
        p = vecmod.params_of(self.edit) if self.edit is not None else dict(
            (n, d) for n, _t, d in vecmod.PROPERTIES["text"])
        self.text = QtWidgets.QLineEdit(p["Text"])
        f.addRow(tr("Text"), self.text)
        self.font = QtWidgets.QComboBox()
        for name, path in vecmod.fonts():
            self.font.addItem(name, path)
        if p.get("Font") and self.font.findData(p["Font"]) < 0:
            self.font.addItem(p["Font"], p["Font"])  # police d'un autre poste : gardée
        if p.get("Font"):
            self.font.setCurrentIndex(self.font.findData(p["Font"]))
        f.addRow(tr("Font"), self.font)
        self.size = _spin(0.5, 1000, p["Size"])
        f.addRow(tr("Letter height (mm)"), self.size)
        self.spacing = _spin(-50, 200, p["Tracking"])
        f.addRow(tr("Extra letter spacing (mm)"), self.spacing)
        self.layout_kind = QtWidgets.QComboBox()
        self.layout_kind.addItem(tr("Straight line"), "line")
        self.layout_kind.addItem(tr("On an arc"), "arc")
        self.layout_kind.addItem(tr("Along a drawing vector"), "curve")
        self.layout_kind.setCurrentIndex(max(0, self.layout_kind.findData(p["Layout"])))
        f.addRow(tr("Layout"), self.layout_kind)
        self.x = _spin(-10000, 10000, p["X"])
        self.y = _spin(-10000, 10000, p["Y"])
        f.addRow(tr("Position X (mm)"), self.x)
        f.addRow(tr("Position Y (mm)"), self.y)
        self.radius = _spin(1, 10000, p["ArcRadius"])
        self.span = _spin(10, 360, p["ArcSpan"], 1)
        self.below = QtWidgets.QCheckBox(tr("Text under the arc (reads along the bottom)"))
        self.below.setChecked(bool(p["Below"]))
        f.addRow(tr("Arc radius (mm)"), self.radius)
        f.addRow(tr("Arc angle (°)"), self.span)
        f.addRow("", self.below)
        rail = self.edit.Rail if self.edit is not None else None
        self.curve = _vector_combo(self.proj, ([rail] if rail is not None else []) + self.selected, closed=False)
        if self.edit is not None:  # le texte ne peut pas suivre son propre tracé
            i = self.curve.findData(self.edit.Name)
            if i >= 0:
                self.curve.removeItem(i)
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

    def params(self):
        k = self.layout_kind.currentData()
        rail = self.obj(self.curve) if k == "curve" else None
        if k == "curve" and rail is None:
            raise ValueError(tr("Choose the curve"))
        return {"Text": self.text.text(), "Font": self.font.currentData() or "", "Size": self.size.value(),
                "Tracking": self.spacing.value(), "Layout": k, "X": self.x.value(), "Y": self.y.value(),
                "ArcRadius": self.radius.value(), "ArcSpan": self.span.value(), "Below": self.below.isChecked(),
                "Rail": rail}

    def shape(self):
        p = self.params()
        if p["Rail"] is not None:
            p["Rail"] = p["Rail"].Shape
        return vecmod.build_shape("text", p)

    def apply(self):
        if self.edit is not None:
            vecmod.update_parametric(self.proj, self.edit, **self.params())
            return self.edit
        return vecmod.add_parametric(self.proj, "text", self.text.text(), **self.params())


class ShapeDialog(_VectorDialog):
    """Rectangle, cercle ou polygone (``kind``), centré en X, Y."""

    kind = ""
    #: (propriété, libellé, mini, maxi, décimales)
    FIELDS = {
        "rectangle": (("X", "Centre X (mm)", -10000, 10000, 2), ("Y", "Centre Y (mm)", -10000, 10000, 2),
                      ("Width", "Width (mm)", 0.01, 10000, 2), ("Height", "Height (mm)", 0.01, 10000, 2),
                      ("CornerRadius", "Corner radius (mm)", 0, 5000, 2), ("Angle", "Rotation (°)", -360, 360, 2)),
        "circle": (("X", "Centre X (mm)", -10000, 10000, 2), ("Y", "Centre Y (mm)", -10000, 10000, 2),
                   ("Radius", "Radius (mm)", 0.01, 10000, 2)),
        "polygon": (("X", "Centre X (mm)", -10000, 10000, 2), ("Y", "Centre Y (mm)", -10000, 10000, 2),
                    ("Radius", "Radius to the corners (mm)", 0.01, 10000, 2), ("Sides", "Number of sides", 3, 200, 0),
                    ("Angle", "Rotation (°)", -360, 360, 2)),
    }

    def build(self):
        p = vecmod.params_of(self.edit) if self.edit is not None else dict(
            (n, d) for n, _t, d in vecmod.PROPERTIES[self.kind])
        self.fields = {}
        for name, label, lo, hi, dec in self.FIELDS[self.kind]:
            if dec == 0:
                w = QtWidgets.QSpinBox()
                w.setRange(int(lo), int(hi))
                w.setValue(int(p[name]))
            else:
                w = _spin(lo, hi, p[name], dec)
            self.form.addRow(tr(label), w)
            self.fields[name] = w

    def params(self):
        return dict((name, w.value()) for name, w in self.fields.items())

    def shape(self):
        return vecmod.build_shape(self.kind, self.params())

    def apply(self):
        if self.edit is not None:
            vecmod.update_parametric(self.proj, self.edit, **self.params())
            return self.edit
        return vecmod.add_parametric(self.proj, self.kind, tr(self.title), **self.params())


class RectangleDialog(ShapeDialog):
    title = "Rectangle"
    kind = "rectangle"


class CircleDialog(ShapeDialog):
    title = "Circle"
    kind = "circle"


class PolygonDialog(ShapeDialog):
    title = "Polygon"
    kind = "polygon"


class NodesDialog(_VectorDialog):
    """Nœuds d'une forme à côtés droits : tableau X / Y modifiable, « Supprimer le nœud », forme fermée ou non."""

    title = "Edit nodes"

    def build(self):
        pts = vecmod.nodes(self.edit)
        self.table = QtWidgets.QTableWidget(len(pts), 2)
        self.table.setHorizontalHeaderLabels([tr("X (mm)"), tr("Y (mm)")])
        for i, (x, y) in enumerate(pts):
            for j, v in enumerate((x, y)):
                self.table.setItem(i, j, QtWidgets.QTableWidgetItem("%.3f" % v))
        self.table.setMinimumHeight(200)
        self.form.addRow(self.table)
        self.delete = QtWidgets.QPushButton(tr("Delete the selected node"))
        self.delete.clicked.connect(self.delete_selected)
        self.form.addRow(self.delete)
        self.closed = QtWidgets.QCheckBox(tr("Closed shape"))
        self.closed.setChecked(self.edit.VectorKind != "polyline" or bool(self.edit.Closed))
        self.form.addRow(self.closed)

    def delete_selected(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.table.removeRow(r)

    def points(self):
        out = []
        for i in range(self.table.rowCount()):
            try:
                out.append(tuple(float(self.table.item(i, j).text().replace(",", ".")) for j in (0, 1)))
            except (AttributeError, ValueError):
                raise ValueError(tr("Node {n}: X and Y must be numbers", n=i + 1))
        return out

    def apply(self):
        vecmod.set_nodes(self.proj, self.edit, self.points(), self.closed.isChecked())
        return self.edit


#: genre de vecteur paramétrique -> dialogue de modification
EDIT_DIALOGS = {"text": TextDialog, "rectangle": RectangleDialog, "circle": CircleDialog, "polygon": PolygonDialog,
                "polyline": NodesDialog}


def edit_vector(proj, obj, nodes_only=False):
    """Rouvre le dialogue d'un vecteur paramétrique (nœuds si ``nodes_only``) ; True si modifié."""
    cls = NodesDialog if nodes_only else EDIT_DIALOGS[obj.VectorKind]
    try:
        dlg = cls(proj, FreeCADGui.getMainWindow(), edit=obj)
    except Exception as exc:
        base._warn(tr_msg(exc))
        return False
    if base.exec_dialog(dlg) != QtWidgets.QDialog.Accepted:
        return False
    try:
        dlg.apply()
    except Exception as exc:
        base._warn(tr("Operation failed: {error}", error=tr_msg(exc)))
        return False
    base._after_change()
    return True


class ViewProviderVector(object):
    """Vue d'un vecteur paramétrique : double-clic = dialogue de modification."""

    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        return theme.icon_path("engrave") if hasattr(theme, "icon_path") else ""

    def doubleClicked(self, vobj):
        from . import state

        proj = state.active_project()
        if proj is None or proj.doc.Name != vobj.Object.Document.Name:
            return False
        from ..project import undo

        with undo.transaction(proj.doc, tr("Edit vector")):
            edit_vector(proj, vobj.Object)
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


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
    if not issubclass(dlg_cls, (TextDialog, ShapeDialog)) and getattr(dlg, "source", getattr(dlg, "first", None)) is not None \
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


class DrawRectangle(base._Base):
    atelier = "contour"
    text = "Rectangle"
    tooltip = "Draw a rectangle (centre, size, rounded corners, rotation); editable afterwards"

    @base._undoable
    def Activated(self):
        _run(RectangleDialog)


class DrawCircle(base._Base):
    atelier = "drill"
    text = "Circle"
    tooltip = "Draw a circle (centre, radius); editable afterwards"

    @base._undoable
    def Activated(self):
        _run(CircleDialog)


class DrawPolygon(base._Base):
    atelier = "contour"
    text = "Polygon"
    tooltip = "Draw a regular polygon (centre, radius to the corners, sides); editable afterwards"

    @base._undoable
    def Activated(self):
        _run(PolygonDialog)


def _selected_parametric():
    proj = base._need_project()
    if proj is None:
        return None, None
    sel = [s.Object for s in FreeCADGui.Selection.getSelectionEx() if s.Object.Document.Name == proj.doc.Name]
    objs = [o for o in sel if vecmod.is_parametric(o)]
    if not objs:
        base._warn(tr("Select a text or a shape drawn in CAM2027 (imported vectors cannot be edited)."))
        return proj, None
    return proj, objs[0]


class EditVector(base._Base):
    atelier = "engrave"
    text = "Edit vector"
    tooltip = "Change the selected text or shape (text, font, size, position...): the operations that machine it are recomputed"

    @base._undoable
    def Activated(self):
        proj, obj = _selected_parametric()
        if obj is not None:
            edit_vector(proj, obj)


class EditNodes(base._Base):
    atelier = "contour"
    text = "Edit nodes"
    tooltip = "Move or delete the nodes of the selected straight-sided shape (a rectangle or polygon becomes a free shape)"

    @base._undoable
    def Activated(self):
        proj, obj = _selected_parametric()
        if obj is not None:
            edit_vector(proj, obj, nodes_only=True)


COMMANDS = [
    ("CAM2027_DrawText", DrawText),
    ("CAM2027_DrawRectangle", DrawRectangle),
    ("CAM2027_DrawCircle", DrawCircle),
    ("CAM2027_DrawPolygon", DrawPolygon),
    ("CAM2027_EditVector", EditVector),
    ("CAM2027_EditNodes", EditNodes),
    ("CAM2027_OffsetVector", OffsetVector),
    ("CAM2027_CombineVectors", CombineVectors),
    ("CAM2027_MirrorVector", MirrorVector),
    ("CAM2027_CircularCopies", CircularCopies),
]
TOOLBAR = [name for name, _cls in COMMANDS]
