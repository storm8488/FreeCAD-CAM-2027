# SPDX-License-Identifier: LGPL-2.1-or-later
"""Scénarios d'utilisation pilotés comme un utilisateur (à lancer avec CAM2027.exe / FreeCAD.exe) :

    CAM2027.exe Mod\\CAM2027\\tests\\gui_scenarios.py

Chaque scénario appelle les **vraies commandes** de l'interface (``Activated``), remplit les dialogues
comme le ferait l'utilisateur (dialogues de fichier, saisie, boîtes modales, éditeur d'opération) et
relève : exceptions, messages d'avertissement, état du panneau Projet (étapes cochées), dock visible,
résultat attendu. Rapport : ``tests/screenshots/gui_scenarios.txt`` ; chaque écart est une ligne
``PROBLEM``, le rapport finit par ``OK`` seulement s'il n'y en a aucun.

Fichiers de l'utilisateur utilisés s'ils existent (variable ``CAM2027_SCENARIO_FILES`` : chemins séparés
par « ; ») ; sinon / en plus, des fichiers synthétiques (STL, STEP, SVG, PNG).
"""

import math
import os
import sys
import tempfile
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
if MOD not in sys.path:
    sys.path.insert(0, MOD)

import FreeCAD
import FreeCADGui
from PySide import QtCore, QtGui, QtWidgets

OUT = os.path.join(HERE, "screenshots")
LOG = os.path.join(OUT, "gui_scenarios.txt")
lines = []
problems = []


def log(msg):
    lines.append(str(msg))
    FreeCAD.Console.PrintMessage("[scenarios] %s\n" % msg)


def problem(scenario, msg):
    problems.append((scenario, msg))
    log("PROBLEM [%s] %s" % (scenario, msg))


def pump(seconds=0.3):
    end = time.time() + seconds
    while time.time() < end:
        QtWidgets.QApplication.processEvents()
        time.sleep(0.02)


# -- pilote : dialogues, fichiers, messages -----------------------------------------------------------------


class Driver(object):
    def __init__(self):
        self.messages = []  # (genre, texte)
        self.dialogs = []
        self.open_files = []
        self.save_files = []
        self.texts = []
        self.handlers = {}  # titre (traduit) -> fonction(dlg) -> True (accepter) / False (annuler)
        self.grabbed = set()

    def install(self):
        from cam2027.gui import commands, panels

        def warn(text):
            self.messages.append(("warn", text))

        def info(text):
            self.messages.append(("info", text))

        for mod in (commands, panels):
            mod._warn = warn
            mod._info = info
            mod.exec_dialog = self.exec_dialog
        def question(*a, **k):
            buttons = a[3] if len(a) > 3 else k.get("buttons", QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
            for b in (QtWidgets.QMessageBox.Discard, QtWidgets.QMessageBox.Yes, QtWidgets.QMessageBox.Ok):
                if buttons & b:
                    return b
            return QtWidgets.QMessageBox.Yes

        QtWidgets.QMessageBox.question = staticmethod(question)
        QtWidgets.QInputDialog.getText = staticmethod(
            lambda *a, **k: (self.texts.pop(0) if self.texts else "Scenario", True))
        QtWidgets.QFileDialog.getOpenFileName = staticmethod(
            lambda *a, **k: (self.open_files.pop(0) if self.open_files else "", ""))
        QtWidgets.QFileDialog.getSaveFileName = staticmethod(
            lambda *a, **k: (self.save_files.pop(0) if self.save_files else "", ""))

    def exec_dialog(self, dlg):
        title = dlg.windowTitle()
        self.dialogs.append(title)
        handler = self.handlers.pop(title, None)
        dlg.show()
        pump(0.1)
        if title not in self.grabbed:
            self.grabbed.add(title)
            safe = "".join(c if c.isalnum() else "_" for c in title)[:40]
            os.makedirs(os.path.join(OUT, "dialogs"), exist_ok=True)
            dlg.grab().save(os.path.join(OUT, "dialogs", "%02d_%s.png" % (len(self.grabbed), safe)))
        ok = True if handler is None else handler(dlg)
        if ok:
            dlg.accept()
            return QtWidgets.QDialog.Accepted
        dlg.reject()
        return QtWidgets.QDialog.Rejected

    def take(self):
        out, self.messages = self.messages, []
        return out


driver = Driver()


def tr(text, **kw):
    from cam2027.i18n import tr as _tr

    return _tr(text, **kw)


def run_command(scenario, name):
    """Lance la commande comme le bouton ; retourne les messages affichés (exception = PROBLEM)."""
    from cam2027.gui import commands

    cls = dict(commands.COMMANDS)[name]
    try:
        cls().Activated()
    except Exception:
        problem(scenario, "%s raised:\n%s" % (name, traceback.format_exc()))
    pump(0.2)
    msgs = driver.take()
    for kind, text in msgs:
        log("  %s %s: %s" % (name, kind, text.replace("\n", " | ")[:300]))
        english = [w for w in ENGLISH_MARKERS if w in " %s " % text.lower()]
        if english:
            problem(scenario, "%s shows English text %s: %s" % (name, english, text[:160]))
    return msgs


#: mots anglais qui ne doivent pas apparaître dans un message montré à un utilisateur français
ENGLISH_MARKERS = (" the ", " must ", " cannot ", " not found", " found ", " should ", " which ", " needs ",
                   " invalid shape", " mesh,", " only ", " failed:")


def panel():
    from cam2027.gui import panels

    dock = panels._docks.get("Project")
    return dock.widget() if dock is not None else None


def steps_done():
    p = panel()
    if p is None:
        return {}
    return {key: row[0].toolTip() == tr("done") for key, row in p.step_rows.items()}


def project():
    from cam2027.gui import state

    return state.active_project()


def combo_select(combo, data):
    i = combo.findData(data)
    if i < 0:
        raise ValueError("choix %r absent" % (data,))
    combo.setCurrentIndex(i)


def find_combo_with(dlg, data):
    for c in dlg.findChildren(QtWidgets.QComboBox):
        if c.findData(data) >= 0:
            return c
    raise ValueError("aucune liste ne propose %r" % (data,))


def accept_open_editors(scenario):
    from cam2027.gui import opeditor

    editors = list(opeditor._open_editors)
    for ed in editors:
        ed.accept()
        if ed.isVisible():
            problem(scenario, "operation editor did not close: %s" % ed.status.text())
            ed.done(0)
    pump(0.2)
    return len(editors)


def check_docks(scenario):
    pump(1.0)  # le rangement du panneau Tâches est périodique
    mw = FreeCADGui.getMainWindow()
    model = mw.findChild(QtWidgets.QDockWidget, "Model")
    tasks = mw.findChild(QtWidgets.QDockWidget, "Tasks")
    active = FreeCADGui.Control.activeDialog()
    vis = lambda d: d is not None and d.isVisible() and not d.visibleRegion().isEmpty()
    log("  docks: model %s, tasks %s, task dialog %s" % (vis(model), vis(tasks), active))
    if not active and vis(tasks) and not vis(model):
        problem(scenario, "empty Tasks panel shown instead of the model tree")


def new_project(scenario, name):
    driver.texts.append(name)
    run_command(scenario, "CAM2027_NewProject")
    proj = project()
    if proj is None:
        problem(scenario, "New project did not create an active project")
    return proj


# -- fichiers d'essai synthétiques ---------------------------------------------------------------------------


def make_files(tmp):
    import Part
    import Mesh

    V = FreeCAD.Vector
    tray = Part.makeBox(90, 60, 12)
    for i in range(3):
        for j in range(2):
            tray = tray.cut(Part.makeBox(24, 22, 8, V(6 + i * 28, 6 + j * 26, 4)))
    step = os.path.join(tmp, "tray.step")
    tray.exportStep(step)
    stl = os.path.join(tmp, "tray.stl")
    pts, tris = tray.tessellate(0.05)
    Mesh.Mesh([[pts[a], pts[b], pts[c]] for a, b, c in tris]).write(stl)
    svg = os.path.join(tmp, "sign.svg")
    with open(svg, "w", encoding="utf-8") as fp:
        fp.write('<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" width="120mm" height="80mm" '
                 'viewBox="0 0 120 80"><rect x="10" y="10" width="60" height="30" fill="none" stroke="black"/>'
                 '<circle cx="95" cy="25" r="14" fill="none" stroke="black"/>'
                 '<path d="M 10 60 L 70 60 L 40 72 Z" fill="none" stroke="black"/></svg>')
    png = os.path.join(tmp, "relief.png")
    img = QtGui.QImage(100, 60, QtGui.QImage.Format_RGB32)
    for y in range(60):
        for x in range(100):
            v = int(255 * math.exp(-((x - 50) ** 2 + (y - 30) ** 2) / 400.0))
            img.setPixel(x, y, QtGui.qRgb(v, v, v))
    img.save(png)
    return {"step": step, "stl": stl, "svg": svg, "png": png}


# -- scénarios ---------------------------------------------------------------------------------------------------


def scenario_solid(scenario, path, tmp, strategy="profile"):
    """Projet -> import -> brut -> opération (toute la pièce) -> recalcul -> contrôle -> simulation -> export."""
    proj = new_project(scenario, "S %s" % os.path.splitext(os.path.basename(path))[0][:20])
    if proj is None:
        return
    t0 = time.time()
    driver.open_files.append(path)
    run_command(scenario, "CAM2027_ImportModel")
    log("  import %.1f s, objects %s" % (time.time() - t0, [o.Label for o in proj.doc.Objects][:8]))
    if not steps_done().get("model"):
        problem(scenario, "step 1 (part) not checked after importing %s" % os.path.basename(path))
    check_docks(scenario)
    run_command(scenario, "CAM2027_StockFixture")
    proj = project()
    if not proj.has_job:
        problem(scenario, "Stock & fixture did not create the job")
        return
    if not steps_done().get("stock"):
        problem(scenario, "step 2 (stock) not checked")
    if proj.surface_models() and strategy not in ("surface3d", "waterline"):
        # surface 3D issue d'un gros maillage : seules les finitions 3D l'usinent (les autres sont refusées
        # avec un message, vérifié dans test_ui_logic)
        log("  3D surface from a mesh: %s replaced by surface3d" % strategy)
        strategy = "surface3d"
    FreeCADGui.Selection.clearSelection()
    driver.handlers[tr("Add operation")] = lambda dlg: (combo_select(find_combo_with(dlg, strategy), strategy), True)[1]
    run_command(scenario, "CAM2027_AddOperation")
    n_ed = accept_open_editors(scenario)
    proj = project()
    if n_ed == 0 or not proj.operations():
        problem(scenario, "Add operation (%s, whole part) created no operation" % strategy)
        return
    run_command(scenario, "CAM2027_Compute")
    states = [proj.operation_state(o) for o in proj.operations()]
    log("  operations %s states %s" % ([o.Label for o in proj.operations()], states))
    if any(o.Label.startswith(tr("Operation")) for o in proj.operations()):
        problem(scenario, "operations keep the generic name %r" % tr("Operation"))
    if any(s in ("failed", "todo") for s in states):
        problem(scenario, "operation states after compute: %s" % states)
    if not steps_done().get("ops"):
        problem(scenario, "step 3 (operations) not checked")
    msgs = run_command(scenario, "CAM2027_MaterialCheck")
    if not any(k == "info" and tr("Removed: {v} cm3", v="").split("{")[0][:6] in t for k, t in msgs):
        problem(scenario, "material check showed no report")
    out = os.path.join(tmp, "%s.nc" % scenario)
    driver.handlers[tr("Export G-code")] = lambda dlg: _export(dlg, out)
    msgs = run_command(scenario, "CAM2027_Export")
    blocked = [t for k, t in msgs if k == "warn" and t.startswith(tr("Export blocked by the checks: {errors}", errors="")[:12])]
    if not os.path.isfile(out) and not blocked:
        problem(scenario, "export wrote no G-code file and gave no reason")
    elif blocked:
        log("  export blocked (expected when the checks find an error): %s" % blocked[0][:200])
    check_docks(scenario)
    FreeCAD.closeDocument(proj.doc.Name)
    pump(0.3)


def _export(dlg, out):
    edits = [e for e in dlg.findChildren(QtWidgets.QLineEdit) if e.text().endswith(".nc")]
    if edits:
        edits[0].setText(out)
    for b in dlg.findChildren(QtWidgets.QPushButton):
        if b.text() == tr("Export G-code"):
            b.click()
            pump(0.5)
            break
    return True


def scenario_simulator(scenario, path):
    proj = new_project(scenario, "Sim")
    driver.open_files.append(path)
    run_command(scenario, "CAM2027_ImportModel")
    run_command(scenario, "CAM2027_StockFixture")
    driver.handlers[tr("Add operation")] = lambda dlg: True
    run_command(scenario, "CAM2027_AddOperation")
    accept_open_editors(scenario)
    run_command(scenario, "CAM2027_Simulate")
    pump(2.0)
    check_docks(scenario)
    windows = [w for w in QtGui.QGuiApplication.topLevelWindows() if w.isVisible() and w.title().endswith(tr("CAM Simulator")[-4:])]
    log("  simulator windows: %s" % [w.title() for w in QtGui.QGuiApplication.topLevelWindows() if w.isVisible()])
    FreeCADGui.Control.closeDialog()
    pump(0.5)
    for w in QtGui.QGuiApplication.topLevelWindows():
        if w.isVisible() and int(w.winId()) != int(FreeCADGui.getMainWindow().winId()) and "CAM" in w.title() \
                and w.title() != FreeCADGui.getMainWindow().windowTitle():
            w.close()
    pump(0.3)
    check_docks(scenario)
    FreeCAD.closeDocument(proj.doc.Name)
    pump(0.3)


def scenario_sheet(scenario, files, tmp):
    """Flux 2D : SVG -> imbrication -> panneau -> contour sur un vecteur sélectionné -> poche -> V-carving + fond plat."""
    proj = new_project(scenario, "Sign")
    driver.open_files.append(files["svg"])
    run_command(scenario, "CAM2027_ImportModel")
    if not steps_done().get("model"):
        problem(scenario, "step 1 not checked after importing an SVG drawing")
    driver.handlers[tr("Nest parts on a sheet")] = lambda dlg: True
    run_command(scenario, "CAM2027_Nest")

    def sheet(dlg):
        combo_select(find_combo_with(dlg, "sheet"), "sheet")
        return True

    driver.handlers[tr("Stock & fixture")] = sheet
    run_command(scenario, "CAM2027_StockFixture")
    proj = project()
    if not proj.has_job:
        problem(scenario, "sheet job not created")
        return
    from cam2027.project import sheet as sheetmod

    vectors = sheetmod.vector_objects(proj.doc)
    rect = [v for v in vectors if len(v.Shape.Edges) == 4]
    if not rect:
        problem(scenario, "rectangle vector not found")
        return
    for strategy in ("profile", "pocket2d", "vcarve", "engrave"):
        FreeCADGui.Selection.clearSelection()
        FreeCADGui.Selection.addSelection(rect[0])
        driver.handlers[tr("Add operation")] = lambda dlg, s=strategy: (combo_select(find_combo_with(dlg, s), s), True)[1]
        run_command(scenario, "CAM2027_AddOperation")
        accept_open_editors(scenario)
    proj = project()
    log("  operations: %s" % [(o.Label, proj.operation_state(o)) for o in proj.operations()])
    vc = [o for o in proj.operations() if proj.registry.get(proj.base_operation(o).Name, {}).get("kind") == "vcarve"]
    if vc:
        FreeCADGui.Selection.clearSelection()
        FreeCADGui.Selection.addSelection(vc[0])
        driver.handlers[tr("Flat depth clearing")] = lambda dlg: True
        run_command(scenario, "CAM2027_FlatDepth")
    run_command(scenario, "CAM2027_Compute")
    proj = project()
    states = [(o.Label, proj.operation_state(o)) for o in proj.operations()]
    log("  states: %s" % states)
    for label, st in states:
        if st in ("failed", "todo"):
            problem(scenario, "operation %s is %s" % (label, st))
    out = os.path.join(tmp, "sign.nc")
    driver.handlers[tr("Export G-code")] = lambda dlg: _export(dlg, out)
    run_command(scenario, "CAM2027_Export")
    if not os.path.isfile(out):
        problem(scenario, "sheet export wrote no file")
    FreeCAD.closeDocument(proj.doc.Name)
    pump(0.3)


def scenario_relief(scenario, files):
    proj = new_project(scenario, "Relief")
    driver.open_files.append(files["png"])
    run_command(scenario, "CAM2027_ImportModel")
    proj = project()
    if not steps_done().get("model"):
        problem(scenario, "step 1 not checked after a relief from image")
    run_command(scenario, "CAM2027_StockFixture")
    driver.handlers[tr("Add operation")] = lambda dlg: (combo_select(find_combo_with(dlg, "surface3d"), "surface3d"), True)[1]
    run_command(scenario, "CAM2027_AddOperation")
    accept_open_editors(scenario)
    run_command(scenario, "CAM2027_Compute")
    proj = project()
    log("  relief states: %s" % [(o.Label, proj.operation_state(o)) for o in proj.operations()])
    if not proj.operations() or any(proj.operation_state(o) in ("failed", "todo") for o in proj.operations()):
        problem(scenario, "relief finishing not computed")
    FreeCAD.closeDocument(proj.doc.Name)
    pump(0.3)


def scenario_panel_actions(scenario, files):
    """Boutons du panneau : modifier, dupliquer, monter, descendre, désactiver, supprimer."""
    proj = new_project(scenario, "Panel")
    driver.open_files.append(files["step"])
    run_command(scenario, "CAM2027_ImportModel")
    run_command(scenario, "CAM2027_StockFixture")
    for _i in range(2):
        driver.handlers[tr("Add operation")] = lambda dlg: True
        run_command(scenario, "CAM2027_AddOperation")
        accept_open_editors(scenario)
    p = panel()
    proj = project()
    if p.tree.topLevelItemCount() != len(proj.operations()):
        problem(scenario, "panel lists %d rows for %d operations" % (p.tree.topLevelItemCount(), len(proj.operations())))
    for action in ("duplicate_selected", "move_selected", "edit_selected", "delete_selected"):
        if not hasattr(p, action):
            continue
        p.tree.setCurrentItem(p.tree.topLevelItem(0))
        before = len(project().operations())
        try:
            if action == "move_selected":
                p.move_selected(1)
            else:
                getattr(p, action)()
        except Exception:
            problem(scenario, "panel %s raised:\n%s" % (action, traceback.format_exc()))
        accept_open_editors(scenario)
        pump(0.2)
        log("  %s: %d -> %d operations, messages %s" % (action, before, len(project().operations()), driver.take()))
    FreeCAD.closeDocument(proj.doc.Name)
    pump(0.3)


def scenario_import_without_project(scenario, path):
    """Importer sans avoir créé de projet : le projet est créé au nom du fichier."""
    for doc in list(FreeCAD.listDocuments()):
        FreeCAD.closeDocument(doc)
    pump(0.3)
    driver.open_files.append(path)
    run_command(scenario, "CAM2027_ImportModel")
    proj = project()
    if proj is None:
        problem(scenario, "Import without a project did not create one")
        return
    log("  project %s, steps %s" % (proj.doc.Label, steps_done()))
    if not steps_done().get("model"):
        problem(scenario, "step 1 not checked after import without a project")
    FreeCAD.closeDocument(proj.doc.Name)
    pump(0.3)


def scenario_tool_library(scenario, tmp):
    """Toutes les actions du panneau Bibliothèque d'outils (profil temporaire : la vraie bibliothèque n'est
    jamais touchée)."""
    from cam2027.gui import panels, state

    dock = panels.show_tool_library()
    p = dock.widget()
    lib = state.library()
    n0 = len(lib.tools)

    def select_row(row=0):
        p.table.clearSelection()
        p.table.selectRow(row)
        pump(0.1)

    for action in ("new_tool", "apply_tool", "duplicate_tool", "toggle_favorite", "new_preset", "apply_preset",
                   "duplicate_preset", "delete_preset", "new_assembly", "apply_assembly", "delete_assembly",
                   "update_preview", "save_library"):
        select_row(0)
        try:
            getattr(p, action)()
        except Exception:
            problem(scenario, "tool library %s raised:\n%s" % (action, traceback.format_exc()))
        pump(0.1)
        for kind, text in driver.take():
            log("  %s %s: %s" % (action, kind, text[:200]))
    log("  tools %d -> %d" % (n0, len(lib.tools)))
    if len(lib.tools) < n0 + 2:
        problem(scenario, "new_tool + duplicate_tool did not add 2 tools (%d -> %d)" % (n0, len(lib.tools)))
    p.search.setText("6 mm")
    pump(0.2)
    if p.table.rowCount() == 0:
        problem(scenario, "search '6 mm' lists nothing")
    p.search.setText("")
    for i in range(p.type_filter.count()):
        p.type_filter.setCurrentIndex(i)
        pump(0.02)
    p.type_filter.setCurrentIndex(0)
    p.fav_only.setChecked(True)
    pump(0.1)
    p.fav_only.setChecked(False)
    out = os.path.join(tmp, "export.cam2027tools")
    driver.save_files.append(out)
    try:
        p.export_library()
    except Exception:
        problem(scenario, "export_library raised:\n%s" % traceback.format_exc())
    if not os.path.isfile(out):
        problem(scenario, "library export wrote no file")
    else:
        driver.open_files.append(out)
        try:
            p.import_library()
        except Exception:
            problem(scenario, "import_library raised:\n%s" % traceback.format_exc())
    # supprimer l'outil dupliqué (sélection = la dernière ligne ajoutée)
    p.search.setText(tr("New tool"))
    pump(0.2)
    if p.table.rowCount():
        select_row(0)
        p.delete_tool()
    log("  messages: %s" % [t[:120] for _k, t in driver.take()])
    dock.hide()


def scenario_editor(scenario, files):
    """Éditeur d'opération : changer une passe, appliquer, changer d'outil compatible, annuler sans perte."""
    from cam2027.gui import opeditor

    proj = new_project(scenario, "Editor")
    driver.open_files.append(files["step"])
    run_command(scenario, "CAM2027_ImportModel")
    run_command(scenario, "CAM2027_StockFixture")
    driver.handlers[tr("Add operation")] = lambda dlg: True
    run_command(scenario, "CAM2027_AddOperation")
    accept_open_editors(scenario)
    proj = project()
    op = proj.operations()[0]
    ed = opeditor.open_editor(proj, proj.base_operation(op))
    pump(0.3)
    ed.grab().save(os.path.join(OUT, "dialogs", "editor.png"))
    spins = [(n, w) for n, (k, w) in ed.widgets.items() if isinstance(w, QtWidgets.QDoubleSpinBox) and n == "StepDown"]
    if not spins:
        problem(scenario, "editor has no StepDown field")
    else:
        spins[0][1].setValue(2.5)
        if not ed.apply():
            problem(scenario, "editor apply failed: %s" % ed.status.text())
        if abs(float(proj.base_operation(op).StepDown.getValueAs("mm")) - 2.5) > 1e-6:
            problem(scenario, "StepDown not applied")
    # changement d'outil comme un utilisateur : « Sélectionner… » puis un autre outil compatible
    from cam2027.gui import toolpicker

    field = ed.asm_combo
    current = field.tool()
    others = [t for t, _l in toolpicker._all_tools(proj) if field.fits(t) and (current is None or t.id != current.id)]
    if others:
        def pick(dlg):
            if isinstance(dlg, toolpicker.ToolPickerDialog):
                dlg.refresh(select=others[0].id)
                dlg.show()
                pump(0.1)
                dlg.accept()
                return QtWidgets.QDialog.Accepted
            return QtWidgets.QDialog.Rejected
        saved = toolpicker.exec_dialog
        toolpicker.exec_dialog = pick
        try:
            field.select()
        finally:
            toolpicker.exec_dialog = saved
        if field.tool() is None or field.tool().id != others[0].id:
            problem(scenario, "tool picker did not change the tool")
        if not ed.apply():
            problem(scenario, "editor tool change failed: %s" % ed.status.text())
    spins and spins[0][1].setValue(1.5)
    ed.reject()  # modification non appliquée : la question est acceptée (Abandonner) par le pilote
    pump(0.2)
    if ed.isVisible():
        problem(scenario, "editor still open after reject")
    log("  editor ok, op state %s, messages %s" % (proj.operation_state(op), driver.take()))
    FreeCAD.closeDocument(proj.doc.Name)
    pump(0.3)


def scenario_machine_and_wrap(scenario, files):
    """Profil machine (axe A renseigné dans le dialogue), brut rond, gravure enroulée, incrustation refusée sans dessin."""
    proj = new_project(scenario, "Rotary")
    import Part

    rstep = os.path.join(os.path.dirname(files["step"]), "round.step")
    Part.makeCylinder(20, 80, FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(1, 0, 0)).exportStep(rstep)
    driver.open_files.append(rstep)
    run_command(scenario, "CAM2027_ImportModel")

    def machine(dlg):
        checks = [c for c in dlg.findChildren(QtWidgets.QCheckBox) if c.text() == tr("Rotary axis A present (about X)")]
        if not checks:
            problem(scenario, "machine dialog: no 'A axis present' checkbox")
            return True
        checks[0].setChecked(True)
        for combo in dlg.findChildren(QtWidgets.QComboBox):
            i = combo.findData("right_hand")
            if i >= 0:
                combo.setCurrentIndex(i)
        box = dlg.findChildren(QtWidgets.QGroupBox)[0]
        for edit, value in zip(box.findChildren(QtWidgets.QLineEdit), ("0", "0", "-720", "720", "3600")):
            edit.setText(value)
        return True

    def machine_bad(dlg):
        box = dlg.findChildren(QtWidgets.QGroupBox)[0]
        box.findChildren(QtWidgets.QLineEdit)[0].setText("abc")
        return True

    driver.handlers[tr("Machine profile")] = machine_bad
    msgs = run_command(scenario, "CAM2027_Machine")
    if not any("abc" in t for _k, t in msgs):
        problem(scenario, "invalid machine value not reported with the field: %s" % msgs)

    driver.handlers[tr("Machine profile")] = machine
    run_command(scenario, "CAM2027_Machine")
    rot = project().machine.rotary
    log("  rotary present %s centre %s direction %s range %s..%s" % (rot.present, rot.center_offset_mm,
                                                                     rot.positive_direction, rot.min_deg, rot.max_deg))

    def round_bar(dlg):
        combo_select(find_combo_with(dlg, "cylinder_x"), "cylinder_x")
        return True

    driver.handlers[tr("Stock & fixture")] = round_bar
    run_command(scenario, "CAM2027_StockFixture")
    proj = project()
    if not proj.has_job:
        problem(scenario, "round bar job not created (A centre: %s)" % (rot.center_offset_mm,))
        FreeCAD.closeDocument(proj.doc.Name)
        return
    import Part as _P

    circ = 2 * math.pi * 20
    V = FreeCAD.Vector
    dr = proj.doc.addObject("Part::Feature", "Unrolled")
    dr.Shape = _P.makePolygon([V(10, 5, 0), V(60, 5, 0), V(60, circ - 5, 0), V(10, circ - 5, 0), V(10, 5, 0)])
    proj.doc.recompute()
    FreeCADGui.Selection.clearSelection()
    FreeCADGui.Selection.addSelection(dr)
    driver.handlers[tr("Wrapped engraving (continuous A axis)")] = lambda dlg: True
    run_command(scenario, "CAM2027_WrapEngrave")
    proj = project()
    if not proj.wrapped_operations():
        problem(scenario, "wrapped engraving not created")
    run_command(scenario, "CAM2027_Inlay")
    FreeCAD.closeDocument(proj.doc.Name)
    pump(0.3)


def scenario_inlay(scenario, files):
    proj = new_project(scenario, "InlayCmd")
    driver.open_files.append(files["svg"])
    run_command(scenario, "CAM2027_ImportModel")
    driver.handlers[tr("Stock & fixture")] = lambda dlg: (combo_select(find_combo_with(dlg, "sheet"), "sheet"), True)[1]
    run_command(scenario, "CAM2027_StockFixture")
    from cam2027.project import sheet as sheetmod

    rect = [v for v in sheetmod.vector_objects(project().doc) if len(v.Shape.Edges) == 4]
    FreeCADGui.Selection.clearSelection()
    FreeCADGui.Selection.addSelection(rect[0])
    before = set(FreeCAD.listDocuments())
    driver.handlers[tr("V inlay (male / female)")] = lambda dlg: True
    msgs = run_command(scenario, "CAM2027_Inlay")
    new_docs = set(FreeCAD.listDocuments()) - before
    if not new_docs:
        problem(scenario, "inlay created no male project")
    proj = project()
    if proj.doc.Label != "InlayCmd":
        problem(scenario, "after the inlay the active project is %s, not the female project" % proj.doc.Label)
    from cam2027.project.project import Project

    for doc_name in [proj.doc.Name] + list(new_docs):
        p = Project.from_document(FreeCAD.getDocument(doc_name))
        states = [(o.Label, p.operation_state(o)) for o in p.operations()]
        log("  %s ops %s" % (p.doc.Label, states))
        for label, st in states:
            if st in ("failed", "todo"):
                problem(scenario, "%s: operation %s is %s" % (p.doc.Label, label, st))
    for name in list(FreeCAD.listDocuments()):
        FreeCAD.closeDocument(name)
    pump(0.3)


def scenario_import_twice(scenario, path):
    """Le plantage signalé : le même fichier importé deux fois, puis « Brut et montage »."""
    proj = new_project(scenario, "Twice")
    for _i in range(2):
        driver.open_files.append(path)
        run_command(scenario, "CAM2027_ImportModel")
    run_command(scenario, "CAM2027_StockFixture")
    proj = project()
    if not proj.has_job:
        problem(scenario, "no job after importing the same file twice")
    else:
        log("  stock %s" % {k: round(v, 2) for k, v in proj.stock_bounds().items() if k in ("length", "width", "height")})
    FreeCAD.closeDocument(proj.doc.Name)
    pump(0.3)


def scenario_ui_commands(scenario):
    """Commandes sans projet et commandes d'interface : aucune exception, messages compréhensibles."""
    for name in ("CAM2027_StockFixture", "CAM2027_AddOperation", "CAM2027_Compute", "CAM2027_Export",
                 "CAM2027_Simulate", "CAM2027_MaterialCheck", "CAM2027_ImportModel", "CAM2027_FlatDepth",
                 "CAM2027_Inlay", "CAM2027_Nest", "CAM2027_WrapEngrave"):
        msgs = run_command(scenario, name)
        if not msgs and name not in ("CAM2027_ImportModel",):
            problem(scenario, "%s without a project: no message at all" % name)
    for name in ("CAM2027_Theme", "CAM2027_Theme", "CAM2027_Theme", "CAM2027_AdvancedMode", "CAM2027_AdvancedMode",
                 "CAM2027_ResetLayout", "CAM2027_ToolLibrary", "CAM2027_About"):
        run_command(scenario, name)
    driver.handlers[tr("Machine profile")] = lambda dlg: True
    run_command(scenario, "CAM2027_Machine")
    check_docks(scenario)


def _s1_scenarios(files, tmp):
    """Scénarios du flux S1 (reprise de matière, zone, finitions des plats et des angles) : ``gui_scenarios_s1``."""
    import types
    from tests import gui_scenarios_s1

    return gui_scenarios_s1.scenarios(types.SimpleNamespace(**globals()), files, tmp)


def main():
    os.makedirs(os.path.join(OUT, "dialogs"), exist_ok=True)
    driver.install()
    FreeCADGui.activateWorkbench("CAM2027Workbench")
    pump(1.0)
    tmp = tempfile.mkdtemp(prefix="cam2027-scen-")
    files = make_files(tmp)
    user = [p for p in os.environ.get("CAM2027_SCENARIO_FILES", "").split(";") if p and os.path.isfile(p)]
    log("application %s, user files %s" % (FreeCAD.ConfigGet("ExeName"), user))
    for name, fn in (
            ("ui-without-project", lambda: scenario_ui_commands("ui-without-project")),
            ("step-tray", lambda: scenario_solid("step-tray", files["step"], tmp)),
            ("stl-tray", lambda: scenario_solid("stl-tray", files["stl"], tmp)),
            ("pocket-step", lambda: scenario_solid("pocket-step", files["step"], tmp, "adaptive")),
            ("pocket-stl", lambda: scenario_solid("pocket-stl", files["stl"], tmp, "pocket")),
            ("facing-step", lambda: scenario_solid("facing-step", files["step"], tmp, "millface")),
            ("import-without-project", lambda: scenario_import_without_project("import-without-project", files["stl"])),
            ("sheet-svg", lambda: scenario_sheet("sheet-svg", files, tmp)),
            ("relief-png", lambda: scenario_relief("relief-png", files)),
            ("panel-actions", lambda: scenario_panel_actions("panel-actions", files)),
            ("simulator", lambda: scenario_simulator("simulator", files["step"])),
            ("tool-library", lambda: scenario_tool_library("tool-library", tmp)),
            ("editor", lambda: scenario_editor("editor", files)),
            ("machine-wrap", lambda: scenario_machine_and_wrap("machine-wrap", files)),
            ("inlay", lambda: scenario_inlay("inlay", files)),
            ("import-twice", lambda: scenario_import_twice("import-twice", next(
                (p for p in user if p.lower().endswith((".step", ".stp"))), files["step"]))),
    ) + _s1_scenarios(files, tmp) + tuple(("user-%d" % i, (lambda p=p, i=i: scenario_solid("user-%d %s" % (i, os.path.basename(p)), p, tmp)))
              for i, p in enumerate(user)) \
            + tuple(("user-pocket-%d" % i, (lambda p=p, i=i: scenario_solid("user-pocket-%d %s" % (i, os.path.basename(p)),
                                                                            p, tmp, "adaptive")))
                    for i, p in enumerate(user) if p.lower().endswith(".stl")) \
            + __import__("tests.gui_scenarios_s2", fromlist=["*"]).scenarios(globals(), files, tmp):
        if os.environ.get("CAM2027_SCENARIO_ONLY") and not name.startswith(os.environ["CAM2027_SCENARIO_ONLY"]):
            continue
        log("== %s" % name)
        try:
            fn()
        except Exception:
            problem(name, "scenario crashed:\n%s" % traceback.format_exc())
        for doc in list(FreeCAD.listDocuments()):
            try:
                FreeCAD.closeDocument(doc)
            except Exception:
                pass
        pump(0.3)
    log("dialogs seen: %s" % sorted(set(driver.dialogs)))
    log("%d problem(s)" % len(problems))
    log("OK" if not problems else "FAILED")


try:
    main()
except Exception:
    log("FAILED\n" + traceback.format_exc())
finally:
    with open(LOG, "w", encoding="utf-8") as fp:
        fp.write("\n".join(lines) + "\n")
    QtCore.QTimer.singleShot(500, lambda: QtWidgets.QApplication.instance().quit())
