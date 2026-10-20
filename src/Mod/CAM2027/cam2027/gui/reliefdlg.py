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
        form.addRow(tr("Width X (mm)"), self.width)
        form.addRow(tr("Length Y (from the image ratio)"), self.length)
        form.addRow(tr("Relief height (mm)"), self.height)
        form.addRow(tr("Base thickness under the relief (mm)"), self.base)
        form.addRow("", self.invert)
        form.addRow(tr("Smoothing (passes)"), self.smoothing)
        form.addRow(tr("Resolution (points on the long side)"), self.cells)
        hint = QtWidgets.QLabel(
            tr("Light = high. The relief bottom is at Z 0; machine it with 3D roughing and 3D finishing."))
        hint.setWordWrap(True)
        theme.set_role(hint, "muted")
        form.addRow(hint)
        self.buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        form.addRow(self.buttons)
        self.width.valueChanged.connect(self._update_length)
        self.set_path(path)

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
        self.buttons.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(self._size_px is not None)
        self._update_length()

    def _update_length(self, *_args):
        if self._size_px is None:
            self.length.setText("-")
            return
        w, h = self._size_px
        self.length.setText("%.1f mm  (%d x %d px)" % (self.width.value() * h / float(w), w, h))

    def options(self):
        """Arguments de ``Project.import_relief``."""
        return {"path": self.path.text(), "width": self.width.value(), "relief_height": self.height.value(),
                "base": self.base.value(), "invert": self.invert.isChecked(), "smoothing": self.smoothing.value(),
                "cells": self.cells.value()}
