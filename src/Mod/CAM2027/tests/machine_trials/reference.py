# SPDX-License-Identifier: LGPL-2.1-or-later
"""Positions attendues d'un parcours CAM2027 et comparaison avec le passage dans le simulateur GRBL.

La référence est calculée sur les commandes ``Path`` des opérations (avant postprocesseur), pas sur le
G-code exporté : elle vérifie donc aussi le postprocesseur (cycles de perçage traduits, arcs, palpage).
Mêmes règles que ``grbl_check.js`` et ``export.analyze_gcode`` : position de travail connue axe par axe
(écrit par un mouvement absolu ; perdu après G38.x, G10, G92, G28, G30, G53), mouvements relatifs (G91) hors
de la liste des positions, enveloppe des axes connus avec les extrêmes exacts des arcs (plan XY).

Sans FreeCAD : utilisable par les tests sur des commandes ``(nom, paramètres)``.
"""

import math

NOT_POSITION = ("G10", "G28", "G30", "G53", "G92", "G38.2", "G38.3", "G38.4", "G38.5")
CYCLES = ("G81", "G82", "G83", "G73")
TOLERANCE = 0.01  # mm, demandé pour la comparaison avec le simulateur
DEDUP = 1e-3  # deux positions successives plus proches (par axe) : un seul point (le simulateur ignore un mouvement
#: de moins de 0,001 mm ; les points proches restants sont appariés par ``compare``)


def norm(name):
    """« G01 » -> « G1 », « G38.20 » -> « G38.2 » ; commentaires et vides -> None."""
    name = (name or "").strip().upper()
    if not name or name.startswith("(") or name[0] not in "GM":
        return None
    try:
        v = float(name[1:])
    except ValueError:
        return None
    return name[0] + (str(int(v)) if v.is_integer() else ("%.1f" % v))


class Reference(object):
    def __init__(self):
        self.pos = {"X": None, "Y": None, "Z": None}
        self.relative = False
        self.retract = "G98"
        self.points = []
        self.env = {}
        self.cycles = 0

    # -- enveloppe et liste --------------------------------------------------------------------------------

    def _grow(self, axis, v):
        if v is None:
            return
        lo, hi = self.env.get(axis, (v, v))
        self.env[axis] = (min(lo, v), max(hi, v))

    def _record(self):
        p = [self.pos[a] for a in "XYZ"]
        for a, v in zip("XYZ", p):
            self._grow(a, v)
        if self.points:
            q = self.points[-1]
            if all((a is None and b is None) or (a is not None and b is not None and abs(a - b) < DEDUP)
                   for a, b in zip(p, q)):
                return
        self.points.append(p)

    def _arc_extremes(self, start, end, center, clockwise):
        """Points cardinaux (XY) parcourus par l'arc de ``start`` à ``end`` autour de ``center``."""
        a0 = math.atan2(start[1] - center[1], start[0] - center[0])
        a1 = math.atan2(end[1] - center[1], end[0] - center[0])
        r = math.hypot(start[0] - center[0], start[1] - center[1])
        if clockwise:
            sweep = (a0 - a1) % (2 * math.pi)
        else:
            sweep = (a1 - a0) % (2 * math.pi)
        if sweep < 1e-9:  # cercle complet (début = fin)
            sweep = 2 * math.pi
        for k in range(4):
            ang = k * math.pi / 2
            d = ((a0 - ang) if clockwise else (ang - a0)) % (2 * math.pi)
            if 1e-9 < d < sweep - 1e-9:
                self._grow("X", center[0] + r * math.cos(ang))
                self._grow("Y", center[1] + r * math.sin(ang))

    # -- commandes -----------------------------------------------------------------------------------------

    def command(self, name, params):
        code = norm(name)
        if code is None:
            return
        params = {k.upper(): float(v) for k, v in params.items()}
        written = [a for a in "XYZ" if a in params]
        if code == "G90":
            self.relative = False
        elif code == "G91":
            self.relative = True
        elif code in ("G98", "G99"):
            self.retract = code
        if code in NOT_POSITION:
            for a in written:
                self.pos[a] = None
            return
        if code in CYCLES:
            self._cycle(code, params)
            return
        if code not in ("G0", "G1", "G2", "G3") or not written:
            return
        if self.relative:
            for a in written:
                self.pos[a] = None if self.pos[a] is None else self.pos[a] + params[a]
            return
        start = dict(self.pos)
        for a in written:
            self.pos[a] = params[a]
        if code in ("G2", "G3") and start["X"] is not None and start["Y"] is not None:
            center = (start["X"] + params.get("I", 0.0), start["Y"] + params.get("J", 0.0))
            self._arc_extremes((start["X"], start["Y"]), (self.pos["X"], self.pos["Y"]), center, code == "G2")
        self._record()

    def _cycle(self, code, params):
        """Cycle de perçage (RS274NGC, absolu) : rapide XY, rapide à R, avance au fond, retrait G98 / G99.
        Le débourrage (G83 / G73) n'est pas développé : refusé (le postprocesseur peut le découper autrement)."""
        if code in ("G83", "G73"):
            raise ValueError("%s : débourrage non développé par la référence" % code)
        if self.relative:
            raise ValueError("cycle de perçage en G91 non pris en charge")
        self.cycles += 1
        z0 = self.pos["Z"]
        r = params.get("R", z0)
        if z0 is not None and z0 < r:
            self.pos["Z"] = r
            self._record()
        for a in "XY":
            if a in params:
                self.pos[a] = params[a]
        self._record()
        self.pos["Z"] = r
        self._record()
        self.pos["Z"] = params["Z"]
        self._record()
        self.pos["Z"] = max(z0, r) if (self.retract == "G98" and z0 is not None) else r
        self._record()

    def result(self):
        return {"points": [list(p) for p in self.points],
                "envelope": {a: list(v) for a, v in self.env.items()},
                "final": list(self.points[-1]) if self.points else None,
                "cycles": self.cycles}


def reference(commands):
    """``commands`` : suite de ``(nom, {paramètre: valeur})`` dans l'ordre du programme."""
    ref = Reference()
    for name, params in commands:
        ref.command(name, params)
    return ref.result()


def dedup(points):
    out = []
    for p in points:
        if out and all((a is None and b is None) or (a is not None and b is not None and abs(a - b) < DEDUP)
                       for a, b in zip(p, out[-1])):
            continue
        out.append(p)
    return out


def compare(ref, sim, tol=TOLERANCE):
    """Écarts entre la référence CAM2027 et le passage dans le simulateur : ``(problèmes, écart max, positions
    appariées)`` ; aucun problème = identiques à ``tol``.

    Compare les positions de fin de mouvement (dans l'ordre), la position finale et l'enveloppe par axe."""
    problems = []

    def same(a, b):
        if a is None or b is None:
            return a is None and b is None
        return abs(a - b) <= tol

    # appariement dans l'ordre : chaque position d'un côté est à ``tol`` d'une position de l'autre ; un point très
    # proche du précédent (arrondi du G-code à 0,001 mm) peut s'apparier au point déjà apparié de l'autre côté
    rp, sp = dedup(ref["points"]), dedup(sim["points"])
    i = j = matched = 0
    worst = 0.0
    while i < len(rp) and j < len(sp):
        if all(same(u, v) for u, v in zip(rp[i], sp[j])):
            worst = max([worst] + [abs(u - v) for u, v in zip(rp[i], sp[j]) if u is not None and v is not None])
            i, j, matched = i + 1, j + 1, matched + 1
        elif j > 0 and all(same(u, v) for u, v in zip(rp[i], sp[j - 1])):
            i += 1
        elif i > 0 and all(same(u, v) for u, v in zip(sp[j], rp[i - 1])):
            j += 1
        else:
            problems.append("position %d du parcours CAM2027 %s, %d du simulateur %s" % (i + 1, rp[i], j + 1, sp[j]))
            break
    else:
        rest = [p for p in rp[i:] if not (sp and all(same(u, v) for u, v in zip(p, sp[-1])))]
        rest += [p for p in sp[j:] if not (rp and all(same(u, v) for u, v in zip(p, rp[-1])))]
        if rest:
            problems.append("positions sans correspondance en fin de programme : %s" % rest[:3])
    if not all(same(u, v) for u, v in zip(ref["final"] or [], sim["final"] or [])) or \
            (ref["final"] is None) != (sim["final"] is None):
        problems.append("position finale : CAM2027 %s, simulateur %s" % (ref["final"], sim["final"]))
    for axis in sorted(set(ref["envelope"]) | set(sim["envelope"])):
        r, s = ref["envelope"].get(axis), sim["envelope"].get(axis)
        if r is None or s is None or not (same(r[0], s[0]) and same(r[1], s[1])):
            problems.append("enveloppe %s : CAM2027 %s, simulateur %s" % (axis, r, s))
        else:
            worst = max(worst, abs(r[0] - s[0]), abs(r[1] - s[1]))
    return problems, worst, matched
