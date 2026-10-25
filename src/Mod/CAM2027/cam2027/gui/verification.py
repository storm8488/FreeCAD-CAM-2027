# SPDX-License-Identifier: LGPL-2.1-or-later
"""Panneau de vérification du contrôle matière (charte « Atelier », § 10) : chaque contrôle avec son résultat et
sa **portée** (ce qui a été contrôlé, ce qui ne l'a pas été), jamais un contrôle non exécuté présenté comme
réussi. ``verification_rows`` est pur (testable) ; ``VerificationPage`` l'affiche dans le panneau de tâche."""

from .qt import QtCore, QtGui, QtWidgets
from ..i18n import tr, tr_msg
from . import theme
from .inspector import Page

#: statut -> (symbole, rôle de couleur du thème, libellé)
STATUS = {
    "ok": ("✓", "ok", "OK"),
    "danger": ("✕", "error", "PROBLEM"),
    "warning": ("△", "warning", "INCOMPLETE"),
    "not_checked": ("○", "muted", "NOT CHECKED"),
    "info": ("•", "muted", "INFO"),
}


def verification_rows(rep):
    """``[(contrôle, statut, résultat, portée)]`` depuis le rapport de ``Project.material_check``."""
    rows = []
    tol = rep["tolerance"]
    scope = (tr("radius map around the A axis, {res} mm grid", res="%g" % rep["resolution"]) if rep.get("rotary")
             else tr("height map, {res} mm grid, 3 axes", res="%g" % rep["resolution"]))
    if not rep.get("simulated"):
        rows.append((tr("Gouges on the part"), "not_checked", tr("No operation simulated"), scope))
    elif rep["gouge_max"] > tol:
        x, y, _z = rep["gouge_at"]
        rows.append((tr("Gouges on the part"), "danger",
                     tr("The tool cuts {d} mm into the part (worst at X {x} Y {y}, {n} cells)",
                        d="%.2f" % rep["gouge_max"], x="%.1f" % x, y="%.1f" % y, n=rep["gouge_cells"]), scope))
    else:
        rows.append((tr("Gouges on the part"), "ok", tr("None found on the top of the part (tolerance {t} mm)", t="%g" % tol), scope))
    bone = rep.get("dogbone_overcut") or {}
    if bone.get("max", 0.0) > tol:
        rows.append((tr("Dogbone overcut"), "info", tr("Intended, up to {d} mm, {n} bone(s)", d="%.2f" % bone["max"], n=bone["bones"]),
                     tr("not counted as a gouge")))
    if rep.get("part_cells"):
        x, y, _z = rep["leftover_at"]
        rows.append((tr("Stock left on the part"), "info",
                     tr("max {m} mm (at X {x} Y {y}), mean {a} mm", m="%.2f" % rep["leftover_max"], x="%.1f" % x, y="%.1f" % y,
                        a="%.2f" % rep["leftover_mean"]), tr("columns of the part top")))
    rows.append((tr("Removed volume"), "info", "%.1f cm3" % (rep["removed_volume"] / 1000.0), tr("simulated operations")))
    if rep["rapid_hits"]:
        rows.append((tr("Rapid moves"), "danger", tr("{n} rapid move(s) into the material", n=rep["rapid_hits"]), scope))
    col = rep.get("collisions")
    if col:
        words = {"ok": ("ok", tr("No conflict detected on the checked items")), "collision": ("danger", tr("Collision")),
                 "not_checked": ("not_checked", tr("Not checked"))}
        st, text = words[col["flute_length"]]
        rows.append((tr("Flute length"), st, text, tr("material above the flute length (shank rubbing)")))
        st, text = words[col["holder"]]
        if col["no_holder"]:
            st, text = "warning", tr("Holder not set for: {ops}", ops=", ".join(col["no_holder"]))
        rows.append((tr("Tool holder"), st, text, tr("holder against the remaining stock")))
        st, text = words[col["clamps"]]
        if not col["clamps_defined"]:
            st, text = "not_checked", tr("No clamp defined (Stock and fixture)")
        rows.append((tr("Clamps"), st, text, tr("tool and holder against the clamps")))
        if not rep["rapid_hits"]:
            st, text = words[col["rapids"]]
            rows.append((tr("Rapid moves"), st, text, tr("rapid moves against the remaining stock")))
        kinds = {"flute_length": tr("material above the flute length"), "holder": tr("tool holder in the material"),
                 "clamp": tr("clamp"), "rapid": tr("rapid into the material"),
                 "undrilled": tr("thread milling in a hole that is not drilled (drill it first)")}
        for e in col["events"]:
            x, y, z = e[3] if e[3] else (0.0, 0.0, 0.0)
            what = kinds[e[0]] + (" %s (%s)" % (e[5], e[6]) if e[0] == "clamp" else "")
            rows.append((tr("Collision"), "danger", tr("{what} - {op}, command {n}", what=what, op=e[1], n=e[2]),
                         tr("tip at X {x} Y {y} Z {z}", x="%.2f" % x, y="%.2f" % y, z="%.2f" % z)))
    for label, reason in rep["skipped"]:
        rows.append((tr("Operation not simulated"), "warning", label, tr_msg(reason)))
    for label, note in rep["approximations"]:
        rows.append((tr("Approximation"), "info", label, tr_msg(note)))
    rows.append((tr("Machine limits"), "not_checked", tr("Checked at export (travel, feeds, spindle)"), tr("machine profile")))
    rows.append((tr("Not checked here"), "not_checked",
                 tr("Undercuts seen from the A axis, tool holder and clamps (round stock)") if rep.get("rotary")
                 else tr("Vertical walls and undercuts (height map), A axis operations"), ""))
    return rows


def overall_status(rows):
    """Statut d'ensemble : problème > incomplet > OK (un contrôle non exécuté rend la vérification incomplète)."""
    statuses = {s for _c, s, _r, _p in rows}
    if "danger" in statuses:
        return "danger", tr("Problems found: check the toolpaths before cutting")
    if "warning" in statuses or any(s == "not_checked" and c not in (tr("Machine limits"), tr("Not checked here"))
                                    for c, s, _r, _p in rows):
        return "warning", tr("Verification incomplete: some items could not be checked")
    return "ok", tr("No conflict detected on the checked items")


class VerificationPage(Page):
    """Tableau contrôle / résultat / portée, statut d'ensemble, rapport texte copiable (panneau contextuel)."""

    def __init__(self, rep, report_text, parent=None):
        super(VerificationPage, self).__init__(tr("Verification"), parent)
        self.setObjectName("CAM2027_Verification")
        body = self.scrolled_body()
        lay = QtWidgets.QVBoxLayout(body)
        lay.setContentsMargins(10, 8, 10, 8)
        rows = verification_rows(rep)
        status, headline = overall_status(rows)
        head = QtWidgets.QLabel("%s  %s" % (STATUS[status][0], headline))
        head.setObjectName("summary")
        head.setWordWrap(True)
        head.setStyleSheet("font-weight: 600; font-size: 16px; color: %s" % theme.status_color(STATUS[status][1]))
        lay.addWidget(head)
        scope = QtWidgets.QLabel(tr("Checks done: {n}. Not checked: {m}.", n=sum(1 for _c, s, _r, _p in rows if s in ("ok", "danger", "info")),
                                    m=sum(1 for _c, s, _r, _p in rows if s in ("not_checked", "warning"))))
        theme.set_role(scope, "muted")
        lay.addWidget(scope)
        # une carte par contrôle (lisible dans un panneau de 360 px, sans défilement horizontal)
        for check, st, result, scope_text in rows:
            symbol, role, word = STATUS[st]
            card = QtWidgets.QFrame()
            card.setObjectName("taskRow")
            cl = QtWidgets.QVBoxLayout(card)
            cl.setContentsMargins(8, 4, 8, 4)
            cl.setSpacing(1)
            head_row = QtWidgets.QLabel("<span style='color:%s'><b>%s %s</b></span> &nbsp; <b>%s</b>" % (
                theme.status_color(role), symbol, tr(word), check))
            head_row.setWordWrap(True)
            cl.addWidget(head_row)
            res = QtWidgets.QLabel(result)
            res.setWordWrap(True)
            cl.addWidget(res)
            if scope_text:
                sc = QtWidgets.QLabel(tr("Scope: {s}", s=scope_text))
                sc.setWordWrap(True)
                theme.set_role(sc, "muted")
                cl.addWidget(sc)
            lay.addWidget(card)
        lay.addStretch(1)
        note = QtWidgets.QLabel(tr("A result has a scope: what was checked and what remains unknown. A verification does not validate the machine setup."))
        note.setWordWrap(True)
        note.setProperty("role", "muted")
        lay.addWidget(note)
        self.add_buttons(tr("Close"), extra=((tr("Copy the report"),
                                             lambda: QtWidgets.QApplication.clipboard().setText(report_text)),))
        theme.apply(self)
        self.rows = rows
        self.status = status
