# SPDX-License-Identifier: LGPL-2.1-or-later
"""Contrôle matière 4e axe : carte de rayon sur le cylindre déroulé (brut rond le long de X, axe A).

La matière restante est un rayon par cellule (X, angle θ du repère pièce) : le long du rayon qui part de l'axe
à l'angle θ, la matière va de l'axe jusqu'à ``r``. Chaque position de la fraise est décrite dans le **repère
tourné** de la machine (A tourné, l'axe A en (cy, cz)) : fraise verticale en X, décalée de ``dy = Y − cy``,
pointe à ``h = Z − cz`` au-dessus de l'axe, la pièce tournée de ``φ`` (A = signe × φ, comme ``wrap.to_machine``
et ``indexing.rotation_matrix``). Les mouvements enroulés (X, Z, A), les parois radiales (X, Y, Z, A), les
opérations indexées et les opérations 3 axes à A = 0 passent par le même calcul.

Pour chaque cellule touchée, le rayon de la cellule coupe la fraise (solide convexe : cylindre, boule, cône,
torique) sur un intervalle ``[s_min, s_sortie]`` ; ``s_min`` est trouvé exactement (plate) ou par échantillonnage
et dichotomie (profils ``sim.ToolProfile``). Deux cartes :

- ``r`` : surface de la matière restante, abaissée à ``s_min`` quand la fraise ressort au-delà de la matière
  (sinon la coupe ferait un trou sous la surface : la carte garde la surface, le reste peut être surestimé) ;
- ``deep`` : rayon le plus bas jamais atteint par la fraise sur chaque rayon : **entaille** = rayon de la pièce
  − ``deep`` (la matière sous la surface de la pièce le long d'un rayon appartient à la pièce).

Le rayon de la pièce par cellule vient de sa triangulation (section par le demi-plan de chaque angle). Limites :
pièce vue de l'axe (pas de contre-dépouille sur un même rayon), pas de collision du porte-outil ni des brides.
"""

import math

from ..i18n import Msg, UserError
from . import sim

#: nombre d'échantillons le long du rayon avant la dichotomie (fraises non plates)
SAMPLES = 8
#: itérations de la dichotomie (intervalle / 2^n)
BISECT = 14


def _np():
    import numpy

    return numpy


class RadialStock(object):
    """Rayon de la matière restante sur une grille (X, θ) ; ``t0``..``t1`` : fenêtre angulaire (tour complet par
    défaut)."""

    def __init__(self, x0, x1, radius, res=sim.DEFAULT_RESOLUTION, t0=0.0, t1=2.0 * math.pi, res_t=None):
        np = _np()
        nx = max(1, int(math.ceil((x1 - x0) / res)))
        res_t = res_t or res / radius
        nt = max(8, int(math.ceil((t1 - t0) / res_t)))
        if nx * nt > sim.MAX_CELLS:
            raise UserError("material check: {nx} x {ny} cells, increase the resolution (max {m} cells)",
                            nx=nx, ny=nt, m=sim.MAX_CELLS)
        self.radius = float(radius)
        self.res_x, self.res_t = (x1 - x0) / nx, (t1 - t0) / nt
        self.xs = x0 + (np.arange(nx) + 0.5) * self.res_x
        self.ts = t0 + (np.arange(nt) + 0.5) * self.res_t
        self.full_turn = abs((t1 - t0) - 2.0 * math.pi) < 1e-9
        self.r = np.full((nx, nt), self.radius)
        self.deep = np.full((nx, nt), np.inf)
        self.rapid_hits = 0
        self.rapid_hit_at = None

    @property
    def cells(self):
        return self.r.shape

    def removed_volume(self):
        np = _np()
        return float(((self.radius ** 2 - self.r ** 2) / 2.0).sum() * self.res_t * self.res_x)

    # -- une position de la fraise ---------------------------------------------------------------------------

    def cut(self, X, dy, h, phi, profile, rapid=False, tolerance=0.02):
        """Enlève la matière d'une position : fraise verticale (repère tourné) en (X, dy), pointe à ``h`` au-dessus
        de l'axe, pièce tournée de ``phi`` (rad). Retourne True si un rapide enlève de la matière."""
        np = _np()
        rt = profile.radius
        R = self.radius
        if h >= R or h <= 1e-6:  # au-dessus du brut (ou sous l'axe : impossible pour une fraise venant de +Z)
            return False
        i0, i1 = np.searchsorted(self.xs, [X - rt, X + rt])
        if i0 >= i1:
            return False
        dlo = min(math.atan2(dy - rt, h), math.atan2(dy - rt, R))
        dhi = max(math.atan2(dy + rt, h), math.atan2(dy + rt, R))
        d_all = np.mod(self.ts - phi + math.pi, 2.0 * math.pi) - math.pi
        cols = np.nonzero((d_all >= dlo - self.res_t) & (d_all <= dhi + self.res_t))[0]
        if not len(cols):
            return False
        dx = (self.xs[i0:i1] - X)[:, None]
        d = d_all[cols][None, :]
        sd, cd = np.sin(d), np.cos(d)
        w2 = rt * rt - dx * dx
        w = np.sqrt(np.maximum(w2, 0.0))
        small = np.abs(sd) < 1e-12
        safe_sd = np.where(small, 1.0, sd)
        s1, s2 = (dy - w) / safe_sd, (dy + w) / safe_sd
        sa = np.where(small, 0.0, np.minimum(s1, s2))
        sb = np.where(small, np.where(abs(dy) <= w, np.inf, -np.inf), np.maximum(s1, s2))
        sa = np.maximum(sa, 0.0)
        safe_cd = np.where(cd > 1e-9, cd, 1.0)
        lo = np.maximum(sa, h / safe_cd)
        valid = (w2 >= 0.0) & (cd > 1e-9) & (lo <= sb)
        if not valid.any():
            return False
        if profile.kind == "flat":
            smin = lo
        else:
            smin, found = self._first_inside(profile, dx, sd, safe_cd, dy, h, sa, sb, lo)
            valid &= found
        sub_r = self.r[i0:i1][:, cols]
        connected = sb >= sub_r - 1e-6  # la fraise ressort au-delà de la surface de la matière sur ce rayon
        hit = False
        # rapide : seulement là où la carte connaît la matière (un trou sous la surface n'est pas représenté :
        # une remontée dans une poche déjà vidée y passerait pour une coupe)
        if rapid and (valid & connected & (smin < sub_r - tolerance)).any():
            hit = True
            if self.rapid_hit_at is None:
                self.rapid_hit_at = (X, dy, h, phi)
        deep = self.deep[i0:i1][:, cols]
        self.deep[i0:i1, cols] = np.where(valid, np.minimum(deep, smin), deep)
        # la fraise ressort au-delà de la matière : la surface descend ; sinon trou sous la surface (ignoré)
        lower = valid & connected & (smin < sub_r)
        if lower.any():
            self.r[i0:i1, cols] = np.where(lower, smin, sub_r)
        return hit

    @staticmethod
    def _first_inside(profile, dx, sd, cd, dy, h, sa, sb, lo):
        """Premier point du rayon dans la fraise (profil quelconque, solide convexe) : échantillons entre ``lo``
        (plan du bout) et le plan à la hauteur de la partie droite, puis dichotomie."""
        np = _np()
        rt = profile.radius
        top = float(profile.lift(np.array([rt]))[0])
        hi = np.minimum(np.maximum(sa, (h + top) / cd), sb)
        hi = np.maximum(hi, lo)

        def inside(s):
            q = np.sqrt(dx[..., None] * dx[..., None] + (s * sd[..., None] - dy) ** 2) if s.ndim == 3 else \
                np.sqrt(dx * dx + (s * sd - dy) ** 2)
            cdx = cd[..., None] if s.ndim == 3 else cd
            return (q <= rt + 1e-9) & (s * cdx - h >= profile.lift(np.minimum(q, rt)) - 1e-12)

        f = np.linspace(0.0, 1.0, SAMPLES)
        S = lo[..., None] + (hi - lo)[..., None] * f
        ins = inside(S)
        found = ins.any(axis=2)
        first = np.argmax(ins, axis=2)
        b = np.take_along_axis(S, first[..., None], axis=2)[..., 0]
        a = np.take_along_axis(S, np.maximum(first - 1, 0)[..., None], axis=2)[..., 0]
        for _ in range(BISECT):
            m = (a + b) / 2.0
            im = inside(m)
            b = np.where(im, m, b)
            a = np.where(im, a, m)
        return np.where(first == 0, lo, b), found

    # -- mouvements ---------------------------------------------------------------------------------------------

    def sweep_states(self, states, profile, tolerance=0.02):
        """Balaye une suite d'états machine ``(rapide, (X, dy, h, φ))`` (le premier fixe la position), interpolés
        linéairement comme la machine (X, Y, Z, A ensemble). Retourne le nombre de rapides dans la matière (comptés
        aussi dans ``rapid_hits``)."""
        step = min(self.res_x, self.res_t * self.radius) / 2.0
        R = self.radius
        hits = 0
        prev = None
        xlo, xhi = self.xs[0] - profile.radius - self.res_x, self.xs[-1] + profile.radius + self.res_x
        for rapid, s in states:
            if prev is None:
                prev = s
                if self.cut(s[0], s[1], s[2], s[3], profile, rapid, tolerance):
                    hits += 1
                    self.rapid_hits += 1
                continue
            (x0, y0, h0, p0), (x1, y1, h1, p1) = prev, s
            prev = s
            if min(h0, h1) >= R or max(x0, x1) < xlo or min(x0, x1) > xhi:
                continue
            n = max(1, int(math.ceil(max(abs(x1 - x0), abs(y1 - y0), abs(h1 - h0), abs(p1 - p0) * R) / step)))
            hit = False
            for k in range(1, n + 1):
                t = float(k) / n
                hit |= self.cut(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, h0 + (h1 - h0) * t, p0 + (p1 - p0) * t,
                                profile, rapid, tolerance)
            if hit:  # un rapide compté une fois
                hits += 1
                self.rapid_hits += 1
        return hits

    def sweep_moves(self, moves, profile, tolerance=0.02):
        """Mouvements déroulés de ``rotary`` / ``wrap`` (``(kind, x, y, z[, dy])``) : φ = y / R, h = R + z."""
        R = self.radius
        states = [(m[0] == "rapid", (m[1], m[4] if len(m) > 4 else 0.0, R + m[3], m[2] / R)) for m in moves]
        return self.sweep_states(states, profile, tolerance)

    # -- comparaison avec la pièce ------------------------------------------------------------------------------

    def part_radius(self, shapes, center, deflection=0.005):
        """Rayon de la pièce sur chaque cellule (NaN hors de la pièce) : section de sa triangulation par le
        demi-plan de chaque angle."""
        np = _np()
        A, B, C = sim._triangles(shapes, deflection)
        cy, cz = center
        out = np.full(self.r.shape, np.nan)
        if not len(A):
            return out
        X = np.stack([A[:, 0], B[:, 0], C[:, 0]], axis=1)
        Y = np.stack([A[:, 1], B[:, 1], C[:, 1]], axis=1) - cy
        Z = np.stack([A[:, 2], B[:, 2], C[:, 2]], axis=1) - cz
        nx = len(self.xs)
        for j, t in enumerate(self.ts.tolist()):
            c, s = math.cos(t), math.sin(t)
            yr = Y * c - Z * s  # le rayon de l'angle t amené au sommet (+Z)
            zr = Y * s + Z * c
            keep = (yr.min(axis=1) <= 0.0) & (yr.max(axis=1) >= 0.0) & (zr.max(axis=1) > 0.0)
            if not keep.any():
                continue
            xk, yk, zk = X[keep], yr[keep], zr[keep]
            px, pz = [], []
            for a, b in ((0, 1), (1, 2), (2, 0)):
                ya, yb = yk[:, a], yk[:, b]
                den = np.where(ya != yb, ya - yb, 1.0)
                u = np.where(ya != yb, ya / den, 0.0)
                ok = ((ya <= 0) & (yb >= 0)) | ((ya >= 0) & (yb <= 0))
                px.append(np.where(ok, xk[:, a] + (xk[:, b] - xk[:, a]) * u, np.nan))
                pz.append(np.where(ok, zk[:, a] + (zk[:, b] - zk[:, a]) * u, np.nan))
            px, pz = np.stack(px, axis=1), np.stack(pz, axis=1)
            lo_i = np.nanargmin(np.where(np.isnan(px), np.inf, px), axis=1)
            hi_i = np.nanargmax(np.where(np.isnan(px), -np.inf, px), axis=1)
            rows = np.arange(len(px))
            x1, z1, x2, z2 = px[rows, lo_i], pz[rows, lo_i], px[rows, hi_i], pz[rows, hi_i]
            good = np.isfinite(x1) & np.isfinite(x2)
            x1, z1, x2, z2 = x1[good], z1[good], x2[good], z2[good]
            i_lo = np.searchsorted(self.xs, x1, "left")
            i_hi = np.searchsorted(self.xs, x2, "right")
            counts = np.maximum(i_hi - i_lo, 0)
            if not counts.sum():
                continue
            seg = np.repeat(np.arange(len(x1)), counts)
            idx = np.arange(counts.sum()) - np.repeat(np.cumsum(counts) - counts, counts) + i_lo[seg]
            span = np.where(x2 - x1 > 1e-12, x2 - x1, 1.0)[seg]
            zz = z1[seg] + (z2[seg] - z1[seg]) * (self.xs[idx] - x1[seg]) / span
            col = np.full(nx, -np.inf)
            np.maximum.at(col, idx, zz)
            col[~np.isfinite(col)] = np.nan
            out[:, j] = np.fmax(out[:, j], col)
        return out

    def compare(self, part, tolerance=0.02, lateral=sim.WALL_TOLERANCE):
        """Entaille et reste (comme ``sim.compare``) ; ``gouge_at`` / ``leftover_at`` en (X, θ, rayon de la
        pièce). L'entaille se mesure contre le rayon le plus bas de la pièce à ``lateral`` mm près (parois)."""
        np = _np()
        on_part = np.isfinite(part)
        report = {"part_cells": int(on_part.sum()), "gouge_max": 0.0, "gouge_cells": 0, "gouge_at": None,
                  "leftover_max": 0.0, "leftover_mean": 0.0, "leftover_at": None}
        if not on_part.any():
            return report
        low = np.where(on_part, part, np.inf)
        ki = int(math.ceil(lateral / self.res_x - 1e-9))
        kj = int(math.ceil(lateral / (self.res_t * self.radius) - 1e-9))
        base = low.copy()
        for di in range(-ki, ki + 1):
            for dj in range(-kj, kj + 1):
                if di or dj:
                    shifted = np.roll(np.roll(base, di, axis=0), dj, axis=1)
                    if di > 0:
                        shifted[:di] = np.inf
                    elif di < 0:
                        shifted[di:] = np.inf
                    if not self.full_turn:
                        if dj > 0:
                            shifted[:, :dj] = np.inf
                        elif dj < 0:
                            shifted[:, dj:] = np.inf
                    low = np.minimum(low, shifted)
        gouge = np.where(on_part & np.isfinite(low), low - self.deep, -np.inf)
        gmax = float(np.max(gouge))
        if gmax > tolerance:
            i, j = np.unravel_index(int(np.argmax(gouge)), gouge.shape)
            report.update(gouge_max=gmax, gouge_cells=int((gouge > tolerance).sum()),
                          gouge_at=(float(self.xs[i]), float(self.ts[j]), float(low[i, j])))
        diff = np.where(on_part, self.r - part, np.nan)
        left = np.where(on_part, diff, -np.inf)
        i, j = np.unravel_index(int(np.argmax(left)), left.shape)
        report.update(leftover_max=max(0.0, float(left[i, j])), leftover_mean=float(np.nanmean(np.maximum(diff, 0.0))),
                      leftover_at=(float(self.xs[i]), float(self.ts[j]), float(part[i, j])))
        self.gouge = gouge
        return report

    def gouge_mask(self, tolerance=0.02):
        np = _np()
        g = getattr(self, "gouge", None)
        return np.zeros(self.r.shape, dtype=bool) if g is None else g > tolerance

    def surface_mesh(self, center, mask=None, lift=0.0):
        """Maillage de la matière restante dans le repère pièce (cellules de ``mask`` seulement si donné)."""
        import Mesh

        np = _np()
        cy, cz = center

        def point(x, t, r):
            return np.stack([x, cy + r * np.sin(t), cz + r * np.cos(t)], axis=-1)

        if mask is None:
            X, T = np.meshgrid(self.xs, self.ts, indexing="ij")
            if self.full_turn:  # tour fermé
                X, T = np.concatenate([X, X[:, :1]], axis=1), np.concatenate([T, T[:, :1] + 2 * math.pi], axis=1)
                Rr = np.concatenate([self.r, self.r[:, :1]], axis=1)
            else:
                Rr = self.r
            P = point(X, T, Rr + lift)
            a, b = P[:-1, :-1].reshape(-1, 3), P[1:, :-1].reshape(-1, 3)
            c, d = P[1:, 1:].reshape(-1, 3), P[:-1, 1:].reshape(-1, 3)
        else:
            i, j = np.nonzero(mask)
            if not len(i):
                return Mesh.Mesh()
            x0, x1 = self.xs[i] - self.res_x / 2, self.xs[i] + self.res_x / 2
            t0, t1 = self.ts[j] - self.res_t / 2, self.ts[j] + self.res_t / 2
            r = self.r[i, j] + lift
            a, b, c, d = point(x0, t0, r), point(x1, t0, r), point(x1, t1, r), point(x0, t1, r)
        tri = np.concatenate([np.stack([a, b, c], axis=1), np.stack([a, c, d], axis=1)]).reshape(-1, 3)
        return Mesh.Mesh([tuple(q) for q in tri.tolist()])


# -- états machine depuis les opérations ------------------------------------------------------------------------


def _states(commands, start, a_deg, center, sign):
    """États ``(rapide, (X, dy, h, φ))`` des commandes G0 / G1 (A modal ; ``a_deg`` : angle avant) et arcs G2 / G3
    (plan XY, découpés par ``sim.path_segments``). Retourne ``(états, dernière position (X, Y, Z, A))``."""
    cy, cz = center
    pos = list(start) if start is not None else None
    a = a_deg
    out = []

    def state(rapid, p, a):
        return rapid, (p[0], p[1] - cy, p[2] - cz, math.radians(a or 0.0) / sign)

    for c in commands:
        name = c.Name.upper()
        p = c.Parameters
        if name not in ("G0", "G00", "G1", "G01", "G2", "G02", "G3", "G03"):
            continue
        if pos is None:
            pos = [p.get("X", 0.0), p.get("Y", cy), p.get("Z", cz + 1e6)]
            a = p.get("A", a)
            out.append(state(True, pos, a))
            continue
        if name in ("G2", "G02", "G3", "G03"):
            segs, end = sim.path_segments([c], pos)
            for _rapid, _p0, p1 in segs:
                out.append(state(False, p1, a))
            pos = list(end)
            continue
        pos = [p.get("X", pos[0]), p.get("Y", pos[1]), p.get("Z", pos[2])]
        a = p.get("A", a)
        out.append(state(name in ("G0", "G00"), pos, a))
    return out, (pos, a)


def material_check(project, resolution=None, tolerance=0.02):
    """Contrôle matière d'un projet sur brut rond (accroche de ``Project.material_check``) : même rapport que le
    contrôle 3 axes (``rotary`` = True, positions d'entaille en X, Y, Z du repère pièce)."""
    from .indexing import check_machine
    from . import dressups as dressupmod
    from . import holes as holesmod
    from . import indexing
    from . import wrap as wrapmod

    np = _np()
    resolution = resolution or sim.DEFAULT_RESOLUTION
    try:
        cy, cz, sign = check_machine(project.machine)
    except ValueError as exc:
        raise UserError("material check on round stock: {error}", error=str(exc))
    radius = wrapmod.radius_of_stock(project.job)
    wrapmod.check_stock_axis(project.job, (cy, cz))
    project.compute()
    bb = project.job.Stock.Shape.BoundBox
    stock = RadialStock(bb.XMin, bb.XMax, radius, resolution)
    simulated, skipped, approximations = [], [], []
    pos, a_deg = None, 0.0
    for obj in project.operations():
        base = dressupmod.base_operation(obj)
        if getattr(base, "Active", True) is False:
            continue
        rec = project.registry.get(base.Name) or {}
        commands = obj.Path.Commands
        if indexing.is_index_op(obj):  # positionnement de A : rapides seulement
            states, (pos, a_deg) = _states(commands, pos, a_deg, (cy, cz), sign)
            continue
        if rec.get("kind") == "probe":
            skipped.append((obj.Label, Msg("probing (no cut)")))
            pos = None
            continue
        if not rec.get("tool_id"):
            skipped.append((obj.Label, Msg("unknown tool")))
            continue
        _asm, tool, _holder = project.library.resolve_assembly(rec["assembly_id"])
        profile, note = sim.ToolProfile.from_library_tool(tool)
        if note:
            approximations.append((obj.Label, note))
        if rec.get("kind") == "drilling" and holesmod.has_cycles(commands):
            commands = holesmod.expand_cycles(commands)
        if not wrapmod.is_wrap_op(obj) and rec.get("index_deg") not in (None, 0, 0.0):
            a_deg = rec["index_deg"] * sign  # opération indexée : A écrit par l'index qui la précède
        states, (pos, a_deg) = _states(commands, pos, a_deg, (cy, cz), sign)
        stock.sweep_states(states, profile, tolerance)
        simulated.append(obj.Label)
    shapes = [o.Shape for o in project.job.Model.Group if getattr(o, "Shape", None) is not None]
    part = stock.part_radius(shapes, (cy, cz))
    report = stock.compare(part, tolerance)
    for key in ("gouge_at", "leftover_at"):  # (X, θ, rayon) -> point du repère pièce
        if report[key]:
            x, t, r = report[key]
            report[key] = (x, cy + r * math.sin(t), cz + r * math.cos(t))
    checked = bool(simulated)
    rapid_status = "collision" if stock.rapid_hits else ("ok" if checked else "not_checked")
    report["collisions"] = {
        "events": [], "flute_length": "not_checked", "holder": "not_checked", "clamps": "not_checked",
        "rapids": rapid_status, "no_holder": [], "clamps_defined": [], "not_run": [label for label, _r in skipped],
    }
    report.update(removed_volume=stock.removed_volume(), rapid_hits=stock.rapid_hits,
                  rapid_hit_at=stock.rapid_hit_at, simulated=simulated, skipped=skipped,
                  approximations=approximations, resolution=resolution, tolerance=tolerance, cells=stock.cells,
                  rotary=True, center=(cy, cz))
    report["part_radius_ok"] = bool(np.isfinite(part).any())
    project.last_zmap = None
    project.last_rotary = stock
    project._store_check(report)
    return report
