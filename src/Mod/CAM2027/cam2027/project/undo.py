# SPDX-License-Identifier: LGPL-2.1-or-later
"""Annulation (Ctrl+Z) des actions CAM2027.

FreeCAD n'enregistre une modification du document que dans une transaction ouverte : sans elle, « Annuler »
reste grisé. Chaque action (ajout d'une opération, brut, suppression, réordonnancement...) est donc une
transaction, une étape d'annulation.

Piège de FreeCAD : la forme d'un ToolBit est copiée depuis un document temporaire, fermé aussitôt
(``Path.Tool.shape.doc.ShapeDocFromBytes``). Une copie depuis un autre document puis la fermeture de ce
document, pendant la transaction, font que les objets créés ensuite ne sont plus enregistrés : l'opération et
son ToolController restaient après « Annuler » (mesuré dans l'interface, pas en console). Pendant une
transaction, la fermeture des autres documents attend donc la fin de la transaction.
"""

import contextlib

import FreeCAD

_open = []  # transaction CAM2027 en cours (une seule : une action imbriquée en fait partie)


@contextlib.contextmanager
def transaction(doc, name):
    """Les modifications de ``doc`` faites dans le bloc forment une étape d'annulation nommée ``name``."""
    if doc is None or _open:
        yield
        return
    doc_name = doc.Name
    real_close = FreeCAD.closeDocument
    deferred = []

    def close_later(other):
        if other == doc_name:
            return real_close(other)
        deferred.append(other)
        return None

    _open.append(doc_name)
    FreeCAD.closeDocument = close_later
    doc.openTransaction(name)
    try:
        yield
    finally:
        FreeCAD.closeDocument = real_close
        _open.pop()
        try:
            if doc_name in FreeCAD.listDocuments():
                doc.commitTransaction()
        finally:
            for other in deferred:
                if other in FreeCAD.listDocuments():
                    real_close(other)
