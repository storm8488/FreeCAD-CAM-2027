# SPDX-License-Identifier: LGPL-2.1-or-later
"""Dialogues du flux 2D « à la Aspire » : fond plat d'un V-carving, incrustation en V, imbrication,
vectorisation d'image et Photo V-Carve, moulure et cannelures."""

from ..i18n import tr, tr_msg
from .labels import preset_label
from ..project import sheet as sheetmod
from . import theme
from .qt import QtCore, QtWidgets


def tool_pickers(proj, keep=lambda tool: True):
    """(champ Outil comme Fusion, liste des préréglages) limités aux outils ``keep``."""
    from .toolpicker import ToolField

    asm = ToolField(proj, accept=keep)
    preset = QtWidgets.QComboBox()

    def fill():
        preset.clear()
        tool = asm.tool()
        if tool is None:
            return
        for p in tool.presets:
            preset.addItem(preset_label(p), p.id)

    asm.changed.connect(fill)
    asm.set_kind(None)
    fill()
    return asm, preset


def is_vbit(tool):
    return tool.tool_type in ("vbit", "engrave", "chamfer") and bool(tool.geometry.tip_included_angle_deg)


def is_flat(tool):
    return tool.tool_type in ("endmill",)


def _spin(lo, hi, value, decimals=2):
    s = QtWidgets.QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(decimals)
    s.setValue(value)
    return s


def _buttons(dlg, form):
    bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    form.addRow(bb)
    return bb


def _hint(form, text):
    label = QtWidgets.QLabel(text)
    label.setWordWrap(True)
    theme.set_role(label, "muted")
    form.addRow(label)
    return label


class FlatDepthDialog(QtWidgets.QDialog):
    def __init__(self, proj, parent=None, selected_op=None):
        super(FlatDepthDialog, self).__init__(parent)
        theme.apply(self)
        self.proj = proj
        self.setWindowTitle(tr("Flat depth clearing"))
        form = QtWidgets.QFormLayout(self)
        self.vcarve = QtWidgets.QComboBox()
        reg = proj.registry
        for op in proj.operations():
            base = proj.base_operation(op)
            if reg.get(base.Name, {}).get("kind") == "vcarve":
                self.vcarve.addItem("%s (%.2f mm)" % (base.Label, -float(base.FinalDepth.getValueAs("mm"))), base.Name)
        if selected_op is not None:
            self.vcarve.setCurrentIndex(max(0, self.vcarve.findData(proj.base_operation(selected_op).Name)))
        form.addRow(tr("V-carve operation"), self.vcarve)
        self.depth = _spin(0.1, 100.0, 3.0)
        self.depth.setToolTip(tr("The V-carve is limited to this depth; wider areas are cleared flat at this depth."))
        form.addRow(tr("Flat depth (mm)"), self.depth)
        self.asm, self.preset = tool_pickers(proj, is_flat)
        form.addRow(tr("Flat end mill"), self.asm)
        form.addRow(tr("Cutting preset"), self.preset)
        _hint(form, tr("The flat end mill clears the wide areas at the V-carve final depth; the V-bit then follows the flat area outline and the sharp corners. Created before the V-carve."))
        self.buttons = _buttons(self, form)
        self.buttons.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(self.vcarve.count() > 0 and self.asm.currentData() is not None)

    def apply(self):
        op = self.proj.doc.getObject(self.vcarve.currentData())
        start = float(op.StartDepth.getValueAs("mm"))
        self.proj.update_operation(op, {"FinalDepth": start - self.depth.value()})
        return self.proj.add_flat_clearing(op, self.asm.currentData(), self.preset.currentData())


class InlayDialog(QtWidgets.QDialog):
    def __init__(self, proj, parent=None, selected=()):
        super(InlayDialog, self).__init__(parent)
        theme.apply(self)
        self.proj = proj
        self.setWindowTitle(tr("V inlay (male / female)"))
        form = QtWidgets.QFormLayout(self)
        self.drawing = QtWidgets.QComboBox()
        names = set()
        for obj in list(selected) + sheetmod.vector_objects(proj.doc):
            if obj.Name not in names and sheetmod.closed_wires(obj):
                self.drawing.addItem(obj.Label, obj.Name)
                names.add(obj.Name)
        form.addRow(tr("Closed drawing"), self.drawing)
        self.vasm, self.vpreset = tool_pickers(proj, is_vbit)
        form.addRow(tr("V-bit"), self.vasm)
        form.addRow(tr("V-bit preset"), self.vpreset)
        self.fasm, self.fpreset = tool_pickers(proj, is_flat)
        form.addRow(tr("Flat end mill"), self.fasm)
        form.addRow(tr("Flat end mill preset"), self.fpreset)
        self.female = _spin(0.1, 50, 5.0)
        self.start = _spin(0.0, 50, 3.0)
        self.male = _spin(0.1, 50, 5.0)
        form.addRow(tr("Female pocket depth (mm)"), self.female)
        form.addRow(tr("Male start depth (mm)"), self.start)
        form.addRow(tr("Male flat depth (mm)"), self.male)
        self.gaps = QtWidgets.QLabel()
        self.gaps.setWordWrap(True)
        form.addRow(self.gaps)
        _hint(form, tr("The male is created in a new project (another board), mirrored. Glue it upside down into the female, then plane the excess."))
        self.buttons = _buttons(self, form)
        for w in (self.female, self.start, self.male):
            w.valueChanged.connect(self._update)
        self._update()

    def _update(self, *_a):
        from ..project import inlay

        try:
            g = inlay.check_inlay_depths(self.female.value(), self.start.value(), self.male.value())
            self.gaps.setText(tr("Glue gap at the bottom: {b} mm; gap between the boards: {s} mm.",
                                 b="%.2f" % g["bottom_gap"], s="%.2f" % g["surface_gap"]))
            ok = self.drawing.count() > 0 and self.vasm.currentData() is not None and self.fasm.currentData() is not None
        except ValueError as exc:
            self.gaps.setText(tr_msg(exc))
            ok = False
        self.buttons.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(ok)

    def apply(self):
        drawing = self.proj.doc.getObject(self.drawing.currentData())
        return self.proj.create_inlay(drawing, self.vasm.currentData(), self.vpreset.currentData(),
                                      self.fasm.currentData(), self.fpreset.currentData(),
                                      self.female.value(), self.start.value(), self.male.value())


class NestDialog(QtWidgets.QDialog):
    def __init__(self, proj, parent=None):
        super(NestDialog, self).__init__(parent)
        theme.apply(self)
        self.proj = proj
        self.setWindowTitle(tr("Nest parts on a sheet"))
        form = QtWidgets.QFormLayout(self)
        self.table = QtWidgets.QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels([tr("Drawing"), tr("Size (mm)"), tr("Copies")])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.objects = [o for o in sheetmod.vector_objects(proj.doc) if sheetmod.closed_wires(o)]
        for obj in self.objects:
            r = self.table.rowCount()
            self.table.insertRow(r)
            item = QtWidgets.QTableWidgetItem(obj.Label)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Checked)
            self.table.setItem(r, 0, item)
            bb = obj.Shape.BoundBox
            self.table.setItem(r, 1, QtWidgets.QTableWidgetItem("%.1f x %.1f" % (bb.XLength, bb.YLength)))
            copies = QtWidgets.QSpinBox()
            copies.setRange(1, 500)
            self.table.setCellWidget(r, 2, copies)
        self.table.setMinimumHeight(160)
        form.addRow(self.table)
        self.width = _spin(10, 10000, 600.0, 1)
        self.length = _spin(10, 10000, 400.0, 1)
        self.spacing = _spin(0, 200, 6.0, 1)
        self.margin = _spin(0, 500, 10.0, 1)
        self.rotate = QtWidgets.QCheckBox(tr("Allow 90° rotation"))
        self.rotate.setChecked(True)
        form.addRow(tr("Sheet width X (mm)"), self.width)
        form.addRow(tr("Sheet length Y (mm)"), self.length)
        form.addRow(tr("Spacing between parts (mm)"), self.spacing)
        form.addRow(tr("Margin to the sheet edge (mm)"), self.margin)
        form.addRow("", self.rotate)
        _hint(form, tr("Parts are placed by their bounding rectangles (not true-shape nesting). Do it before Stock & fixture; the sheet will have this size."))
        self.buttons = _buttons(self, form)
        self.buttons.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(bool(self.objects) and not proj.has_job)

    def apply(self):
        chosen, copies = [], {}
        for r, obj in enumerate(self.objects):
            if self.table.item(r, 0).checkState() == QtCore.Qt.Checked:
                chosen.append(obj)
                copies[obj] = self.table.cellWidget(r, 2).value()
        return self.proj.nest_drawings(chosen, self.width.value(), self.length.value(), self.spacing.value(),
                                       self.margin.value(), self.rotate.isChecked(), copies)


class TraceBitmapDialog(QtWidgets.QDialog):
    """Vectorisation d'une image (Aspire « Trace Bitmap ») : seuil, inversion, taille, simplification."""

    def __init__(self, proj, parent=None, path=""):
        super(TraceBitmapDialog, self).__init__(parent)
        theme.apply(self)
        self.proj = proj
        self.path = path
        self.setWindowTitle(tr("Trace bitmap"))
        form = QtWidgets.QFormLayout(self)
        form.addRow(tr("Image"), QtWidgets.QLabel(path))
        self.width = _spin(1, 10000, 100.0, 1)
        form.addRow(tr("Width (mm)"), self.width)
        self.threshold = _spin(0.01, 0.99, 0.5)
        self.threshold.setSingleStep(0.05)
        self.threshold.setToolTip(tr("Grey level separating the shapes from the background (0 black, 1 white)."))
        form.addRow(tr("Threshold"), self.threshold)
        self.invert = QtWidgets.QCheckBox(tr("Trace the light areas (instead of the dark ones)"))
        form.addRow("", self.invert)
        self.tolerance = _spin(0.001, 5.0, 0.05, 3)
        self.tolerance.setToolTip(tr("Largest distance between the traced outline and the pixel edge (smoothing)."))
        form.addRow(tr("Outline tolerance (mm)"), self.tolerance)
        self.min_area = _spin(0.0, 10000, 1.0)
        form.addRow(tr("Ignore spots smaller than (mm²)"), self.min_area)
        self.x = _spin(-10000, 10000, 0.0)
        self.y = _spin(-10000, 10000, 0.0)
        form.addRow(tr("Lower left corner X (mm)"), self.x)
        form.addRow(tr("Lower left corner Y (mm)"), self.y)
        _hint(form, tr("The outlines become a drawing vector (holes kept), to be machined with pocket, profile or V-carve."))
        self.buttons = _buttons(self, form)

    def apply(self):
        from ..project import bitmap

        return bitmap.trace_to_vector(self.proj, self.path, self.width.value(), threshold=self.threshold.value(),
                                      invert=self.invert.isChecked(), tolerance=self.tolerance.value(),
                                      min_area=self.min_area.value(), origin=(self.x.value(), self.y.value()))


class PhotoVCarveDialog(QtWidgets.QDialog):
    """Photo V-Carve (Aspire) : lignes parallèles au V-bit, profondeur selon le gris."""

    def __init__(self, proj, parent=None, path=""):
        super(PhotoVCarveDialog, self).__init__(parent)
        theme.apply(self)
        self.proj = proj
        self.path = path
        self.setWindowTitle(tr("Photo V-carve"))
        form = QtWidgets.QFormLayout(self)
        form.addRow(tr("Image"), QtWidgets.QLabel(path))
        self.asm, self.preset = tool_pickers(proj, is_vbit)
        form.addRow(tr("V-bit"), self.asm)
        form.addRow(tr("Cutting preset"), self.preset)
        sb = proj.stock_bounds()
        self.width = _spin(1, 10000, round(min(200.0, sb["xmax"] - sb["xmin"]), 1), 1)
        form.addRow(tr("Width (mm)"), self.width)
        self.x = _spin(-10000, 10000, round(sb["xmin"], 2))
        self.y = _spin(-10000, 10000, round(sb["ymin"], 2))
        form.addRow(tr("Lower left corner X (mm)"), self.x)
        form.addRow(tr("Lower left corner Y (mm)"), self.y)
        self.depth = _spin(0.05, 20, 1.5)
        form.addRow(tr("Maximum depth (black) (mm)"), self.depth)
        self.spacing = _spin(0.0, 50, 0.0, 3)
        self.spacing.setSpecialValueText(tr("Auto (V-bit width at the maximum depth)"))
        form.addRow(tr("Line spacing (mm)"), self.spacing)
        self.gamma = _spin(0.2, 5.0, 1.0)
        self.gamma.setToolTip(tr("Above 1: light greys carved less deep (more contrast in the light areas)."))
        form.addRow(tr("Gamma"), self.gamma)
        self.invert = QtWidgets.QCheckBox(tr("Carve the light areas (negative)"))
        form.addRow("", self.invert)
        _hint(form, tr("Dark = deep and wide groove, white = not cut. Horizontal lines, back and forth, from the top of the stock."))
        self.buttons = _buttons(self, form)
        self.buttons.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(self.asm.currentData() is not None)

    def apply(self):
        from ..project import bitmap

        return bitmap.add_photo_vcarve(self.proj, tr("Photo V-carve"), self.asm.currentData(), self.preset.currentData(),
                                       self.path, self.width.value(), self.depth.value(), self.spacing.value() or None,
                                       origin=(self.x.value(), self.y.value()), invert=self.invert.isChecked(),
                                       gamma=self.gamma.value())


def is_ball(tool):
    return tool.tool_type == "ballend"


def _rail_combo(proj, selected):
    combo = QtWidgets.QComboBox()
    names = [o.Name for o in selected]
    for obj in sorted(sheetmod.vector_objects(proj.doc), key=lambda o: (o.Name not in names, o.Label)):
        combo.addItem(obj.Label, obj.Name)
    return combo


class MouldingDialog(QtWidgets.QDialog):
    """Moulure (Aspire « Moulding Toolpath ») : section prédéfinie extrudée le long d'un vecteur, fraise boule."""

    PROFILES = (("quarter_round", "Quarter round (convex)"), ("cove", "Cove (concave)"), ("chamfer", "Chamfer"),
                ("ogee", "Ogee"))

    def __init__(self, proj, parent=None, selected=()):
        super(MouldingDialog, self).__init__(parent)
        theme.apply(self)
        self.proj = proj
        self.setWindowTitle(tr("Moulding"))
        form = QtWidgets.QFormLayout(self)
        self.rail = _rail_combo(proj, selected)
        form.addRow(tr("Rail (drawing vector)"), self.rail)
        self.profile = QtWidgets.QComboBox()
        for key, label in self.PROFILES:
            self.profile.addItem(tr(label), key)
        form.addRow(tr("Profile"), self.profile)
        self.width = _spin(0.5, 500, 10.0)
        self.depth = _spin(0.1, 200, 10.0)
        form.addRow(tr("Profile width (mm)"), self.width)
        form.addRow(tr("Profile depth (mm)"), self.depth)
        self.flip = QtWidgets.QCheckBox(tr("Profile on the right of the vector"))
        form.addRow("", self.flip)
        self.asm, self.preset = tool_pickers(proj, is_ball)
        form.addRow(tr("Ball end mill"), self.asm)
        form.addRow(tr("Cutting preset"), self.preset)
        self.stepover = _spin(0.02, 20, 0.3, 3)
        form.addRow(tr("Stepover (mm)"), self.stepover)
        self.step_down = _spin(0.0, 100, 0.0)
        self.step_down.setSpecialValueText(tr("No roughing levels"))
        form.addRow(tr("Roughing step down (mm)"), self.step_down)
        _hint(form, tr("The profile edge (full depth) is on the vector, the top is kept on the profile side; the ball goes one radius past the edge to finish a steep flank."))
        self.buttons = _buttons(self, form)
        self.buttons.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(self.rail.count() > 0 and self.asm.currentData() is not None)

    def apply(self):
        from ..project import decor

        rail = self.proj.doc.getObject(self.rail.currentData())
        return decor.add_moulding(self.proj, tr("Moulding"), self.asm.currentData(), self.preset.currentData(), rail,
                                  self.profile.currentData(), self.width.value(), self.depth.value(),
                                  self.stepover.value(), self.step_down.value() or None, self.flip.isChecked())


class FlutingDialog(QtWidgets.QDialog):
    """Cannelures (Aspire « Fluting Toolpath ») : vecteurs suivis avec rampes de profondeur."""

    def __init__(self, proj, parent=None, selected=()):
        super(FlutingDialog, self).__init__(parent)
        theme.apply(self)
        self.proj = proj
        self.setWindowTitle(tr("Fluting"))
        form = QtWidgets.QFormLayout(self)
        self.vectors = QtWidgets.QListWidget()
        names = [o.Name for o in selected]
        for obj in sheetmod.vector_objects(proj.doc):
            item = QtWidgets.QListWidgetItem(obj.Label)
            item.setData(QtCore.Qt.UserRole, obj.Name)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Checked if obj.Name in names or not names else QtCore.Qt.Unchecked)
            self.vectors.addItem(item)
        self.vectors.setMaximumHeight(120)
        form.addRow(tr("Vectors"), self.vectors)
        self.asm, self.preset = tool_pickers(proj, lambda t: is_ball(t) or is_vbit(t))
        form.addRow(tr("Ball end mill or V-bit"), self.asm)
        form.addRow(tr("Cutting preset"), self.preset)
        self.depth = _spin(0.05, 50, 2.0)
        self.ramp_start = _spin(0.0, 1000, 10.0)
        self.ramp_end = _spin(0.0, 1000, 10.0)
        form.addRow(tr("Depth (mm)"), self.depth)
        form.addRow(tr("Start ramp length (mm)"), self.ramp_start)
        form.addRow(tr("End ramp length (mm)"), self.ramp_end)
        _hint(form, tr("Each vector is followed from its start: the depth rises from 0 over the start ramp, stays, then comes back to 0 over the end ramp."))
        self.buttons = _buttons(self, form)
        self.buttons.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(self.vectors.count() > 0 and self.asm.currentData() is not None)

    def apply(self):
        from ..project import decor

        rails = [self.proj.doc.getObject(self.vectors.item(i).data(QtCore.Qt.UserRole)) for i in range(self.vectors.count())
                 if self.vectors.item(i).checkState() == QtCore.Qt.Checked]
        if not rails:
            raise ValueError(tr("Choose at least one vector"))
        return decor.add_fluting(self.proj, tr("Fluting"), self.asm.currentData(), self.preset.currentData(), rails,
                                 self.depth.value(), self.ramp_start.value(), self.ramp_end.value())
