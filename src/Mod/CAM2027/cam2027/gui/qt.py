# SPDX-License-Identifier: LGPL-2.1-or-later
"""Import unique de Qt : PySide2 (FreeCAD 1.0) ou PySide6 (FreeCAD 1.1+)."""

try:
    from PySide6 import QtCore, QtGui, QtWidgets  # noqa: F401

    QT_VERSION = 6
except ImportError:  # pragma: no cover
    from PySide2 import QtCore, QtGui, QtWidgets  # noqa: F401

    QT_VERSION = 5



def exec_dialog(dialog):
    """``QDialog.exec()`` sur PySide6, ``exec_()`` sur PySide2 ; retourne le code de résultat. Le dialogue est
    ensuite détruit (``dispose``)."""
    runner = getattr(dialog, "exec", None) or getattr(dialog, "exec_")
    try:
        return runner()
    finally:
        dispose(dialog)


def dispose(dialog):
    """Détruit un dialogue fermé quand la main revient à la boucle d'événements (ses champs restent lisibles
    jusqu'à la fin de la commande). Créés avec la fenêtre principale pour parent, les dialogues fermés restaient
    en mémoire : 150 après 50 ajouts d'opérations."""
    try:
        dialog.deleteLater()
    except RuntimeError:
        pass  # déjà détruit


__all__ = ["QtCore", "QtGui", "QtWidgets", "QT_VERSION", "exec_dialog", "dispose"]
