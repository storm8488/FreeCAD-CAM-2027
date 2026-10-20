# SPDX-License-Identifier: LGPL-2.1-or-later
"""Dialogue « Gravure enroulée (4e axe continu) » : dessin déroulé, outil, profondeur, passes."""

import math

from ..i18n import tr, tr_msg
from .labels import asm_label, preset_label
from ..project import sheet as sheetmod
from ..project import wrap as wrapmod
from . import theme
from .qt import QtWidgets


def drawing_candidates(proj, selected=()):
    """Dessins proposés : objets sélectionnés à arêtes sans solide, puis vecteurs du document."""
    out = []
    for obj in list(selected) + sheetmod.vector_objects(proj.doc):
        shape = getattr(obj, "Shape", None)
        if shape is not None and shape.Edges and not shape.Solids and obj not in out:
            out.append(obj)
    return out


class WrapDialog(QtWidgets.QDialog):
    """Création (``op`` None) ou modification d'une gravure enroulée."""

    def __init__(self, proj, parent=None, selected=(), op=None):
        super(WrapDialog, self).__init__(parent)
        theme.apply(self)
        self.proj = proj
        self.op = op
        rec = proj.registry.get(op.Name) if op is not None else None
        self.setWindowTitle(tr(wrapmod.LABEL))
        form = QtWidgets.QFormLayout(self)
        self.name = QtWidgets.QLineEdit(op.Label if op is not None else tr("Wrapped engraving"))
        form.addRow(tr("Name"), self.name)
        self.drawing = QtWidgets.QComboBox()
        for obj in drawing_candidates(proj, selected):
            self.drawing.addItem(obj.Label, obj.Name)
        if rec:
            names = [n for n, _s in rec["wrap_base"]]
            self.drawing.setCurrentIndex(max(0, self.drawing.findData(names[0]) if names else 0))
        form.addRow(tr("Unrolled drawing"), self.drawing)
        lib = proj.library
        self.asm = QtWidgets.QComboBox()
        from ..project.operations import tool_fits, tool_rank

        fitting = [a for a in lib.assemblies.values() if tool_fits("engrave", lib.tool(a.tool_id))]
        for a in sorted(fitting, key=lambda a: (tool_rank("engrave", lib.tool(a.tool_id)), a.output.tool_number)):
            self.asm.addItem(asm_label(a), a.id)
        self.preset = QtWidgets.QComboBox()
        self.asm.currentIndexChanged.connect(lambda _i: self._fill_presets())
        if rec:
            self.asm.setCurrentIndex(max(0, self.asm.findData(rec["assembly_id"])))
        self._fill_presets()
        if rec:
            self.preset.setCurrentIndex(max(0, self.preset.findData(rec["preset_id"])))
            for w in (self.drawing, self.asm, self.preset):
                w.setEnabled(False)  # outil et dessin : recréer l'opération pour les changer
        form.addRow(tr("Tool assembly"), self.asm)
        form.addRow(tr("Cutting preset"), self.preset)
        params = rec["params"] if rec else {"depth": -0.5, "step_down": 0.25, "safe_margin": 5.0}
        self.depth = self._spin(0.01, 50.0, -params["depth"])
        self.step_down = self._spin(0.01, 50.0, params["step_down"])
        self.safe = self._spin(0.5, 200.0, params["safe_margin"])
        form.addRow(tr("Depth below the surface (mm)"), self.depth)
        form.addRow(tr("Step down (mm)"), self.step_down)
        form.addRow(tr("Safe height above the surface (mm)"), self.safe)
        self.layout_info = QtWidgets.QLabel()
        self.layout_info.setWordWrap(True)
        try:
            radius = wrapmod.radius_of_stock(proj.job)
            info = tr("Round stock R {r} mm. Draw unrolled: X along the A axis, Y = arc length from 0 to {c} mm (A 0 to 360 deg). Cuts move X, Z and A together in inverse-time feed (G93).",  # noqa: E501
                      r="%.2f" % radius, c="%.2f" % (2 * math.pi * radius))
            self.layout_info.setText(info)
            ok = self.drawing.count() > 0
        except ValueError as exc:
            self.layout_info.setText(tr_msg(exc))
            ok = False
        theme.set_role(self.layout_info, "muted")
        form.addRow(self.layout_info)
        self.buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(ok)
        form.addRow(self.buttons)

    @staticmethod
    def _spin(lo, hi, value):
        s = QtWidgets.QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setDecimals(3)
        s.setValue(value)
        return s

    def _fill_presets(self):
        self.preset.clear()
        if self.asm.currentData() is None:
            return
        lib = self.proj.library
        tool = lib.tool(lib.assembly(self.asm.currentData()).tool_id)
        for p in tool.presets:
            self.preset.addItem(preset_label(p), p.id)

    def apply(self):
        """Crée ou met à jour l'opération ; retourne l'opération."""
        depth, step, safe = -self.depth.value(), self.step_down.value(), self.safe.value()
        if self.op is not None:
            self.op.Label = self.name.text().strip() or self.op.Label
            self.proj.update_wrapped_engraving(self.op, depth=depth, step_down=step, safe_margin=safe)
            return self.op
        drawing = self.proj.doc.getObject(self.drawing.currentData())
        op, _rec = self.proj.add_wrapped_engraving(self.name.text().strip() or tr("Wrapped engraving"),
                                                   self.asm.currentData(), self.preset.currentData(),
                                                   [(drawing, [])], depth, step, safe)
        return op
