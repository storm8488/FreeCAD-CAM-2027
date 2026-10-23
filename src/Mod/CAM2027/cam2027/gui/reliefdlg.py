# SPDX-License-Identifier: LGPL-2.1-or-later
"""Dialogue « Relief depuis une image » : image, taille, hauteur, épaisseur, inversion, lissage, résolution."""

import os

from ..i18n import tr
from ..project import relief
from . import theme
from .qt import QtCore, QtGui, QtWidgets


class ReliefDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, path=""):
        super(ReliefDialog, self).__init__(parent)
        theme.apply(self)
        self.setWindowTitle(tr("Relief from image"))
        self._size_px = None
        form = QtWidgets.QFormLayout(self)
        row = QtWidgets.QHBoxLayout()
        self.path = QtWidgets.QLineEdit(path)
        self.path.setReadOnly(True)
        browse = QtWidgets.QPushButton(tr("Browse..."))
        browse.clicked.connect(self.browse)
        row.addWidget(self.path, 1)
        row.addWidget(browse)
        form.addRow(tr("Image"), row)
        self.preview = QtWidgets.QLabel()
        self.preview.setMinimumSize(220, 120)
        self.preview.setAlignment(QtCore.Qt.AlignCenter)
        form.addRow(self.preview)
        self.width = self._spin(1, 5000, 100.0, 1)
        self.length = QtWidgets.QLabel()
        self.height = self._spin(0.1, 200, 5.0, 2)
        self.base = self._spin(0.1, 200, 3.0, 2)
        self.invert = QtWidgets.QCheckBox(tr("Dark = high (invert)"))
        self.smoothing = QtWidgets.QSpinBox()
        self.smoothing.setRange(0, 20)
        self.smoothing.setValue(1)
        self.cells = QtWidgets.QSpinBox()
        self.cells.setRange(relief.MIN_CELLS, relief.MAX_CELLS)
        self.cells.setValue(relief.DEFAULT_CELLS)
        self.source = QtWidgets.QComboBox()
        self.source.addItem(tr("Grey level (light = high): depth maps"), "grey")
        self.source.addItem(tr("Inflated shapes: drawings, logos, line art"), "inflate")
        self.source.addItem(tr("AI depth (Depth Anything): photos, illustrations"), "depth")
        self.depth_button = QtWidgets.QPushButton(tr("Download the AI model (about 110 MB)..."))
        self.depth_button.clicked.connect(self.install_depth)
        self.threshold = self._spin(0.05, 0.95, 0.5, 2)
        self.threshold.setSingleStep(0.05)
        self.threshold.setToolTip(tr("Grey level separating the shapes from the background (0 black, 1 white)."))
        self.rounding = self._spin(0.05, 100, 1.0, 2)
        self.rounding.setToolTip(tr("Width over which a shape rises from its edge to the full height, as a rounded dome; a line narrower than twice this width stays lower."))
        self.grey_mix = QtWidgets.QSpinBox()
        self.grey_mix.setRange(0, 100)
        self.grey_mix.setSuffix(" %")
        self.grey_mix.setToolTip(tr("Share of the grey levels kept on top of the inflated shapes (shading of the drawing)."))
        form.addRow(tr("Height from"), self.source)
        form.addRow("", self.depth_button)
        form.addRow(tr("Width X (mm)"), self.width)
        form.addRow(tr("Length Y (from the image ratio)"), self.length)
        form.addRow(tr("Relief height (mm)"), self.height)
        form.addRow(tr("Base thickness under the relief (mm)"), self.base)
        form.addRow("", self.invert)
        form.addRow(tr("Shape threshold"), self.threshold)
        form.addRow(tr("Rounding width (mm)"), self.rounding)
        form.addRow(tr("Grey levels kept"), self.grey_mix)
        self._inflate_rows = (self.threshold, self.rounding, self.grey_mix)
        self._form = form
        form.addRow(tr("Smoothing (passes)"), self.smoothing)
        form.addRow(tr("Resolution (points on the long side)"), self.cells)
        self.hint = hint = QtWidgets.QLabel()
        hint.setWordWrap(True)
        theme.set_role(hint, "muted")
        form.addRow(hint)
        self.buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        form.addRow(self.buttons)
        self.width.valueChanged.connect(self._update_length)
        self.source.currentIndexChanged.connect(self._update_source)
        self.set_path(path)
        self._update_source()

    def _update_source(self, *_args):
        source = self.source.currentData()
        inflate = source == "inflate"
        for widget in self._inflate_rows:
            shown = inflate or (source == "depth" and widget is self.grey_mix)
            widget.setVisible(shown)
            label = self._form.labelForField(widget)
            if label is not None:
                label.setVisible(shown)
        missing = source == "depth" and not relief.depth_available()
        self.depth_button.setVisible(missing)
        self.buttons.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(self._size_px is not None and not missing)
        if source == "depth":
            self.invert.setText(tr("Far = high (invert)"))
            self.hint.setText(tr("An AI model estimates the depth of the image (near = high): the volume of a photo or an illustration. Keep some grey levels to carve the lines of a drawing into the volume. Runs on this computer, nothing is sent."))
        elif inflate:
            self.invert.setText(tr("Raise the light areas (instead of the dark ones)"))
            self.hint.setText(tr("Dark shapes become rounded domes, flat beyond the rounding width; for a drawing, keep the resolution high (400) so thin lines stay sharp. The relief bottom is at Z 0; machine it with 3D roughing and 3D finishing (small ball end mill)."))
        else:
            self.invert.setText(tr("Dark = high (invert)"))
            self.hint.setText(tr("Light = high. The relief bottom is at Z 0; machine it with 3D roughing and 3D finishing."))

    @staticmethod
    def _spin(lo, hi, value, decimals):
        s = QtWidgets.QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setDecimals(decimals)
        s.setValue(value)
        return s

    def browse(self):
        exts = " ".join("*" + e for e in relief.IMAGE_EXTENSIONS)
        path, _f = QtWidgets.QFileDialog.getOpenFileName(self, tr("Relief from image"), "",
                                                         tr("Images") + " (" + exts + ")")
        if path:
            self.set_path(path)

    def set_path(self, path):
        self.path.setText(path or "")
        self._size_px = None
        self.preview.clear()
        if path and os.path.isfile(path):
            relief.ensure_image_plugins()
            img = QtGui.QImage(path)
            if not img.isNull():
                self._size_px = (img.width(), img.height())
                self.preview.setPixmap(QtGui.QPixmap.fromImage(img).scaled(
                    220, 120, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
        if hasattr(self, "hint"):  # OK : image lue (et modèle d'IA présent pour la profondeur)
            self._update_source()
        self._update_length()

    def _update_length(self, *_args):
        if self._size_px is None:
            self.length.setText("-")
            return
        w, h = self._size_px
        self.length.setText("%.1f mm  (%d x %d px)" % (self.width.value() * h / float(w), w, h))

    def install_depth(self):
        """Téléchargement du modèle de profondeur, seulement après l'accord de l'utilisateur."""
        answer = QtWidgets.QMessageBox.question(
            self, tr("AI depth"),
            tr("Download onnxruntime (about 12 MB) and the Depth Anything V2 Small model (about 100 MB, Apache 2.0 licence) from the Internet into {folder}? The model then runs on this computer; no image is sent.", folder=relief.depth_dir()))
        if answer != QtWidgets.QMessageBox.Yes:
            return
        wait = QtWidgets.QProgressDialog(tr("Downloading the AI model..."), "", 0, 0, self)
        wait.setCancelButton(None)
        wait.setWindowModality(QtCore.Qt.WindowModal)
        wait.show()

        def progress(text):
            wait.setLabelText(tr("Downloading the AI model...") + chr(10) + text)
            QtWidgets.QApplication.processEvents()

        try:
            relief.install_depth(progress)
        except Exception as exc:
            wait.close()
            from ..i18n import tr_msg

            QtWidgets.QMessageBox.warning(self, tr("AI depth"), tr_msg(exc))
            return
        wait.close()
        self._update_source()

    def options(self):
        """Arguments de ``Project.import_relief``."""
        return {"path": self.path.text(), "width": self.width.value(), "relief_height": self.height.value(),
                "base": self.base.value(), "invert": self.invert.isChecked(), "smoothing": self.smoothing.value(),
                "cells": self.cells.value(), "source": self.source.currentData(), "threshold": self.threshold.value(),
                "rounding": self.rounding.value(), "grey_mix": self.grey_mix.value() / 100.0}
