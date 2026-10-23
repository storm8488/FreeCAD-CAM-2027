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

from ..i18n import Msg, UserError

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp")
DEFAULT_CELLS = 120
MIN_CELLS = 8
MAX_CELLS = 400
TILE_CELLS = 8  # points par côté d'une face du dessus (voir ``top_tiles``)


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
        raise UserError("unreadable image: {file}", file=os.path.basename(path))
    w, h = img.width(), img.height()
    if w < 2 or h < 2:
        raise UserError("image too small: {w}x{h}", w=w, h=h)
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


#: plus grand côté (px) de l'image analysée pour le gonflage (distance au bord à la résolution de l'image)
INFLATE_MAX_PX = 1600
SOURCES = ("grey", "inflate", "depth")

# -- profondeur par IA (Depth Anything V2 Small, Apache-2.0), installée à la demande -------------------------------
#: modèle ONNX et paquet onnxruntime, hors du Python de FreeCAD (dossier de l'utilisateur)
DEPTH_MODEL_URL = "https://huggingface.co/onnx-community/depth-anything-v2-small/resolve/main/onnx/model.onnx"
DEPTH_MODEL_FILE = "depth_anything_v2_small.onnx"
DEPTH_RUNTIME = "onnxruntime==1.20.1"
DEPTH_SIZE = 518  # côté de l'image vue par le modèle (multiple de 14)


def depth_dir():
    """Dossier du modèle et d'onnxruntime : ``CAM2027_DEPTH_DIR`` ou ``%LOCALAPPDATA%/CAM2027/depth``."""
    if os.environ.get("CAM2027_DEPTH_DIR"):
        return os.environ["CAM2027_DEPTH_DIR"]
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "CAM2027", "depth")


def _onnxruntime():
    import sys

    site = os.path.join(depth_dir(), "site")
    if os.path.isdir(site) and site not in sys.path:
        sys.path.insert(0, site)
    import onnxruntime

    return onnxruntime


def depth_available():
    """True si le modèle et onnxruntime sont installés (rien n'est téléchargé ici)."""
    if not os.path.isfile(os.path.join(depth_dir(), DEPTH_MODEL_FILE)):
        return False
    try:
        _onnxruntime()
    except Exception:
        return False
    return True


def install_depth(progress=None):
    """Installe onnxruntime (pip, dossier à part, sans dépendances : numpy suffit) et télécharge le modèle (~100 Mo).
    À appeler seulement après l'accord de l'utilisateur. ``progress(texte)`` est appelé pendant le travail."""
    import subprocess
    import urllib.request

    folder = depth_dir()
    os.makedirs(folder, exist_ok=True)
    say = progress or (lambda _text: None)
    try:
        _onnxruntime()
    except Exception:
        say("onnxruntime")
        python = os.path.join(FreeCAD.getHomePath(), "bin", "python.exe")
        proc = subprocess.run([python, "-m", "pip", "install", "--disable-pip-version-check", "--no-deps", "--target",
                               os.path.join(folder, "site"), DEPTH_RUNTIME], capture_output=True, text=True,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if proc.returncode != 0:
            raise UserError("onnxruntime could not be installed: {error}", error=(proc.stderr or proc.stdout)[-300:])
    model = os.path.join(folder, DEPTH_MODEL_FILE)
    if not os.path.isfile(model):
        part = model + ".part"
        with urllib.request.urlopen(DEPTH_MODEL_URL, timeout=60) as response, open(part, "wb") as fp:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = response.read(1 << 20)
                if not chunk:
                    break
                fp.write(chunk)
                done += len(chunk)
                say("model %d / %d MB" % (done >> 20, total >> 20) if total else "model %d MB" % (done >> 20))
        os.replace(part, model)
    if not depth_available():
        raise UserError("the AI depth model is not usable after installation")


def depth_grid(path, cells=DEFAULT_CELLS, grey_mix=0.0):
    """Hauteurs [0, 1] estimées par Depth Anything V2 Small (proche = haut) : le volume d'une photo ou d'une
    illustration ; ``grey_mix`` (0..1) y ajoute les niveaux de gris (clair = haut : les traits sombres d'un dessin
    se creusent dans le volume). Même grille que ``load_heightmap``."""
    import numpy as np
    from scipy import ndimage

    if not depth_available():
        raise UserError("the AI depth model is not installed")
    grey, (w_px, h_px) = load_grey_array(path)
    QtCore, QtGui = _qt()
    img = QtGui.QImage(path).convertToFormat(QtGui.QImage.Format_RGB888)
    scale = float(DEPTH_SIZE) / max(w_px, h_px)
    mw, mh = (max(14, int(round(v * scale / 14.0)) * 14) for v in (w_px, h_px))
    img = img.scaled(mw, mh, QtCore.Qt.IgnoreAspectRatio, QtCore.Qt.SmoothTransformation)
    rgb = np.frombuffer(bytes(img.constBits()), np.uint8).reshape(mh, img.bytesPerLine())[:, :mw * 3]
    rgb = rgb.reshape(mh, mw, 3) / 255.0
    x = ((rgb - [0.485, 0.456, 0.406]) / [0.229, 0.224, 0.225]).transpose(2, 0, 1)[None].astype(np.float32)
    ort = _onnxruntime()
    session = ort.InferenceSession(os.path.join(depth_dir(), DEPTH_MODEL_FILE), providers=["CPUExecutionProvider"])
    depth = session.run(None, {session.get_inputs()[0].name: x})[0].reshape(mh, mw).astype(np.float64)
    span = depth.max() - depth.min()
    depth = (depth - depth.min()) / span if span > 0 else np.zeros_like(depth)
    cells = max(MIN_CELLS, min(MAX_CELLS, int(cells)))
    s = min(1.0, float(cells) / max(w_px, h_px))
    nx, ny = max(2, int(round(w_px * s))), max(2, int(round(h_px * s)))
    small = ndimage.zoom(depth, (ny / float(mh), nx / float(mw)), order=1)[:ny, :nx]
    mix = min(1.0, max(0.0, float(grey_mix)))
    if mix:
        factor = grey.shape[1] / float(nx)
        g = ndimage.gaussian_filter(grey, sigma=0.5 * factor) if factor > 1.0 else grey
        g = ndimage.zoom(g, (ny / float(grey.shape[0]), nx / float(grey.shape[1])), order=1)[:ny, :nx]
        small = (1.0 - mix) * small + mix * g
    small = np.clip(small, 0.0, 1.0)
    return [[float(small[ny - 1 - j, i]) for j in range(ny)] for i in range(nx)], (w_px, h_px)


def load_grey_array(path, max_px=INFLATE_MAX_PX):
    """Image en niveaux de gris [0, 1] (numpy, ``a[ligne][colonne]``, ligne 0 = haut), réduite à ``max_px`` sur le
    grand côté, et sa taille d'origine en pixels. Les pixels transparents comptent comme noirs."""
    import numpy as np

    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    QtCore, QtGui = _qt()
    ensure_image_plugins()
    img = QtGui.QImage(path)
    if img.isNull():
        raise UserError("unreadable image: {file}", file=os.path.basename(path))
    w, h = img.width(), img.height()
    if w < 2 or h < 2:
        raise UserError("image too small: {w}x{h}", w=w, h=h)
    if max(w, h) > max_px:
        img = img.scaled(max_px, max_px, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
    img = img.convertToFormat(QtGui.QImage.Format_ARGB32)
    raw = bytes(img.constBits())
    arr = np.frombuffer(raw, dtype=np.uint8).reshape(img.height(), img.bytesPerLine())[:, :img.width() * 4]
    arr = arr.reshape(img.height(), img.width(), 4).astype(np.float64)
    b_, g_, r_, a_ = arr[..., 0], arr[..., 1], arr[..., 2], arr[..., 3]  # ARGB32 = octets B G R A
    grey = (r_ * 11 + g_ * 16 + b_ * 5) / 32.0 / 255.0 * (a_ / 255.0)
    return grey, (w, h)


def inflate_grid(path, width, relief_height, cells=DEFAULT_CELLS, threshold=0.5, raise_light=False, rounding=3.0,
                 grey_mix=0.0):
    """Hauteurs [0, 1] « gonflées » (comme « Créer une forme > arrondi » d'Aspire) : les formes sombres de l'image
    (les claires avec ``raise_light``) deviennent des dômes arrondis sur ``rounding`` mm depuis leur bord, plats
    au-delà ; un trait fin devient une arête arrondie d'autant plus haute qu'il est large. ``grey_mix`` (0..1)
    garde une part des niveaux de gris (ombrages du dessin). Pour un dessin au trait, un logo, une silhouette — une
    image en niveaux de gris n'est pas une carte de profondeur. Même grille que ``load_heightmap``."""
    import numpy as np
    from scipy import ndimage

    grey, (w_px, h_px) = load_grey_array(path)
    mask = grey >= threshold if raise_light else grey < threshold
    if not mask.any():
        raise UserError("no shape found in the image at this threshold")
    px_mm = width / float(grey.shape[1])
    dist = np.maximum(ndimage.distance_transform_edt(mask) - 0.5, 0.0) * px_mm  # au bord réel (demi-pixel)
    r = max(1e-6, float(rounding))
    t = np.clip(dist / r, 0.0, 1.0)
    dome = np.sqrt(1.0 - (1.0 - t) ** 2)  # quart de cercle (étiré à la hauteur du relief)
    dome[~mask] = 0.0
    mix = min(1.0, max(0.0, float(grey_mix)))
    if mix:
        shade = grey if raise_light else 1.0 - grey
        dome = (1.0 - mix) * dome + mix * shade
    cells = max(MIN_CELLS, min(MAX_CELLS, int(cells)))
    scale = min(1.0, float(cells) / max(w_px, h_px))
    nx, ny = max(2, int(round(w_px * scale))), max(2, int(round(h_px * scale)))
    factor = dome.shape[1] / float(nx)
    if factor > 1.0:  # anti-crénelage avant réduction
        dome = ndimage.gaussian_filter(dome, sigma=0.5 * factor)
    small = ndimage.zoom(dome, (ny / float(dome.shape[0]), nx / float(dome.shape[1])), order=1)[:ny, :nx]
    small = np.clip(small, 0.0, 1.0)
    grid = [[float(small[ny - 1 - j, i]) for j in range(ny)] for i in range(nx)]  # ligne 0 de l'image = Y max
    return grid, (w_px, h_px)


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


def top_tiles(surf, nx, ny, cells=TILE_CELLS):
    """Faces du dessus : la B-spline découpée en tuiles d'environ ``cells`` × ``cells`` points (même surface).
    OpenCascade triangule une grande face B-spline en un temps et une mémoire bien plus que proportionnels :
    à l'écart de la finition 3D (0,0025 mm), le relief 80 × 60 du test prenait 23 s et 3,1 Go d'un seul tenant,
    0,3 s et 0,25 Go en 10 × 10 tuiles."""
    import Part

    nu, nv = max(1, -(-(nx - 1) // cells)), max(1, -(-(ny - 1) // cells))
    u0, u1, v0, v1 = surf.bounds()
    us = [u0 + (u1 - u0) * k / float(nu) for k in range(nu + 1)]
    vs = [v0 + (v1 - v0) * k / float(nv) for k in range(nv + 1)]
    faces = []
    for a in range(nu):
        for b in range(nv):
            tile = surf.copy()
            tile.segment(us[a], us[a + 1], vs[b], vs[b + 1])
            faces.append(Part.Face(tile))
    return faces


def build_shape(heights, width, length, z_bottom=0.0):
    """Solide fermé : surface B-spline par les hauteurs (en tuiles), parois réglées, fond plan."""
    import Part

    V = FreeCAD.Vector
    nx, ny = len(heights), len(heights[0])
    dx, dy = width / (nx - 1.0), length / (ny - 1.0)
    surf = Part.BSplineSurface()
    surf.interpolate(heights, 0.0, dx, 0.0, dy)
    faces = top_tiles(surf, nx, ny)
    eps = 1e-6 * max(width, length)
    bottom = []
    for tile in list(faces):
        for edge in tile.Edges:
            a, b = edge.Vertexes[0].Point, edge.Vertexes[-1].Point
            if not any(abs(a[k] - c) < eps and abs(b[k] - c) < eps for k, c in ((0, 0.0), (0, width), (1, 0.0),
                                                                                (1, length))):
                continue  # arête entre deux tuiles
            line = Part.makeLine(V(a.x, a.y, z_bottom), V(b.x, b.y, z_bottom))
            faces.append(Part.makeRuledSurface(edge, line))
            bottom.append(line)
    faces.append(Part.Face(Part.Wire(Part.__sortEdges__(bottom))))
    shell = Part.Shell(faces)
    shell.sewShape()
    solid = Part.Solid(shell)
    if solid.Volume < 0:
        solid.reverse()
    if not solid.isValid() or not solid.isClosed():
        raise UserError("relief solid is not valid")
    return solid


def make_relief(doc, path, width, relief_height, base=2.0, invert=False, smoothing=1, cells=DEFAULT_CELLS,
                z_bottom=0.0, label=None, source="grey", threshold=0.5, rounding=3.0, grey_mix=0.0):
    """Crée l'objet « Relief » (Part::Feature) ; retourne ``(objet, avertissements)``. ``source`` : ``grey``
    (niveau de gris = hauteur), ``inflate`` (formes gonflées, voir ``inflate_grid`` ; ``invert`` y lève les zones
    claires au lieu des sombres) ou ``depth`` (profondeur estimée par l'IA, voir ``depth_grid``)."""
    if width <= 0 or relief_height <= 0:
        raise UserError("width and relief height must be positive")
    if base <= 0:
        raise UserError("base thickness must be positive")
    if source not in SOURCES:
        raise UserError("unknown relief source: {s}", s=source)
    if source == "inflate":
        grid, (w_px, h_px) = inflate_grid(path, width, relief_height, cells, threshold, invert, rounding, grey_mix)
        heights = relief_heights(grid, relief_height, base, False, smoothing, z_bottom)
    elif source == "depth":
        grid, (w_px, h_px) = depth_grid(path, cells, grey_mix)
        heights = relief_heights(grid, relief_height, base, invert, smoothing, z_bottom)
    else:
        grid, (w_px, h_px) = load_heightmap(path, cells)
        heights = relief_heights(grid, relief_height, base, invert, smoothing, z_bottom)
    length = width * h_px / float(w_px)
    shape = build_shape(heights, width, length, z_bottom)
    warnings = []
    nx, ny = len(grid), len(grid[0])
    if (nx, ny) != (w_px, h_px):
        warnings.append(Msg("image {w}x{h} px resampled to {nx}x{ny} points", w=w_px, h=h_px, nx=nx, ny=ny))
    # boîte optimale : BoundBox suit les points de contrôle de la B-spline et surestime le dessus
    overshoot = shape.optimalBoundingBox().ZMax - max(max(col) for col in heights)
    if overshoot > 0.02 * relief_height:
        warnings.append(Msg("surface overshoots the image by {d:.2f} mm near sharp edges: increase smoothing", d=overshoot))
    obj = doc.addObject("Part::Feature", "Relief")
    obj.Shape = shape
    obj.Label = label or os.path.splitext(os.path.basename(path))[0]
    for prop, kind, value in (("ReliefImage", "App::PropertyFile", path),
                              ("ReliefWidth", "App::PropertyLength", width),
                              ("ReliefHeight", "App::PropertyLength", relief_height),
                              ("ReliefBase", "App::PropertyLength", base),
                              ("ReliefInvert", "App::PropertyBool", bool(invert)),
                              ("ReliefSmoothing", "App::PropertyInteger", int(smoothing)),
                              ("ReliefSource", "App::PropertyString", source)):
        obj.addProperty(kind, prop, "CAM2027 relief", "")
        setattr(obj, prop, value)
    if FreeCAD.GuiUp and obj.ViewObject is not None:
        # ombré sans arêtes : les bords des tuiles du dessus (des milliers) cachaient le relief sous un quadrillage
        obj.ViewObject.DisplayMode = "Shaded"
    doc.recompute()
    return obj, warnings
