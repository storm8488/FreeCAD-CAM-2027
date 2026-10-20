# SPDX-License-Identifier: LGPL-2.1-or-later
"""Imbrication de pièces 2D sur un panneau (placement sur rectangles englobants).

Chaque dessin est représenté par son rectangle englobant, agrandi de l'espacement demandé. Les
rectangles sont placés du plus grand au plus petit, là où leur dessus reste le plus bas puis le plus
à gauche (ligne d'horizon), avec rotation de 90° si elle est permise et meilleure. Ce n'est **pas**
une imbrication par forme réelle (les pièces ne s'emboîtent pas dans les creux les unes des autres) ;
une pièce qui ne tient pas est rapportée, jamais posée hors du panneau.
"""

import FreeCAD


def skyline_pack(items, width, height, spacing=0.0, rotate=True):
    """Place ``items`` = ``[(clé, l, h)]`` dans ``width × height`` (origine 0, 0).

    Retourne ``(placements, non_placés)`` ; ``placements[clé] = (x, y, tourné)`` coin bas-gauche de la
    pièce (sans l'espacement). Deux pièces restent à ``spacing`` l'une de l'autre au moins.
    """
    # l'espacement est ajouté à droite et en haut de chaque pièce ; la zone utile en reçoit autant
    W, H = width + spacing, height + spacing
    skyline = [[0.0, W, 0.0]]  # segments [x, largeur, hauteur]
    order = sorted(items, key=lambda it: (max(it[1], it[2]), it[1] * it[2]), reverse=True)
    placed, unplaced = {}, []
    for key, w, h in order:
        best = None
        for rot in ((False, True) if rotate and abs(w - h) > 1e-9 else (False,)):
            pw, ph = ((h, w) if rot else (w, h))
            pw, ph = pw + spacing, ph + spacing
            xs = sorted({s[0] for s in skyline} | {s[0] + s[1] - pw for s in skyline if s[0] + s[1] - pw >= -1e-9})
            for x in xs:  # calé sur le début ou sur la fin de chaque segment de la ligne d'horizon
                x = max(0.0, x)
                if x + pw > W + 1e-9:
                    continue
                y = max(s[2] for s in skyline if s[0] < x + pw - 1e-9 and s[0] + s[1] > x + 1e-9)
                if y + ph > H + 1e-9:
                    continue
                cand = (y + ph, x, y, rot, pw, ph)  # dessus de la pièce le plus bas, puis le plus à gauche
                if best is None or cand[:2] < best[:2]:
                    best = cand
        if best is None:
            unplaced.append(key)
            continue
        _top, x, y, rot, pw, ph = best
        placed[key] = (x, y, rot)
        _raise_skyline(skyline, x, pw, y + ph)
    return placed, unplaced


def _raise_skyline(skyline, x, w, top):
    new = []
    for sx, sw, sh in skyline:
        ex = sx + sw
        if ex <= x + 1e-9 or sx >= x + w - 1e-9:
            new.append([sx, sw, sh])
            continue
        if sx < x:
            new.append([sx, x - sx, sh])
        if ex > x + w:
            new.append([x + w, ex - (x + w), sh])
    new.append([x, w, top])
    new.sort(key=lambda s: s[0])
    merged = []
    for s in new:
        if merged and abs(merged[-1][2] - s[2]) < 1e-9 and abs(merged[-1][0] + merged[-1][1] - s[0]) < 1e-9:
            merged[-1][1] += s[1]
        else:
            merged.append(s)
    skyline[:] = merged


def move_to(obj, x, y, rotated):
    """Tourne l'objet de 90° autour de Z si demandé puis pose le coin bas-gauche de son englobant en (x, y)."""
    if rotated:
        obj.Placement = FreeCAD.Placement(FreeCAD.Vector(), FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), 90)) \
            .multiply(obj.Placement)
    bb = obj.Shape.BoundBox
    obj.Placement = FreeCAD.Placement(FreeCAD.Vector(x - bb.XMin, y - bb.YMin, 0), FreeCAD.Rotation()) \
        .multiply(obj.Placement)


def outline_area(obj):
    """Surface des contours fermés du dessin (pour le taux d'utilisation)."""
    from . import sheet as sheetmod
    import Part

    wires = sheetmod.closed_wires(obj)
    if not wires:
        return 0.0
    try:
        return Part.makeFace(wires, "Part::FaceMakerBullseye").Area
    except Exception:
        return 0.0
