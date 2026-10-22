# SPDX-License-Identifier: LGPL-2.1-or-later
"""Interface du recto-verso : dialogue de mise en place (axe, repérage) et bascule A / B du panneau Projet."""

from ..i18n import tr, tr_msg
from ..project import twosided
from . import theme
from .qt import QtWidgets


class TwoSidedDialog(QtWidgets.QDialog):
    """Axe de retournement et repérage (même coin ou goujons). Sur un projet déjà recto-verso : ajout des
    goujons seulement."""

    def __init__(self, proj, parent=None):
        super(TwoSidedDialog, self).__init__(parent)
        theme.apply(self)
        self.proj = proj
        self.setWindowTitle(tr("Two-sided machining"))
        form = QtWidgets.QFormLayout(self)
        already = twosided.is_two_sided(proj)
        self.axis = QtWidgets.QComboBox()
        self.axis.addItem(tr("About X (front and back edges swap)"), "X")
        self.axis.addItem(tr("About Y (left and right edges swap)"), "Y")
        if already:
            self.axis.setCurrentIndex(self.axis.findData(twosided.config(proj)["axis"]))
            self.axis.setEnabled(False)
        form.addRow(tr("Flip axis"), self.axis)
        self.registration = QtWidgets.QComboBox()
        self.registration.addItem(tr("Same corner (stock against the same stops)"), "corner")
        self.registration.addItem(tr("Dowel pins (two holes drilled from side A on the flip axis)"), "dowels")
        form.addRow(tr("Registration"), self.registration)
        from .sheetdlgs import tool_pickers, _spin

        self.tool, self.preset = tool_pickers(proj, keep=lambda t: t.tool_type in ("endmill", "drill"))
        self.depth = _spin(0.0, 50.0, 5.0, 1)
        form.addRow(tr("Dowel tool (hole diameter = pin diameter)"), self.tool)
        form.addRow(tr("Preset"), self.preset)
        form.addRow(tr("Depth into the spoilboard (mm)"), self.depth)
        self.registration.currentIndexChanged.connect(self._sync)
        if already:
            self.registration.setCurrentIndex(1)
        hint = QtWidgets.QLabel(tr("Side B is the part turned over about the axis through the centre of the stock: same stock, same work offset. Switch between side A and side B in the Project panel; the material check machines side B on what side A left."))
        hint.setWordWrap(True)
        theme.set_role(hint, "muted")
        form.addRow(hint)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)
        self._sync()

    def _sync(self, *_a):
        dowels = self.registration.currentData() == "dowels"
        for w in (self.tool, self.preset, self.depth):
            w.setEnabled(dowels)

    def apply(self):
        if not twosided.is_two_sided(self.proj):
            twosided.enable(self.proj, self.axis.currentData())
        op = None
        if self.registration.currentData() == "dowels":
            op = twosided.add_dowel_holes(self.proj, self.tool.currentData(), self.preset.currentData(),
                                          depth_below=self.depth.value())
        return op


class SideBar(QtWidgets.QWidget):
    """« Face A / Face B » dans le panneau Projet (caché hors recto-verso)."""

    def __init__(self, on_switch, parent=None):
        super(SideBar, self).__init__(parent)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.label = QtWidgets.QLabel()
        lay.addWidget(self.label, 1)
        self.buttons = {}
        for side in ("A", "B"):
            b = QtWidgets.QPushButton(tr("Side {s}", s=side))
            b.setCheckable(True)
            b.setToolTip(tr("Show and machine side {s}: operations added, recomputed and exported apply to this side", s=side))
            b.clicked.connect(lambda _c=False, s=side: on_switch(s))
            lay.addWidget(b)
            self.buttons[side] = b
        self.setVisible(False)

    def refresh(self, proj):
        on = proj is not None and proj.has_job and twosided.is_two_sided(proj)
        self.setVisible(bool(on))
        if not on:
            return
        side = twosided.current_side(proj)
        cfg = twosided.config(proj)
        reg = cfg.get("registration") or {}
        self.label.setText(tr("Two-sided, flip about {axis} ({reg})", axis=cfg["axis"],
                              reg=tr("dowel pins") if reg.get("kind") == "dowels" else tr("same corner")))
        for s, b in self.buttons.items():
            b.setChecked(s == side)
            theme.set_role(b, "primary" if s == side else "")


def switch_side(proj, side):
    """Bascule de face depuis le panneau (une étape d'annulation)."""
    from ..project import undo
    import FreeCAD

    with undo.transaction(proj.doc, tr("Side {s}", s=side)):
        twosided.set_side(proj, side)
    FreeCAD.ActiveDocument.recompute() if FreeCAD.ActiveDocument else None


def report_lines(rep):
    """Lignes du rapport de contrôle matière propres au recto-verso."""
    ts = rep.get("two_sided")
    if not ts:
        return []
    lines = [tr("Two-sided: side B simulated on what side A left (flip about {axis})", axis=ts["axis"])]
    for side in ("A", "B"):
        r = ts[side]
        vol = r["removed_volume"] if side == "A" else ts["removed_volume_B"]
        lines.append(tr("Side {s}: removed {v} cm3, gouge {g} mm, stock left max {m} mm",
                        s=side, v="%.1f" % (vol / 1000.0), g="%.2f" % r["gouge_max"], m="%.2f" % r["leftover_max"]))
    return lines


def describe_error(exc):
    return tr("Two-sided machining failed: {error}", error=tr_msg(exc))
