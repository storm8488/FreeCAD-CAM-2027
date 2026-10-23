# SPDX-License-Identifier: LGPL-2.1-or-later
"""Projet d'essais machine (flux C5) : génère les G-code des premiers usinages et leurs fiches.

    FreeCADCmd.exe -M <CAM2027> <CAM2027>/tests/machine_trials/build.py

(dossier de sortie : variable d'environnement ``CAM2027_TRIALS_OUT``, sinon ``tests/machine_trials/output``)

Bois tendre 200 x 150 x 18 mm, origine G54 au coin avant gauche du dessus (X0 Y0 Z0), fraise plate 6 mm (T1),
boule 6 mm (T3), V-bit 60° (T5) de la bibliothèque de démarrage, profil LUNYEE 4040 Nova. Un projet CAM2027
par essai et **un seul outil par fichier** (aucun changement d'outil en cours de programme). Les essais 01 à 08
sont sur la planche 1 (une zone chacun), le recto-verso (09) sur la planche 2.

Pour chaque essai : ``<id>.nc`` et sa fiche CAM2027 (``-setup.md``), ``FICHE.md`` (montage, cotes au pied à
coulisse avec la valeur attendue et la valeur simulée par CAM2027), et dans ``trials.json`` la référence des
positions (parcours CAM2027 avant postprocesseur, voir ``reference.py``) pour la validation par le simulateur
GRBL (``validate.py``). Par défaut la sortie va dans ``tests/machine_trials/output``.
"""

import ast
import json
import math
import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(os.path.dirname(HERE))
if MOD not in sys.path:
    sys.path.insert(0, MOD)

import FreeCAD  # noqa: E402
import Part  # noqa: E402

from cam2027 import i18n  # noqa: E402
from cam2027.project import export as exportmod  # noqa: E402
from cam2027.project import operations as opsmod  # noqa: E402
from cam2027.project import probe as probemod  # noqa: E402
from cam2027.project import sim  # noqa: E402
from cam2027.project import trim  # noqa: E402
from cam2027.project import twosided  # noqa: E402
from cam2027.project.machine import lunyee_4040_nova  # noqa: E402
from cam2027.project.project import Project  # noqa: E402
from cam2027.tools.library import starter_library  # noqa: E402

try:
    from . import reference as refmod
except ImportError:  # lancé comme script par FreeCADCmd
    sys.path.insert(0, HERE)
    import reference as refmod  # noqa: E402

V = FreeCAD.Vector
L, W, T = 200.0, 150.0, 18.0  # planche
OUTPUT = os.path.join(HERE, "output")

#: palpeur du profil d'essai : VALEURS À REMPLACER par celles du palpeur réel (fiche de l'essai 01)
PROBE = {"present": True, "tip_diameter_mm": 2.0, "plate_thickness_mm": 0.0, "feed_mm_min": 100.0,
         "travel_mm": 25.0, "tool_number": 99}


def machine():
    m = lunyee_4040_nova()
    m.probe = dict(PROBE)
    return m


def _default_params_function():
    """``gui.commands.default_params`` (réglages initiaux d'une opération dérivés du préréglage, ceux que
    l'utilisateur obtient dans l'interface), relu dans le fichier source : ``gui.commands`` importe Qt."""
    src_path = os.path.join(MOD, "cam2027", "gui", "commands.py")
    with open(src_path, encoding="utf-8") as fp:
        tree = ast.parse(fp.read())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "default_params")
    scope = {"thread_names": opsmod.thread_names, "DEFAULT_THREAD_TYPE": opsmod.DEFAULT_THREAD_TYPE}
    exec(compile(ast.Module(body=[node], type_ignores=[]), src_path, "exec"), scope)
    return scope["default_params"]


default_params = _default_params_function()


# -- géométrie --------------------------------------------------------------------------------------------


def board():
    return Part.makeBox(L, W, T, V(0, 0, -T))


def rounded_box(x, y, length, width, height, radius, z=-T):
    """Boîte aux coins verticaux arrondis."""
    box = Part.makeBox(length, width, height, V(x, y, z))
    edges = [e for e in box.Edges if abs(e.Vertexes[0].Point.x - e.Vertexes[1].Point.x) < 1e-9
             and abs(e.Vertexes[0].Point.y - e.Vertexes[1].Point.y) < 1e-9]
    return box.makeFillet(radius, edges)


def planar_face(clone, z, area=None):
    best = None
    for i, f in enumerate(clone.Shape.Faces, 1):
        bb = f.BoundBox
        if f.Surface.__class__.__name__ == "Plane" and abs(bb.ZMin - z) < 1e-6 and abs(bb.ZMax - z) < 1e-6:
            if area is None or abs(f.Area - area) < 1.0:
                if best is None or f.Area > best[1]:
                    best = ("Face%d" % i, f.Area)
    return best[0] if best else None


def faces_of_type(clone, surface, zmin=None):
    out = []
    for i, f in enumerate(clone.Shape.Faces, 1):
        if f.Surface.__class__.__name__ == surface and (zmin is None or f.BoundBox.ZMin > zmin - 1e-6):
            out.append("Face%d" % i)
    return out


def cylinder_face(clone, x, y, radius):
    for i, f in enumerate(clone.Shape.Faces, 1):
        s = f.Surface
        if s.__class__.__name__ == "Cylinder" and abs(s.Radius - radius) < 1e-6 \
                and math.hypot(s.Center.x - x, s.Center.y - y) < 1e-6:
            return "Face%d" % i
    return None


# -- outils ----------------------------------------------------------------------------------------------


TOOLS = {"flat": "6 mm flat end mill 2F", "ball": "6 mm ball end mill 2F", "vbit": "60° V-bit"}


def tool(lib, key):
    t = [x for x in lib.search(TOOLS[key]) if x.name == TOOLS[key]][0]
    asm = lib.assemblies_for_tool(t.id)[0]
    return t, asm, t.presets[0]


def add_op(proj, kind, label, key, base=None, **extra):
    """Opération avec les réglages initiaux de l'interface (``default_params``) complétés par ``extra``."""
    lib = proj.library
    t, asm, preset = tool(lib, key)
    params = default_params(kind, t, preset.resolve(t))
    params.update(extra)
    op, rec = proj.add_operation(kind, label, asm.id, preset.id, base=base, params=params)
    ignored = [p for p in rec.get("ignored_params") or [] if p in extra]  # ceux de l'interface : ignorés là-bas aussi
    if ignored:
        raise RuntimeError("%s : paramètres ignorés %s" % (label, ignored))
    return op


#: poches : zigzag puis une passe le long des parois (comme Fusion). Le motif par défaut (zigzag seul) laisse des
#: festons de ~0,5 mm sur les parois (défaut décrit dans le bilan C5, ``test_jour4_c5.TestPocketWalls``)
POCKET = {"ClearingPattern": "ZigZagOffset"}


def new_project(name, shape, tmp, stock=None):
    lib = starter_library()
    proj = Project.create(name, lib, machine())
    step = os.path.join(tmp, re.sub(r"\W+", "_", name) + ".step")
    shape.exportStep(step)
    part = proj.import_model(step, label=name).objects[0]
    proj.create_job([part], stock=stock or {"kind": "box_margins", "xy": 0.0, "z_top": 0.0, "z_bottom": 0.0})
    return proj, proj.job.Model.Group[0]


BOARD_STOCK = {"kind": "box", "length": L, "width": W, "height": T, "origin": [0.0, 0.0, -T]}


# -- mesures sur la matière simulée ----------------------------------------------------------------------


class _Cmd(object):
    __slots__ = ("Name", "Parameters")

    def __init__(self, name, params):
        self.Name, self.Parameters = name, params


_WORD = re.compile(r"([A-Z])([-+]?\d*\.?\d+)")


def nc_commands(text):
    """Commandes de mouvement d'un G-code GRBL exporté (mouvement modal, commentaires ôtés)."""
    out = []
    motion = None
    for raw in text.splitlines():
        line = re.sub(r"\(.*?\)", "", raw).split(";")[0].upper().replace(" ", "")
        words = _WORD.findall(line)
        params = {}
        for letter, num in words:
            if letter == "G" and float(num) in (0, 1, 2, 3):
                motion = "G%d" % int(float(num))
            elif letter in "XYZIJ":
                params[letter] = float(num)
        if motion and any(k in params for k in "XYZ"):
            out.append(_Cmd(motion, params))
    return out


def carve(nc_texts_and_tools, window, res, z_top=0.0):
    """Carte de hauteur après les fichiers ``[(texte G-code, outil bibliothèque)]`` dans ``window``."""
    x0, y0, x1, y1 = window
    zm = sim.ZMap(x0, y0, x1, y1, z_top, res)
    for text, libtool in nc_texts_and_tools:
        profile, _note = sim.ToolProfile.from_library_tool(libtool)
        segs, _pos = sim.path_segments(nc_commands(text))
        cuts = [(p0, p1) for rapid, p0, p1 in segs if not rapid]
        if cuts:
            zm.sweep_many(cuts, profile)
    return zm


def run_length(zm, axis, at, center, below):
    """Longueur (mm) de la plage continue de colonnes de hauteur ``< below`` (``> -below`` si ``below`` est
    négatif : matière restante) qui contient ``center`` sur la ligne ``axis`` = X (y = ``at``) ou Y (x = ``at``)."""
    if axis == "X":
        j = int((at - zm.y0) / zm.res)
        line, coords = zm.top[:, j], zm.xs
    else:
        i = int((at - zm.x0) / zm.res)
        line, coords = zm.top[i, :], zm.ys
    k = int(round((center - coords[0]) / zm.res))
    ok = (line < below) if below >= -1e9 else None
    if not ok[k]:
        return 0.0, None
    lo = k
    while lo > 0 and ok[lo - 1]:
        lo -= 1
    hi = k
    while hi < len(line) - 1 and ok[hi + 1]:
        hi += 1
    return (hi - lo + 1) * zm.res, (coords[lo] + coords[hi]) / 2.0


def height(zm, x, y):
    return float(zm.top[int((x - zm.x0) / zm.res), int((y - zm.y0) / zm.res)])


# -- essais ----------------------------------------------------------------------------------------------


def measure(label, how, nominal, tol, simulated=None, unit="mm"):
    return {"label": label, "how": how, "nominal": nominal, "tol": tol, "simulated": simulated, "unit": unit}


def trial_probe(tmp):
    proj, _clone = new_project("01 Palpage du coin", board(), tmp)
    probemod.add_probe(proj, "corner")
    return proj, {
        "zone": "coin avant gauche de la planche 1 (palpeur posé au-dessus de la planche, à 10 mm des deux bords)",
        "tools": [],
        "files": [("01-palpage-coin", None)],
        "measures": [
            measure("Écart X entre l'origine palpée et l'origine à la feuille de papier",
                    "après le palpage : G0 Z5 puis G0 X0 Y0 ; descendre à Z0,5 au pas de 0,1 mm, comparer au coin "
                    "(réglet contre le chant, ou feuille de papier) ; lire aussi WCO dans CNCjs avant / après", 0.0, 0.1),
            measure("Écart Y", "idem sur le chant avant", 0.0, 0.1),
            measure("Écart Z (dessus de la planche)", "feuille de papier sous la fraise à Z0 : elle accroche à peine",
                    0.0, 0.1),
        ],
    }


def trial_pocket(tmp):
    shape = board().cut(Part.makeBox(40, 30, 6, V(15, 20, -6)))
    proj, clone = new_project("02 Poche", shape, tmp)
    add_op(proj, "pocket", "Poche 40x30x6", "flat", base=[(clone, [planar_face(clone, -6.0)])], **POCKET)
    return proj, {
        "zone": "X 15..55, Y 20..50 (avant gauche)",
        "tools": ["flat"],
        "files": [("02-poche", None)],
        "window": (10, 15, 60, 55), "res": 0.05,
        "measures": [
            ("X", 35.0, 35.0, 0.0, "Longueur intérieure (X)", "becs intérieurs du pied à coulisse, à mi-profondeur",
             40.0, 0.15),
            ("Y", 35.0, 35.0, 0.0, "Largeur intérieure (Y)", "becs intérieurs, à mi-profondeur", 30.0, 0.15),
            ("depth", 35.0, 35.0, None, "Profondeur", "jauge de profondeur, au centre", 6.0, 0.1),
            ("radius", None, None, None, "Rayon des angles", "comparer à la fraise : rayon = 3 mm (rayon de la fraise)",
             3.0, 0.2),
        ],
    }


def trial_stepped(tmp):
    shape = board().cut(Part.makeBox(50, 40, 3, V(70, 15, -3))).cut(Part.makeBox(24, 16, 8, V(83, 27, -8)))
    proj, clone = new_project("03 Poche a deux profondeurs", shape, tmp)
    add_op(proj, "pocket", "Poche haute 50x40x3", "flat", base=[(clone, [planar_face(clone, -3.0)])], **POCKET)
    add_op(proj, "pocket", "Poche basse 24x16x8", "flat", base=[(clone, [planar_face(clone, -8.0)])], **POCKET)
    return proj, {
        "zone": "X 70..120, Y 15..55 (avant milieu)",
        "tools": ["flat"],
        "files": [("03-poche-2-profondeurs", None)],
        "window": (65, 10, 125, 60), "res": 0.05,
        "measures": [
            ("X", 35.0, 76.0, -0.0, "Grande poche : longueur (X)", "becs intérieurs, entre 0 et -3", 50.0, 0.15),
            ("Y", 74.0, 35.0, -0.0, "Grande poche : largeur (Y)", "becs intérieurs, entre 0 et -3", 40.0, 0.15),
            ("depth", 74.0, 20.0, None, "Grande poche : profondeur", "jauge de profondeur sur la marche", 3.0, 0.1),
            ("X", 35.0, 95.0, -3.0, "Petite poche : longueur (X)", "becs intérieurs, sous la marche", 24.0, 0.15),
            ("Y", 95.0, 35.0, -3.0, "Petite poche : largeur (Y)", "becs intérieurs, sous la marche", 16.0, 0.15),
            ("depth", 95.0, 35.0, None, "Petite poche : profondeur depuis le dessus",
             "jauge de profondeur depuis le dessus de la planche", 8.0, 0.1),
        ],
    }


HOLES = ((140.0, 35.0), (160.0, 35.0), (180.0, 35.0))


def trial_holes(tmp):
    shape = board()
    for x, y in HOLES:
        shape = shape.cut(Part.makeCylinder(3.0, 10.0, V(x, y, -10.0)))
    proj, clone = new_project("04 Percage", shape, tmp)
    add_op(proj, "drilling", "Percage 3 trous", "flat", base=[(clone, [])])
    return proj, {
        "zone": "X 137..183, Y 32..38 (avant droite)",
        "tools": ["flat"],
        "files": [("04-percage", None)],
        "window": (130, 25, 190, 45), "res": 0.05,
        "measures": [
            ("X", 35.0, 140.0, -0.0, "Diamètre du trou 1", "becs intérieurs (fraise plate en plongée : 6,0 à 6,1)",
             6.0, 0.15),
            ("pitch", 35.0, (140.0, 160.0), -0.0, "Entraxe trous 1-2", "bord à bord extérieur moins un diamètre",
             20.0, 0.1),
            ("pitch", 35.0, (140.0, 180.0), -0.0, "Entraxe trous 1-3", "idem", 40.0, 0.1),
            ("depth", 160.0, 35.0, None, "Profondeur (trou 2)", "jauge de profondeur au centre", 10.0, 0.1),
        ],
    }


DOME = (45.0, 112.5, -40.0, 40.0)  # centre x, y, z, rayon : sommet à Z0, pied à Z-10 (rayon 26,46)
#: cuvette ouverte sur le chant arrière : l'ébauche 3D « pièce entière » (mode modèle de FreeCAD 1.1) ne dégage que
#: la matière accessible depuis l'extérieur de la pièce ; dans une cuvette fermée elle ne coupe rien (défaut décrit
#: dans le bilan C5, test ``test_jour4_c5.TestRough3dEnclosed``)
RECESS = (10.0, 75.0, 70.0, 75.0, 10.0)  # x, y, longueur, largeur, profondeur


def dome_shape():
    cx, cy, cz, r = DOME
    x, y, length, width, depth = RECESS
    recess = Part.makeBox(length, width, depth, V(x, y, -depth))
    dome = Part.makeSphere(r, V(cx, cy, cz)).common(recess)
    return board().cut(recess).fuse(dome).removeSplitter()


def trial_dome(tmp):
    proj, clone = new_project("05-06 Dome", dome_shape(), tmp)
    # passe de 1,5 mm (au lieu des 3 mm du préréglage) : marches plus petites, au plus ~2 mm de reste pour la boule
    rough = add_op(proj, "rough3d", "Ebauche dome", "flat", base=[(clone, [])], StockToLeave=0.5, StepDown=1.5,
                   FinalDepth=-10.0)
    # habillage « Limiter à une zone » : sans lui, l'ébauche « pièce entière » contourne aussi toute la planche à
    # chaque palier (4,5 m d'avance dans le vide, 0,5 mm du chant, là où seraient des butées ou des brides)
    x, y, length, width, _depth = RECESS
    rough = trim.set_limit(proj, rough, trim.rectangle(x - 4.0, y - 4.0, x + length + 4.0, y + width + 6.0),
                           inside=True, source="rectangle")
    faces = faces_of_type(clone, "Sphere") + [planar_face(clone, -10.0)]
    finish = add_op(proj, "surface3d", "Finition dome", "ball", base=[(clone, faces)], BoundBox="BaseBoundBox")
    cx, cy, cz, r = DOME
    foot = math.sqrt(r * r - (cz + 10) ** 2)
    return proj, {
        "zone": "X 10..80, Y 75..150 (arrière gauche) : cuvette 70 x 75 x 10 ouverte sur le chant arrière, dôme R40 "
                "au milieu (sommet au ras du dessus)",
        "tools": ["flat", "ball"],
        "files": [("05-dome-ebauche", rough), ("06-dome-finition", finish)],
        "notes": ["L'ébauche est limitée à un rectangle autour de la cuvette (habillage « Limiter à une zone ») : "
                  "sans lui elle contournerait toute la planche à chaque palier, dans le vide.",
                  "L'ébauche laisse des marches de 1,5 mm et 0,5 mm de surépaisseur : au pied du dôme, la boule enlève "
                  "jusqu'à ~2 mm. Lancer la finition sans démonter la planche (même origine X Y), seul Z0 est refait."],
        "window": (5, 70, 85, 150), "res": 0.1,
        "measures": {
            "05-dome-ebauche": [
                ("X", 140.0, 13.0, -5.0, "Cuvette après ébauche : côté (X), près du bord arrière",
                 "becs intérieurs, à 5 mm sous le dessus", None, 0.2),
                ("depth", 14.0, 80.0, None, "Fond de la cuvette après ébauche (coin avant gauche)",
                 "jauge de profondeur à 4 mm des parois", None, 0.1),
                ("top", cx, cy, None, "Sommet du dôme après ébauche", "règle posée sur la planche : aucun jour",
                 0.0, 0.1),
            ],
            "06-dome-finition": [
                ("X", 140.0, 13.0, -5.0, "Cuvette finie : côté (X), près du bord arrière",
                 "becs intérieurs, à 5 mm sous le dessus", 70.0, 0.2),
                ("depth", 14.0, 80.0, None, "Fond de la cuvette fini (coin avant gauche)",
                 "jauge de profondeur à 4 mm des parois", 10.0, 0.1),
                ("height", cx + 20.0, cy, None, "Dôme à 20 mm de l'axe (vers +X)",
                 "jauge de profondeur posée sur la planche, tige sur le dôme à 20 mm du sommet", r - math.sqrt(r * r - 400.0),
                 0.15),
                ("diameter", None, None, None, "Diamètre du pied du dôme", "becs extérieurs au ras du fond (congé de "
                 "3 mm laissé par la boule : mesurer 2 mm au-dessus du fond = %.2f mm)" % (2 * math.sqrt(r * r - (cz + 8) ** 2)),
                 2 * foot, 0.3),
            ],
        },
    }


TEXT = ("CAM2027", 20.0, (95.0, 118.0))  # texte, hauteur de police, début de la ligne de base


def trial_vcarve(tmp):
    from cam2027.project import vectors

    lib = starter_library()
    proj = Project.create("07 V-carving", lib, machine())
    text, size, origin = TEXT
    obj = proj.doc.addObject("Part::Feature", "Vector")
    obj.Label = "Texte"
    obj.Shape = vectors.text_shape(text, size=size, origin=origin)
    proj.doc.recompute()
    proj.create_sheet_job(vectors=[obj], thickness=T, sheet_rect=(0.0, 0.0, L, W))
    face = proj.drawing_clone(obj, face=True)
    add_op(proj, "vcarve", "V-carving texte", "vbit", base=[(face, ["Face%d" % (i + 1) for i in range(len(face.Shape.Faces))])],
           FinalDepth=-3.0)
    bb = obj.Shape.BoundBox
    return proj, {
        "zone": "X %.0f..%.0f, Y %.0f..%.0f (arrière droite) : texte « %s »" % (bb.XMin, bb.XMax, bb.YMin, bb.YMax, text),
        "tools": ["vbit"],
        "files": [("07-vcarving-texte", None)],
        "notes": ["Le contrôle matière CAM2027 signale une petite entaille (0,10 mm à la résolution 0,5 mm). Analyse fine "
                  "(carte 0,05 mm, test exact dans les lettres) : le V-bit déborde d'au plus 0,08 mm hors du dessin, à la "
                  "pointe du A et du M (discrétisation du V-carving) ; invisible dans le bois, non bloquant."],
        "window": (bb.XMin - 3, bb.YMin - 3, bb.XMax + 3, bb.YMax + 3), "res": 0.05,
        "measures": [
            ("bbox_x", None, None, None, "Longueur totale du texte (bord gauche du C au bord droit du 7)",
             "becs extérieurs du pied à coulisse, à la surface", round(bb.XLength, 2), 0.2),
            ("bbox_y", None, None, None, "Hauteur du C", "becs extérieurs, à la surface", round(bb.YLength, 2), 0.2),
            ("maxdepth", None, None, None, "Profondeur la plus forte (traits les plus larges)",
             "jauge de profondeur (pointe fine) ou comparaison visuelle", None, 0.1),
        ],
    }


CONTOUR = (135.0, 72.0, 50.0, 30.0, 5.0)  # x, y, longueur, largeur, rayon des coins


def trial_contour(tmp):
    x, y, length, width, radius = CONTOUR
    proj, clone = new_project("08 Contour", rounded_box(x, y, length, width, T, radius), tmp, stock=BOARD_STOCK)
    op = add_op(proj, "profile", "Contour 50x30", "flat", base=[(clone, [])], FinalDepth=-T - 0.2)
    proj.add_dressup(op, "leads", params={"RadiusIn": 3.0, "RadiusOut": 3.0})
    proj.add_dressup(op, "tags", params={"Height": 4.0, "Width": 8.0}, count=4)
    return proj, {
        "zone": "X 135..185, Y 72..102 (milieu droit) : pièce 50 x 30 R5 découpée, 4 attaches",
        "tools": ["flat"],
        "files": [("08-contour-attaches", None)],
        "window": (125, 62, 195, 112), "res": 0.05,
        "measures": [
            ("part_X", 87.0, 160.0, None, "Pièce découpée : longueur", "becs extérieurs (après avoir coupé les attaches)",
             50.0, 0.15),
            ("part_Y", 160.0, 87.0, None, "Pièce découpée : largeur", "becs extérieurs", 30.0, 0.15),
            ("tags", None, None, None, "Épaisseur des attaches", "pied à coulisse sur le reste d'attache, depuis le "
             "dessous de la planche (attache de 4 mm au-dessus du fond de coupe, qui est 0,2 mm sous la planche)",
             3.8, 0.3),
        ],
    }


TWO = {"part": (20.0, 180.0), "hole": (100.0, 75.0, 10.0), "pocket_a": (40.0, 100.0, 30.0, 20.0, 3.0),
       "pocket_b": (130.0, 30.0, 30.0, 20.0, 3.0)}


def trial_two_sided(tmp):
    x0, x1 = TWO["part"]
    hx, hy, hr = TWO["hole"]
    ax, ay, al, aw, ad = TWO["pocket_a"]
    bx, by, bl, bw, bd = TWO["pocket_b"]
    shape = Part.makeBox(x1 - x0, W, T, V(x0, 0, -T))
    shape = shape.cut(Part.makeCylinder(hr, T + 2, V(hx, hy, -T - 1)))
    shape = shape.cut(Part.makeBox(al, aw, ad, V(ax, ay, -ad)))
    shape = shape.cut(Part.makeBox(bl, bw, bd, V(bx, by, -T)))
    proj, _clone = new_project("09 Recto-verso", shape, tmp, stock=BOARD_STOCK)
    twosided.enable(proj, "X")
    t, asm, preset = tool(proj.library, "flat")
    twosided.add_dowel_holes(proj, asm.id, preset.id)
    clone_a = twosided.jobs(proj)["A"].Model.Group[0]
    add_op(proj, "helix", "Alesage face A", "flat", base=[(clone_a, [cylinder_face(clone_a, hx, hy, hr)])],
           StartDepth=0.0, FinalDepth=-10.0)
    add_op(proj, "pocket", "Poche face A", "flat", base=[(clone_a, [planar_face(clone_a, -ad, al * aw)])], **POCKET)
    twosided.set_side(proj, "B")
    clone_b = proj.job.Model.Group[0]
    hyb = W - hy  # retournement autour de X par le centre du brut : Y -> 150 - Y
    add_op(proj, "helix", "Alesage face B", "flat", base=[(clone_b, [cylinder_face(clone_b, hx, hyb, hr)])],
           StartDepth=0.0, FinalDepth=-10.0)
    add_op(proj, "pocket", "Poche face B", "flat", base=[(clone_b, [planar_face(clone_b, -bd, bl * bw)])], **POCKET)
    twosided.set_side(proj, "A")
    dowels = twosided.config(proj)["registration"]["positions"]
    return proj, {
        "zone": "planche 2 entière : goujons Ø6 à X %.0f et X %.0f (Y %.0f), alésage Ø20 traversant fait moitié par "
                "face, une poche 30 x 20 x 3 sur chaque face" % (dowels[0][0], dowels[1][0], dowels[0][1]),
        "tools": ["flat"],
        "files": [("09-recto-verso-A", "A"), ("09-recto-verso-B", "B")],
        "dowels": dowels,
        "measures": [
            measure("Marche dans l'alésage Ø20 (décalage entre les deux moitiés)",
                    "doigt ou jauge : aucune marche sensible ; becs intérieurs en haut et en bas : même valeur", 0.0, 0.2),
            measure("Diamètre de l'alésage (face A puis face B)", "becs intérieurs", 20.0, 0.15),
            measure("Poche face A : distance au chant gauche (X)", "jauge de profondeur ou réglet depuis le chant gauche",
                    ax, 0.2),
            measure("Poche face B : distance au chant gauche (X), planche retournée",
                    "réglet depuis le même chant gauche (le retournement autour de X garde la gauche)", bx, 0.2),
            measure("Poche face B : distance au chant avant (Y), planche retournée",
                    "réglet depuis le chant qui est devant après retournement", W - by - bw, 0.2),
        ],
    }


TRIALS = [trial_probe, trial_pocket, trial_stepped, trial_holes, trial_dome, trial_vcarve, trial_contour,
          trial_two_sided]


# -- export et références --------------------------------------------------------------------------------


def path_commands(job):
    """Commandes ``(nom, paramètres)`` des opérations exportées du job, dans l'ordre du programme."""
    out = []
    for op in job.Operations.Group:
        if not exportmod._is_active(op) or getattr(op, "Path", None) is None:
            continue
        for c in op.Path.Commands:
            out.append((c.Name, dict(c.Parameters)))
    return out


def _evaluate(spec, zm, nc_text):
    """Valeur simulée d'une mesure ``(genre, a, b, niveau, ...)`` sur la carte ``zm``."""
    kind, a, b, level = spec[:4]
    if kind in ("X", "Y"):
        return run_length(zm, kind, a, b, level - 0.02 if level is not None else -0.02)[0]
    if kind == "pitch":
        c0 = run_length(zm, "X", a, b[0], -0.02)[1]
        c1 = run_length(zm, "X", a, b[1], -0.02)[1]
        return abs(c1 - c0)
    if kind == "depth":
        return -height(zm, a, b)
    if kind == "top":
        return height(zm, a, b)
    if kind == "height":
        return -height(zm, a, b)
    if kind in ("part_X", "part_Y"):
        np = sim._np()
        line_axis = "X" if kind == "part_X" else "Y"
        if line_axis == "X":
            j = int((a - zm.y0) / zm.res)
            line, coords, k = zm.top[:, j], zm.xs, int(round((b - zm.xs[0]) / zm.res))
        else:
            i = int((a - zm.x0) / zm.res)
            line, coords, k = zm.top[i, :], zm.ys, int(round((b - zm.ys[0]) / zm.res))
        solid = line > -0.02
        lo = hi = k
        while lo > 0 and solid[lo - 1]:
            lo -= 1
        while hi < len(line) - 1 and solid[hi + 1]:
            hi += 1
        del np
        return (hi - lo + 1) * zm.res
    if kind in ("bbox_x", "bbox_y", "maxdepth"):
        np = sim._np()
        cut = zm.top < -0.02
        if kind == "maxdepth":
            return -float(zm.top.min())
        idx = np.nonzero(cut.any(axis=1 if kind == "bbox_x" else 0))[0]
        return (idx[-1] - idx[0] + 1) * zm.res
    return None


def build_all(out_dir=OUTPUT, log=print):
    """Construit et exporte tous les essais dans ``out_dir`` (vidé d'abord). Retourne le manifeste."""
    i18n.set_language("en")  # fiches CAM2027 comme l'export de l'interface anglaise (stables d'une machine à l'autre)
    FreeCAD.ConfigSet("SuppressRecomputeRequiredDialog", "True")
    if os.path.isdir(out_dir):
        for name in os.listdir(out_dir):
            p = os.path.join(out_dir, name)
            if os.path.isdir(p):
                shutil.rmtree(p)
            elif name != ".gitattributes":
                os.remove(p)
    os.makedirs(out_dir, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="cam2027-trials-")
    manifest = {"board": [L, W, T], "probe": PROBE, "trials": []}
    try:
        for make in TRIALS:
            proj, info = make(tmp)
            try:
                manifest["trials"].extend(_export_trial(proj, info, out_dir, log))
            finally:
                proj.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    with open(os.path.join(out_dir, "trials.json"), "w", encoding="utf-8", newline="\n") as fp:
        json.dump(manifest, fp, indent=1, ensure_ascii=False)
    return manifest


def _clean_sheet(text):
    """Fiche CAM2027 sans la date ni les chemins locaux (fichiers régénérés à l'identique)."""
    out = []
    for line in text.splitlines():
        if line.startswith("- Date: ") or line.startswith("- Output: "):
            continue
        out.append(line)
    return "\n".join(out) + "\n"


def _clean_gcode(text):
    """Sans la ligne d'heure du postprocesseur (fichiers régénérés à l'identique)."""
    return "".join(l for l in text.splitlines(True) if not l.startswith("(Output Time:"))


def _export_trial(proj, info, out_dir, log):
    lib = proj.library
    results = []
    files = info["files"]
    measures = info["measures"]
    for fid, sel in files:
        folder = os.path.join(out_dir, fid)
        os.makedirs(folder, exist_ok=True)
        nc = os.path.join(folder, fid + ".nc")
        if sel in ("A", "B"):  # recto-verso : une face par fichier
            twosided.set_side(proj, sel)
            res = proj.export_gcode(nc)
            sheet_extra = twosided.setup_text(proj, sel)
            job = proj.job
        else:
            if sel is not None:  # un seul outil par fichier : les autres opérations désactivées pour l'export
                for op in proj.operations():
                    proj.set_operation_active(op, op.Name == sel.Name)
            res = proj.export_gcode(nc)
            sheet_extra = ""
            job = proj.job
        errors = [str(m) for level, m in res["issues"] if level == "error"]
        if errors:
            raise RuntimeError("%s : %s" % (fid, errors))
        with open(nc, encoding="utf-8") as fp:
            text = _clean_gcode(fp.read())
        with open(nc, "w", encoding="utf-8", newline="\n") as fp:
            fp.write(text)
        with open(res["sheet"], encoding="utf-8") as fp:
            sheet = _clean_sheet(fp.read())
        with open(res["sheet"], "w", encoding="utf-8", newline="\n") as fp:
            fp.write(sheet)
        ref = refmod.reference(path_commands(job))
        an = res["analysis"]
        if sel is not None and sel not in ("A", "B"):
            tools = [lib.tool(proj.registry[proj.base_operation(sel).Name]["tool_id"]).name]
        else:
            tools = [TOOLS[k] for k in info["tools"]]
        record = {"id": fid, "nc": os.path.relpath(nc, out_dir).replace("\\", "/"), "zone": info["zone"],
                  "tools": tools, "reference": ref,
                  "lines": an["lines"], "codes": an["codes"], "pauses": an.get("pauses", 0),
                  "bbox": {k: list(v) for k, v in an["bbox"].items()},
                  "issues": [[level, str(m)] for level, m in res["issues"]]}
        try:
            record["time"] = exportmod.timing_lines(proj)[1]["total"]
        except Exception:  # l'estimation ne bloque pas l'essai
            record["time"] = None
        specs = measures.get(fid, []) if isinstance(measures, dict) else measures
        out_measures = []
        zm = None
        if info.get("window") and specs and not isinstance(specs[0], dict):
            done = [r for r in results]
            texts = [(open(os.path.join(out_dir, r["nc"]), encoding="utf-8").read(), lib.tool(_tool_id(lib, r["tools"][0])))
                     for r in done] + [(text, lib.tool(_tool_id(lib, record["tools"][0])))]
            zm = carve(texts, info["window"], info["res"])
        for spec in specs:
            if isinstance(spec, dict):
                out_measures.append(spec)
                continue
            label, how, nominal, tol = spec[4:8]
            simulated = _evaluate(spec, zm, text) if zm is not None and spec[0] not in ("radius", "diameter", "tags") else None
            if nominal is None and simulated is not None:
                nominal = round(simulated, 2)
            out_measures.append(measure(label, how, nominal, tol,
                                        None if simulated is None else round(float(simulated), 3)))
        record["measures"] = out_measures
        record["dowels"] = info.get("dowels")
        record["notes"] = info.get("notes", [])
        record["check"] = _material(proj, sel)  # opérations du fichier et des fichiers précédents de l'essai
        with open(os.path.join(folder, "FICHE.md"), "w", encoding="utf-8", newline="\n") as fp:
            fp.write(fiche(record, sheet_extra))
        if sel is not None and sel not in ("A", "B"):
            for op in proj.operations():
                proj.set_operation_active(op, True)
        log("%s : %d lignes, %s, entaille %.3f mm" % (fid, an["lines"], " ".join(an["codes"]),
                                                     record["check"]["gouge_max"]))
        results.append(record)
    return results


def _tool_id(lib, name):
    return [t for t in lib.tools.values() if t.name == name][0].id


def _material(proj, sel):
    """Contrôle matière CAM2027 (toutes les opérations de l'essai jusqu'à ce fichier)."""
    if sel in ("A", "B"):
        rep = twosided.material_check(proj)
        return {"gouge_max": float(rep["gouge_max"]), "rapid_hits": int(rep["rapid_hits"])}
    rep = proj.material_check()
    return {"gouge_max": float(rep["gouge_max"]), "rapid_hits": int(rep["rapid_hits"]),
            "skipped": [s[0] for s in rep.get("skipped", [])]}


def _fmt(v):
    return "—" if v is None else ("%.2f" % v).replace(".", ",")


def fiche(rec, sheet_extra=""):
    """Fiche d'essai (français) : ce qui est usiné, montage, mesures attendues."""
    lines = ["# Essai %s" % rec["id"], ""]
    lines.append("- Fichier : `%s` (%d lignes ; codes : %s)" % (os.path.basename(rec["nc"]), rec["lines"],
                                                                ", ".join(rec["codes"])))
    lines.append("- Zone : %s" % rec["zone"])
    lines.append("- Outil : %s" % (", ".join(rec["tools"]) or "palpeur (broche arrêtée)"))
    if rec.get("time"):
        lines.append("- Temps estimé par CAM2027 : %d min %02d s" % divmod(int(round(rec["time"])), 60))
    bb = rec["bbox"]
    lines.append("- Enveloppe des mouvements : %s" % ", ".join(
        "%s %s..%s" % (a, _fmt(bb[a][0]), _fmt(bb[a][1])) for a in "XYZ" if a in bb))
    lines.append("- Contrôle matière CAM2027 : entaille %s mm, rapides dans la matière : %d" % (
        _fmt(rec["check"]["gouge_max"]), rec["check"]["rapid_hits"]))
    lines.append("- Origine : G54 au coin avant gauche du dessus de la planche (X0 Y0 Z0) ; Z0 refait au dessus de "
                 "la planche après chaque changement d'outil")
    lines.append("- Fiche de préparation CAM2027 : `%s-setup.md`" % rec["id"])
    for note in rec.get("notes") or []:
        lines.append("")
        lines.append("> %s" % note)
    lines.append("")
    lines.append("## Mesures")
    lines.append("")
    lines.append("| Cote | Comment | Attendu | Tolérance | Simulé CAM2027 |")
    lines.append("|---|---|---|---|---|")
    for m in rec["measures"]:
        lines.append("| %s | %s | %s | ± %s | %s |" % (m["label"], m["how"], _fmt(m["nominal"]), _fmt(m["tol"]),
                                                       _fmt(m["simulated"])))
    lines.append("")
    lines.append("Réussi si toutes les cotes sont dans la tolérance, aucune marque d'entrée ni de rapide dans la "
                 "matière, et le bruit de coupe reste régulier. Sinon : voir « En cas d'écart » dans "
                 "`docs/cam2027/ESSAIS-MACHINE.md`.")
    if sheet_extra:
        lines.append("")
        lines.append(sheet_extra)
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__" or not __package__:  # lancé par FreeCADCmd (pas importé par les tests)
    build_all(os.path.abspath(os.environ.get("CAM2027_TRIALS_OUT") or OUTPUT))
