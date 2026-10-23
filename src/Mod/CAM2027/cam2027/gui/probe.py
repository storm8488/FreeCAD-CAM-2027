# SPDX-License-Identifier: LGPL-2.1-or-later
"""Usiner > Palper l'origine : réglages du palpeur (profil machine), type de palpage, aperçu du G-code."""

import copy

from ..i18n import tr, tr_msg
from ..project import probe as probemod
from . import theme
from .qt import QtWidgets


def _spin(lo, hi, value, decimals=2, suffix=" mm"):
    s = QtWidgets.QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(decimals)
    s.setValue(value)
    s.setSuffix(suffix)
    return s


class ProbeDialog(QtWidgets.QDialog):
    """Palpeur du profil machine (pointe, plaque, avance, course) et palpage à ajouter en tête du programme."""

    def __init__(self, proj, parent=None):
        super(ProbeDialog, self).__init__(parent)
        self.proj = proj
        self.setWindowTitle(tr("Probe the origin"))
        self.setMinimumWidth(560)
        form = QtWidgets.QFormLayout(self)
        hint = QtWidgets.QLabel(tr("Bring the probe above the part (near the corner, or inside the hole) before running the program. Each contact sets one axis of the work offset; the spindle is stopped."))
        hint.setWordWrap(True)
        theme.set_role(hint, "muted")
        form.addRow(hint)
        p = dict(probemod.DEFAULTS, **(getattr(proj.machine, "probe", None) or {}))
        self.tip = _spin(0.0, 20.0, float(p.get("tip_diameter_mm") or 0.0))
        self.plate = _spin(0.0, 100.0, float(p.get("plate_thickness_mm") or 0.0))
        self.feed = _spin(1.0, 2000.0, float(p.get("feed_mm_min") or 100.0), decimals=0, suffix=" mm/min")
        self.travel = _spin(1.0, 200.0, float(p.get("travel_mm") or 25.0))
        form.addRow(tr("Probe tip diameter"), self.tip)
        form.addRow(tr("Touch plate thickness"), self.plate)
        form.addRow(tr("Probing feed"), self.feed)
        form.addRow(tr("Probing travel"), self.travel)
        self.mode = QtWidgets.QComboBox()
        for key in probemod.MODES:
            self.mode.addItem(tr(probemod.MODE_LABELS[key]), key)
        form.addRow(tr("Probing"), self.mode)
        self.corner = QtWidgets.QComboBox()
        for key in probemod.CORNERS:
            self.corner.addItem(tr(key), key)
        form.addRow(tr("Corner"), self.corner)
        self.hole = _spin(0.0, 500.0, 10.0)
        form.addRow(tr("Hole diameter"), self.hole)
        self.wcs = QtWidgets.QComboBox()
        self.wcs.addItems(list(probemod.WCS))
        form.addRow(tr("Work offset"), self.wcs)
        self.offset_mode = QtWidgets.QComboBox()
        self.offset_mode.addItem(tr("G10 L20 (stored work offset)"), "G10")
        self.offset_mode.addItem(tr("G92 (temporary offset)"), "G92")
        form.addRow(tr("Set the origin with"), self.offset_mode)
        self.preview = QtWidgets.QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMinimumHeight(180)
        form.addRow(self.preview)
        self.status = QtWidgets.QLabel("")
        self.status.setWordWrap(True)
        form.addRow(self.status)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(self._check_and_accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)
        for w in (self.tip, self.plate, self.feed, self.travel, self.hole):
            w.valueChanged.connect(self._refresh)
        for w in (self.mode, self.corner, self.wcs, self.offset_mode):
            w.currentIndexChanged.connect(self._refresh)
        self._refresh()

    def machine(self):
        """Copie du profil avec le palpeur saisi (le profil du projet n'est changé qu'à l'application)."""
        m = copy.deepcopy(self.proj.machine)
        m.probe = {"present": True, "tip_diameter_mm": self.tip.value() or None,
                   "plate_thickness_mm": self.plate.value(), "feed_mm_min": self.feed.value(),
                   "travel_mm": self.travel.value(),
                   "tool_number": int((self.proj.machine.probe or {}).get("tool_number") or 99)}
        return m

    def options(self):
        kw = {"wcs": self.wcs.currentText(), "offset_mode": self.offset_mode.currentData()}
        mode = self.mode.currentData()
        if mode in ("corner", "inner_corner"):
            kw["corner"] = self.corner.currentData()
        elif mode == "hole":
            kw["hole_diameter"] = self.hole.value()
        return mode, kw

    def _refresh(self, *_args):
        mode = self.mode.currentData()
        self.corner.setEnabled(mode in ("corner", "inner_corner"))
        self.hole.setEnabled(mode == "hole")
        try:
            mode, kw = self.options()
            self.preview.setPlainText("\n".join(probemod.probe_gcode(self.machine(), mode, **kw)))
            self.status.setText("")
            self.ok = True
        except Exception as exc:
            self.preview.setPlainText("")
            self.status.setText("<span style='color:%s'>%s</span>" % (theme.status_color("error"), tr_msg(exc)))
            self.ok = False

    def _check_and_accept(self):
        self._refresh()
        if self.ok:
            self.accept()

    def apply(self):
        self.proj.set_machine(self.machine())
        mode, kw = self.options()
        return probemod.add_probe(self.proj, mode, **kw)


class ProbeCommand(object):
    icon = "CAM2027.svg"
    accel = ""
    atelier = "cmd-probe"
    text = "Probe the origin"
    tooltip = "Probing program (G38.2) that sets the work offset from a corner, a hole or the top surface"

    def GetResources(self):
        from . import commands

        return commands._Base.GetResources(self)

    def IsActive(self):
        return True

    def Activated(self):
        import FreeCAD
        import FreeCADGui
        from . import commands
        from ..project import undo

        proj = commands._need_project()
        if proj is None:
            return
        if not proj.has_job:
            commands._warn(tr("Define the stock and fixture first (this creates the job)."))
            return
        dlg = ProbeDialog(proj, FreeCADGui.getMainWindow())
        if commands.exec_dialog(dlg) != QtWidgets.QDialog.Accepted:
            return
        try:
            with undo.transaction(FreeCAD.ActiveDocument, tr(self.text)):
                op = dlg.apply()
                proj.compute()
        except Exception as exc:
            commands._warn(tr("Operation failed: {error}", error=tr_msg(exc)))
            return
        commands._after_change()
        commands._info(tr("{name} added at the start of the program.", name=op.Label))
