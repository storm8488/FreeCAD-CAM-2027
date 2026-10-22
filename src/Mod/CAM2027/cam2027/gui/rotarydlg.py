# SPDX-License-Identifier: LGPL-2.1-or-later
"""Dialogue « Usinage rotatif (4e axe continu) » : contour, poche enroulés et finition 3D rotative."""

import math

from ..i18n import tr, tr_msg
from .labels import preset_label
from ..project import rotary
from ..project import wrap as wrapmod
from . import theme
from .qt import QtWidgets
from .wrapdlg import drawing_candidates

#: stratégie -> genre d'outil proposé par défaut (stratégie CAM2027 la plus proche)
TOOL_KIND = {"wrap_contour": "pocket", "wrap_pocket": "pocket", "rotary3d": "surface3d"}


class RotaryDialog(QtWidgets.QDialog):
    """Création (``op`` None) ou modification d'une opération rotative continue."""

    def __init__(self, proj, parent=None, selected=(), op=None, kind=None):
        super(RotaryDialog, self).__init__(parent)
        theme.apply(self)
        self.proj = proj
        self.op = op
        rec = proj.registry.get(op.Name) if op is not None else None
        self.setWindowTitle(tr("Rotary machining (continuous A axis)"))
        form = QtWidgets.QFormLayout(self)
        self.kind = QtWidgets.QComboBox()
        for key, label in rotary.KINDS.items():
            self.kind.addItem(tr(label), key)
        kind = rec["kind"] if rec else (kind or "wrap_pocket")
        self.kind.setCurrentIndex(max(0, self.kind.findData(kind)))
        form.addRow(tr("Strategy"), self.kind)
        self.name = QtWidgets.QLineEdit(op.Label if op is not None else "")
        form.addRow(tr("Name"), self.name)
        self.drawing = QtWidgets.QComboBox()
        for obj in drawing_candidates(proj, selected):
            self.drawing.addItem(obj.Label, obj.Name)
        if rec and rec.get("wrap_base"):
            self.drawing.setCurrentIndex(max(0, self.drawing.findData(rec["wrap_base"][0][0])))
        form.addRow(tr("Unrolled drawing"), self.drawing)
        from .toolpicker import ToolField

        self.asm = ToolField(proj, TOOL_KIND[kind],
                             accept=lambda t: t.tool_type in ("endmill", "ballend", "bullnose"))
        self.preset = QtWidgets.QComboBox()
        self.asm.changed.connect(self._fill_presets)
        if rec:
            self.asm.set_assembly(rec["assembly_id"])
        else:
            self.asm.set_kind(TOOL_KIND[kind])
        self._fill_presets()
        if rec:
            self.preset.setCurrentIndex(max(0, self.preset.findData(rec["preset_id"])))
            for w in (self.kind, self.drawing, self.asm, self.preset):
                w.setEnabled(False)  # stratégie, outil et dessin : recréer l'opération pour les changer
        form.addRow(tr("Tool"), self.asm)
        form.addRow(tr("Cutting preset"), self.preset)
        p = dict(rotary.defaults(kind), **(rec["params"] if rec else {}))
        self.depth = self._spin(0.01, 100.0, -p.get("depth", -1.0))
        self.step_down = self._spin(0.0, 50.0, p.get("step_down", 0.5))
        self.side = QtWidgets.QComboBox()
        for key, label in (("outside", "Outside"), ("inside", "Inside"), ("on", "On the line")):
            self.side.addItem(tr(label), key)
        self.side.setCurrentIndex(max(0, self.side.findData(p.get("side", "outside"))))
        self.stepover = self._spin(0.01, 100.0, p.get("stepover", 0.4) * (100.0 if kind == "wrap_pocket" else 1.0))
        self.sample = self._spin(0.01, 5.0, p.get("sample", 0.25))
        self.leave = self._spin(0.0, 10.0, p.get("leave", 0.0))
        self.safe = self._spin(0.5, 200.0, p.get("safe_margin", 5.0))
        self.rows = {}
        for key, label, widget in (
                ("depth", "Depth below the surface (mm)", self.depth),
                ("step_down", "Step down (mm)", self.step_down),
                ("side", "Side", self.side),
                ("stepover", "Stepover", self.stepover),
                ("sample", "Sample interval (mm)", self.sample),
                ("leave", "Stock to leave (mm)", self.leave),
                ("safe", "Safe height above the surface (mm)", self.safe)):
            lab = QtWidgets.QLabel(tr(label))
            form.addRow(lab, widget)
            self.rows[key] = (lab, widget)
        self.info = QtWidgets.QLabel()
        self.info.setWordWrap(True)
        theme.set_role(self.info, "muted")
        form.addRow(self.info)
        self.buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        form.addRow(self.buttons)
        self.kind.currentIndexChanged.connect(self._update)
        self._update()

    @staticmethod
    def _spin(lo, hi, value):
        s = QtWidgets.QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setDecimals(3)
        s.setValue(value)
        return s

    def current_kind(self):
        return self.kind.currentData()

    def _update(self):
        kind = self.current_kind()
        shown = {"wrap_contour": ("depth", "step_down", "side", "safe"),
                 "wrap_pocket": ("depth", "step_down", "stepover", "safe"),
                 "rotary3d": ("step_down", "stepover", "sample", "leave", "safe")}[kind]
        for key, (lab, widget) in self.rows.items():
            lab.setVisible(key in shown)
            widget.setVisible(key in shown)
        self.rows["stepover"][0].setText(tr("Stepover (% of the diameter)") if kind == "wrap_pocket"
                                         else tr("Stepover along the surface (mm)"))
        self.rows["step_down"][0].setText(tr("Roughing step down (mm, 0 = finishing only)") if kind == "rotary3d"
                                          else tr("Step down (mm)"))
        self.drawing.setVisible(kind != "rotary3d")
        if self.op is None and not self.asm.user_chose:
            self.asm.set_kind(TOOL_KIND[kind])
            self._fill_presets()
        if not self.name.text().strip() or self.name.text() in [tr(l) for l in rotary.KINDS.values()]:
            self.name.setText(tr(rotary.KINDS[kind]))
        ok = True
        try:
            radius = wrapmod.radius_of_stock(self.proj.job)
            if kind == "rotary3d":
                text = tr("Round stock R {r} mm. Lines along the A axis follow the part (OpenCamLib), the tool pointing at the axis; X, Z and A move together in inverse-time feed (G93).",  # noqa: E501
                          r="%.2f" % radius)
            else:
                text = tr("Round stock R {r} mm. Draw unrolled: X along the A axis, Y = arc length from 0 to {c} mm (A 0 to 360 deg). The tool radius is compensated at the radius of each depth.",  # noqa: E501
                          r="%.2f" % radius, c="%.2f" % (2 * math.pi * radius))
                ok = self.drawing.count() > 0
        except ValueError as exc:
            text, ok = tr_msg(exc), False
        self.info.setText(text)
        self.buttons.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(ok)

    def _fill_presets(self):
        self.preset.clear()
        if self.asm.currentData() is None:
            return
        lib = self.proj.library
        tool = lib.tool(lib.assembly(self.asm.currentData()).tool_id)
        for p in tool.presets:
            self.preset.addItem(preset_label(p), p.id)

    def params(self):
        kind = self.current_kind()
        p = {"safe_margin": self.safe.value(), "step_down": self.step_down.value()}
        if kind == "rotary3d":
            p.update(stepover=self.stepover.value(), sample=self.sample.value(), leave=self.leave.value())
        else:
            p["depth"] = -self.depth.value()
            if kind == "wrap_contour":
                p["side"] = self.side.currentData()
            else:
                p["stepover"] = self.stepover.value() / 100.0
        return p

    def apply(self):
        """Crée ou met à jour l'opération ; retourne l'opération."""
        if self.op is not None:
            self.op.Label = self.name.text().strip() or self.op.Label
            rotary.update_operation(self.proj, self.op, **self.params())
            return self.op
        kind = self.current_kind()
        base = None
        if kind != "rotary3d":
            base = [(self.proj.doc.getObject(self.drawing.currentData()), [])]
        op, _rec = rotary.add_operation(self.proj, kind, self.name.text().strip() or tr(rotary.KINDS[kind]),
                                        self.asm.currentData(), self.preset.currentData(), base=base,
                                        params=self.params())
        return op
