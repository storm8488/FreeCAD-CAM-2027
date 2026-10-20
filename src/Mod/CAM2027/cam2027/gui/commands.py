# SPDX-License-Identifier: LGPL-2.1-or-later
"""Commandes de l'atelier (barre d'outils et menu)."""

import os

import FreeCAD
import FreeCADGui

from .qt import QtCore, QtGui, QtWidgets, exec_dialog
from ..i18n import tr
from .. import compat
from ..version import __version__, FREECAD_PINNED_TAG
from ..project.project import Project, ExportBlocked
from ..project.operations import STRATEGIES, DEFAULT_THREAD_TYPE, thread_names
from ..project.importers import SUPPORTED_EXTENSIONS
from ..project import export as exportmod
from ..project.machine import MachineProfile
from . import state, panels

_ICON_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "Resources", "icons")


def _icon(name):
    return os.path.join(_ICON_DIR, name)


def _warn(text):
    QtWidgets.QMessageBox.warning(FreeCADGui.getMainWindow(), "CAM2027", text)


def _info(text):
    QtWidgets.QMessageBox.information(FreeCADGui.getMainWindow(), "CAM2027", text)


def _need_project():
    proj = state.active_project()
    if proj is None:
        _warn(tr("The active document is not a CAM2027 project. Use 'New project' first."))
    return proj


def _after_change():
    if FreeCAD.ActiveDocument:
        FreeCAD.ActiveDocument.recompute()
    panels.refresh_project_panel()


class _Base(object):
    icon = "CAM2027.svg"
    text = ""
    tooltip = ""

    accel = ""

    def GetResources(self):
        res = {"Pixmap": _icon(self.icon), "MenuText": tr(self.text), "ToolTip": tr(self.tooltip)}
        if self.accel:
            res["Accel"] = self.accel
        return res

    def IsActive(self):
        return True


class NewProject(_Base):
    icon = "cam2027-new-project.svg"
    accel = "Ctrl+Shift+N"
    text = "New project"
    tooltip = "Create a CAM2027 project document with a frozen copy of the tool library"

    def Activated(self):
        name, ok = QtWidgets.QInputDialog.getText(FreeCADGui.getMainWindow(), tr("New project"), tr("Project name"),
                                                  text=tr("Project"))
        if not ok or not name.strip():
            return
        lib = state.library()
        proj = Project.create(name.strip(), lib)
        FreeCADGui.ActiveDocument = FreeCADGui.getDocument(proj.doc.Name)
        panels.ensure_project_panel()
        _after_change()


class ImportModel(_Base):
    icon = "cam2027-import.svg"
    accel = "Ctrl+Shift+I"
    text = "Import model / drawing"
    tooltip = "Import STEP, STL, OBJ, SVG or DXF into the project"

    def Activated(self):
        proj = _need_project()
        if proj is None:
            return
        filt = tr("Models and drawings") + " (" + " ".join("*" + e for e in SUPPORTED_EXTENSIONS) + ")"
        path, _f = QtWidgets.QFileDialog.getOpenFileName(FreeCADGui.getMainWindow(), tr("Import a file"), "", filt)
        if not path:
            return
        try:
            res = proj.import_model(path)
        except Exception as exc:  # erreurs OCC / lecteurs
            _warn(tr("Import failed: {error}", error=str(exc)))
            return
        if res.warnings:
            _info("\n".join(res.warnings))
        FreeCADGui.SendMsgToActiveView("ViewFit")
        _after_change()


class ToolLibrary(_Base):
    icon = "cam2027-tool-library.svg"
    accel = "Ctrl+Shift+T"
    text = "Tool library"
    tooltip = "Tools, holders, assemblies and cutting presets"

    def Activated(self):
        panels.show_tool_library()


class StockFixture(_Base):
    icon = "cam2027-stock.svg"
    accel = "Ctrl+Shift+B"
    text = "Stock & fixture"
    tooltip = "Create the job (if needed), define the stock and the work coordinate system"

    def Activated(self):
        proj = _need_project()
        if proj is None:
            return
        dlg = QtWidgets.QDialog(FreeCADGui.getMainWindow())
        dlg.setWindowTitle(tr("Stock & fixture"))
        form = QtWidgets.QFormLayout(dlg)
        kind = QtWidgets.QComboBox()
        kind.addItem(tr("Box around the model with margins"), "box_margins")
        kind.addItem(tr("Explicit box"), "box")
        kind.addItem(tr("Cylinder (rotary / round stock)"), "cylinder")
        kind.addItem(tr("Sheet under the 2D drawing (top at Z 0)"), "sheet")
        from ..project import sheet as sheetmod

        if not proj.has_job and sheetmod.vector_objects(proj.doc) and not any(
                getattr(o, "Shape", None) and o.Shape.Solids for o in proj.doc.Objects):
            kind.setCurrentIndex(kind.count() - 1)
        form.addRow(tr("Stock type"), kind)
        xy = QtWidgets.QDoubleSpinBox(); xy.setRange(0, 1000); xy.setValue(2.0)
        ztop = QtWidgets.QDoubleSpinBox(); ztop.setRange(0, 1000); ztop.setValue(0.0)
        zbot = QtWidgets.QDoubleSpinBox(); zbot.setRange(0, 1000); zbot.setValue(0.0)
        form.addRow(tr("XY margin (mm)"), xy)
        form.addRow(tr("Top margin (mm)"), ztop)
        form.addRow(tr("Bottom margin (mm)"), zbot)
        length = QtWidgets.QDoubleSpinBox(); length.setRange(0.1, 5000); length.setValue(100)
        width = QtWidgets.QDoubleSpinBox(); width.setRange(0.1, 5000); width.setValue(100)
        height = QtWidgets.QDoubleSpinBox(); height.setRange(0.1, 5000); height.setValue(20)
        radius = QtWidgets.QDoubleSpinBox(); radius.setRange(0.1, 5000); radius.setValue(25)
        form.addRow(tr("Length X (mm)"), length)
        form.addRow(tr("Width Y (mm)"), width)
        form.addRow(tr("Height Z (mm)"), height)
        form.addRow(tr("Radius (mm)"), radius)
        thickness = QtWidgets.QDoubleSpinBox(); thickness.setRange(0.1, 500); thickness.setValue(18.0)
        sheet_margin = QtWidgets.QDoubleSpinBox(); sheet_margin.setRange(0, 1000); sheet_margin.setValue(10.0)
        form.addRow(tr("Sheet thickness (mm)"), thickness)
        form.addRow(tr("Sheet margin around the drawing (mm)"), sheet_margin)
        fixture = QtWidgets.QComboBox()
        fixture.addItems(["G54", "G55", "G56", "G57", "G58", "G59"])
        form.addRow(tr("Work coordinate system"), fixture)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        if exec_dialog(dlg) != QtWidgets.QDialog.Accepted:
            return
        k = kind.currentData()
        if k == "sheet":
            try:
                if proj.has_job:
                    _warn(tr("The project already has a job: the sheet is only available for a new 2D project."))
                    return
                proj.create_sheet_job(thickness=thickness.value(), margin=sheet_margin.value(),
                                      fixtures=[fixture.currentText()])
            except Exception as exc:
                _warn(str(exc))
                return
            FreeCADGui.SendMsgToActiveView("ViewFit")
            _after_change()
            return
        if k == "box_margins":
            spec = {"kind": k, "xy": xy.value(), "z_top": ztop.value(), "z_bottom": zbot.value()}
        elif k == "box":
            spec = {"kind": k, "length": length.value(), "width": width.value(), "height": height.value()}
        else:
            spec = {"kind": k, "radius": radius.value(), "height": height.value()}
        try:
            if not proj.has_job:
                sel = [o for o in FreeCADGui.Selection.getSelection() if getattr(o, "Shape", None)]
                if not sel:
                    sel = [o for o in proj.doc.Objects if getattr(o, "Shape", None) and o.Shape.Solids
                           and o.TypeId.startswith("Part::")]
                if not sel:
                    _warn(tr("Select or import a solid model first."))
                    return
                proj.create_job(sel, stock=spec, fixtures=[fixture.currentText()])
            else:
                proj.set_stock(spec)
                from ..project.stock import set_fixtures

                set_fixtures(proj.job, [fixture.currentText()])
        except Exception as exc:
            _warn(str(exc))
            return
        _after_change()


class AddOperation(_Base):
    icon = "cam2027-add-operation.svg"
    accel = "Ctrl+Shift+O"
    text = "Add operation"
    tooltip = "Add a machining operation using a tool assembly and a cutting preset"

    def Activated(self):
        proj = _need_project()
        if proj is None:
            return
        if not proj.has_job:
            _warn(tr("Define the stock & fixture first (this creates the job)."))
            return
        lib = proj.library
        sel = FreeCADGui.Selection.getSelectionEx()
        base = []
        for s in sel:
            if s.Object.Document.Name == proj.doc.Name and getattr(s.Object, "Shape", None):
                base.append((s.Object, list(s.SubElementNames)))
        dlg = QtWidgets.QDialog(FreeCADGui.getMainWindow())
        dlg.setWindowTitle(tr("Add operation"))
        form = QtWidgets.QFormLayout(dlg)
        name = QtWidgets.QLineEdit(tr("Operation"))
        form.addRow(tr("Name"), name)
        kind = QtWidgets.QComboBox()
        for key, meta in STRATEGIES.items():
            kind.addItem(tr(meta["label"]), key)
        form.addRow(tr("Strategy"), kind)
        limits = QtWidgets.QLabel()
        limits.setWordWrap(True)
        form.addRow(tr("Known limits"), limits)
        kind.currentIndexChanged.connect(lambda _i: limits.setText(tr(STRATEGIES[kind.currentData()]["limits"]) or "-"))
        limits.setText(tr(STRATEGIES[kind.currentData()]["limits"]) or "-")
        asm = QtWidgets.QComboBox()
        for a in sorted(lib.assemblies.values(), key=lambda a: a.output.tool_number):
            asm.addItem("T%d - %s" % (a.output.tool_number, a.name), a.id)
        form.addRow(tr("Tool assembly"), asm)
        preset = QtWidgets.QComboBox()
        form.addRow(tr("Cutting preset"), preset)

        def fill_presets():
            preset.clear()
            if asm.currentData() is None:
                return
            tool = lib.tool(lib.assembly(asm.currentData()).tool_id)
            for p in tool.presets:
                preset.addItem("%s (%s, %s)" % (p.name, tr(p.usage), p.material or "-"), p.id)

        asm.currentIndexChanged.connect(lambda _i: fill_presets())
        fill_presets()
        sel_label = QtWidgets.QLabel(", ".join("%s: %s" % (o.Label, " ".join(subs) or tr("whole")) for o, subs in base)
                                     or tr("(nothing selected: the whole model is used)"))
        sel_label.setWordWrap(True)
        form.addRow(tr("Geometry (selection)"), sel_label)
        hint = QtWidgets.QLabel(tr("Depths, passes and strategy settings are edited in the next window (tabs), with values prefilled from the cutting preset."))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #9aa7b8;")
        form.addRow(hint)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        if exec_dialog(dlg) != QtWidgets.QDialog.Accepted:
            return
        if asm.currentData() is None or preset.currentData() is None:
            _warn(tr("The library snapshot has no assembly or preset for this tool."))
            return
        a, tool, _h = lib.resolve_assembly(asm.currentData())
        values = tool.preset(preset.currentData()).resolve(tool)
        k = kind.currentData()
        params = default_params(k, tool, values)
        try:
            op, rec = proj.add_operation(k, name.text().strip() or "Operation", a.id, preset.currentData(),
                                         base=base or [(proj.job.Model.Group[0], [])], params=params)
            proj.compute()
        except Exception as exc:
            _warn(tr("Operation failed: {error}", error=str(exc)))
            _after_change()
            return
        if rec["warnings"]:
            _info("\n".join(rec["warnings"]))
        _after_change()
        from . import opeditor

        def on_close(accepted):
            if not accepted:
                try:
                    proj.remove_operation(op)
                except Exception as exc:
                    _warn(tr("Operation failed: {error}", error=str(exc)))
                _after_change()

        opeditor.open_editor(proj, op, on_close=on_close, title=tr("New operation: {name}", name=op.Label))


def default_params(kind, tool, values):
    """Paramètres initiaux d'une opération dérivés du préréglage (passe axiale, recouvrement, etc.)."""
    params = {"StepDown": values["axial_engagement_mm"]}
    stepover = max(1, min(100, int(round(100.0 * (values["radial_engagement_mm"] or tool.geometry.diameter * 0.4)
                                         / tool.geometry.diameter))))
    if kind in ("pocket", "millface", "adaptive", "helix"):
        params["StepOver"] = stepover
    if kind == "millface":
        params["ClearEdges"] = True
    if kind == "chamfer":
        params["Width"] = 1.0
    if kind == "threadmill":
        names = thread_names(DEFAULT_THREAD_TYPE)
        params["ThreadType"] = DEFAULT_THREAD_TYPE
        params["ThreadName"] = "M6 x 1" if "M6 x 1" in names else names[0]
    return params


class Compute(_Base):
    icon = "cam2027-compute.svg"
    accel = "Ctrl+Shift+R"
    text = "Recompute toolpaths"
    tooltip = "Recompute every operation and refresh the summary"

    def Activated(self):
        proj = _need_project()
        if proj is None:
            return
        results = proj.compute() if proj.has_job else []
        bad = [r["name"] for r in results if not r["valid"] or r["commands"] == 0]
        if bad:
            _warn(tr("Operations without a valid toolpath: {names}", names=", ".join(bad)))
        _after_change()


class Export(_Base):
    icon = "cam2027-export.svg"
    accel = "Ctrl+Shift+E"
    text = "Export G-code"
    tooltip = "Post-process, check and write the G-code and the setup sheet"

    def Activated(self):
        proj = _need_project()
        if proj is None or not proj.has_job:
            if proj is not None:
                _warn(tr("No job to export."))
            return
        dlg = QtWidgets.QDialog(FreeCADGui.getMainWindow())
        dlg.setWindowTitle(tr("Export G-code"))
        dlg.resize(900, 650)
        lay = QtWidgets.QVBoxLayout(dlg)
        form = QtWidgets.QFormLayout()
        post = QtWidgets.QComboBox()
        posts = exportmod.available_postprocessors()
        post.addItems(posts)
        if proj.job.PostProcessor in posts:
            post.setCurrentText(proj.job.PostProcessor)
        form.addRow(tr("Post processor"), post)
        args = QtWidgets.QLineEdit(proj.job.PostProcessorArgs)
        form.addRow(tr("Arguments"), args)
        default_out = proj.job.PostProcessorOutputFile or os.path.join(
            os.path.dirname(proj.doc.FileName) if proj.doc.FileName else os.path.expanduser("~"),
            (proj.doc.Label or "program") + ".nc")
        out = QtWidgets.QLineEdit(default_out)
        browse = QtWidgets.QPushButton(tr("Browse..."))

        def pick():
            p, _f = QtWidgets.QFileDialog.getSaveFileName(dlg, tr("Output file"), out.text(), "G-code (*.nc *.gcode *.ngc)")
            if p:
                out.setText(p)

        browse.clicked.connect(pick)
        row = QtWidgets.QHBoxLayout(); row.addWidget(out); row.addWidget(browse)
        form.addRow(tr("Output file"), row)
        lay.addLayout(form)
        tabs = QtWidgets.QTabWidget()
        preview = QtWidgets.QPlainTextEdit(); preview.setReadOnly(True)
        preview.setFont(QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont))
        checks = QtWidgets.QTextEdit(); checks.setReadOnly(True)
        sheet = QtWidgets.QPlainTextEdit(); sheet.setReadOnly(True)
        tabs.addTab(preview, tr("G-code preview"))
        tabs.addTab(checks, tr("Checks"))
        tabs.addTab(sheet, tr("Setup sheet"))
        lay.addWidget(tabs)
        btns = QtWidgets.QHBoxLayout()
        b_prev = QtWidgets.QPushButton(tr("Preview"))
        b_exp = QtWidgets.QPushButton(tr("Export"))
        b_close = QtWidgets.QPushButton(tr("Close"))
        btns.addWidget(b_prev); btns.addWidget(b_exp); btns.addStretch(); btns.addWidget(b_close)
        lay.addLayout(btns)

        def do_preview():
            try:
                text, analysis, issues = proj.preview_gcode(post.currentText(), args.text())
            except Exception as exc:
                checks.setPlainText(tr("Post-processing failed: {error}", error=str(exc)))
                return
            preview.setPlainText(text)
            checks.setHtml(_format_checks(analysis, issues))
            sheet.setPlainText(exportmod.prep_sheet(proj, [], analysis, issues, [out.text()]))

        def do_export():
            try:
                result = proj.export_gcode(out.text(), post.currentText(), args.text())
            except ExportBlocked as exc:
                checks.setHtml(_format_checks(exc.analysis, exc.issues))
                tabs.setCurrentWidget(checks)
                _warn(tr("Export blocked by the checks: {errors}", errors=str(exc)))
                return
            except Exception as exc:
                _warn(tr("Export failed: {error}", error=str(exc)))
                return
            preview.setPlainText(result["gcode"])
            checks.setHtml(_format_checks(result["analysis"], result["issues"]))
            sheet.setPlainText(result["sheet_text"])
            _info(tr("Written: {files}\nSetup sheet: {sheet}\nLoad the file in CNCjs yourself; nothing is sent automatically.",
                     files=", ".join(result["files"]), sheet=result["sheet"]))
            panels.refresh_project_panel()

        b_prev.clicked.connect(do_preview)
        b_exp.clicked.connect(do_export)
        b_close.clicked.connect(dlg.accept)
        do_preview()
        exec_dialog(dlg)


def _format_checks(analysis, issues):
    """Contrôles en HTML : erreurs en rouge, « non vérifiable » en ambre, avertissements en orange."""
    import html

    colors = {"error": "#e06060", "warning": "#e0a050", "unverifiable": "#e0c060", "info": "#9aa7b8", "ok": "#5ec8a0"}
    lines = [html.escape(tr("Lines: {n}, units: {u}, axes: {a}", n=analysis["lines"], u=analysis["units"],
                            a=" ".join(analysis["axes"]))),
             html.escape(tr("Codes: {c}", c=" ".join(analysis["codes"])))]
    for axis, (lo, hi) in sorted(analysis["bbox"].items()):
        lines.append("%s: %.3f .. %.3f" % (axis, lo, hi))
    lines.append("")
    if not issues:
        lines.append("<span style='color:%s'>%s</span>" % (colors["ok"], html.escape(tr("No issue found (see the documentation for what is checked)."))))
    for level, msg in issues:
        color = colors.get(level, colors["info"])
        lines.append("<span style='color:%s'><b>[%s]</b> %s</span>" % (color, html.escape(tr(level).upper()), html.escape(msg)))
    return "<html><body style='font-family: monospace'>" + "<br>".join(lines) + "</body></html>"


class Simulate(_Base):
    icon = "cam2027-simulate.svg"
    accel = "Ctrl+Shift+S"
    text = "Simulate"
    tooltip = "Simulate material removal with the FreeCAD CAM simulator"

    def Activated(self):
        proj = _need_project()
        if proj is None:
            return
        if not proj.has_job or not proj.operations():
            _warn(tr("No operation to simulate."))
            return
        commands = FreeCADGui.listCommands()
        name = next((c for c in ("CAM_SimulatorGL", "CAM_Simulator") if c in commands), None)
        if name is None:
            _warn(tr("No simulator command is available in this FreeCAD (expected CAM_SimulatorGL or CAM_Simulator)."))
            return
        proj.doc.recompute()
        FreeCADGui.Selection.clearSelection()
        FreeCADGui.Selection.addSelection(proj.job)
        FreeCADGui.runCommand(name)


class Machine(_Base):
    icon = "cam2027-machine.svg"
    accel = "Ctrl+Shift+M"
    text = "Machine profile"
    tooltip = "Travels, feeds, spindle, controller, rotary axis (unknown values stay empty)"

    def Activated(self):
        proj = _need_project()
        if proj is None:
            return
        m = proj.machine
        dlg = QtWidgets.QDialog(FreeCADGui.getMainWindow())
        dlg.setWindowTitle(tr("Machine profile"))
        form = QtWidgets.QFormLayout(dlg)
        widgets = {}
        for key, label in (("name", "Name"), ("vendor", "Vendor"), ("model", "Model"), ("controller", "Controller"),
                           ("post_processor", "Post processor"), ("post_processor_args", "Post arguments"),
                           ("travel_x_mm", "Travel X (mm)"), ("travel_y_mm", "Travel Y (mm)"), ("travel_z_mm", "Travel Z (mm)"),
                           ("max_feed_xy_mm_min", "Max feed XY (mm/min)"), ("max_feed_z_mm_min", "Max feed Z (mm/min)"),
                           ("spindle_min_rpm", "Spindle min (rpm)"), ("spindle_max_rpm", "Spindle max (rpm)"),
                           ("spindle_power_w", "Spindle power (W)"), ("collet", "Collet"), ("notes", "Notes")):
            w = QtWidgets.QLineEdit("" if getattr(m, key) is None else str(getattr(m, key)))
            w.setPlaceholderText(tr("to fill in"))
            form.addRow(tr(label), w)
            widgets[key] = w
        rot = QtWidgets.QCheckBox(tr("Rotary axis A present (about X)"))
        rot.setChecked(bool(m.rotary.present))
        form.addRow(rot)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        if exec_dialog(dlg) != QtWidgets.QDialog.Accepted:
            return
        d = m.to_dict()
        numeric = ("travel_x_mm", "travel_y_mm", "travel_z_mm", "max_feed_xy_mm_min", "max_feed_z_mm_min",
                   "spindle_min_rpm", "spindle_max_rpm", "spindle_power_w")
        try:
            for key, w in widgets.items():
                text = w.text().strip()
                if key in numeric:
                    d[key] = float(text.replace(",", ".")) if text else None
                else:
                    d[key] = text or (None if key in ("post_processor", "collet") else "")
            d["rotary"]["present"] = rot.isChecked()
            new = MachineProfile.from_dict(d)
        except ValueError as exc:
            _warn(str(exc))
            return
        proj.set_machine(new)
        if proj.has_job and new.post_processor:
            try:
                proj.job.PostProcessor = new.post_processor
                proj.job.PostProcessorArgs = new.post_processor_args or ""
            except Exception as exc:
                _warn(str(exc))
        _after_change()


class About(_Base):
    icon = "cam2027-about.svg"
    text = "About CAM2027"
    tooltip = "Version, environment and limits"

    def Activated(self):
        env = compat.environment_report()
        text = "\n".join([
            "CAM2027 %s (pinned FreeCAD base: %s)" % (__version__, FREECAD_PINNED_TAG),
            tr("Running on FreeCAD {v} ({build})", v=env["freecad_version"], build=env["freecad_build"]),
            tr("Tool API: {api}, OpenCamLib: {ocl}", api=env["tool_api"], ocl=env["opencamlib"]),
            tr("User config: {dir}", dir=env["user_config_dir"]),
            tr("Logs: FreeCAD.log in the user config directory (launcher starts FreeCAD with -l)."),
            "",
            tr("Not available yet: 3D surfacing in this workbench, 4th axis, simulation with material removal, collision checks."),
        ])
        _info(text)


COMMANDS = [
    ("CAM2027_NewProject", NewProject),
    ("CAM2027_ImportModel", ImportModel),
    ("CAM2027_ToolLibrary", ToolLibrary),
    ("CAM2027_StockFixture", StockFixture),
    ("CAM2027_AddOperation", AddOperation),
    ("CAM2027_Compute", Compute),
    ("CAM2027_Export", Export),
    ("CAM2027_Simulate", Simulate),
    ("CAM2027_Machine", Machine),
    ("CAM2027_About", About),
]
TOOLBAR = [name for name, _cls in COMMANDS]
MENU = TOOLBAR

_registered = False


def register():
    global _registered
    if _registered:
        return
    for name, cls in COMMANDS:
        FreeCADGui.addCommand(name, cls())
    _registered = True
