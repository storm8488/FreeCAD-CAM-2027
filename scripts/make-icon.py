# SPDX-License-Identifier: LGPL-2.1-or-later
"""Fabrique un .ico multi-résolutions (16 à 256 px) à partir d'un SVG ou d'un PNG, avec le Qt de FreeCAD.

    set CAM2027_ICON_SRC=<entrée.png ou .svg>
    set CAM2027_ICON_OUT=<sortie.ico>
    CAM2027Cmd.exe scripts/make-icon.py

(chemins passés par variables d'environnement : FreeCADCmd ouvrirait un fichier passé en argument)

Les images sont rendues par QSvgRenderer ou réduites depuis le PNG (lissage), plateforme Qt
« offscreen », puis assemblées en ICO (PNG embarqués, format reconnu par Windows Vista et suivants).
"""

import os
import struct
import sys

SIZES = (16, 24, 32, 48, 64, 128, 256)


def main(src, ico):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide import QtCore, QtGui

    if src.lower().endswith(".png"):
        app = QtGui.QGuiApplication.instance() or QtGui.QGuiApplication([sys.argv[0], "-platform", "offscreen"])
        source = QtGui.QImage(src)
        if source.isNull():
            raise SystemExit("PNG illisible : %s" % src)
        images = []
        for size in SIZES:
            img = source.scaled(size, size, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
            buf = QtCore.QBuffer()
            buf.open(QtCore.QIODevice.WriteOnly)
            img.save(buf, "PNG")
            images.append((size, bytes(buf.data())))
        write_ico(images, ico)
        del app
        return
    svg = src
    try:
        from PySide import QtSvg
    except ImportError:  # selon la version du shim PySide de FreeCAD
        try:
            from PySide6 import QtSvg
        except ImportError:
            from PySide2 import QtSvg
    app = QtGui.QGuiApplication.instance() or QtGui.QGuiApplication([sys.argv[0], "-platform", "offscreen"])
    renderer = QtSvg.QSvgRenderer(svg)
    if not renderer.isValid():
        raise SystemExit("SVG illisible : %s" % svg)
    images = []
    for size in SIZES:
        img = QtGui.QImage(size, size, QtGui.QImage.Format_ARGB32)
        img.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(img)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        renderer.render(painter)
        painter.end()
        buf = QtCore.QBuffer()
        buf.open(QtCore.QIODevice.WriteOnly)
        img.save(buf, "PNG")
        images.append((size, bytes(buf.data())))
    write_ico(images, ico)
    del app


def write_ico(images, ico):
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = b""
    payload = b""
    for size, data in images:
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset + len(payload))
        payload += data
    with open(ico, "wb") as fp:
        fp.write(header + entries + payload)
    print("icône écrite : %s (%s px)" % (ico, ", ".join(str(s) for s in SIZES)))


main(os.environ.get("CAM2027_ICON_SRC") or os.environ["CAM2027_ICON_SVG"], os.environ["CAM2027_ICON_OUT"])
