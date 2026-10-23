# SPDX-License-Identifier: LGPL-2.1-or-later
"""Icônes des commandes CAM2027 (barres d'outils et menus), thèmes sombre et clair.

    python scripts/make-command-icons.py

Écrit ``src/Mod/CAM2027/Resources/icons/atelier/{dark,light}/cmd-*.svg``. Style « Atelier » : 24 × 24, traits de
1,75 arrondis ; deux tons : le trait principal prend la couleur du texte du thème, l'élément qui dit l'action (la
fraise, la flèche, le résultat) la couleur d'accent (`focus` des jetons : #8CB7FF sombre, #215ED6 clair).
Une icône par commande : avant, plusieurs commandes partageaient « poche », « perçage » ou « contour ».
"""

import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "src", "Mod", "CAM2027", "Resources", "icons", "atelier")
THEMES = {
    "dark": {"fg": "#F1F5FA", "ac": "#8CB7FF"},
    "light": {"fg": "#182433", "ac": "#215ED6"},
}
DASH = 'stroke-dasharray="2.2 2.2"'


def doc(x0, x1):
    """Feuille à coin plié de ``x0`` à ``x1`` (Y 3 à 21)."""
    return "M%g 3h%gl4 4v14H%gz M%g 3v4h4" % (x0, x1 - x0 - 4, x0, x1 - 4)


def endmill(x, y=2, w=6, shank=7, flute=7):
    """Fraise vue de côté : queue (trait principal) et partie taillée (accent)."""
    body = '<rect x="%g" y="%g" width="%g" height="%g" rx="1"/>' % (x, y, w, shank)
    cut = "M%g %gv%gl%g 3 %g-3v-%g" % (x + 0.5, y + shank, flute, w / 2 - 0.5, w / 2 - 0.5, flute)
    return body, cut


def hexagon(cx, cy, r):
    import math

    pts = [(cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a))) for a in range(-90, 270, 60)]
    return "M" + " L".join("%.2f %.2f" % p for p in pts) + " Z", pts


def ring(cx, cy, r, n, dot):
    import math

    return "".join('<circle cx="%.2f" cy="%.2f" r="%g" fill="{ac}" stroke="none"/>'
                   % (cx + r * math.cos(2 * math.pi * k / n - math.pi / 2), cy + r * math.sin(2 * math.pi * k / n - math.pi / 2), dot)
                   for k in range(n))


_em_shank, _em_cut = endmill(6)
_hex, _hex_pts = hexagon(12, 12, 8.5)

#: nom -> (éléments au trait principal, éléments en accent) ; « P:… » = chemin, sinon élément SVG brut
ICONS = {
    # ---- projet
    "cmd-new-project": (["P:" + doc(5, 19)], ["P:M12 11v7 M8.5 14.5h7"]),
    "cmd-import-model": (["P:M15 7l7 4v8l-7 4-7-4v-8z M8 11l7 4 7-4 M15 15v8"], ["P:M2.5 3.5l6 6 M8.5 5v4.5H4"]),
    "cmd-import-relief": (["P:M3 5h18v14H3z", '<circle cx="16.5" cy="9" r="1.6"/>'], ["P:M3 17l5-6 4 4 3-3 6 5"]),
    "cmd-tool-library": (['<rect x="3" y="2.5" width="4.5" height="7" rx="1"/>', '<rect x="9.75" y="2.5" width="4.5" height="5" rx="1"/>',
                          '<rect x="16.5" y="2.5" width="4.5" height="6" rx="1"/>'],
                         ["P:M3.5 9.5v7.5l1.75 2.5 1.75-2.5v-7.5 M10.25 7.5v9.5l1.75 2.5 1.75-2.5v-9.5 M17 8.5v8.5l1.75 2.5 1.75-2.5v-8.5"]),
    "cmd-stock": (["P:M3 11h13v10H3z M3 11l4-4h13l-4 4 M16 21l4-4V7"], ["P:M8.5 3h6 M11.5 3v6"]),
    "cmd-machine": (["P:M3 21h18 M5 21V6 M19 21V6 M4 6h16"], ["P:M12 6v6 M10 12h4l-2 3.5z M8 18h8"]),
    "cmd-two-sided": (["P:M3 5h12v5H3z M9 14h12v5H9z"], ["P:M18 5.5c2.2 0 3.5 1.6 3.5 3.8 M20 7.6l1.5 1.7 1.5-1.7 M6 18.5c-2.2 0-3.5-1.6-3.5-3.8 M4 16.4l-1.5-1.7-1.5 1.7"]),
    "cmd-nest": (["P:M2 4h20v16H2z"], ["P:M5 7h5v3H8v7H5z M17 16.5h3v-4.5h-3z", '<circle cx="14.5" cy="9.5" r="2.5"/>']),
    "cmd-bulk-edit": (["P:M3 6h8 M3 12h8 M3 18h8"], ["P:M16 4v16 M20.5 4v16", '<circle cx="16" cy="9" r="1.9" fill="{ac}" stroke="none"/>',
                                                     '<circle cx="20.5" cy="15" r="1.9" fill="{ac}" stroke="none"/>']),
    # ---- usiner
    "cmd-add-operation": ([_em_shank], ["P:" + _em_cut, "P:M18 13v8 M14 17h8"]),
    "cmd-compute": (["P:M20 12a8 8 0 1 1-2.35-5.65 M20.5 3.5v4h-4"], ["P:M8 10h8 M8 14h8 M16 10a2 2 0 0 1 0 4"]),
    "cmd-flat-depth": (["P:M2 7h5 M17 7h5 M7 7l3 9 M17 7l-3 9"], ["P:M10 16h4", "P:M12 4v5.5 M10.4 8 12 9.6 13.6 8"]),
    "cmd-inlay": (["P:M3 21v-8h5l2 4h4l2-4h5v8z"], ["P:M7.5 3h9l-2.5 6h-4z", "P:M12 9.5v2.5"]),
    "cmd-wrap-engrave": (['<ellipse cx="12" cy="5" rx="7" ry="2.5"/>', "P:M5 5v14 M19 5v14 M5 19a7 2.5 0 0 0 14 0"],
                         ["P:M8 10.5c1.5 1 6.5 1 8 0 M8 14.5c1.5 1 6.5 1 8 0"]),
    "cmd-rotary": (['<ellipse cx="7" cy="13" rx="2.5" ry="6"/>', "P:M7 7h11 M7 19h11 M18 7a2.5 6 0 0 1 0 12"],
                   ["P:M9 3.2c2.8-1.4 6.2-1.4 9 0 M15.8 1.6l2.2 1.6-1.6 2.2"]),
    "cmd-project-on-part": (["P:M3 21h18 M4 21c0-7 3.6-11 8-11s8 4 8 11"], ["P:M8 2v6.5 M6.4 7 8 8.6 9.6 7 M16 2v6.5 M14.4 7 16 8.6 17.6 7"]),
    "cmd-holes": (['<circle cx="6.5" cy="6.5" r="3"/>', '<circle cx="17.5" cy="6.5" r="3"/>', '<circle cx="6.5" cy="17.5" r="3"/>'],
                  ['<circle cx="17.5" cy="17.5" r="3"/>', "P:M17.5 12.5v10 M12.5 17.5h10"]),
    "cmd-probe": (["P:M3 21V9 M3 21h13"], ["P:M15 2v8", '<circle cx="15" cy="12" r="2"/>', "P:M11 12H6.5 M8 10.5 6.5 12 8 13.5"]),
    # ---- simuler
    "cmd-simulate": (["P:M3 15h18v6H3z"], ["P:M9.5 3v9l7-4.5z"]),
    "cmd-material-check": (["P:M3 10h5v4h6v-4h7v11H3z"], ["P:M13 5.5l2.2 2.2 4.8-4.8"]),
    # ---- exporter
    "cmd-export": (["P:" + doc(3, 15), "P:M6 12h5 M6 15h4 M6 18h5"], ["P:M13 15h8.5 M18.5 12l3 3-3 3"]),
    "cmd-setup-sheet": (["P:" + doc(5, 19), "P:M12.5 11h3 M12.5 16h3"], ["P:M8 11l1.2 1.2 2-2 M8 16l1.2 1.2 2-2"]),
    "cmd-save-template": (["P:M8 3h12v14H8z M4 7v14h12"], ["P:M14 6.5v6 M11.5 10l2.5 2.5 2.5-2.5"]),
    "cmd-apply-template": (["P:M8 3h12v14H8z M4 7v14h12"], ["P:M11 10l2.2 2.2 4.3-4.3"]),
    # ---- dessin
    "cmd-draw-text": (["P:M5 5h12 M11 5v14 M8 19h6"], ["P:M19 11v10"]),
    "cmd-draw-rectangle": (['<rect x="2.5" y="5" width="2.5" height="2.5" fill="{fg}" stroke="none"/>',
                            '<rect x="19" y="16.5" width="2.5" height="2.5" fill="{fg}" stroke="none"/>'],
                           ["P:M3.75 6.25h16.5v11.5H3.75z"]),
    "cmd-draw-circle": (["P:M12 10.5v3 M10.5 12h3"], ['<circle cx="12" cy="12" r="8.5"/>', "P:M12 12l6-6"]),
    "cmd-draw-polygon": (['<circle cx="%.2f" cy="%.2f" r="1.4" fill="{fg}" stroke="none"/>' % p for p in _hex_pts[::2]], ["P:" + _hex]),
    "cmd-edit-vector": (["P:M3 19c3-9 8-13 15-13"], ["P:M14 21l7-7-2.5-2.5-7 7V21z M16.5 13.5l2.5 2.5"]),
    "cmd-edit-nodes": (["P:M4 18C7 6 15 20 20 6 M12 13l4-6"], ['<rect x="2.6" y="16.6" width="2.8" height="2.8" fill="{ac}" stroke="none"/>',
                                                             '<rect x="10.6" y="11.6" width="2.8" height="2.8" fill="{ac}" stroke="none"/>',
                                                             '<rect x="18.6" y="4.6" width="2.8" height="2.8" fill="{ac}" stroke="none"/>',
                                                             '<circle cx="16" cy="7" r="1.4"/>']),
    "cmd-offset-vector": (['<rect x="8" y="8" width="8" height="8" rx="1"/>'], ['<rect x="3" y="3" width="18" height="18" rx="4.5"/>']),
    "cmd-combine-vectors": (['<circle cx="9" cy="12" r="6"/>'], ['<circle cx="15" cy="12" r="6"/>']),
    "cmd-circular-copies": (['<circle cx="12" cy="12" r="1.6"/>'], [ring(12, 12, 8, 6, 1.9)]),
    "cmd-trace-bitmap": (["P:M3 21v-4h4v-4h4V9h4V5h4V3"], ["P:M5 21C12 21 19 14 21 3"]),
    "cmd-photo-vcarve": (["P:M3 4h18v16H3z"], ["P:M6 9c2-1.6 4 1.6 6 0s4 1.6 6 0 M6 12.5c2-1.6 4 1.6 6 0s4 1.6 6 0 M6 16c2-1.6 4 1.6 6 0s4 1.6 6 0"]),
    "cmd-moulding": (["P:M3 21h18"], ["P:M4 21V5h3.5c0 7.5 4.5 12 12.5 12v4"]),
    "cmd-fluting": (["P:M3 3h18v18H3z"], ['<path d="M8 6.5v11 M12 6.5v11 M16 6.5v11" stroke-width="2.6"/>']),
    "cmd-texture": (["P:M3 4h18v16H3z"], ["P:M6 8l3 1 M11 7.5l3 1 M16 8l2.5 1 M7.5 12.5l3 1 M13 12l3 1 M6 16.5l3 1 M11 16l3 1 M16 16.5l2.5 1"]),
    "cmd-prism": (["P:M3 4h18v16H3z"], ["P:M3 4l6 8-6 8 M21 4l-6 8 6 8 M9 12h6"]),
    # ---- affichage / aide
    "cmd-theme": (['<circle cx="12" cy="12" r="8.5"/>'], ['<path d="M12 3.5a8.5 8.5 0 0 1 0 17z" fill="{ac}" stroke="none"/>']),
    "cmd-advanced": (["P:M4 7h16 M4 12h16 M4 17h16"], ['<circle cx="9" cy="7" r="2.1" fill="{ac}" stroke="none"/>',
                                                    '<circle cx="15.5" cy="12" r="2.1" fill="{ac}" stroke="none"/>',
                                                    '<circle cx="7" cy="17" r="2.1" fill="{ac}" stroke="none"/>']),
    "cmd-reset-layout": (["P:M3 4h18v16H3z M9 4v16 M9 10h12"], ["P:M19 16.5a3 3 0 1 1-1.2-2.4 M18.5 12.6v1.9h-1.9"]),
    "cmd-about": (['<circle cx="12" cy="12" r="9"/>'], ["P:M12 11v6", '<circle cx="12" cy="7.6" r="1.2" fill="{ac}" stroke="none"/>']),
    "cmd-report-bug": (["P:M9.5 7.5a2.5 2.5 0 0 1 5 0 M8 9.5h8v4.5a4 4 0 0 1-8 0z M12 9.5V18"],
                       ["P:M4 12.5h4 M16 12.5h4 M5 7l3 2.5 M19 7l-3 2.5 M5 19l3-2.5 M19 19l-3-2.5"]),
    "cmd-support": (["P:M4 9h12v6a5 5 0 0 1-5 5H9a5 5 0 0 1-5-5z M16 11h1.5a2.5 2.5 0 0 1 0 5H16"],
                    ["P:M8 3.5c-.8 1 .8 2 0 3 M12 3.5c-.8 1 .8 2 0 3"]),
    "cmd-suggest-feature": (["P:M9.5 18h5 M10.5 21h3"],
                            ["P:M12 3a6 6 0 0 0-3.6 10.8c.7.5 1.1 1.3 1.1 2.1V16h5v-.1c0-.8.4-1.6 1.1-2.1A6 6 0 0 0 12 3z"]),
}
# barres de FreeCAD gardées dans le logiciel (Fichier, Édition, Vue) : même style que les commandes CAM2027
_corners = "P:M3 8V3h5 M16 3h5v5 M21 16v5h-5 M8 21H3v-5"
_cube = "P:M12 3l8 4.5v9L12 21l-8-4.5v-9z M4 7.5l8 4.5 8-4.5 M12 12v9"
ICONS.update({
    "std-open": (["P:M3 6h6l2 2h10v12H3z"], ["P:M12 18v-6 M9.5 14.5 12 12l2.5 2.5"]),
    "std-save": (["P:M4 4h13l3 3v13H4z M8 4v5h7V4"], ["P:M8 20v-6h8v6"]),
    "std-undo": (["P:M4.5 10h10a5 5 0 0 1 0 10h-3"], ["P:M8.5 6 4.5 10l4 4"]),
    "std-redo": (["P:M19.5 10h-10a5 5 0 0 0 0 10h3"], ["P:M15.5 6l4 4-4 4"]),
    "std-refresh": (["P:M20 12a8 8 0 1 1-2.35-5.65 M20.5 3.5v4h-4"], ["P:M12 8.5V12l2.5 1.5"]),
    "std-fit-all": ([_corners], ["P:M8 8h8v8H8z"]),
    "std-fit-selection": ([_corners], ["P:M8.5 8.5l7.5 3-3.2 1.3-1.3 3.2z"]),
    "std-views": ([_cube], ["P:M4 7.5 12 3l8 4.5-8 4.5z"]),
    "std-align": (["P:M3 19l5-4h13l-5 4z"], ["P:M13 3v8 M10.5 8.5 13 11l2.5-2.5"]),
})
# icônes à trait pointillé (zone interdite, copies du motif, axe du miroir)
ICONS["cmd-keep-out"] = (['<path d="M3 4h18v16H3z" %s/>' % DASH], ['<circle cx="12" cy="12" r="5.5"/>', "P:M8.2 15.8l7.6-7.6"])
ICONS["cmd-pattern"] = (["P:M3 3h7v7H3z"], ['<path d="M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z" %s/>' % DASH])
ICONS["cmd-mirror-vector"] = (["P:M10 5v14L3 19z", '<path d="M12 2.5v19" %s/>' % DASH], ["P:M14 5v14h7z"])


def element(item, colour_key):
    return ('<path d="%s"/>' % item[2:]) if item.startswith("P:") else item


def svg(name, colours):
    main, accent = ICONS[name]
    body = ('<g fill="none" stroke="{fg}" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">%s</g>'
            '<g fill="none" stroke="{ac}" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">%s</g>'
            % ("".join(element(i, "fg") for i in main), "".join(element(i, "ac") for i in accent)))
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">%s</svg>\n'
            % body.replace("{fg}", colours["fg"]).replace("{ac}", colours["ac"]))


def main():
    for theme, colours in THEMES.items():
        folder = os.path.join(OUT, theme)
        os.makedirs(folder, exist_ok=True)
        for name in ICONS:
            with open(os.path.join(folder, name + ".svg"), "w", encoding="utf-8", newline="\n") as fp:
                fp.write(svg(name, colours))
    print("%d icônes × %d thèmes -> %s" % (len(ICONS), len(THEMES), os.path.normpath(OUT)))


if __name__ == "__main__":
    main()
