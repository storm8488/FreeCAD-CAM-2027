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
    """Durée (s) d'une suite de mouvements ``(p0, p1, avance mm/s)`` enchaînés (arrêt au début et à la fin)."""
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


def path_moves(commands, rapid_mm_min, start=None):
    """``(p0, p1, avance mm/s)`` d'une liste de commandes Path (F en mm/s, unité interne de FreeCAD ; arcs
    découpés), et la position finale."""
    from . import sim

    out, feed = [], None
    segments, pos = sim.path_segments(commands, start, with_index=True)
    feeds = {}
    current = None
    for i, c in enumerate(commands):
        if "F" in c.Parameters:
            current = float(c.Parameters["F"])
        feeds[i] = current
    for rapid, p0, p1, index in segments:
        feed = rapid_mm_min / 60.0 if rapid else (feeds.get(index) or 0.0)
        out.append((tuple(p0), tuple(p1), feed if feed > 0 else rapid_mm_min / 60.0))
    return out, pos


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
        moves, pos_end = path_moves(op.Path.Commands, rapid, pos)
        t = plan_time(moves, accel)
        rows.append((op.Label, t))
        total += t
        naive += sum(math.dist(p0, p1) / f for p0, p1, f in moves if f > 0)
        pos = pos_end
    return {"operations": rows, "total": total, "assumed": assumed, "without_accel": naive,
            "acceleration": accel, "rapid": rapid}


def format_duration(seconds):
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return "%d h %02d min %02d s" % (h, m, s) if h else "%d min %02d s" % (m, s)
