# SPDX-License-Identifier: LGPL-2.1-or-later
"""Aperçu coté d'un assemblage d'outil (vue 2D de révolution, peinte avec Qt).

L'aperçu 3D n'est pas coté : le bouton « Show in 3D » du panneau crée l'objet
ToolBit FreeCAD paramétrique dans le document actif.
"""

from .qt import QtCore, QtGui, QtWidgets
from ..i18n import tr


class ToolPreview(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super(ToolPreview, self).__init__(parent)
        self.tool = None
        self.holder = None
        self.stickout = None
        self.error = None
        self.setMinimumSize(220, 260)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)

    def set_tool(self, tool, holder=None, stickout=None):
        self.tool = tool
        self.holder = holder
        self.stickout = stickout
        self.error = None
        self.update()

    def set_error(self, message):
        """Valeur saisie incohérente : le dernier outil valable reste dessiné, le message s'affiche dessous."""
        self.error = message
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        pal = self.palette()
        painter.fillRect(self.rect(), pal.base())
        if self.tool is None:
            painter.setPen(pal.color(QtGui.QPalette.Mid))
            painter.drawText(self.rect(), QtCore.Qt.AlignCenter, tr("Select a tool to preview it"))
            return
        segs = self.tool.silhouette()
        holder_segs = []
        if self.holder is not None:
            holder_segs = list(self.holder.segments)
        total_h = sum(s.length for s in segs) + sum(s.length for s in holder_segs)
        max_d = max([s.lower_diameter for s in segs + holder_segs] + [s.upper_diameter for s in segs + holder_segs] + [1.0])
        margin = 46
        w = self.width() - 2 * margin
        h = self.height() - 2 * margin
        if w <= 10 or h <= 10:
            return
        scale = min(h / total_h, w / (max_d * 1.6))
        cx = margin + w / 2.0
        y = self.height() - margin  # pointe en bas
        text_pen = QtGui.QPen(pal.color(QtGui.QPalette.Text))
        dim_pen = QtGui.QPen(QtGui.QColor(94, 200, 160))
        dim_pen.setWidthF(1.2)
        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)

        def draw_segments(segments, brush):
            nonlocal y
            start_y = y
            for s in segments:
                top = y - s.length * scale
                poly = QtGui.QPolygonF([
                    QtCore.QPointF(cx - s.lower_diameter * scale / 2, y),
                    QtCore.QPointF(cx + s.lower_diameter * scale / 2, y),
                    QtCore.QPointF(cx + s.upper_diameter * scale / 2, top),
                    QtCore.QPointF(cx - s.upper_diameter * scale / 2, top),
                ])
                painter.setPen(QtGui.QPen(pal.color(QtGui.QPalette.Text), 1))
                painter.setBrush(brush)
                painter.drawPolygon(poly)
                y = top
            return start_y

        g = self.tool.geometry
        # partie taillée en jaune, queue en gris, porte-outil en bleu-gris
        flute_h = g.flute_length
        acc = 0.0
        cut_segs, rest_segs = [], []
        for s in segs:
            if acc + s.length <= flute_h + 1e-6:
                cut_segs.append(s)
            else:
                rest_segs.append(s)
            acc += s.length
        tip_y = y
        draw_segments(cut_segs, QtGui.QBrush(QtGui.QColor(232, 178, 74)))
        flute_top_y = y
        draw_segments(rest_segs, QtGui.QBrush(QtGui.QColor(190, 198, 210)))
        tool_top_y = y
        draw_segments(holder_segs, QtGui.QBrush(QtGui.QColor(120, 140, 170)))
        holder_top_y = y

        # cotes : diamètre, longueur taillée, longueur totale, sortie
        painter.setPen(dim_pen)
        d_y = tip_y + 14
        painter.drawLine(QtCore.QPointF(cx - g.diameter * scale / 2, d_y), QtCore.QPointF(cx + g.diameter * scale / 2, d_y))
        painter.drawText(QtCore.QRectF(cx - 60, d_y + 2, 120, 14), QtCore.Qt.AlignCenter, "D %.3g mm" % g.diameter)
        x_dim = cx + max_d * scale / 2 + 10
        painter.drawLine(QtCore.QPointF(x_dim, tip_y), QtCore.QPointF(x_dim, flute_top_y))
        painter.drawText(QtCore.QRectF(x_dim + 3, (tip_y + flute_top_y) / 2 - 7, 60, 14), QtCore.Qt.AlignLeft,
                         "Lc %.3g" % g.flute_length)
        if self.tool.tool_type not in ("taper", "taperedball", "taperbarrel") and abs(g.shank_diameter - g.diameter) > 1e-6:
            # diamètre du corps (queue), coté en haut de l'outil
            ds_y = tool_top_y - 6
            painter.drawLine(QtCore.QPointF(cx - g.shank_diameter * scale / 2, ds_y),
                             QtCore.QPointF(cx + g.shank_diameter * scale / 2, ds_y))
            painter.drawText(QtCore.QRectF(cx - 60, ds_y - 16, 120, 14), QtCore.Qt.AlignCenter,
                             "Ds %.3g mm" % g.shank_diameter)
        x_dim2 = x_dim + 22
        painter.drawLine(QtCore.QPointF(x_dim2, tip_y), QtCore.QPointF(x_dim2, tool_top_y))
        painter.drawText(QtCore.QRectF(x_dim2 + 3, (tip_y + tool_top_y) / 2 - 7, 60, 14), QtCore.Qt.AlignLeft,
                         "L %.3g" % g.overall_length)
        if self.stickout:
            x_dim3 = cx - max_d * scale / 2 - 10
            so_top = tip_y - self.stickout * scale
            painter.drawLine(QtCore.QPointF(x_dim3, tip_y), QtCore.QPointF(x_dim3, so_top))
            painter.drawText(QtCore.QRectF(x_dim3 - 62, (tip_y + so_top) / 2 - 7, 60, 14), QtCore.Qt.AlignRight,
                             "%s %.3g" % (tr("Stickout"), self.stickout))
            painter.drawLine(QtCore.QPointF(x_dim3 - 4, so_top), QtCore.QPointF(cx + max_d * scale / 2, so_top))
        painter.setPen(text_pen)
        label = "%s - %s - z=%d" % (self.tool.name, tr(self.tool.type_label()), self.tool.flute_count)
        painter.drawText(QtCore.QRectF(6, 4, self.width() - 12, 16), QtCore.Qt.AlignLeft, label)
        if g.tip_included_angle_deg is not None and self.tool.tool_type in ("vbit", "engrave", "chamfer", "drill", "dovetail"):
            painter.drawText(QtCore.QRectF(6, 20, self.width() - 12, 16), QtCore.Qt.AlignLeft,
                             "%s %.4g°" % (tr("Included angle"), g.tip_included_angle_deg))
        if g.taper_half_angle_deg is not None and (g.taper_half_angle_deg > 0 or self.tool.tool_type != "facemill"):
            painter.drawText(QtCore.QRectF(6, 36, self.width() - 12, 16), QtCore.Qt.AlignLeft,
                             "%s %.4g°" % (tr("Taper half-angle"), g.taper_half_angle_deg))
        if self.error:
            painter.setPen(QtGui.QPen(QtGui.QColor(230, 90, 80)))
            painter.drawText(QtCore.QRectF(6, self.height() - 34, self.width() - 12, 30),
                             QtCore.Qt.AlignLeft | QtCore.Qt.TextWordWrap, self.error)
