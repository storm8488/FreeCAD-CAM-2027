# SPDX-License-Identifier: LGPL-2.1-or-later
"""Fabrique les images de marque de CAM2027 à partir du logo horizontal choisi (PNG avec alpha).

    set CAM2027_LOGO_SRC=docs\\design\\brand\\logo-proposition.png
    set CAM2027_BRANDING_OUT=src\\Mod\\CAM2027\\Resources\\branding
    CAM2027.exe scripts\\make-branding.py      (ou FreeCAD.exe : il faut l'interface pour les polices)

Le symbole (F rouge, engrenage bleu, fraise) est recadré depuis la partie gauche du logo ; le texte
du logo source (« FreeCAD CAM ») est remplacé par le nom du logiciel, « CAM2027 », et la ligne
« FAO · USINAGE CNC », dans la même disposition (Segoe UI Black, police d'interface du thème).

Sorties (PNG, sauf l'icône) :
- ``cam2027-mark.png`` : symbole seul, carré 512 px (fonds clairs et sombres) ;
- ``cam2027-logo-light.png`` / ``cam2027-logo-dark.png`` : logo horizontal pour fond clair / sombre ;
- ``cam2027-splash.png`` : écran de démarrage (fond clair, 760 × 380) ;
- ``cam2027-icon.png`` : icône 256 px (symbole), base du ``.ico`` fabriqué à la construction ;
- ``cam2027-programlogo.png`` : logo sombre de 28 px de haut (coin de la fenêtre principale).
Les images produites sont enregistrées dans le dépôt : la construction n'a besoin d'aucune police.
"""

import os

from PySide import QtCore, QtGui, QtWidgets

DARK_TEXT = "#111827"
LIGHT_TEXT = "#F1F5FA"
BLUE = "#1F55D6"
BLUE_ON_DARK = "#4F8AF5"
SPLIT_X = 660  # le texte du logo source commence après cette colonne (px du PNG source)


def opaque_bbox(img, x_max):
    """Rectangle des pixels non transparents de la partie gauche (x < x_max)."""
    xs, ys = [], []
    h = img.height()
    for y in range(0, h, 2):
        for x in range(0, min(x_max, img.width()), 2):
            if QtGui.qAlpha(img.pixel(x, y)) > 24:
                xs.append(x)
                ys.append(y)
    return QtCore.QRect(min(xs), min(ys), max(xs) - min(xs) + 2, max(ys) - min(ys) + 2)


def square(img, size, pad=0.06):
    out = QtGui.QImage(size, size, QtGui.QImage.Format_ARGB32)
    out.fill(QtCore.Qt.transparent)
    inner = int(size * (1 - 2 * pad))
    scaled = img.scaled(inner, inner, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
    p = QtGui.QPainter(out)
    p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
    p.drawImage((size - scaled.width()) // 2, (size - scaled.height()) // 2, scaled)
    p.end()
    return out


def font(px, weight):
    f = QtGui.QFont("Segoe UI")
    f.setPixelSize(px)
    f.setWeight(weight)
    return f


def wordmark(mark, text_colour, blue, height=360):
    """Logo horizontal : symbole + « CAM2027 » (CAM foncé / clair, 2027 bleu) + « FAO · USINAGE CNC »."""
    mark_h = height
    m = mark.scaledToHeight(mark_h, QtCore.Qt.SmoothTransformation)
    name_font = font(int(height * 0.40), QtGui.QFont.Black)
    tag_font = font(int(height * 0.13), QtGui.QFont.DemiBold)
    tag_font.setLetterSpacing(QtGui.QFont.PercentageSpacing, 135)
    fm_name, fm_tag = QtGui.QFontMetrics(name_font), QtGui.QFontMetrics(tag_font)
    tag = "FAO · USINAGE CNC"
    name_w = fm_name.horizontalAdvance("CAM2027")
    text_w = max(name_w, fm_tag.horizontalAdvance(tag))
    gap = int(height * 0.12)
    w = m.width() + gap + text_w + int(height * 0.06)
    out = QtGui.QImage(w, height, QtGui.QImage.Format_ARGB32)
    out.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(out)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.setRenderHint(QtGui.QPainter.TextAntialiasing)
    p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
    p.drawImage(0, 0, m)
    x = m.width() + gap
    base_name = int(height * 0.62)
    p.setFont(name_font)
    p.setPen(QtGui.QColor(text_colour))
    p.drawText(x, base_name, "CAM")
    p.setPen(QtGui.QColor(blue))
    p.drawText(x + fm_name.horizontalAdvance("CAM"), base_name, "2027")
    p.setFont(tag_font)
    p.setPen(QtGui.QColor(text_colour))
    p.drawText(x + int(height * 0.01), int(height * 0.86), tag)
    p.end()
    return out


def splash(logo_light, size=(760, 380)):
    w, h = size
    out = QtGui.QImage(w, h, QtGui.QImage.Format_ARGB32)
    out.fill(QtGui.QColor("#F7F9FC"))
    p = QtGui.QPainter(out)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
    p.setRenderHint(QtGui.QPainter.TextAntialiasing)
    p.fillRect(0, h - 8, w, 8, QtGui.QColor(BLUE))
    logo = logo_light.scaledToWidth(int(w * 0.80), QtCore.Qt.SmoothTransformation)
    p.drawImage((w - logo.width()) // 2, int(h * 0.12), logo)
    p.setFont(font(15, QtGui.QFont.Normal))
    p.setPen(QtGui.QColor("#4B5563"))
    p.drawText(QtCore.QRect(0, int(h * 0.72), w, 24), QtCore.Qt.AlignHCenter,
               "Fork indépendant basé sur FreeCAD et son atelier CAM - LGPL-2.1+")
    p.end()
    return out


def main(src, out_dir):
    img = QtGui.QImage(src)
    if img.isNull():
        raise SystemExit("logo illisible : %s" % src)
    img = img.convertToFormat(QtGui.QImage.Format_ARGB32)
    mark = img.copy(opaque_bbox(img, SPLIT_X))
    os.makedirs(out_dir, exist_ok=True)
    outputs = {
        "cam2027-mark.png": square(mark, 512),
        "cam2027-icon.png": square(mark, 256, pad=0.02),
        "cam2027-logo-light.png": wordmark(mark, DARK_TEXT, BLUE),
        "cam2027-logo-dark.png": wordmark(mark, LIGHT_TEXT, BLUE_ON_DARK),
    }
    outputs["cam2027-splash.png"] = splash(outputs["cam2027-logo-light.png"])
    outputs["cam2027-programlogo.png"] = outputs["cam2027-logo-dark.png"].scaledToHeight(
        28, QtCore.Qt.SmoothTransformation)
    for name, image in outputs.items():
        path = os.path.join(out_dir, name)
        if not image.save(path, "PNG"):
            raise SystemExit("écriture impossible : %s" % path)
        print("%s : %d x %d" % (name, image.width(), image.height()))
    with open(os.path.join(out_dir, "make-branding.log"), "w", encoding="utf-8") as fp:
        fp.write("mark bbox %s\n" % (opaque_bbox(img, SPLIT_X).getRect(),))


try:
    main(os.environ["CAM2027_LOGO_SRC"], os.environ["CAM2027_BRANDING_OUT"])
finally:
    app = QtWidgets.QApplication.instance()
    if app is not None:
        QtCore.QTimer.singleShot(200, app.quit)
