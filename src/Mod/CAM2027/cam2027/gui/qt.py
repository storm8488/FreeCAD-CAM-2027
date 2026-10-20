# SPDX-License-Identifier: LGPL-2.1-or-later
"""Import unique de Qt : PySide2 (FreeCAD 1.0) ou PySide6 (FreeCAD 1.1+)."""

try:
    from PySide6 import QtCore, QtGui, QtWidgets  # noqa: F401

    QT_VERSION = 6
except ImportError:  # pragma: no cover
    from PySide2 import QtCore, QtGui, QtWidgets  # noqa: F401

    QT_VERSION = 5



def exec_dialog(dialog):
    """``QDialog.exec()`` sur PySide6, ``exec_()`` sur PySide2 ; retourne le code de résultat."""
    runner = getattr(dialog, "exec", None) or getattr(dialog, "exec_")
    return runner()


__all__ = ["QtCore", "QtGui", "QtWidgets", "QT_VERSION", "exec_dialog"]
