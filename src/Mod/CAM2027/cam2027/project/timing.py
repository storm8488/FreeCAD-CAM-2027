# SPDX-License-Identifier: LGPL-2.1-or-later
"""Estimation du temps d'usinage avec l'accélération de la machine (Aspire 12.5 « Estimating Machining
Times », Fusion « Machine time » avec accélération).

Chaque mouvement est un segment (arcs découpés) parcouru avec un profil de vitesse trapézoïdal :
accélération ``a`` jusqu'à l'avance programmée, palier, décélération. Aux jonctions, la vitesse est limitée
comme dans le planificateur de GRBL (« junction deviation » : ``v² = a·δ·sin(θ/2) / (1 − sin(θ/2))``,
``θ`` = angle entre les deux directions, ``δ`` = 0,01 mm par défaut) ; un passage avant / arrière garantit que
chaque segment peut accélérer et freiner sur sa longueur (planificateur à anticipation complète, plus
optimiste que les 16 blocs de GRBL sur les très petits segments). Les rapides (G0) vont à l'avance maximale
du profil machine ; temps de changement d'outil et de mise en route de la broche non comptés.
"""

import math

#: valeurs supposées quand le profil machine ne les donne pas (signalées)
DEFAULT_ACCELERATION = 500.0  # mm/s²
DEFAULT_RAPID = 3000.0  # mm/min
DEFAULT_JUNCTION_DEVIATION = 0.01  # mm (GRBL $11)


def segment_time(length, v_in, v_out, v_max, accel):
    """Durée (s) d'un segment de ``length`` mm entré à ``v_in``, sorti à ``v_out`` (mm/s), palier à au plus
    ``v_max``, accélération ``accel`` (mm/s²). Les vitesses d'entrée / sortie doivent être atteignables."""
    if length <= 0:
        return 0.0
    if accel <= 0:
        return length / v_max
    d_up = max(0.0, (v_max * v_max - v_in * v_in) / (2 * accel))
    d_down = max(0.0, (v_max * v_max - v_out * v_out) / (2 * accel))
    if d_up + d_down <= length:  # trapèze
        return (v_max - v_in) / accel + (v_max - v_out) / accel + (length - d_up - d_down) / v_max
    # triangle : vitesse de pointe atteinte au croisement des deux rampes
    v_peak = math.sqrt(max(0.0, (2 * accel * length + v_in * v_in + v_out * v_out) / 2.0))
    v_peak = max(v_peak, v_in, v_out)
    return max(0.0, (v_peak - v_in) / accel) + max(0.0, (v_peak - v_out) / accel)


def _junction_speed(u, w, accel, deviation):
    """Vitesse maximale (mm/s) au passage de la direction ``u`` à ``w`` (vecteurs unitaires)."""
    cos_theta = -(u[0] * w[0] + u[1] * w[1] + u[2] * w[2])  # angle entre -u et w (GRBL)
    if cos_theta > 0.999999:  # demi-tour
        return 0.0
    if cos_theta < -0.999999:  # tout droit
        return float("inf")
    sin_half = math.sqrt(0.5 * (1.0 - cos_theta))
    return math.sqrt(accel * deviation * sin_half / (1.0 - sin_half))


def plan_time(moves, accel=DEFAULT_ACCELERATION, deviation=DEFAULT_JUNCTION_DEVIATION):
    """Durée (s) d'une suite de mouvements ``(p0, p1, avance mm/s)`` enchaînés (arrêt au début et à la fin).

    Passages arrière et avant en carrés de vitesse ``w = v²`` : ``w[k] = min(w[k], w[k+1] + 2·a·L[k])`` se
    résout d'un coup en minimum cumulé (``w[k] = min_j≥k(cap[j] + 2a·S[j]) − 2a·S[k]``, ``S`` longueur
    cumulée) : même résultat que la boucle, vectorisé (numpy)."""
    import numpy as np

    if not moves:
        return 0.0
    P0 = np.array([m[0] for m in moves], dtype=float)
    P1 = np.array([m[1] for m in moves], dtype=float)
    F = np.array([m[2] for m in moves], dtype=float)
    D = P1 - P0
    L = np.sqrt((D * D).sum(axis=1))
    keep = (L >= 1e-9) & (F > 0)
    L, F, D = L[keep], F[keep], D[keep]
    n = len(L)
    if not n:
        return 0.0
    U = D / L[:, None]
    # vitesse maximale aux jonctions (GRBL), arrêt au départ et à l'arrivée
    cap = np.zeros(n + 1)
    if n > 1:
        cos_theta = -(U[:-1] * U[1:]).sum(axis=1)
        sin_half = np.sqrt(np.clip(0.5 * (1.0 - cos_theta), 0.0, 1.0))
        with np.errstate(divide="ignore", invalid="ignore"):
            vj = np.sqrt(accel * deviation * sin_half / (1.0 - sin_half))
        vj = np.where(cos_theta > 0.999999, 0.0, np.where(cos_theta < -0.999999, np.inf, vj))
        cap[1:n] = np.minimum(np.minimum(F[:-1], F[1:]), vj)
    w = cap * cap
    S = np.concatenate(([0.0], np.cumsum(L)))
    two_a = 2.0 * accel
    # arrière : freinage possible jusqu'à la vitesse suivante
    w = np.minimum.accumulate((w + two_a * S)[::-1])[::-1] - two_a * S
    # avant : accélération possible depuis la vitesse précédente
    w = np.minimum.accumulate(w - two_a * S) + two_a * S
    v = np.sqrt(np.clip(w, 0.0, None))
    v_in, v_out = v[:-1], v[1:]
    # trapèze ou triangle par segment
    d_up = np.clip((F * F - v_in * v_in) / two_a, 0.0, None)
    d_down = np.clip((F * F - v_out * v_out) / two_a, 0.0, None)
    trap = d_up + d_down <= L
    t_trap = (F - v_in) / accel + (F - v_out) / accel + (L - d_up - d_down) / F
    v_peak = np.maximum(np.sqrt(np.clip((two_a * L + v_in * v_in + v_out * v_out) / 2.0, 0.0, None)), np.maximum(v_in, v_out))
    t_tri = np.clip((v_peak - v_in) / accel, 0.0, None) + np.clip((v_peak - v_out) / accel, 0.0, None)
    return float(np.where(trap, t_trap, t_tri).sum())


def naive_time(moves):
    """Durée sans accélération : somme des longueurs / avances (comparaison sur la fiche)."""
    import numpy as np

    if not moves:
        return 0.0
    P0 = np.array([m[0] for m in moves], dtype=float)
    P1 = np.array([m[1] for m in moves], dtype=float)
    F = np.array([m[2] for m in moves], dtype=float)
    L = np.sqrt(((P1 - P0) ** 2).sum(axis=1))
    return float((L[F > 0] / F[F > 0]).sum())


def plan_time_loop(moves, accel=DEFAULT_ACCELERATION, deviation=DEFAULT_JUNCTION_DEVIATION):
    """Même calcul que :func:`plan_time`, en boucle Python (référence des tests)."""
    segs = []
    for p0, p1, feed in moves:
        d = [p1[k] - p0[k] for k in range(3)]
        length = math.sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2])
        if length < 1e-9 or feed <= 0:
            continue
        segs.append((length, [c / length for c in d], float(feed)))
    n = len(segs)
    if not n:
        return 0.0
    # vitesse maximale aux jonctions (entrée de chaque segment), arrêt au départ et à l'arrivée
    v_entry = [0.0] * (n + 1)
    for k in range(1, n):
        v_entry[k] = min(segs[k - 1][2], segs[k][2], _junction_speed(segs[k - 1][1], segs[k][1], accel, deviation))
    # passage arrière : freinage possible jusqu'à la vitesse suivante
    for k in range(n - 1, -1, -1):
        v_entry[k] = min(v_entry[k], math.sqrt(v_entry[k + 1] ** 2 + 2 * accel * segs[k][0]))
    # passage avant : accélération possible depuis la vitesse précédente
    for k in range(1, n + 1):
        v_entry[k] = min(v_entry[k], math.sqrt(v_entry[k - 1] ** 2 + 2 * accel * segs[k - 1][0]))
    return sum(segment_time(segs[k][0], v_entry[k], v_entry[k + 1], segs[k][2], accel) for k in range(n))


_MOVES = {"G0": True, "G00": True, "G1": False, "G01": False}
_ARCS = ("G2", "G02", "G3", "G03")


def path_moves(commands, rapid_mm_min, start=None, timed=None):
    """``(p0, p1, avance mm/s)`` d'une liste de commandes Path (F en mm/s, unité interne de FreeCAD, modale ;
    arcs découpés par ``sim.path_segments``), et la position finale. Un seul passage sur les commandes (lire
    ``Parameters`` coûte : l'estimation est faite à chaque export).

    Mouvements en temps inverse (G93, axe A continu) : F est l'inverse de la durée (1 / min, donc 1 / s dans
    l'unité interne) ; leur durée est ajoutée à la liste ``timed`` (secondes) au lieu d'un segment."""
    from . import sim

    rapid = rapid_mm_min / 60.0
    out, feed = [], 0.0
    inverse = False
    pos = tuple(start) if start is not None else None
    for c in commands:
        name = c.Name.upper()
        if name in ("G93", "G94"):
            inverse = name == "G93"
            continue
        rapid_move = _MOVES.get(name)
        if rapid_move is None and name not in _ARCS:
            continue
        p = c.Parameters
        if "F" in p:
            feed = float(p["F"])
        if pos is None:
            pos = (p.get("X", 0.0), p.get("Y", 0.0), p.get("Z", 0.0))
            continue
        if inverse and not rapid_move:
            if timed is not None and "F" in p and float(p["F"]) > 0:
                timed.append(1.0 / float(p["F"]))
            pos = (p.get("X", pos[0]), p.get("Y", pos[1]), p.get("Z", pos[2]))
            continue
        speed = rapid if rapid_move else (feed if feed > 0 else rapid)
        if rapid_move is None:  # arc : découpé comme dans le contrôle matière
            segments, end = sim.path_segments([c], pos)
            out.extend((tuple(a), tuple(b), speed) for _r, a, b in segments)
            pos = tuple(end)
            continue
        end = (p.get("X", pos[0]), p.get("Y", pos[1]), p.get("Z", pos[2]))
        out.append((pos, end, speed))
        pos = end
    return out, (list(pos) if pos is not None else None)


def machine_settings(machine):
    """``(accélération, avance rapide mm/min, suppositions)`` du profil machine (valeurs supposées listées)."""
    assumed = []
    accel = getattr(machine, "acceleration_mm_s2", None)
    if not accel:
        accel = DEFAULT_ACCELERATION
        assumed.append("acceleration %g mm/s²" % accel)
    rapid = getattr(machine, "max_feed_xy_mm_min", None)
    if not rapid:
        rapid = DEFAULT_RAPID
        assumed.append("rapid feed %g mm/min" % rapid)
    return float(accel), float(rapid), assumed


def estimate(project):
    """Temps par opération active et total : ``{"operations": [(libellé, s)], "total": s, "assumed": [...],
    "without_accel": s}`` (le dernier : distance / avance, pour comparaison)."""
    from . import dressups as dressupmod

    accel, rapid, assumed = machine_settings(project.machine)
    rows, total, naive = [], 0.0, 0.0
    pos = None
    for op in project.operations():
        base = dressupmod.base_operation(op)
        if getattr(base, "Active", True) is False:
            continue
        timed = []
        moves, pos_end = path_moves(op.Path.Commands, rapid, pos, timed)
        t = plan_time(moves, accel) + sum(timed)
        rows.append((op.Label, t))
        total += t
        naive += naive_time(moves) + sum(timed)
        pos = pos_end
    return {"operations": rows, "total": total, "assumed": assumed, "without_accel": naive,
            "acceleration": accel, "rapid": rapid}


def format_duration(seconds):
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return "%d h %02d min %02d s" % (h, m, s) if h else "%d min %02d s" % (m, s)
