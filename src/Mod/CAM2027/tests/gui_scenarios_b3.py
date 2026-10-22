# SPDX-License-Identifier: LGPL-2.1-or-later
"""Scénarios d'interface du flux B3 (jour 3 : interface et stabilité), appelés par ``gui_scenarios.py``.

- **Audit** (``CAM2027_B3_AUDIT=1``, valable pour *tous* les scénarios de la suite) :
  - chaque commande lancée par un scénario est suivie de Ctrl+Z (``Std_Undo``) puis Ctrl+Y (``Std_Redo``) :
    une seule étape d'annulation, le document revient exactement à l'état d'avant, puis à celui d'après ;
    le panneau Projet suit ; une commande qui modifie le document sans étape d'annulation est signalée ;
  - interface figée : plus grand écart entre deux tops d'une horloge Qt de 50 ms pendant la commande ;
  - chaque projet fermé par un scénario est d'abord enregistré, fermé, rouvert : mêmes opérations, mêmes
    parcours, panneau Projet, page de tâches FreeCAD de chaque opération (double-clic dans l'arbre).
- Scénarios B3 : boutons du panneau Projet et éditeur sous Ctrl+Z, longue session (50 opérations ajoutées /
  modifiées / supprimées : mémoire, fenêtres restantes, temps du panneau).
"""

import os
import time
import traceback

import FreeCAD
import FreeCADGui
from PySide import QtCore, QtWidgets

G = None  # module gui_scenarios (outils du pilote)

#: commandes qui ne modifient pas le projet (aucune étape d'annulation attendue)
NO_UNDO = {"CAM2027_ToolLibrary", "CAM2027_Theme", "CAM2027_AdvancedMode", "CAM2027_ResetLayout", "CAM2027_About",
           "CAM2027_Simulate", "CAM2027_Export", "CAM2027_SaveTemplate", "CAM2027_SetupSheetPdf",
           "CAM2027_Compute", "CAM2027_MaterialCheck", "CAM2027_NewProject"}
#: propriétés recalculées (résultat du calcul, pas une donnée de l'utilisateur) ou d'affichage
DERIVED = {"Path", "Shape", "Mesh", "CycleTime", "ExpressionEngine", "Label2", "Visibility", "MaterialCheck",
           "Placement_", "StopProcessing", "AreaParams", "PathParams", "removalshape", "ModelAwareExperiment",
           }
#: profondeurs et hauteurs par défaut que FreeCAD recalcule à chaque exécution (parcours inchangé) : jamais comparées
OP_DEFAULTS = {"OpStartDepth", "OpFinalDepth", "OpToolDiameter", "OpStockZMax", "OpStockZMin"}

FREEZE_S = 0.5
#: stratégies trop gourmandes pour les scénarios B3 (reprise des angles sur le plateau : plus de 6 Go, arrêtée
#: par le garde-fou du brief ; même page de tâches que les plats, vérifiée avec eux)
HEAVY = ("pencil",)
#: Annuler sur une page de tâches sans modification : rien à recalculer
CANCEL_MAX_S = 2.0


# -- état du document -----------------------------------------------------------------------------------------


def _val(v, depth=0):
    if isinstance(v, bool) or v is None or isinstance(v, int):
        return v
    if isinstance(v, float):
        return round(v, 6)
    if isinstance(v, str):
        return v
    if isinstance(v, FreeCAD.Vector):
        return ("V",) + tuple(round(c, 6) for c in v)
    if isinstance(v, FreeCAD.Placement):
        return ("P",) + tuple(round(c, 6) for c in v.Base) + tuple(round(c, 6) for c in v.Rotation.Q)
    if isinstance(v, FreeCAD.Units.Quantity):
        return round(v.Value, 6)
    if hasattr(v, "TypeId") and hasattr(v, "Name") and hasattr(v, "Document"):
        return "@" + v.Name
    if hasattr(v, "Commands") and hasattr(v, "toGCode"):
        return ("path", len(v.Commands))
    if hasattr(v, "ShapeType") and hasattr(v, "BoundBox"):
        if v.isNull():
            return ("shape", None)
        b = v.BoundBox
        return ("shape", v.ShapeType, round(b.XMin, 3), round(b.YMin, 3), round(b.ZMin, 3), round(b.XMax, 3),
                round(b.YMax, 3), round(b.ZMax, 3))
    if hasattr(v, "CountFacets"):
        return ("mesh", v.CountFacets)
    if isinstance(v, (list, tuple)) and depth < 3:
        return tuple(_val(x, depth + 1) for x in v)
    if isinstance(v, dict) and depth < 3:
        return tuple(sorted((str(k), _val(x, depth + 1)) for k, x in v.items()))
    return type(v).__name__


def doc_state(doc, derived=True):
    """{nom : (type, libellé, {propriété : valeur})} ; ``derived=False`` : sans les résultats de calcul."""
    out = {}
    for o in doc.Objects:
        props = {}
        for p in o.PropertiesList:
            if not derived and p in DERIVED:
                continue
            if p in ("ExpressionEngine", "Label2") or p in OP_DEFAULTS:
                continue
            try:
                props[p] = _val(o.getPropertyByName(p))
            except Exception:
                continue
        out[o.Name] = (o.TypeId, o.Label, props)
    return out


def state_diff(a, b, limit=8):
    """Différences lisibles entre deux états (objets ajoutés / retirés, propriétés changées)."""
    out = []
    for n in sorted(set(a) - set(b)):
        out.append("-%s(%s)" % (n, a[n][1]))
    for n in sorted(set(b) - set(a)):
        out.append("+%s(%s)" % (n, b[n][1]))
    for n in sorted(set(a) & set(b)):
        pa, pb = a[n][2], b[n][2]
        if a[n][1] != b[n][1]:
            out.append("%s.Label %r->%r" % (n, a[n][1], b[n][1]))
        for p in sorted(set(pa) | set(pb)):
            if pa.get(p, "<absent>") != pb.get(p, "<absent>"):
                out.append("%s.%s %s->%s" % (n, p, str(pa.get(p, "<absent>"))[:80], str(pb.get(p, "<absent>"))[:80]))
    return out[:limit] + (["... %d more" % (len(out) - limit)] if len(out) > limit else [])


def panel_ops():
    p = G.panel()
    if p is None:
        return None
    return [p.tree.topLevelItem(i).text(0) for i in range(p.tree.topLevelItemCount())]


def project_ops(doc):
    from cam2027.project.project import Project

    try:
        proj = Project.from_document(doc)
        return [o.Label for o in proj.operations()] if proj.has_job else []
    except Exception:
        return None


# -- mesures --------------------------------------------------------------------------------------------------


class Heartbeat(object):
    """Horloge Qt de 50 ms : le plus grand écart entre deux tops = durée pendant laquelle l'interface n'a pas
    traité ses événements."""

    def __init__(self):
        self.timer = QtCore.QTimer()
        self.timer.setInterval(50)
        self.timer.timeout.connect(self._tick)
        self.last = None
        self.worst = 0.0

    def _tick(self):
        now = time.time()
        if self.last is not None:
            self.worst = max(self.worst, now - self.last)
        self.last = now

    def __enter__(self):
        self.last = self.first = time.time()
        self.worst = 0.0
        self.timer.start()
        return self

    def __exit__(self, *_a):
        self._tick()
        self.timer.stop()
        return False


def memory_mb():
    """Mémoire privée (commit) et ensemble de travail du processus, en Mo (Windows)."""
    import ctypes
    from ctypes import wintypes

    class PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
    try:
        k32 = ctypes.WinDLL("kernel32")
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
        k32.K32GetProcessMemoryInfo.restype = wintypes.BOOL
        c = PMC()
        c.cb = ctypes.sizeof(PMC)
        if not k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(c), c.cb):
            return 0.0, 0.0
        return c.PagefileUsage / 1048576.0, c.WorkingSetSize / 1048576.0
    except Exception:
        return 0.0, 0.0


def live_dialogs():
    """Dialogues encore vivants (enfants de la fenêtre principale) : chaque commande en créait un nouveau.
    Les destructions différées sont faites d'abord, comme au retour dans la boucle d'événements."""
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    return [d for d in FreeCADGui.getMainWindow().findChildren(QtWidgets.QDialog)]


# -- audit des commandes : Ctrl+Z / Ctrl+Y ----------------------------------------------------------------------


def flush_live(note=""):
    """Rapport écrit au fil de l'eau (celui de la suite n'est écrit qu'à la fin : rien si le processus est
    arrêté), avec la mémoire du processus."""
    if note:
        G.log("  B3 %s, memory %.0f MB" % (note, memory_mb()[0]))
    try:
        with open(os.path.join(G.OUT, "gui_scenarios_b3_live.txt"), "w", encoding="utf-8") as fp:
            fp.write("\n".join(G.lines) + "\n")
    except OSError:
        pass

stats = {"commands": 0, "undo_checked": 0, "freezes": []}


def _gui_undo(doc, redo=False):
    """Ctrl+Z / Ctrl+Y comme l'utilisateur (commande de FreeCAD sur le document actif)."""
    FreeCAD.setActiveDocument(doc.Name)
    FreeCADGui.ActiveDocument = FreeCADGui.getDocument(doc.Name)
    before = doc.UndoCount, doc.RedoCount
    FreeCADGui.runCommand("Std_Redo" if redo else "Std_Undo", 0)
    G.pump(0.2)
    if (doc.UndoCount, doc.RedoCount) == before:  # pas de vue active : même action par le document
        if redo:
            doc.redo()
        else:
            doc.undo()
        G.pump(0.1)


def audit_undo(scenario, name, doc, before, n0, editors0):
    """Après la commande ``name`` sur ``doc`` : une étape, Ctrl+Z revient à ``before``, Ctrl+Y revient à
    l'état d'après."""
    try:
        if doc.Name not in FreeCAD.listDocuments():
            return
    except Exception:
        return
    after = doc_state(doc, derived=False)
    steps = doc.UndoCount - n0
    changed = state_diff(before, after)
    if name in NO_UNDO:
        structural = [c for c in changed if c[:1] in "+-"]
        if steps:
            G.problem(scenario, "B3 %s added %d undo step(s) although it does not change the project" % (name, steps))
        if structural:
            G.log("  B3 %s changed the document without undo step: %s" % (name, structural[:4]))
        return
    if not changed:
        if steps:
            G.log("  B3 %s: empty undo step(s) %d %s" % (name, steps, doc.UndoNames[:steps]))
        return
    if steps == 0:
        G.problem(scenario, "B3 %s changed the project without an undo step: %s" % (name, changed))
        return
    if steps > 1:
        G.problem(scenario, "B3 %s made %d undo steps instead of one: %s" % (name, steps, doc.UndoNames[:steps]))
    stats["undo_checked"] += 1
    full_after = doc_state(doc, derived=True)
    ops_after = project_ops(doc)
    for _i in range(steps):
        _gui_undo(doc)
    back = doc_state(doc, derived=False)
    diff = state_diff(before, back)
    if diff:
        G.problem(scenario, "B3 %s: Ctrl+Z did not restore the project: %s" % (name, diff))
    G.pump(0.3)
    if FreeCAD.ActiveDocument is doc and G.panel() is not None:
        shown, real = panel_ops(), project_ops(doc)
        if real is not None and shown != real:
            G.problem(scenario, "B3 %s: Project panel not refreshed after Ctrl+Z: %s instead of %s" % (name, shown, real))
    for _i in range(steps):
        _gui_undo(doc, redo=True)
    again = doc_state(doc, derived=True)
    diff = state_diff(full_after, again)
    if diff:
        G.problem(scenario, "B3 %s: Ctrl+Y did not restore the result: %s" % (name, diff))
    if project_ops(doc) != ops_after:
        G.problem(scenario, "B3 %s: operations after Ctrl+Y %s instead of %s" % (name, project_ops(doc), ops_after))
    G.pump(0.3)


def audited(cls, name):
    """Classe de commande dont ``Activated`` est suivi de l'audit (Ctrl+Z / Ctrl+Y, interface figée)."""

    class Audited(cls):
        def Activated(self, *args):
            doc = FreeCAD.ActiveDocument
            before = doc_state(doc, derived=False) if doc is not None else None
            n0 = doc.UndoCount if doc is not None else 0
            from cam2027.gui import opeditor

            editors0 = len(opeditor._open_editors)
            stats["commands"] += 1
            with Heartbeat() as hb:
                result = cls.Activated(self, *args)
            if hb.worst > FREEZE_S:
                stats["freezes"].append((name, round(hb.worst, 2)))
                G.log("  B3 FREEZE %s: interface not refreshed for %.2f s" % (name, hb.worst))
            flush_live("%s done in %.1f s" % (name, hb.last - hb.first))
            if doc is not None and FreeCAD.ActiveDocument is doc:
                try:
                    audit_undo(_current(), name, doc, before, n0, editors0)
                except Exception:
                    G.problem(_current(), "B3 audit of %s crashed:\n%s" % (name, traceback.format_exc()))
                flush_live("%s audited" % name)
            return result

    Audited.__name__ = cls.__name__
    return Audited


def _current():
    """Scénario en cours (dernière ligne « == nom » du rapport)."""
    for line in reversed(G.lines):
        if line.startswith("== "):
            return line[3:]
    return "?"


# -- audit de la réouverture -----------------------------------------------------------------------------------

_real_close = None
_tmp = None


def _summary(proj):
    out = {}
    for op in proj.operations():
        rec = proj.registry.get(proj.base_operation(op).Name, {})
        out[op.Name] = (op.Label, rec.get("kind"), len(op.Path.Commands) if hasattr(op, "Path") else None)
    return out


def check_reopen(scenario, doc_name):
    """Enregistre, ferme et rouvre le projet ``doc_name`` : opérations, parcours, panneau, pages de tâches."""
    from cam2027.project.project import Project
    from cam2027.project import docobjects
    from cam2027.gui import panels

    doc = FreeCAD.getDocument(doc_name)
    if docobjects.find_info(doc) is None:
        return
    proj = Project.from_document(doc)
    if not proj.has_job or not proj.operations():
        return
    for ed in list(__import__("cam2027.gui.opeditor", fromlist=["x"])._open_editors):
        ed.on_close = None
        ed.done(0)
    before = _summary(proj)
    path = os.path.join(_tmp, "reopen-%s.FCStd" % doc_name)
    doc.saveAs(path)
    _real_close(doc.Name)
    G.pump(0.2)
    t0 = time.time()
    opening = _ConsoleErrors()
    try:
        doc = FreeCAD.openDocument(path)
    except Exception:
        G.problem(scenario, "B3 reopen: %s does not open again:\n%s" % (path, traceback.format_exc()))
        return
    FreeCADGui.ActiveDocument = FreeCADGui.getDocument(doc.Name)
    G.pump(0.5)
    proj = Project.from_document(doc)
    jvp = getattr(proj.job.ViewObject, "Proxy", None) if proj.has_job else None
    G.log("  B3 reopen: job view provider %s, attached %s" % (type(jvp).__name__, hasattr(jvp, "obj")))
    G.pump(0.5)  # la vue rapport reçoit ses lignes en différé : pas comptées pour le double-clic qui suit
    for err in opening.close():
        # écrites par FreeCAD pendant la relecture du job (fournisseur de vue pas encore attaché, voir
        # project.attach_job_view) : signalées, sans effet ensuite
        G.log("  B3 reopen: errors written while opening the project: %s" % err.splitlines()[-1].strip())
    after = _summary(proj)
    if after != before:
        G.problem(scenario, "B3 reopen: operations differ after reopening: %s / %s" % (
            sorted(set(before.items()) - set(after.items()))[:4], sorted(set(after.items()) - set(before.items()))[:4]))
    shown = panel_ops()
    if shown is not None and shown != [v[0] for v in after.values()] and shown != [o.Label for o in proj.operations()]:
        G.problem(scenario, "B3 reopen: Project panel shows %s instead of %s" % (shown, [o.Label for o in proj.operations()]))
    kinds = {}
    touched = [o.Label for o in doc.Objects if "Touched" in o.State]
    G.log("  B3 reopen: %d object(s) to recompute after opening: %s" % (len(touched), touched[:6]))
    for op in proj.operations():
        kind = before.get(op.Name, (None, "?"))[1]
        t1 = time.time()
        kinds[kind] = "%s %.1f s" % (tree_edit(scenario, proj, op, kind), time.time() - t1)
    G.log("  B3 reopen %s: %d operation(s) in %.1f s, task pages %s" % (doc_name, len(after), time.time() - t0, kinds))
    check_panel_edit(scenario, proj, before)
    try:
        proj.compute()
    except Exception as exc:
        G.problem(scenario, "B3 reopen: recompute after reopening failed: %s" % exc)
    again = _summary(proj)
    changed = {n: (before[n], again.get(n)) for n in before if before[n][2] and again.get(n) != before[n]}
    if changed:
        G.problem(scenario, "B3 reopen: toolpaths differ after recompute of the reopened project: %s" % list(changed.values())[:4])
    _real_close(doc.Name)
    G.pump(0.2)


def tree_edit(scenario, proj, op, kind, button="reject"):
    """Double-clic sur ``op`` dans l'arbre (page de tâches FreeCAD), puis Annuler (``reject``) ou OK
    (``accept``) : la page s'ouvre, se ferme, l'opération reste, aucune transaction ne reste ouverte."""
    doc = proj.doc
    gdoc = FreeCADGui.getDocument(doc.Name)
    vo = op.ViewObject
    proxy = getattr(vo, "Proxy", None) if vo is not None else None
    if proxy is None or not hasattr(proxy, "setEdit"):
        return "no task page"
    name, n_undo = op.Name, doc.UndoCount
    errors = []
    observer = _ConsoleErrors()
    FreeCADGui.Selection.clearSelection()
    gdoc.setEdit(name)  # ce que fait le double-clic (les exceptions vont à la vue rapport)
    G.pump(0.3)
    panel = getattr(proxy, "panel", None)
    touched = [o.Name for o in doc.Objects if "Touched" in o.State]
    if touched:
        G.log("  B3 task page of %s opened: to recompute %s" % (op.Label, touched[:6]))
    if not FreeCADGui.Control.activeDialog() or panel is None:
        errors.append("no task page")
    else:
        t_button = time.time()
        try:
            getattr(panel, button)()  # bouton Annuler / OK de la page
        except Exception as exc:
            errors.append("%s raised %s: %s" % (button, type(exc).__name__, exc))
        t_button = time.time() - t_button
        if button == "reject" and t_button > CANCEL_MAX_S:
            errors.append("interface frozen %.1f s by Cancel (nothing changed)" % t_button)
        G.pump(0.3)
        if FreeCADGui.Control.activeDialog():
            errors.append("task page still open after %s" % button)
    # remise en état pour la suite du scénario
    try:
        FreeCADGui.Control.closeDialog()
        gdoc.resetEdit()
    except Exception:
        pass
    if doc.HasPendingTransaction:
        errors.append("transaction left open")
        doc.abortTransaction()
    G.pump(0.2)
    if doc.getObject(name) is None:
        errors.append("operation DELETED by %s" % button)
    elif button == "reject" and doc.UndoCount != n_undo:
        errors.append("undo steps %d -> %d" % (n_undo, doc.UndoCount))
    errors += observer.close()
    if errors:
        G.problem(scenario, "B3 double-click on %s (%s) in the tree: %s" % (op.Label if doc.getObject(name) else name, kind, "; ".join(errors)))
        return "error"
    return "ok"


class _ConsoleErrors(object):
    """Erreurs écrites dans la vue rapport (exceptions des fournisseurs de vue de FreeCAD)."""

    def __init__(self):
        self.report = FreeCADGui.getMainWindow().findChild(QtWidgets.QTextEdit, "Report view")
        self.start = len(self.report.toPlainText()) if self.report is not None else 0

    def close(self):
        if self.report is None:
            return []
        text = self.report.toPlainText()[self.start:]
        lines = [l for l in text.splitlines() if "[scenarios]" not in l]
        if not any("Error" in l or "Traceback" in l for l in lines):
            return []
        start = next(i for i, l in enumerate(lines) if "Error" in l or "Traceback" in l)
        return ["report view:\n    " + "\n    ".join(l.rstrip()[:200] for l in lines[start:start + 14])]


def check_panel_edit(scenario, proj, kinds):
    """« Modifier » du panneau Projet sur chaque opération : un éditeur (ou le dialogue propre) s'ouvre, sans
    exception, avec la stratégie écrite en clair (pas l'identifiant interne)."""
    from cam2027.gui import opeditor
    from cam2027.project.operations import STRATEGIES

    p = G.panel()
    if p is None:
        return
    seen = {}
    for i in range(p.tree.topLevelItemCount()):
        item = p.tree.topLevelItem(i)
        op = proj.doc.getObject(item.data(0, QtCore.Qt.UserRole))
        kind = kinds.get(op.Name, (None, "?"))[1] if op is not None else "?"
        if kind in seen:
            continue
        p.tree.setCurrentItem(item)
        G.pump(0.1)
        n0 = len(opeditor._open_editors)
        dialogs0 = len(G.driver.dialogs)
        from cam2027.gui import commands

        saved = commands.exec_dialog  # dialogue propre (gravure enroulée...) : ouvert puis annulé
        commands.exec_dialog = lambda dlg: (G.driver.dialogs.append(dlg.windowTitle()), QtWidgets.QDialog.Rejected)[1]
        try:
            p.edit_selected()
        except Exception:
            G.problem(scenario, "B3 panel Edit on %s (%s) raised:\n%s" % (item.text(0), kind, traceback.format_exc()))
            continue
        finally:
            commands.exec_dialog = saved
        G.pump(0.2)
        editors = opeditor._open_editors[n0:]
        if editors:
            ed = editors[-1]
            labels = [l.text() for l in ed.findChildren(QtWidgets.QLabel) if l.text().startswith("<b>")]
            seen[kind] = labels[0] if labels else "?"
            if kind not in STRATEGIES and any(l == "<b>%s</b>" % kind for l in labels):
                G.problem(scenario, "B3 editor of %s shows the internal strategy name %r" % (item.text(0), kind))
            ed.on_close = None
            ed.done(0)
        elif len(G.driver.dialogs) > dialogs0:
            seen[kind] = "dialog %s" % G.driver.dialogs[-1]
        else:
            seen[kind] = "nothing"
            msgs = G.driver.take()
            if not msgs:
                G.problem(scenario, "B3 panel Edit on %s (%s) opens nothing" % (item.text(0), kind))
        G.pump(0.1)
    G.driver.take()
    G.log("  B3 panel Edit: %s" % seen)


def closing(name):
    """``FreeCAD.closeDocument`` des scénarios : réouverture vérifiée avant la vraie fermeture."""
    try:
        if os.environ.get("CAM2027_B3_AUDIT") and name in FreeCAD.listDocuments():
            check_reopen(_current(), name)
    except Exception:
        G.problem(_current(), "B3 reopen check of %s crashed:\n%s" % (name, traceback.format_exc()))
    flush_live("closing %s" % name)
    if name in FreeCAD.listDocuments():
        return _real_close(name)
    return None


class _ModalWatch(object):
    """Boîte de message de FreeCAD (C++, non pilotée par le pilote) ouverte plus de 3 s : texte relevé, puis
    « Non » (sinon la suite reste bloquée : question d'annulation sur plusieurs documents en 1.0)."""

    def __init__(self):
        self.seen = {}
        self.timer = QtCore.QTimer()
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.check)
        self.timer.start()

    def check(self):
        for w in QtWidgets.QApplication.topLevelWidgets():
            if isinstance(w, QtWidgets.QMessageBox) and w.isVisible():
                first = self.seen.setdefault(id(w), time.time())
                if time.time() - first > 3:
                    G.problem(_current(), "B3 FreeCAD message box %r left open: %s" % (w.windowTitle(), w.text()[:300]))
                    button = w.button(QtWidgets.QMessageBox.No) or w.button(QtWidgets.QMessageBox.Cancel) \
                        or w.button(QtWidgets.QMessageBox.Abort)
                    if button is not None:
                        button.click()
                    else:
                        w.reject()
                    self.seen.pop(id(w), None)


_watch = None
_layout_seen = set()


def check_layout(dlg):
    """Dialogue affiché par un scénario : texte de bouton, case ou libellé (sans retour à la ligne) plus large que
    son widget (texte coupé), ou mot anglais (texte non traduit). Une fois par titre de dialogue."""
    title = dlg.windowTitle()
    if title in _layout_seen:
        return
    _layout_seen.add(title)
    G.pump(0.1)
    cut, english = [], []
    for w in dlg.findChildren(QtWidgets.QWidget):
        if not w.isVisible():
            continue
        if isinstance(w, (QtWidgets.QPushButton, QtWidgets.QCheckBox, QtWidgets.QRadioButton)):
            text = w.text().replace("&", "")
        elif isinstance(w, QtWidgets.QLabel) and not w.wordWrap() and "<" not in w.text():
            text = w.text()
        else:
            continue
        if not text.strip():
            continue
        need = w.sizeHint().width()  # largeur que Qt demande pour tout afficher (case, icône, marges comprises)
        if need > w.width() + 4:  # 3 px de moins que demandé : texte encore entier à l'écran (captures vérifiées)
            cut.append("%r (%d > %d px)" % (text[:40], need, w.width()))
        low = " %s " % text.lower()
        if any(m in low for m in G.ENGLISH_MARKERS):
            english.append(text[:60])
    if cut:
        G.problem(_current(), "B3 dialog %r: text cut %s" % (title, cut[:4]))
    if english:
        G.problem(_current(), "B3 dialog %r: English text %s" % (title, english[:4]))


def install(gs, tmp):
    """Audit de toutes les commandes et de toutes les fermetures de projet (``CAM2027_B3_AUDIT=1``)."""
    global G, _real_close, _tmp, _watch
    G = gs
    _watch = _watch or _ModalWatch()
    # plantage de FreeCAD : le rapport n'est écrit qu'à la fin ; chaque ligne est aussi ajoutée à un journal, et
    # la pile Python de chaque fil est écrite par faulthandler
    import faulthandler

    trace = open(os.path.join(G.OUT, "gui_scenarios_trace.txt"), "w", encoding="utf-8")
    faulthandler.enable(trace, all_threads=True)
    plain_log = G.log

    def log(msg):
        plain_log(msg)
        trace.write(str(msg) + "\n")
        trace.flush()
    G.log = log
    if os.environ.get("CAM2027_B3_LAYOUT"):
        plain_exec = G.driver.exec_dialog

        def exec_dialog(dlg):
            dlg.show()
            try:
                check_layout(dlg)
            except Exception:
                G.problem(_current(), "B3 layout check crashed:\n%s" % traceback.format_exc())
            return plain_exec(dlg)
        G.driver.exec_dialog = exec_dialog
        from cam2027.gui import commands, panels

        for mod in (commands, panels):
            mod.exec_dialog = exec_dialog
    _tmp = tmp
    if not os.environ.get("CAM2027_B3_AUDIT"):
        return
    from cam2027.gui import commands

    commands.COMMANDS[:] = [(n, audited(c, n)) for n, c in commands.COMMANDS]
    _real_close = FreeCAD.closeDocument
    FreeCAD.closeDocument = closing
    G.log("B3 audit installed: Ctrl+Z / Ctrl+Y after each command, reopen before each close")


# -- scénarios B3 ------------------------------------------------------------------------------------------------


def _tray_project(scenario, files, name):
    proj = G.new_project(scenario, name)
    G.driver.open_files.append(files["step"])
    G.run_command(scenario, "CAM2027_ImportModel")
    G.run_command(scenario, "CAM2027_StockFixture")
    return G.project()


def _add(scenario, strategy):
    FreeCADGui.Selection.clearSelection()
    G.driver.handlers[G.tr("Add operation")] = lambda dlg: (G.combo_select(G.find_combo_with(dlg, strategy), strategy), True)[1]
    G.run_command(scenario, "CAM2027_AddOperation")
    G.accept_open_editors(scenario)


def _undo_step(scenario, label, doc, action):
    """``action()`` (un bouton du panneau, l'éditeur) : une étape, Ctrl+Z revient à l'état d'avant."""
    before = doc_state(doc, derived=False)
    n0 = doc.UndoCount
    action()
    G.pump(0.3)
    after = doc_state(doc, derived=False)
    steps = doc.UndoCount - n0
    if not state_diff(before, after):
        G.problem(scenario, "B3 %s changed nothing" % label)
        return
    if steps != 1:
        G.problem(scenario, "B3 %s: %d undo steps instead of one: %s" % (label, steps, doc.UndoNames[:max(steps, 0)]))
        if steps == 0:
            return
    for _i in range(steps):
        _gui_undo(doc)
    G.pump(0.3)
    diff = state_diff(before, doc_state(doc, derived=False))
    if diff:
        G.problem(scenario, "B3 %s: Ctrl+Z did not restore the project: %s" % (label, diff))
    shown, real = panel_ops(), project_ops(doc)
    if shown != real:
        G.problem(scenario, "B3 %s: Project panel shows %s after Ctrl+Z instead of %s" % (label, shown, real))
    for _i in range(steps):
        _gui_undo(doc, redo=True)
    G.pump(0.3)
    diff = state_diff(after, doc_state(doc, derived=False))
    if diff:
        G.problem(scenario, "B3 %s: Ctrl+Y did not restore the change: %s" % (label, diff))
    G.log("  B3 %s: undo / redo ok" % label)


def _select_row(index):
    p = G.panel()
    p.tree.setCurrentItem(p.tree.topLevelItem(index))
    G.pump(0.1)


def scenario_stock_undo(scenario, files):
    """Brut et montage puis Ajouter une opération : chacun une étape, Ctrl+Z remet le document exactement (sur 1.0,
    l'outil par défaut du job et chaque ToolBit faisaient leurs propres étapes et le brut restait)."""
    G.new_project(scenario, "B3 stock")
    G.driver.open_files.append(files["step"])
    G.run_command(scenario, "CAM2027_ImportModel")
    doc = G.project().doc
    _undo_step(scenario, "Stock & fixture", doc, lambda: G.run_command(scenario, "CAM2027_StockFixture"))
    G.driver.handlers[G.tr("Add operation")] = lambda dlg: (G.combo_select(G.find_combo_with(dlg, "profile"), "profile"), True)[1]

    def add():
        G.run_command(scenario, "CAM2027_AddOperation")
        from cam2027.gui import opeditor

        for ed in list(opeditor._open_editors):  # OK sans modification : pas d'étape de plus
            ed.accept()
    _undo_step(scenario, "Add operation", doc, add)
    FreeCAD.closeDocument(doc.Name)
    G.pump(0.3)


def scenario_panel_undo(scenario, files):
    """Boutons du panneau Projet (cocher, monter, descendre, dupliquer, supprimer) et éditeur : Ctrl+Z / Ctrl+Y."""
    from cam2027.gui import opeditor

    proj = _tray_project(scenario, files, "B3 panel")
    for strategy in ("profile", "pocket2d", "pocket"):
        _add(scenario, strategy)
    proj = G.project()
    doc = proj.doc
    p = G.panel()
    if p.tree.topLevelItemCount() != 3:
        G.problem(scenario, "3 operations expected in the panel, %d shown" % p.tree.topLevelItemCount())
        return
    _select_row(1)
    _undo_step(scenario, "panel Up", doc, lambda: p.buttons["up"].click())
    _select_row(0)
    _undo_step(scenario, "panel Down", doc, lambda: p.buttons["down"].click())
    _select_row(0)
    _undo_step(scenario, "panel Duplicate", doc, lambda: p.buttons["dup"].click())
    _select_row(0)
    _undo_step(scenario, "panel Delete", doc, lambda: p.buttons["del"].click())
    item = p.tree.topLevelItem(0)
    _undo_step(scenario, "panel check box", doc, lambda: item.setCheckState(
        0, QtCore.Qt.Unchecked if item.checkState(0) == QtCore.Qt.Checked else QtCore.Qt.Checked))
    _select_row(0)
    op = proj.base_operation(proj.operations()[0])

    def edit():
        ed = opeditor.open_editor(proj, op)
        G.pump(0.2)
        if os.environ.get("CAM2027_B3_LAYOUT"):
            for i in range(ed.tabs.count()):  # chaque onglet de l'éditeur
                ed.tabs.setCurrentIndex(i)
                _layout_seen.discard(ed.windowTitle())
                check_layout(ed)
            ed.tabs.setCurrentIndex(0)
        for n, (_k, w) in ed.widgets.items():
            if n == "StepDown" and isinstance(w, QtWidgets.QDoubleSpinBox):
                w.setValue(w.value() / 2 or 1.0)
        ed.accept()
        G.pump(0.2)
    _undo_step(scenario, "operation editor OK", doc, edit)
    FreeCAD.closeDocument(doc.Name)
    G.pump(0.3)


def scenario_long_session(scenario, files):
    """50 opérations ajoutées, modifiées, dupliquées, supprimées : mémoire, dialogues restants, temps du panneau."""
    from cam2027.gui import opeditor, panels

    proj = _tray_project(scenario, files, "B3 long")
    doc = proj.doc
    p = G.panel()
    import gc

    gc.collect()
    mem0 = memory_mb()
    dlg0 = len(live_dialogs())
    t_panel = []
    strategies = ("profile", "pocket2d", "pocket")
    for i in range(50):
        _add(scenario, strategies[i % len(strategies)])
        proj = G.project()
        n = p.tree.topLevelItemCount()
        if i % 5 == 1 and n:
            _select_row(n - 1)
            op = proj.base_operation(proj.operations()[-1])
            ed = opeditor.open_editor(proj, op)
            G.pump(0.1)
            ed.name.setText("B3 edited %d" % i)
            ed.accept()
            G.pump(0.1)
        if i % 5 == 2 and n:
            _select_row(n - 1)
            p.buttons["dup"].click()
            G.pump(0.1)
        if i % 5 == 3 and n > 1:
            _select_row(0)
            p.buttons["del"].click()
            G.pump(0.1)
        if i % 10 == 9:
            t0 = time.time()
            for _r in range(3):
                panels.refresh_project_panel()
            t_panel.append((p.tree.topLevelItemCount(), round((time.time() - t0) / 3, 3)))
            gc.collect()
            G.log("  B3 long session %d: %d ops, memory %.0f / %.0f MB, dialogs %d, panel %.3f s" % (
                i + 1, p.tree.topLevelItemCount(), memory_mb()[0], memory_mb()[1], len(live_dialogs()), t_panel[-1][1]))
    if os.environ.get("CAM2027_B3_PROFILE"):
        import cProfile
        import io
        import pstats

        prof = cProfile.Profile()
        prof.enable()
        for _r in range(10):
            panels.refresh_project_panel()
        prof.disable()
        out = io.StringIO()
        pstats.Stats(prof, stream=out).strip_dirs().sort_stats("cumulative").print_stats(14)
        G.log("  B3 profile of 10 panel refreshes (%d ops):\n%s" % (p.tree.topLevelItemCount(), out.getvalue()[-3500:]))
    t0 = time.time()
    for _r in range(10):
        panels.refresh_project_panel()
    G.log("  B3 panel refresh with %d operations: %.1f ms" % (p.tree.topLevelItemCount(), (time.time() - t0) * 100))
    from cam2027.project.operations import COMPUTE_STATES

    shown = [p.tree.topLevelItem(i).text(1) for i in range(p.tree.topLevelItemCount())]
    real = [G.tr(COMPUTE_STATES[proj.operation_state(o)][0]) for o in proj.operations()]
    if shown != real:
        G.problem(scenario, "B3 panel states %s differ from the project %s" % (shown[:5], real[:5]))
    G.log("  B3 panel states: %s" % sorted(set(shown)))
    gc.collect()
    mem1 = memory_mb()
    dlg1 = len(live_dialogs())
    G.log("  B3 long session: memory %.0f -> %.0f MB, live dialogs %d -> %d, panel times %s, undo steps %d" % (
        mem0[0], mem1[0], dlg0, dlg1, t_panel, doc.UndoCount))
    if dlg1 - dlg0 > 5:
        kinds = {}
        for d in live_dialogs():
            key = "%s %s" % (type(d).__name__, d.windowTitle()[:30])
            kinds[key] = kinds.get(key, 0) + 1
        G.problem(scenario, "B3 long session: %d dialogs still alive after closing them: %s" % (
            dlg1 - dlg0, sorted(kinds.items(), key=lambda kv: -kv[1])[:5]))
    t_undo = time.time()
    k = 0
    while doc.UndoCount and k < 20:
        _gui_undo(doc)
        k += 1
    G.log("  B3 long session: %d Ctrl+Z in %.1f s, %d operations left" % (k, time.time() - t_undo, len(project_ops(doc) or [])))
    shown, real = panel_ops(), project_ops(doc)
    if shown != real:
        G.problem(scenario, "B3 long session: Project panel shows %d operations after Ctrl+Z, project has %d" % (
            len(shown or []), len(real or [])))
    FreeCAD.closeDocument(doc.Name)
    G.pump(0.3)
    gc.collect()
    live_dialogs()
    G.log("  B3 long session: memory after closing the project %.0f MB (start %.0f MB)" % (memory_mb()[0], mem0[0]))


def scenario_reopen(scenario, files, tmp):
    """Chaque stratégie ajoutée sur toute la pièce, projet enregistré, fermé, rouvert « dans une nouvelle
    session » (pages de tâches des stratégies CAM2027 oubliées, comme au lancement) : double-clic sur chaque
    opération dans l'arbre = page de tâches FreeCAD ouverte, parcours identiques après recalcul."""
    import importlib
    from cam2027.project.operations import STRATEGIES
    from cam2027.gui import commands

    proj = _tray_project(scenario, files, "B3 reopen")
    for strategy in STRATEGIES:
        if strategy in HEAVY:
            continue
        _add(scenario, strategy)
        flush_live("%s added" % strategy)
    proj = G.project()
    kinds = sorted({proj.registry.get(proj.base_operation(o).Name, {}).get("kind") for o in proj.operations()})
    G.log("  B3 reopen: %d operations, kinds %s" % (len(proj.operations()), kinds))
    G.driver.take()
    name = proj.doc.Name
    proj.job.ViewObject.Proxy = 0  # projet enregistré avant que le job ait son fournisseur de vue (jour 3)
    # nouvelle session : les modules des stratégies CAM2027 n'ont pas encore servi à créer une opération
    for meta in STRATEGIES.values():
        if meta["module"].startswith("cam2027."):
            importlib.import_module(meta["module"]).__dict__.pop("TaskPanelOpPage", None)
    getattr(commands, "register_task_pages", lambda: None)()  # ce que fait le démarrage de l'atelier
    global _real_close, _tmp
    _real_close = _real_close or FreeCAD.closeDocument
    _tmp = _tmp or tmp
    check_reopen(scenario, name)


def scenario_tree_edit(scenario, files):
    """Même session : double-clic sur une opération dans l'arbre (page de tâches FreeCAD), Annuler puis OK."""
    proj = _tray_project(scenario, files, "B3 tree")
    for strategy in ("profile", "scallop"):
        _add(scenario, strategy)
    proj = G.project()
    states = {}
    for op in proj.operations():
        kind = proj.registry.get(op.Name, {}).get("kind")
        states[kind] = (tree_edit(scenario, proj, op, kind, "reject"),
                        tree_edit(scenario, proj, op, kind, "accept") if proj.doc.getObject(op.Name) else "-")
    G.log("  B3 tree double-click (Cancel, OK): %s" % states)
    G.pump(0.3)
    if panel_ops() != project_ops(proj.doc):
        G.problem(scenario, "B3 Project panel %s after the task pages, project %s" % (panel_ops(), project_ops(proj.doc)))
    FreeCAD.closeDocument(proj.doc.Name)
    G.pump(0.3)


def scenario_undo_redo_job(scenario, files):
    """Brut annulé puis rétabli (Ctrl+Z, Ctrl+Y), surfaçage ajouté, annulé, rétabli : le recalcul suivant donne le
    même parcours, et le double-clic sur l'opération ouvre et ferme sa page sans erreur."""
    proj = G.new_project(scenario, "B3 redo")
    G.driver.open_files.append(files["step"])
    G.run_command(scenario, "CAM2027_ImportModel")
    G.run_command(scenario, "CAM2027_StockFixture")
    doc = G.project().doc
    _gui_undo(doc)
    _gui_undo(doc, redo=True)
    proj = G.project()
    if not proj.has_job:
        G.problem(scenario, "B3 no job after Ctrl+Z, Ctrl+Y of Stock & fixture")
        return
    _add(scenario, "millface")
    proj = G.project()
    op = proj.operations()[0]
    ref = (round(op.OpStartDepth.Value, 3), len(op.Path.Commands))
    _gui_undo(doc)
    _gui_undo(doc, redo=True)
    op = proj.doc.getObject(op.Name)
    redone = (round(op.OpStartDepth.Value, 3), len(op.Path.Commands))
    op.touch()
    proj.compute()
    again = (round(op.OpStartDepth.Value, 3), len(op.Path.Commands))
    ref, again = ref[1:], again[1:]  # OpStartDepth : défaut recalculé par FreeCAD, seul le parcours compte
    G.log("  B3 facing (OpStartDepth, commands): added %s, after Ctrl+Y %s, recomputed %s" % (ref, redone, again))
    if again != ref:
        G.problem(scenario, "B3 facing recomputed after Ctrl+Z, Ctrl+Y differs: %s instead of %s" % (again, ref))
    kind = proj.registry.get(op.Name, {}).get("kind")
    G.log("  B3 tree double-click after Ctrl+Z / Ctrl+Y: %s" % tree_edit(scenario, proj, op, kind))
    FreeCAD.closeDocument(proj.doc.Name)
    G.pump(0.3)


def scenario_reopen_dome(scenario, tmp, undo_stock=False):
    """Dôme, finition à crête constante, enregistré, fermé, rouvert (sans l'audit) ; ``undo_stock`` : le brut est
    d'abord annulé puis rétabli (Ctrl+Z, Ctrl+Y)."""
    import Part

    V = FreeCAD.Vector
    dome = Part.makeSphere(25.0, V(30, 20, -15)).common(Part.makeBox(60, 40, 30, V(0, 0, 5)))
    path = os.path.join(tmp, "b3dome.step")
    Part.makeBox(60, 40, 5).fuse(dome).removeSplitter().exportStep(path)
    G.new_project(scenario, "B3 dome")
    G.driver.open_files.append(path)
    G.run_command(scenario, "CAM2027_ImportModel")
    G.run_command(scenario, "CAM2027_StockFixture")
    if undo_stock:
        doc = G.project().doc
        _gui_undo(doc)
        _gui_undo(doc, redo=True)
    _add(scenario, "scallop")
    global _real_close, _tmp
    _real_close = _real_close or FreeCAD.closeDocument
    _tmp = _tmp or tmp
    check_reopen(scenario, G.project().doc.Name)


def _panel_title():
    p = G.panel()
    return p.title.text() if p is not None else ""


def _activate_tab(doc):
    """Clic sur l'onglet du document dans la zone centrale."""
    area = FreeCADGui.getMainWindow().findChild(QtWidgets.QMdiArea)
    for sub in area.subWindowList():
        if sub.widget() is not None and sub.widget().windowTitle().startswith(doc.Label):
            area.setActiveSubWindow(sub)
            G.pump(0.4)
            return True
    return False


def scenario_doc_switch(scenario, files, tmp):
    """Deux projets ouverts : changer d'onglet, fermer l'un, rouvrir un fichier : le panneau Projet montre
    toujours le projet du document actif."""
    a = _tray_project(scenario, files, "B3 alpha")
    _add(scenario, "profile")
    a = G.project()
    a_doc = a.doc
    path = os.path.join(tmp, "b3-alpha.FCStd")
    a_doc.saveAs(path)
    b = _tray_project(scenario, files, "B3 beta")
    _add(scenario, "pocket2d")
    _add(scenario, "drilling")
    b = G.project()
    b_doc = b.doc
    checks = []

    def expect(when, doc):
        G.pump(0.3)
        title, ops = _panel_title(), panel_ops()
        real = project_ops(doc) if doc is not None else []
        ok = (doc is None and not ops) or (doc is not None and doc.Label in title and ops == real)
        checks.append((when, ok))
        if not ok:
            G.problem(scenario, "B3 %s: Project panel shows %r %s instead of %s %s" % (
                when, title[:60], ops, doc.Label if doc is not None else "no project", real))

    if not _activate_tab(a_doc):
        G.problem(scenario, "B3 no tab for %s" % a_doc.Label)
    expect("tab switch to alpha", a_doc)
    _activate_tab(b_doc)
    expect("tab switch to beta", b_doc)
    FreeCAD.closeDocument(a_doc.Name)
    G.pump(0.3)
    _activate_tab(b_doc)
    FreeCAD.closeDocument(b_doc.Name)
    expect("all projects closed", None)
    doc = FreeCAD.openDocument(path)
    expect("project file opened", doc)
    G.log("  B3 document switch: %s" % checks)
    FreeCAD.closeDocument(doc.Name)
    G.pump(0.3)


def entries(gs, files, tmp):
    """Scénarios B3 pour la boucle de ``gui_scenarios.main`` (et installation de l'audit si demandé)."""
    install(gs, tmp)

    def named(name, fn):
        def run():
            flush_live()
            try:
                fn()
            finally:
                flush_live("end of %s" % name)
        return name, run

    out = [named("b3-stock-undo", lambda: scenario_stock_undo("b3-stock-undo", files)),
           named("b3-reopen-dome", lambda: scenario_reopen_dome("b3-reopen-dome", tmp)),
           named("b3-reopen-dome-undo", lambda: scenario_reopen_dome("b3-reopen-dome-undo", tmp, True)),
           named("b3-undo-redo-job", lambda: scenario_undo_redo_job("b3-undo-redo-job", files)),
           named("b3-doc-switch", lambda: scenario_doc_switch("b3-doc-switch", files, tmp)),
           named("b3-tree-edit", lambda: scenario_tree_edit("b3-tree-edit", files)),
           named("b3-reopen", lambda: scenario_reopen("b3-reopen", files, tmp)),
           named("b3-panel-undo",lambda: scenario_panel_undo("b3-panel-undo", files)),
           named("b3-long-session", lambda: scenario_long_session("b3-long-session", files))]
    if os.environ.get("CAM2027_B3_AUDIT"):
        G.log("B3 audit: summary at the end of the report")
        out.append(named("b3-audit-summary", lambda: G.log("B3 audit: %d command(s), %d undo checked, freezes %s" % (
            stats["commands"], stats["undo_checked"], stats["freezes"]))))
    return out
