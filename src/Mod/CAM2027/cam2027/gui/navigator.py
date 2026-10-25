# SPDX-License-Identifier: LGPL-2.1-or-later
"""Navigateur métier (dock de gauche) : compact et adapté à l'espace courant.

* Préparer : pièce, brut, origine et repère, machine et postprocesseur, montage (brides, zones interdites,
  recto-verso, axe A), chaque ligne avec son état et son action ; face active d'un projet recto-verso.
* Dessiner : vecteurs du dessin ; outils groupés par intention (créer, modifier, aligner / répartir,
  organiser) ; vues Dessus / 3D.
* Usiner : opérations dans l'ordre de fabrication (inclusion, affichage, nom, outil, état, durée) ; ajouter,
  modifier, dupliquer, supprimer, déplacer ; fonctions spécialisées dans un menu.
* Vérifier et exporter : parcours calculés, simulation, contrôle matière, export, fiche ; problèmes à consulter.

Le résumé compact du projet (brut, repère, référence Z, machine) est en tête dans tous les espaces et ouvre
les mêmes réglages que Préparer. Tout est lu sur le document (``state.active_project``), jamais maintenu à part.
"""

import FreeCAD
import FreeCADGui

from .qt import QtCore, QtGui, QtWidgets
from ..i18n import tr, tr_msg
from ..tools import bridge
from ..project import undo
from . import state, theme

_STATE_ICONS = {"inactive": "visibility", "todo": "calculate", "stale": "recalculate", "failed": "error",
                "warning": "warning", "computed": "check"}
#: colonnes de la liste des opérations
COL_NAME, COL_STATE, COL_TOOL, COL_TIME, COL_SHOW = range(5)


def _warn(text):
    QtWidgets.QMessageBox.warning(FreeCADGui.getMainWindow(), "CAM2027", text)


def _info(text):
    QtWidgets.QMessageBox.information(FreeCADGui.getMainWindow(), "CAM2027", text)


def _run(name):
    FreeCADGui.runCommand(name)


class TaskRow(QtWidgets.QFrame):
    """Ligne du navigateur : état (✔ / ○), titre, détail sur une ligne (…), bouton d'action."""

    def __init__(self, title, action_label, on_action, icon=None, parent=None):
        super(TaskRow, self).__init__(parent)
        self.setObjectName("taskRow")
        self.setProperty("role", "row")
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(6, 3, 6, 3)
        lay.setSpacing(6)
        self.mark = QtWidgets.QLabel()
        self.mark.setFixedWidth(18)
        self.mark.setAlignment(QtCore.Qt.AlignCenter)
        lay.addWidget(self.mark)
        col = QtWidgets.QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        self.title = QtWidgets.QLabel("<b>%s</b>" % title)
        self.title_text = title
        col.addWidget(self.title)
        self.detail = _ElidedLabel()
        theme.set_role(self.detail, "muted")
        col.addWidget(self.detail)
        lay.addLayout(col, 1)
        self.button = QtWidgets.QPushButton(action_label)
        if icon:
            self.button.setIcon(theme.icon(icon))
        self.button.clicked.connect(lambda _c=False: on_action())
        lay.addWidget(self.button)
        self.done = None

    def set_state(self, done, detail=""):
        """``done`` : True (fait), False (à faire), None (facultatif, pas d'état)."""
        self.done = done
        if done is None:
            self.mark.setText("")
            self.mark.setToolTip("")
        else:
            self.mark.setText("<span style='color:%s;font-size:13pt'>%s</span>" % (
                theme.status_color("done" if done else "todo"), "✔" if done else "○"))
            self.mark.setToolTip(tr("done") if done else tr("to do"))
        self.detail.set_text(detail or "")
        self.detail.setVisible(bool(detail))

    def toolTip(self):  # compat : état lisible comme une étape (« done » / « to do »)
        return self.mark.toolTip()


class _ElidedLabel(QtWidgets.QLabel):
    def __init__(self):
        super(_ElidedLabel, self).__init__()
        self._text = ""
        self.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed)
        self.setMinimumWidth(40)

    def set_text(self, text):
        self._text = text
        self.setToolTip(text)
        self._render()

    def resizeEvent(self, event):
        super(_ElidedLabel, self).resizeEvent(event)
        self._render()

    def _render(self):
        self.setText(self.fontMetrics().elidedText(self._text, QtCore.Qt.ElideRight, max(20, self.width() - 2)))


def _section_title(text):
    label = QtWidgets.QLabel(text)
    theme.set_role(label, "section")
    label.setContentsMargins(4, 6, 4, 2)
    return label


class Navigator(QtWidgets.QWidget):
    SPACES = ("prepare", "draw", "machine", "verify")

    def __init__(self, parent=None):
        super(Navigator, self).__init__(parent)
        self.setObjectName("CAM2027_Navigator")
        self._updating = False
        self._vectors_dirty = True
        self.space = "prepare"
        # tout le contenu dans une zone défilante : la fenêtre ne grandit jamais à cause du navigateur
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        inner = QtWidgets.QWidget()
        self.scroll.setWidget(inner)
        outer.addWidget(self.scroll)
        lay = QtWidgets.QVBoxLayout(inner)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)
        # sans projet (mode atelier FreeCAD, où il n'y a pas de page d'accueil) : les deux seuls boutons
        self.start_row = QtWidgets.QWidget()
        row0 = QtWidgets.QVBoxLayout(self.start_row)
        row0.setContentsMargins(0, 0, 0, 0)
        self.no_project = QtWidgets.QLabel(tr("No CAM2027 project in the active document."))
        self.no_project.setWordWrap(True)
        row0.addWidget(self.no_project)
        b_new = QtWidgets.QPushButton(tr("New project"))
        b_new.setIcon(theme.icon("new-project"))
        theme.set_role(b_new, "primary")
        b_new.clicked.connect(lambda: _run("CAM2027_NewProject"))
        b_open = QtWidgets.QPushButton(tr("Open a project..."))
        b_open.setIcon(theme.icon("open-project"))
        b_open.clicked.connect(lambda: _run("Std_Open"))
        row0.addWidget(b_new)
        row0.addWidget(b_open)
        lay.addWidget(self.start_row)
        # résumé compact, réutilisé dans tous les espaces
        self.summary = QtWidgets.QLabel()
        self.summary.setObjectName("projectSummary")
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(QtCore.Qt.RichText)
        self.summary.setOpenExternalLinks(False)
        self.summary.linkActivated.connect(self._summary_link)
        self.summary.setContentsMargins(6, 4, 6, 4)
        lay.addWidget(self.summary)
        from . import twosided as tsgui

        self.side_bar = tsgui.SideBar(self._switch_side)  # recto-verso : bascule face A / face B
        lay.addWidget(self.side_bar)
        self.stack = QtWidgets.QStackedWidget()
        self.pages = {}
        for key, builder in (("prepare", self._build_prepare), ("draw", self._build_draw),
                             ("machine", self._build_machine), ("verify", self._build_verify)):
            page = builder()
            self.pages[key] = page
            self.stack.addWidget(page)
        lay.addWidget(self.stack, 1)
        self.machine_note = QtWidgets.QLabel()
        self.machine_note.setWordWrap(True)
        theme.set_role(self.machine_note, "warning")
        lay.addWidget(self.machine_note)
        self.refresh()

    # -- construction : Préparer -------------------------------------------------------------------------

    def _build_prepare(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self.rows = {}
        for key, title, label, slot, icon in (
                ("model", tr("Part or drawing"), tr("Import..."), lambda: _run("CAM2027_ImportModel"), "cmd-import-model"),
                ("stock", tr("Stock"), tr("Set..."), self._open_stock, "cmd-stock"),
                ("origin", tr("Origin and work offset"), tr("Set..."), self._open_stock, "origin"),
                ("machine", tr("Machine and post-processor"), tr("Set..."), self._open_machine, "cmd-machine"),
                ("fixture", tr("Fixture and setup"), tr("Options"), None, "cmd-keep-out")):
            row = TaskRow(title, label, slot or (lambda: None), icon)
            self.rows[key] = row
            lay.addWidget(row)
        fixture_menu = QtWidgets.QMenu(self.rows["fixture"].button)
        for text, cmd in ((tr("Keep-out zones..."), "CAM2027_KeepOut"), (tr("Two-sided machining..."), "CAM2027_TwoSided"),
                          (tr("Nest parts on a sheet..."), "CAM2027_Nest"), (tr("Relief from image..."), "CAM2027_ImportRelief"),
                          (tr("Probe the origin..."), "CAM2027_Probe")):
            fixture_menu.addAction(text).triggered.connect(lambda _c=False, c=cmd: _run(c))
        self.rows["fixture"].button.setMenu(fixture_menu)
        lay.addWidget(_section_title(tr("Next")))
        self.next_hint = QtWidgets.QLabel()
        self.next_hint.setWordWrap(True)
        theme.set_role(self.next_hint, "muted")
        self.next_hint.setContentsMargins(6, 0, 6, 0)
        lay.addWidget(self.next_hint)
        self.next_button = QtWidgets.QPushButton()
        theme.set_role(self.next_button, "primary")
        self.next_button.clicked.connect(self._next_step)
        lay.addWidget(self.next_button)
        lay.addStretch(1)
        return w

    # -- construction : Dessiner ---------------------------------------------------------------------------

    def _build_draw(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        views = QtWidgets.QHBoxLayout()
        for text, slot in ((tr("Top view"), lambda: self._view("top")), (tr("3D view"), lambda: self._view("iso"))):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(lambda _c=False, f=slot: f())
            views.addWidget(b)
        lay.addLayout(views)
        lay.addWidget(_section_title(tr("Drawing vectors")))
        self.vectors = QtWidgets.QListWidget()
        self.vectors.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.vectors.itemSelectionChanged.connect(self._select_vectors)
        self.vectors.itemDoubleClicked.connect(lambda _i: _run("CAM2027_EditVector"))
        lay.addWidget(self.vectors, 1)
        self.draw_groups = {}
        for title, items in (
                (tr("Create"), (("CAM2027_DrawText", tr("Text")), ("CAM2027_DrawRectangle", tr("Rectangle")),
                                ("CAM2027_DrawCircle", tr("Circle")), ("CAM2027_DrawPolygon", tr("Polygon")),
                                ("CAM2027_TraceBitmap", tr("Trace bitmap")))),
                (tr("Modify"), (("CAM2027_EditVector", tr("Edit")), ("CAM2027_EditNodes", tr("Nodes")),
                                ("CAM2027_OffsetVector", tr("Offset")), ("CAM2027_CombineVectors", tr("Combine")),
                                ("CAM2027_MirrorVector", tr("Mirror")))),
                (tr("Align and repeat"), (("CAM2027_CircularCopies", tr("Circular copies")),)),
                (tr("Organise"), (("CAM2027_Nest", tr("Nest on a sheet")), ("CAM2027_ImportRelief", tr("Relief from image")),
                                  ("CAM2027_ImportModel", tr("Import a drawing"))))):
            lay.addWidget(_section_title(title))
            grid = QtWidgets.QGridLayout()
            grid.setSpacing(3)
            buttons = []
            for i, (cmd, label) in enumerate(items):
                b = QtWidgets.QToolButton()
                b.setText(label)
                b.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
                b.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
                try:
                    from . import commands

                    cls = dict(commands.COMMANDS).get(cmd)
                    if cls is not None and getattr(cls, "atelier", ""):
                        b.setIcon(theme.icon(cls.atelier))
                except Exception:
                    pass
                b.clicked.connect(lambda _c=False, c=cmd: _run(c))
                grid.addWidget(b, i // 2, i % 2)
                buttons.append((cmd, b))
            lay.addLayout(grid)
            self.draw_groups[title] = buttons
        return w

    # -- construction : Usiner -------------------------------------------------------------------------------

    def _build_machine(self):
        from .panels import _OperationTree

        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)
        self.add_button = QtWidgets.QPushButton(tr("Add operation"))
        self.add_button.setIcon(theme.icon("cmd-add-operation"))
        theme.set_role(self.add_button, "primary")
        self.add_button.clicked.connect(lambda: _run("CAM2027_AddOperation"))
        lay.addWidget(self.add_button)
        self.tree = _OperationTree(self.move_to)
        self.tree.setHeaderLabels([tr("Operation"), tr("State"), tr("Tool"), tr("Time"), ""])
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(COL_NAME, QtWidgets.QHeaderView.Stretch)
        for col in (COL_STATE, COL_TOOL, COL_TIME, COL_SHOW):
            header.setSectionResizeMode(col, QtWidgets.QHeaderView.ResizeToContents)
        self.tree.setTextElideMode(QtCore.Qt.ElideRight)
        self.tree.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.tree.setAllColumnsShowFocus(True)
        self.tree.headerItem().setToolTip(COL_NAME, tr("Tick: included in the machining and the export. The eye shows or hides the toolpath only."))
        self.tree.headerItem().setToolTip(COL_STATE, tr("To compute / Computed / To recompute / Warning / Failed. Computed does not mean verified or safe for the machine."))
        self.tree.headerItem().setIcon(COL_SHOW, theme.icon("visibility"))
        self.tree.headerItem().setToolTip(COL_SHOW, tr("Show or hide the toolpath in the 3D view (does not change the export)"))
        self.tree.setRootIsDecorated(False)
        self.tree.setMinimumHeight(140)
        self.tree.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.tree.itemDoubleClicked.connect(self.on_double_click)
        self.tree.itemChanged.connect(self.on_item_changed)
        self.tree.itemClicked.connect(self.on_item_clicked)
        self.tree.itemSelectionChanged.connect(self._select_in_3d)
        lay.addWidget(self.tree, 1)
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(3)
        row2 = QtWidgets.QHBoxLayout()
        row2.setSpacing(3)
        self.buttons = {}
        for key, label, slot, icon in (
                ("edit", tr("Edit"), self.edit_selected, "settings"),
                ("dup", tr("Duplicate"), self.duplicate_selected, "redo"),
                ("del", tr("Delete"), self.delete_selected, "delete"),
                ("up", "▲", lambda: self.move_selected(-1), None),
                ("down", "▼", lambda: self.move_selected(1), None)):
            b = QtWidgets.QPushButton(label)
            if icon:
                b.setIcon(theme.icon(icon))
            if key in ("up", "down"):
                b.setToolTip(tr("Move up (Alt+Up)") if key == "up" else tr("Move down (Alt+Down)"))
                b.setFixedWidth(34)
            if key == "del":
                theme.set_role(b, "danger")
            b.clicked.connect(slot)
            (row2 if key in ("up", "down") else row).addWidget(b)
            self.buttons[key] = b
        lay.addLayout(row)
        self.recompute_button = QtWidgets.QPushButton(tr("Recompute toolpaths"))
        self.recompute_button.setIcon(theme.icon("recalculate"))
        self.recompute_button.clicked.connect(lambda: _run("CAM2027_Compute"))
        row2.addWidget(self.recompute_button, 1)
        more = QtWidgets.QToolButton()
        more.setText(tr("More..."))
        more.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        more.setToolButtonStyle(QtCore.Qt.ToolButtonTextOnly)
        menu = QtWidgets.QMenu(more)
        for text, cmd in ((tr("Compare and edit operations..."), "CAM2027_BulkEdit"), (None, None),
                          (tr("Flat depth clearing (V-carve)..."), "CAM2027_FlatDepth"), (tr("V inlay (male / female)..."), "CAM2027_Inlay"),
                          (tr("Photo V-carve..."), "CAM2027_PhotoVCarve"), (tr("Moulding..."), "CAM2027_Moulding"),
                          (tr("Fluting..."), "CAM2027_Fluting"), (tr("Texture..."), "CAM2027_Texture"), (tr("Prism..."), "CAM2027_Prism"),
                          (None, None),
                          (tr("Hole recognition and drilling..."), "CAM2027_Holes"), (tr("Toolpath pattern..."), "CAM2027_Pattern"),
                          (tr("Project on the part..."), "CAM2027_ProjectOnPart"), (None, None),
                          (tr("Wrapped engraving (A axis)..."), "CAM2027_WrapEngrave"), (tr("Rotary machining (A axis)..."), "CAM2027_RotaryMachining"),
                          (None, None),
                          (tr("Save toolpath template..."), "CAM2027_SaveTemplate"), (tr("Apply toolpath template..."), "CAM2027_ApplyTemplate")):
            if text is None:
                menu.addSeparator()
            else:
                menu.addAction(text).triggered.connect(lambda _c=False, c=cmd: _run(c))
        more.setMenu(menu)
        row2.addWidget(more)
        lay.addLayout(row2)
        return w

    # -- construction : Vérifier et exporter ------------------------------------------------------------------

    def _build_verify(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self.vrows = {}
        for key, title, label, slot, icon in (
                ("paths", tr("Toolpaths"), tr("Recompute"), lambda: _run("CAM2027_Compute"), "recalculate"),
                ("sim", tr("Simulation (preview run)"), tr("Simulate"), lambda: _run("CAM2027_Simulate"), "play"),
                ("check", tr("Material and collision check"), tr("Check"), lambda: _run("CAM2027_MaterialCheck"), "cmd-material-check"),
                ("export", tr("G-code export"), tr("Export..."), lambda: _run("CAM2027_Export"), "export-gcode"),
                ("sheet", tr("Setup sheet (PDF)"), tr("Write..."), lambda: _run("CAM2027_SetupSheetPdf"), "cmd-setup-sheet")):
            row = TaskRow(title, label, slot, icon)
            self.vrows[key] = row
            lay.addWidget(row)
        lay.addWidget(_section_title(tr("Problems to review")))
        self.problems = QtWidgets.QListWidget()
        self.problems.setWordWrap(True)
        self.problems.itemActivated.connect(self._open_problem)
        self.problems.itemClicked.connect(self._open_problem)
        lay.addWidget(self.problems, 1)
        note = QtWidgets.QLabel(tr("A green result is not a guaranteed safe machining: each check has a scope."))
        note.setWordWrap(True)
        theme.set_role(note, "muted")
        lay.addWidget(note)
        return w

    def sizeHint(self):
        return QtCore.QSize(320, 640)

    def minimumSizeHint(self):
        return QtCore.QSize(280, 160)

    # -- espaces -----------------------------------------------------------------------------------------------

    def set_space(self, key):
        self.space = key if key in self.SPACES else "prepare"
        self.stack.setCurrentWidget(self.pages[self.space])
        self.summary.setVisible(self.space != "prepare" and state.active_project() is not None)
        if self.space == "draw" and self._vectors_dirty:
            self._refresh_vectors(state.active_project())

    # -- rafraîchissement ------------------------------------------------------------------------------------------

    def refresh(self):
        self._updating = True
        try:
            self._refresh()
        finally:
            self._updating = False

    def steps_done(self):
        """{étape: fait} : pièce, brut, opérations, export (lecture seule)."""
        return dict(self._steps)

    def _refresh(self):
        self.tree.clear()
        self.vectors.clear()
        self.problems.clear()
        proj = state.active_project()
        has_project = proj is not None
        self.start_row.setVisible(not has_project)
        self.stack.setVisible(has_project)
        self.summary.setVisible(has_project and self.space != "prepare")
        for b in self.buttons.values():
            b.setEnabled(has_project)
        self.add_button.setEnabled(has_project and proj.has_job)
        self._steps = {"model": False, "stock": False, "ops": False, "export": False}
        if proj is None:
            self.side_bar.refresh(None)
            self.machine_note.setText("")
            return
        self.side_bar.refresh(proj)
        from ..project.operations import toolpath_summary, STRATEGIES, COMPUTE_STATES, compute_state
        from ..project import indexing, sheet as sheetmod
        from .opeditor import extra_label  # gravure enroulée, angles vifs, palpage, Photo V-Carve, décors
        from .panels import _seconds, _hms

        # ---- Préparer
        if proj.has_job:
            models = [m.Label for m in proj.job.Model.Group]
        else:
            models = [o.Label for o in proj.model_candidates()] + [v.Label for v in sheetmod.vector_objects(proj.doc)]
        self._steps["model"] = bool(models)
        self.rows["model"].set_state(bool(models), ", ".join(models) if models else tr("import STEP, STL, SVG or DXF"))
        if proj.has_job:
            sb = proj.stock_bounds()
            from ..project.stock import clamps

            n_clamps = len(clamps(proj.doc))
            stock_text = "%.1f x %.1f x %.1f mm" % (sb["length"], sb["width"], sb["height"])
            self._steps["stock"] = True
            self.rows["stock"].set_state(True, stock_text)
            fixture = " ".join(proj.job.Fixtures) or "?"
            self.rows["origin"].set_state(True, tr("{wcs}, Z 0 at the stock top", wcs=fixture)
                                          if sb.get("zmax") is not None and abs(sb["zmax"]) < 1e-6 else fixture)
            fixture_bits = []
            if n_clamps:
                fixture_bits.append("%d %s" % (n_clamps, tr("clamps")))
            from ..project import keepout, twosided

            zones = keepout.zones(proj.doc)
            if zones:
                fixture_bits.append("%d %s" % (len(zones), tr("keep-out zones")))
            if twosided.is_two_sided(proj):
                fixture_bits.append(tr("two-sided"))
            if proj.machine.rotary.present:
                fixture_bits.append(tr("A axis"))
            self.rows["fixture"].set_state(None, ", ".join(fixture_bits) if fixture_bits else tr("none (optional)"))
        else:
            self.rows["stock"].set_state(False, tr("creates the job"))
            self.rows["origin"].set_state(False, tr("set with the stock"))
            self.rows["fixture"].set_state(None, tr("after the stock"))
        missing = proj.machine.unknown_fields()
        from ..project.machine import FIELD_LABELS

        self.rows["machine"].set_state(not missing, "%s, %s" % (proj.machine.name, proj.job.PostProcessor if proj.has_job else (proj.machine.post_processor or tr("post-processor to choose"))))
        self.machine_note.setText(tr("Machine data to fill in: {fields}",
                                     fields=", ".join(tr(FIELD_LABELS.get(f, f)) for f in missing)) if missing else "")
        self.machine_note.setToolTip(tr("Fill them in with the Machine profile command: until then, the matching export checks stay 'not verifiable'."))
        self.machine_note.setVisible(bool(missing) and self.space in ("prepare", "verify"))

        # ---- Dessiner (liste des vecteurs : coûteuse sur un gros document, seulement dans cet espace)
        self._vectors_dirty = True
        if self.space == "draw":
            self._refresh_vectors(proj)

        # ---- Usiner
        ops = proj.operations() if proj.has_job else []
        reg = proj.registry if proj.has_job else {}
        bad = pending = total_seconds = 0
        states = []
        for op in ops:
            s = toolpath_summary(op)
            total_seconds += _seconds(s["cycle_time"])
            base = proj.base_operation(op)
            rec = reg.get(base.Name, {})
            kind = rec.get("kind", "?")
            tc = getattr(base, "ToolController", None)
            tool_text = ""
            if tc is not None:
                v = bridge.tool_controller_values(tc)
                tool_text = "T%d Ø%.3g" % (v["tool_number"], v["diameter_mm"] or 0)
            # registre déjà lu : ``operation_state`` le relisait (JSON) pour chaque ligne
            op_state = proj.operation_state(op) if indexing.is_index_op(op) else compute_state(op, base, rec or None)
            states.append((op.Label, op_state))
            valid = op_state not in ("failed",)
            if not valid:
                bad += 1
            if op_state in ("todo", "stale"):
                pending += 1
            state_label, state_level = COMPUTE_STATES[op_state]
            if indexing.is_index_op(op):
                strategy_text = tr("A axis positioning (automatic)")
            else:
                strategy_text = tr(STRATEGIES.get(kind, {}).get("label", extra_label(kind)))
                if rec.get("index_deg") is not None:
                    strategy_text += "  @A%g" % rec["index_deg"]
            item = QtWidgets.QTreeWidgetItem([op.Label, tr(state_label), tool_text, str(s["cycle_time"] or ""), ""])
            item.setData(COL_NAME, QtCore.Qt.UserRole, op.Name)
            row_tip = "%s\n%s : %s" % (strategy_text, tr("Commands"), s["commands"] if base.Active else tr("(inactive)"))
            if s["commands"]:
                row_tip += "\nZ (mm) : %.2f .. %.2f" % (s["zmin"] or 0, s["zmax"] or 0)
            for col in (COL_STATE, COL_TOOL, COL_TIME):
                item.setToolTip(col, row_tip)
            if not base.Active:  # opération exclue : ligne grisée
                for col in range(4):
                    item.setForeground(col, QtGui.QBrush(QtGui.QColor(theme.color("muted"))))
            if indexing.is_index_op(op):
                item.setIcon(COL_NAME, theme.icon("axis-a"))
                item.setToolTip(COL_NAME, tr("Rebuilt automatically in front of each change of A angle."))
            else:
                item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
                item.setCheckState(COL_NAME, QtCore.Qt.Checked if base.Active else QtCore.Qt.Unchecked)
            shown = True
            try:
                shown = bool(op.ViewObject.Visibility) if op.ViewObject is not None else True
            except Exception:
                pass
            item.setIcon(COL_SHOW, theme.icon("visibility") if shown else theme.icon("visibility-off"))
            item.setToolTip(COL_SHOW, tr("Toolpath shown") if shown else tr("Toolpath hidden (still exported if included)"))
            item.setData(COL_SHOW, QtCore.Qt.UserRole, shown)
            tips = list(rec.get("warnings", []))
            if rec.get("ignored_params"):
                tips.append(tr("ignored parameters") + ": " + ", ".join(rec["ignored_params"]))
            item.setIcon(COL_STATE, theme.icon(_STATE_ICONS[op_state]))
            item.setForeground(COL_STATE, QtGui.QBrush(QtGui.QColor(theme.status_color(state_level))))
            if not valid:
                tips.append(tr("No cutting move: check the geometry, the depths and the tool."))
                for col in range(4):
                    item.setForeground(col, QtGui.QBrush(QtGui.QColor(theme.status_color("error"))))
            item.setToolTip(COL_NAME, "\n".join([op.Label, row_tip] + tips))
            if indexing.is_index_op(op):
                item.setFlags(item.flags() & ~QtCore.Qt.ItemIsDragEnabled)
            self.tree.addTopLevelItem(item)
        self._steps["ops"] = bool(ops) and bad == 0
        if pending:
            theme.set_role(self.recompute_button, "primary")
            self.recompute_button.setText(tr("Recompute toolpaths ({n} pending)", n=pending))
        else:
            theme.set_role(self.recompute_button, "")
            self.recompute_button.setText(tr("Recompute toolpaths"))
        self.recompute_button.setEnabled(proj.has_job)

        # ---- Vérifier et exporter
        self._steps["export"] = bool(proj.has_job and proj.job.PostProcessorOutputFile)
        n_ok = sum(1 for _l, st in states if st in ("computed", "warning"))
        detail = tr("{ok} of {n} computed", ok=n_ok, n=len(ops))
        if total_seconds:
            detail += ", %s %s" % (tr("total time"), _hms(total_seconds))
        if pending:
            detail += ", %s" % tr("{n} to recompute", n=pending)
        self.vrows["paths"].set_state(bool(ops) and bad == 0 and not pending, detail if ops else tr("no operation yet"))
        self.vrows["sim"].set_state(None, tr("preview run of the toolpaths in the FreeCAD simulator (A axis excluded)"))
        last = proj.last_check() if proj.has_job else None
        # l'empreinte des parcours resérialise tout le G-code : seulement dans l'espace Vérifier et exporter
        fresh = (last is not None and last.get("fingerprint") == proj._paths_fingerprint()) if self.space == "verify"             else (last is not None)
        if not proj.has_job or not ops:
            self.vrows["check"].set_state(False, tr("no operation yet"))
        elif last is None:
            self.vrows["check"].set_state(False, tr("not run"))
        elif not fresh:
            self.vrows["check"].set_state(False, tr("outdated: the toolpaths changed since the last check"))
        elif last["events"] or last["gouge_max"] > last["tolerance"]:
            self.vrows["check"].set_state(False, tr("{n} problem(s) found", n=len(last["events"]) + (1 if last["gouge_max"] > last["tolerance"] else 0)))
        else:
            self.vrows["check"].set_state(True, tr("done: no gouge or collision found (height map, 3 axes)"))
        self.vrows["export"].set_state(self._steps["export"], proj.job.PostProcessorOutputFile if proj.has_job and proj.job.PostProcessorOutputFile
                                       else (("%s" % proj.job.PostProcessor) if proj.has_job else ""))
        self.vrows["sheet"].set_state(None, "")
        self.vrows["sheet"].detail.setVisible(False)
        for label, st in states:
            if st == "failed":
                self._add_problem("error", tr("{op}: no valid toolpath", op=label), ("op", label))
            elif st in ("todo", "stale"):
                self._add_problem("warning", tr("{op}: to recompute", op=label), ("op", label))
            elif st == "warning":
                self._add_problem("info", tr("{op}: computed with warnings", op=label), ("op", label))
        if proj.has_job and ops and last is not None and fresh and (last["events"] or last["gouge_max"] > last["tolerance"]):
            self._add_problem("error", tr("Material check: gouges or collisions found"), ("check", None))
        if proj.has_job and ops and (last is None or not fresh):
            self._add_problem("info", tr("Material check not run for these toolpaths") if last is None
                              else tr("Material check outdated: the toolpaths changed"), ("check", None))
        if missing:
            self._add_problem("info", tr("Machine data missing: some export checks stay not verifiable"), ("machine", None))
        try:
            from ..project import keepout

            for lvl, msg in keepout.issues(proj) if proj.has_job else []:
                self._add_problem("error" if lvl == "error" else "warning", tr_msg(msg), ("fixture", None))
        except Exception:
            pass
        if self.problems.count() == 0:
            item = QtWidgets.QListWidgetItem(tr("No problem to review on the checks performed."))
            item.setFlags(QtCore.Qt.NoItemFlags)
            self.problems.addItem(item)

        # ---- Préparer : prochaine étape
        self._refresh_next(proj, ops)
        # résumé compact (tous les espaces)
        bits = []
        if proj.has_job:
            sb = proj.stock_bounds()
            bits.append('<a href="stock">%s</a> %.0f × %.0f × %.0f' % (tr("Stock"), sb["length"], sb["width"], sb["height"]))
            bits.append('<a href="stock">%s</a> %s' % (tr("Offset"), " ".join(proj.job.Fixtures) or "?"))
        else:
            bits.append('<a href="stock">%s</a>' % tr("Stock: to set"))
        bits.append('<a href="machine">%s</a> %s' % (tr("Machine"), proj.machine.name))
        self.summary.setText(" &nbsp;·&nbsp; ".join(bits))

    def _refresh_vectors(self, proj):
        from ..project import sheet as sheetmod

        self._updating = True
        try:
            self.vectors.clear()
            if proj is not None:
                for v in sheetmod.vector_objects(proj.doc):
                    item = QtWidgets.QListWidgetItem(v.Label)
                    item.setData(QtCore.Qt.UserRole, v.Name)
                    self.vectors.addItem(item)
            self._vectors_dirty = False
        finally:
            self._updating = False

    def _add_problem(self, level, text, target):
        symbol = {"error": "✕", "warning": "△", "info": "•"}[level]
        item = QtWidgets.QListWidgetItem("%s %s" % (symbol, text))
        item.setForeground(QtGui.QBrush(QtGui.QColor(theme.status_color(level))))
        item.setData(QtCore.Qt.UserRole, target)
        item.setToolTip({"error": tr("Blocking"), "warning": tr("Warning"), "info": tr("Information")}[level] + " - " + tr("click to open the related setting"))
        self.problems.addItem(item)

    def _refresh_next(self, proj, ops):
        if not self._steps["model"]:
            text, label, slot = tr("Import a part (STEP, STL, OBJ) or a drawing (SVG, DXF)."), tr("Import..."), lambda: _run("CAM2027_ImportModel")
        elif not proj.has_job:
            text, label, slot = tr("Define the stock and the work offset: this creates the job."), tr("Stock and fixture..."), self._open_stock
        elif not ops:
            text, label, slot = tr("Add the first operation in the Machining space."), tr("Go to Machining"), lambda: self._go("machine")
        else:
            text, label, slot = tr("Check the toolpaths, then export the G-code."), tr("Go to Check and export"), lambda: self._go("verify")
        self.next_hint.setText(text)
        self.next_button.setText(label)
        try:
            self.next_button.clicked.disconnect()
        except (TypeError, RuntimeError):
            pass
        self.next_button.clicked.connect(lambda _c=False, f=slot: f())

    # -- actions ---------------------------------------------------------------------------------------------

    def _go(self, space):
        from . import shell

        shell.show_space(space)

    def _next_step(self):
        pass  # connecté dynamiquement par _refresh_next

    def _open_stock(self):
        proj = state.active_project()
        if proj is None:
            return
        from . import preparepages

        preparepages.open_stock(proj)

    def _open_machine(self):
        proj = state.active_project()
        if proj is None:
            return
        from . import preparepages

        preparepages.open_machine(proj)

    def _summary_link(self, href):
        {"stock": self._open_stock, "machine": self._open_machine}.get(href, lambda: None)()

    def _open_problem(self, item):
        target = item.data(QtCore.Qt.UserRole)
        if not target:
            return
        kind, label = target
        if kind == "op":
            self._go("machine")
            for i in range(self.tree.topLevelItemCount()):
                if self.tree.topLevelItem(i).text(COL_NAME) == label:
                    self.tree.setCurrentItem(self.tree.topLevelItem(i))
                    self.edit_selected()
                    return
        elif kind == "check":
            _run("CAM2027_MaterialCheck")
        elif kind == "machine":
            self._open_machine()
        elif kind == "fixture":
            _run("CAM2027_KeepOut")

    def _view(self, which):
        view = FreeCADGui.ActiveDocument.ActiveView if FreeCADGui.ActiveDocument else None
        if view is None:
            return
        try:
            (view.viewTop if which == "top" else view.viewIsometric)()
            view.fitAll()
        except Exception:
            pass

    def _select_vectors(self):
        proj = state.active_project()
        if proj is None or self._updating:
            return
        FreeCADGui.Selection.clearSelection()
        for item in self.vectors.selectedItems():
            obj = proj.doc.getObject(item.data(QtCore.Qt.UserRole))
            if obj is not None:
                FreeCADGui.Selection.addSelection(obj)

    def _switch_side(self, side):
        from . import twosided as tsgui

        proj = state.active_project()
        if proj is not None:
            tsgui.switch_side(proj, side)
        self.refresh()

    def _selected(self, quiet=False):
        proj = state.active_project()
        items = self.tree.selectedItems()
        if proj is None or not items:
            return None, None
        op = proj.doc.getObject(items[0].data(COL_NAME, QtCore.Qt.UserRole))
        from ..project import indexing

        if op is not None and indexing.is_index_op(op):
            if quiet:
                return proj, None
            _info(tr("A axis positionings are managed automatically: edit, move or delete the operations instead."))
            return None, None
        return proj, op

    def _select_in_3d(self):
        proj, op = self._selected(quiet=True)
        if op is not None:
            FreeCADGui.Selection.clearSelection()
            FreeCADGui.Selection.addSelection(op)

    def _reselect(self, name):
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item.data(COL_NAME, QtCore.Qt.UserRole) == name:
                self.tree.setCurrentItem(item)
                return

    def on_double_click(self, item, _col):
        self.edit_selected()

    def on_item_clicked(self, item, col):
        if col != COL_SHOW or self._updating:
            return
        proj = state.active_project()
        if proj is None:
            return
        op = proj.doc.getObject(item.data(COL_NAME, QtCore.Qt.UserRole))
        if op is None or op.ViewObject is None:
            return
        shown = not bool(item.data(COL_SHOW, QtCore.Qt.UserRole))
        op.ViewObject.Visibility = shown  # affichage seul : l'export ne change pas
        item.setData(COL_SHOW, QtCore.Qt.UserRole, shown)
        item.setIcon(COL_SHOW, theme.icon("visibility") if shown else theme.icon("visibility-off"))
        item.setToolTip(COL_SHOW, tr("Toolpath shown") if shown else tr("Toolpath hidden (still exported if included)"))

    def on_item_changed(self, item, col):
        if self._updating or col != COL_NAME:
            return
        # traité après le signal : ``refresh`` reconstruit la liste ; pendant le signal, il détruisait l'élément
        # que Qt était en train de cocher (violation d'accès, plantage de FreeCAD au hasard)
        name, active = item.data(COL_NAME, QtCore.Qt.UserRole), item.checkState(COL_NAME) == QtCore.Qt.Checked
        QtCore.QTimer.singleShot(0, lambda: self._set_active(name, active))

    def _set_active(self, name, active):
        proj = state.active_project()
        if proj is None:
            return
        op = proj.doc.getObject(name)
        if op is None:
            return
        with undo.transaction(proj.doc, tr("Enable or disable the operation")):
            proj.set_operation_active(op, active)
            proj.compute()
        self.refresh()
        self._reselect(op.Name)

    def edit_selected(self):
        proj, op = self._selected()
        if op is None:
            return
        from ..project import wrap

        if wrap.is_wrap_op(op):
            from .commands import open_wrap_dialog

            open_wrap_dialog(proj, op)
            return
        from . import opeditor

        opeditor.open_editor(proj, proj.base_operation(op))

    def move_to(self, name, index):
        """Glisser-déposer : l'opération ``name`` prend le rang ``index`` parmi les opérations (positionnements A
        exclus, recréés automatiquement)."""
        proj = state.active_project()
        if proj is None:
            return
        op = proj.doc.getObject(name)
        if op is None:
            return
        try:
            with undo.transaction(proj.doc, tr("Move the operation")):
                proj.move_operation_to(op, index)
                proj.compute()
        except Exception as exc:
            _warn(tr_msg(exc))
        self.refresh()
        self._reselect(name)

    def move_selected(self, delta):
        proj, op = self._selected()
        if op is None:
            return
        with undo.transaction(proj.doc, tr("Move the operation")):
            proj.move_operation(op, delta)
            proj.compute()
        self.refresh()
        self._reselect(op.Name)

    def duplicate_selected(self):
        proj, op = self._selected()
        if op is None:
            return
        try:
            with undo.transaction(proj.doc, tr("Duplicate")):
                new, _rec = proj.duplicate_operation(op)
                proj.compute()
        except Exception as exc:
            _warn(tr_msg(exc))
            return
        self.refresh()
        self._reselect(new.Name)

    def delete_selected(self):
        proj, op = self._selected()
        if op is None:
            return
        if QtWidgets.QMessageBox.question(self, "CAM2027", tr("Delete the operation '{name}'?", name=op.Label)) \
                != QtWidgets.QMessageBox.Yes:
            return
        try:
            with undo.transaction(proj.doc, tr("Delete")):
                proj.remove_operation(op)
                proj.compute()
        except Exception as exc:
            _warn(tr_msg(exc))
        self.refresh()
