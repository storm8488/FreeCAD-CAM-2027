# SPDX-License-Identifier: LGPL-2.1-or-later
"""Relief depuis une image (carte de hauteur), cœur des reliefs 3D façon Aspire.

L'image (PNG, JPG, BMP) est lue en niveaux de gris : clair = haut (``invert`` pour l'inverse).
Elle est rééchantillonnée sur une grille (au plus ``cells`` points sur le grand côté), lissée
(``smoothing`` passes d'un flou 3 × 3), puis une surface B-spline passe exactement par les points
de la grille. Le solide : cette surface au-dessus, quatre parois réglées et un fond plan à
``z_bottom`` ; épaisseur sous le relief = ``base``. Il s'usine avec l'ébauche et la finition 3D
existantes (``rough3d``, ``surface3d``, ``waterline``).

Unités : mm. X = largeur de l'image (gauche → droite), Y = hauteur de l'image (bas → haut).
"""

import os

import FreeCAD

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp")
DEFAULT_CELLS = 120
MIN_CELLS = 8
MAX_CELLS = 400


def _qt():
    try:
        from PySide6 import QtCore, QtGui
    except ImportError:  # pragma: no cover - FreeCAD 1.0 (Qt 5)
        from PySide2 import QtCore, QtGui
    return QtCore, QtGui


def supported_formats():
    _QtCore, QtGui = _qt()
    return sorted(bytes(f).decode().lower() for f in QtGui.QImageReader.supportedImageFormats())


def ensure_image_plugins():
    """En console (FreeCADCmd), Qt ne trouve pas seul le lecteur JPEG : ajoute le dossier des modules Qt."""
    QtCore, _QtGui = _qt()
    if "jpg" in supported_formats():
        return True
    home = FreeCAD.getHomePath()
    for sub in ("lib/qt6/plugins", "lib/qt5/plugins", "plugins", "bin"):
        path = os.path.join(home, sub)
        if os.path.isdir(os.path.join(path, "imageformats")):
            QtCore.QCoreApplication.addLibraryPath(path)
    return "jpg" in supported_formats()


def load_heightmap(path, cells=DEFAULT_CELLS):
    """Grille ``g[i][j]`` dans [0, 1] (i : colonnes de gauche à droite, j : lignes de bas en haut)
    et taille de l'image en pixels. Les pixels transparents comptent comme bas (0)."""
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    QtCore, QtGui = _qt()
    ensure_image_plugins()
    img = QtGui.QImage(path)
    if img.isNull():
        raise ValueError("unreadable image: %s" % os.path.basename(path))
    w, h = img.width(), img.height()
    if w < 2 or h < 2:
        raise ValueError("image too small: %dx%d" % (w, h))
    cells = max(MIN_CELLS, min(MAX_CELLS, int(cells)))
    scale = min(1.0, float(cells) / max(w, h))
    nx, ny = max(2, int(round(w * scale))), max(2, int(round(h * scale)))
    if (nx, ny) != (w, h):
        img = img.scaled(nx, ny, QtCore.Qt.IgnoreAspectRatio, QtCore.Qt.SmoothTransformation)
    img = img.convertToFormat(QtGui.QImage.Format_ARGB32)
    grid = [[0.0] * ny for _ in range(nx)]
    for row in range(ny):
        j = ny - 1 - row  # ligne 0 de l'image = haut = Y max
        for i in range(nx):
            argb = img.pixel(i, row) & 0xFFFFFFFF
            a = (argb >> 24) & 255
            r, g, b = (argb >> 16) & 255, (argb >> 8) & 255, argb & 255
            grid[i][j] = (r * 11 + g * 16 + b * 5) / 32.0 / 255.0 * (a / 255.0)  # formule qGray de Qt
    return grid, (w, h)


def smooth(grid, passes):
    """``passes`` flous 3 × 3 (bords recopiés)."""
    nx, ny = len(grid), len(grid[0])
    for _ in range(max(0, int(passes))):
        out = [[0.0] * ny for _ in range(nx)]
        for i in range(nx):
            i0, i1 = max(0, i - 1), min(nx - 1, i + 1)
            for j in range(ny):
                j0, j1 = max(0, j - 1), min(ny - 1, j + 1)
                total = 0.0
                for a in range(i0, i1 + 1):
                    for b in range(j0, j1 + 1):
                        total += grid[a][b]
                out[i][j] = total / ((i1 - i0 + 1) * (j1 - j0 + 1))
        grid = out
    return grid


def relief_heights(grid, relief_height, base, invert=False, smoothing=1, z_bottom=0.0):
    """Hauteurs absolues (mm) de la grille : fond + épaisseur + relief × niveau de gris."""
    grid = [[1.0 - v for v in col] for col in grid] if invert else grid
    grid = smooth(grid, smoothing)
    return [[z_bottom + base + relief_height * v for v in col] for col in grid]


def build_shape(heights, width, length, z_bottom=0.0):
    """Solide fermé : surface B-spline par les hauteurs, parois réglées, fond plan."""
    import Part

    V = FreeCAD.Vector
    nx, ny = len(heights), len(heights[0])
    dx, dy = width / (nx - 1.0), length / (ny - 1.0)
    surf = Part.BSplineSurface()
    surf.interpolate(heights, 0.0, dx, 0.0, dy)
    top = Part.Face(surf)
    faces = [top]
    for edge in top.Edges:
        a, b = edge.Vertexes[0].Point, edge.Vertexes[-1].Point
        faces.append(Part.makeRuledSurface(edge, Part.makeLine(V(a.x, a.y, z_bottom), V(b.x, b.y, z_bottom))))
    corners = [V(0, 0, z_bottom), V(width, 0, z_bottom), V(width, length, z_bottom), V(0, length, z_bottom)]
    faces.append(Part.Face(Part.makePolygon(corners + corners[:1])))
    shell = Part.Shell(faces)
    shell.sewShape()
    solid = Part.Solid(shell)
    if solid.Volume < 0:
        solid.reverse()
    if not solid.isValid() or not solid.isClosed():
        raise ValueError("relief solid is not valid")
    return solid


def make_relief(doc, path, width, relief_height, base=2.0, invert=False, smoothing=1, cells=DEFAULT_CELLS,
                z_bottom=0.0, label=None):
    """Crée l'objet « Relief » (Part::Feature) ; retourne ``(objet, avertissements)``."""
    if width <= 0 or relief_height <= 0:
        raise ValueError("width and relief height must be positive")
    if base <= 0:
        raise ValueError("base thickness must be positive")
    grid, (w_px, h_px) = load_heightmap(path, cells)
    length = width * h_px / float(w_px)
    heights = relief_heights(grid, relief_height, base, invert, smoothing, z_bottom)
    shape = build_shape(heights, width, length, z_bottom)
    warnings = []
    nx, ny = len(grid), len(grid[0])
    if (nx, ny) != (w_px, h_px):
        warnings.append("image %dx%d px resampled to %dx%d points" % (w_px, h_px, nx, ny))
    # boîte optimale : BoundBox suit les points de contrôle de la B-spline et surestime le dessus
    overshoot = shape.optimalBoundingBox().ZMax - max(max(col) for col in heights)
    if overshoot > 0.02 * relief_height:
        warnings.append("surface overshoots the image by %.2f mm near sharp edges: increase smoothing" % overshoot)
    obj = doc.addObject("Part::Feature", "Relief")
    obj.Shape = shape
    obj.Label = label or os.path.splitext(os.path.basename(path))[0]
    for prop, kind, value in (("ReliefImage", "App::PropertyFile", path),
                              ("ReliefWidth", "App::PropertyLength", width),
                              ("ReliefHeight", "App::PropertyLength", relief_height),
                              ("ReliefBase", "App::PropertyLength", base),
                              ("ReliefInvert", "App::PropertyBool", bool(invert)),
                              ("ReliefSmoothing", "App::PropertyInteger", int(smoothing))):
        obj.addProperty(kind, prop, "CAM2027 relief", "")
        setattr(obj, prop, value)
    doc.recompute()
    return obj, warnings
