# SPDX-License-Identifier: LGPL-2.1-or-later
"""Commandes de l'atelier (barre d'outils et menu)."""

import os

import FreeCAD
import FreeCADGui

from .qt import QtCore, QtGui, QtWidgets, exec_dialog
from ..i18n import tr, tr_msg
from .labels import preset_label
from .. import compat
from ..version import __version__, FREECAD_PINNED_TAG
from ..project.project import Project, ExportBlocked
from ..project.operations import STRATEGIES, DEFAULT_THREAD_TYPE, thread_names
from ..project.importers import SUPPORTED_EXTENSIONS
from ..project import export as exportmod
from ..project import undo
from ..project.machine import MachineProfile
from . import state, panels, standalone, theme, welcome

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


class busy(object):
    """Curseur d'attente + message dans la barre d'état pendant une action longue (import, calcul...).

    ``stoppable`` (projet) : fenêtre de progression avec « Arrêter le calcul » ; l'adaptative de FreeCAD rend
    la main à l'interface pendant son calcul et s'arrête quand ``StopProcessing`` passe à vrai."""

    def __init__(self, message, stoppable=None):
        self.message = message
        self.project = stoppable
        self.dialog = None
        self.stopped = False

    def __enter__(self):
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            FreeCADGui.getMainWindow().statusBar().showMessage(self.message)
        except Exception:
            pass
        if self.project is not None:
            self.dialog = QtWidgets.QProgressDialog(self.message, tr("Stop the computation"), 0, 0,
                                                    FreeCADGui.getMainWindow())
            self.dialog.setWindowTitle("CAM2027")
            self.dialog.setMinimumDuration(0)
            self.dialog.setWindowModality(QtCore.Qt.WindowModal)
            self.dialog.canceled.connect(self.stop)
            self.dialog.show()
        QtWidgets.QApplication.processEvents()
        return self

    def stop(self):
        self.stopped = True
        try:
            for op in self.project.operations():
                base = self.project.base_operation(op)
                if "StopProcessing" in base.PropertiesList:
                    base.StopProcessing = True
        except Exception:
            pass

    def __exit__(self, *_exc):
        if self.dialog is not None:
            self.dialog.canceled.disconnect(self.stop)
            self.dialog.close()
            self.dialog.deleteLater()
        QtWidgets.QApplication.restoreOverrideCursor()
        try:
            FreeCADGui.getMainWindow().statusBar().clearMessage()
        except Exception:
            pass
        if self.stopped:
            _warn(tr("Computation stopped: the operations concerned have an incomplete toolpath (recompute them later)."))
        return False


#: au-delà, le brut simulé affiché est simplifié (erreur 0,01 mm) : 700 000 triangles alourdissaient la vue 3D
DISPLAY_MESH_MAX_FACETS = 100000


def _display_mesh(mesh):
    """Maillage pour l'affichage seulement : zones planes simplifiées (``decimate``, 0,01 mm au plus), 10 fois
    moins de triangles sur une grande pièce ; le contrôle garde sa carte de hauteur complète."""
    if mesh.CountFacets > DISPLAY_MESH_MAX_FACETS:
        try:
            mesh.decimate(0.01, 0.9)
        except Exception:
            pass
    return mesh


def _after_change():
    if FreeCAD.ActiveDocument:
        FreeCAD.ActiveDocument.recompute()
    panels.refresh_project_panel()


#: stratégie -> icône « Atelier »
STRATEGY_ICONS = {
    "profile": "contour", "pocket": "pocket", "pocket2d": "pocket", "adaptive": "pocket", "drilling": "drill",
    "millface": "surface", "engrave": "engrave", "vcarve": "engrave", "chamfer": "engrave", "helix": "drill",
    "slot": "contour", "threadmill": "drill", "surface3d": "surface", "waterline": "surface", "rough3d": "pocket",
}


def _undoable(activated):
    """Commande qui modifie le projet : une étape d'annulation (Ctrl+Z), nommée comme la commande."""
    def run(self, *args):
        with undo.transaction(FreeCAD.ActiveDocument, tr(self.text)):
            return activated(self, *args)
    return run


class _Base(object):
    icon = "CAM2027.svg"
    text = ""
    tooltip = ""

    accel = ""

    atelier = ""  # icône de la direction artistique « Atelier » (Resources/icons/atelier)

    def GetResources(self):
        pixmap = _icon(self.icon)
        if self.atelier:
            try:
                pixmap = theme.icon_path(self.atelier)
            except FileNotFoundError:
                pass
        res = {"Pixmap": pixmap, "MenuText": tr(self.text), "ToolTip": tr(self.tooltip)}
        if self.accel:
            res["Accel"] = self.accel
        return res

    def IsActive(self):
        return True


class NewProject(_Base):
    icon = "cam2027-new-project.svg"
    atelier = "new-project"
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
    atelier = "open-project"
    accel = "Ctrl+Shift+I"
    text = "Import model / drawing"
    tooltip = "Import STEP, STL, OBJ, SVG or DXF into the project"

    @_undoable
    def Activated(self):
        from ..project import relief

        exts = SUPPORTED_EXTENSIONS + relief.IMAGE_EXTENSIONS
        filt = tr("Models and drawings") + " (" + " ".join("*" + e for e in exts) + ")"
        path, _f = QtWidgets.QFileDialog.getOpenFileName(FreeCADGui.getMainWindow(), tr("Import a file"), "", filt)
        if not path:
            return
        proj = state.active_project()
        if proj is None:  # pas encore de projet : il est créé au nom du fichier (un clic de moins)
            proj = Project.create(os.path.splitext(os.path.basename(path))[0], state.library())
            FreeCADGui.ActiveDocument = FreeCADGui.getDocument(proj.doc.Name)
            panels.ensure_project_panel()
        if os.path.splitext(path)[1].lower() in relief.IMAGE_EXTENSIONS:
            import_relief_dialog(proj, path)  # une image devient un relief 3D
            return
        try:
            with busy(tr("Importing {file}...", file=os.path.basename(path))):
                res = proj.import_model(path)
        except Exception as exc:  # erreurs OCC / lecteurs
            _warn(tr("Import failed: {error}", error=tr_msg(exc)))
            return
        FreeCADGui.SendMsgToActiveView("ViewFit")
        _after_change()
        shown = [o.Label for o in res.objects if o.TypeId.startswith(("Part::", "Mesh::"))]  # pas les repères du STEP
        lines = [tr("Imported: {objects}", objects=", ".join(shown) or "-")]
        if res.kind == "vector":
            lines.append(tr("2D drawing: next, Stock & fixture > Sheet under the 2D drawing."))
        lines += [tr_msg(w) for w in res.warnings]
        if res.warnings or res.kind == "vector":
            _info("\n".join(lines))


def import_relief_dialog(proj, path=""):
    """Dialogue relief puis création ; retourne l'objet créé ou None."""
    from .reliefdlg import ReliefDialog

    dlg = ReliefDialog(FreeCADGui.getMainWindow(), path)
    if exec_dialog(dlg) != QtWidgets.QDialog.Accepted:
        return None
    opts = dlg.options()
    try:
        res = proj.import_relief(opts.pop("path"), opts.pop("width"), opts.pop("relief_height"), **opts)
    except Exception as exc:
        _warn(tr("Import failed: {error}", error=tr_msg(exc)))
        return None
    if res.warnings:
        _info("\n".join(tr_msg(w) for w in res.warnings))
    FreeCADGui.SendMsgToActiveView("ViewFit")
    _after_change()
    return res.objects[0]


class ImportRelief(_Base):
    atelier = "surface"
    text = "Relief from image"
    tooltip = "Build a 3D relief from a grey-level image (PNG, JPG, BMP): light = high"

    @_undoable
    def Activated(self):
        proj = _need_project()
        if proj is None:
            return
        import_relief_dialog(proj)


class ToolLibrary(_Base):
    icon = "cam2027-tool-library.svg"
    atelier = "tool-library"
    accel = "Ctrl+Shift+T"
    text = "Tool library"
    tooltip = "Tools, holders, assemblies and cutting presets"

    def Activated(self):
        panels.show_tool_library()


#: au-delà, la fusion des corps d'un assemblage est trop lente (STEP de 37 000 faces : environ 1 min)
MERGE_MAX_FACES = 20000


class StockFixture(_Base):
    icon = "cam2027-stock.svg"
    atelier = "stock"
    accel = "Ctrl+Shift+B"
    text = "Stock & fixture"
    tooltip = "Create the job (if needed), define the stock and the work coordinate system"

    @_undoable
    def Activated(self):
        proj = _need_project()
        if proj is None:
            return
        dlg = QtWidgets.QDialog(FreeCADGui.getMainWindow())
        theme.apply(dlg)
        dlg.setWindowTitle(tr("Stock & fixture"))
        form = QtWidgets.QFormLayout(dlg)
        kind = QtWidgets.QComboBox()
        kind.addItem(tr("Box around the model with margins"), "box_margins")
        kind.addItem(tr("Explicit box"), "box")
        kind.addItem(tr("Cylinder (rotary / round stock)"), "cylinder")
        kind.addItem(tr("Sheet under the 2D drawing (top at Z 0)"), "sheet")
        kind.addItem(tr("Round bar along X on the A axis (4th axis)"), "cylinder_x")
        from ..project import sheet as sheetmod

        if not proj.has_job and sheetmod.vector_objects(proj.doc) and not proj.model_candidates():
            kind.setCurrentIndex(kind.findData("sheet"))  # seulement des dessins 2D : panneau
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
        # seulement les champs du type de brut choisi
        fields = {"box_margins": (xy, ztop, zbot), "box": (length, width, height), "cylinder": (radius, height),
                  "sheet": (thickness, sheet_margin), "cylinder_x": (radius, xy)}
        all_fields = {w for ws in fields.values() for w in ws}

        def show_fields(_i=None):
            wanted = set(fields.get(kind.currentData(), ()))
            for w in all_fields:
                w.setVisible(w in wanted)
                label = form.labelForField(w)
                if label is not None:
                    label.setVisible(w in wanted)
            dlg.adjustSize()

        kind.currentIndexChanged.connect(show_fields)
        show_fields()
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
                _warn(tr_msg(exc))
                return
            FreeCADGui.SendMsgToActiveView("ViewFit")
            _after_change()
            return
        if k == "cylinder_x":
            centre = proj.machine.rotary.center_offset_mm
            if centre is None:
                _warn(tr("Fill in the A axis centre in the machine profile first."))
                return
            models = [o for o in FreeCADGui.Selection.getSelection() if getattr(o, "Shape", None)] or \
                proj.model_candidates()
            if proj.has_job:
                models = [c for c in proj.job.Model.Group]
            if not models:
                _warn(tr("Select or import a solid model first."))
                return
            box = models[0].Shape.BoundBox
            for o in models[1:]:
                box.add(o.Shape.BoundBox)
            spec = {"kind": k, "radius": radius.value(), "length": box.XLength + 2 * xy.value(),
                    "x_start": box.XMin - xy.value(), "center": tuple(centre)}
        elif k == "box_margins":
            spec = {"kind": k, "xy": xy.value(), "z_top": ztop.value(), "z_bottom": zbot.value()}
        elif k == "box":
            spec = {"kind": k, "length": length.value(), "width": width.value(), "height": height.value()}
        else:
            spec = {"kind": k, "radius": radius.value(), "height": height.value()}
        try:
            if not proj.has_job:
                candidates = proj.model_candidates()
                sel = [o for o in FreeCADGui.Selection.getSelection() if o in candidates]
                if not sel:
                    sel = candidates
                    if len(sel) > 1 and all(o.TypeId.startswith("Part::") for o in sel):
                        unique = proj.unique_bodies(sel)
                        if len(unique) < len(sel):
                            _info(tr("{n} duplicate bodies ignored (file imported twice?).", n=len(sel) - len(unique)))
                        sel = unique
                    faces = sum(len(o.Shape.Faces) for o in sel if hasattr(o, "Shape"))
                    if len(sel) > 1 and all(o.TypeId.startswith("Part::") for o in sel):
                        if faces <= MERGE_MAX_FACES:
                            with busy(tr("Merging the {n} bodies into one part...", n=len(sel))):
                                merged = proj.merge_models(sel, proj.doc.Label)
                            if merged is not None:
                                sel = [merged]
                            else:
                                _info(tr("The {n} bodies could not be merged into one solid: they are machined as separate parts.", n=len(sel)))
                        else:
                            _info(tr("{n} bodies ({f} faces): too large to merge, they are machined as separate parts. To machine only some of them, select them before Stock & fixture.",
                                     n=len(sel), f=faces))
                if not sel:
                    from ..project import sheet as sheetmod

                    if sheetmod.vector_objects(proj.doc):
                        _warn(tr("The project only has 2D drawings: choose the stock type 'Sheet under the 2D drawing'."))
                    else:
                        _warn(tr("Import a part (STEP, STL, OBJ) or a drawing (SVG, DXF) first."))
                    return
                proj.create_job(sel, stock=spec, fixtures=[fixture.currentText()])
            else:
                proj.set_stock(spec)
                from ..project.stock import set_fixtures

                set_fixtures(proj.job, [fixture.currentText()])
        except Exception as exc:
            _warn(tr_msg(exc))
            return
        _after_change()


class AddOperation(_Base):
    icon = "cam2027-add-operation.svg"
    atelier = "contour"
    accel = "Ctrl+Shift+O"
    text = "Add operation"
    tooltip = "Add a machining operation using a tool assembly and a cutting preset"

    @_undoable
    def Activated(self):
        proj = _need_project()
        if proj is None:
            return
        if not proj.has_job:
            _warn(tr("Define the stock & fixture first (this creates the job)."))
            return
        # outils créés dans la bibliothèque depuis la création du projet : ajoutés à son instantané
        user = state.library()
        if any(user.ensure_usable(tid, tr("New preset")) for tid in list(user.tools)):
            try:
                user.save()
            except (ValueError, OSError):
                pass
        proj.merge_library(user)
        lib = proj.library
        sel = FreeCADGui.Selection.getSelectionEx()
        base = []
        ignored = {proj.job.Name, getattr(proj.job.Stock, "Name", "")}
        for s in sel:
            if s.Object.Document.Name == proj.doc.Name and getattr(s.Object, "Shape", None) \
                    and s.Object.Name not in ignored:
                base.append((s.Object, list(s.SubElementNames)))
        dlg = QtWidgets.QDialog(FreeCADGui.getMainWindow())
        theme.apply(dlg)
        dlg.setWindowTitle(tr("Add operation"))
        form = QtWidgets.QFormLayout(dlg)
        name = QtWidgets.QLineEdit()
        name.setProperty("auto", True)
        name.textEdited.connect(lambda _t: name.setProperty("auto", False))  # nom tapé : ne plus le remplacer
        form.addRow(tr("Name"), name)
        kind = QtWidgets.QComboBox()
        for key, meta in STRATEGIES.items():
            kind.addItem(theme.icon(STRATEGY_ICONS.get(key, "contour")), tr(meta["label"]), key)
        form.addRow(tr("Strategy"), kind)
        limits = QtWidgets.QLabel()
        limits.setWordWrap(True)
        form.addRow(tr("Known limits"), limits)
        from .toolpicker import ToolField

        asm = ToolField(proj)  # comme Fusion : Sélectionner… / Éditer…, outils du document en liste
        form.addRow(tr("Tool"), asm)
        tool_note = QtWidgets.QLabel()
        tool_note.setWordWrap(True)
        theme.set_role(tool_note, "warning")
        form.addRow(tool_note)
        from ..project import operations as opsmod

        def on_strategy(_i=None):
            k = kind.currentData()
            limits.setText(tr(STRATEGIES[k]["limits"]) or "-")
            asm.blockSignals(True)
            asm.set_kind(k)
            asm.blockSignals(False)
            ok = asm.tool() is not None and opsmod.tool_fits(k, asm.tool())
            tool_note.setText("" if ok else tr("No tool of the right type for this strategy: click Select... to choose one or create a new one."))
            tool_note.setVisible(not ok)
            fill_presets()
            if name.property("auto"):
                label = tr(STRATEGIES[k]["label"]).split(" (")[0]
                used = {o.Label for o in proj.operations()}
                n = 1
                while ("%s %d" % (label, n)) in used:
                    n += 1
                name.setText("%s %d" % (label, n))
        preset = QtWidgets.QComboBox()
        form.addRow(tr("Cutting preset"), preset)

        def fill_presets():
            preset.clear()
            tool = asm.tool()
            if tool is None:
                return
            for p in tool.presets:
                preset.addItem(preset_label(p), p.id)
            ok = opsmod.tool_fits(kind.currentData(), tool)
            tool_note.setText("" if ok else tr("No tool of the right type for this strategy: click Select... to choose one or create a new one."))
            tool_note.setVisible(not ok)

        asm.changed.connect(fill_presets)
        kind.currentIndexChanged.connect(on_strategy)
        on_strategy()
        sel_label = QtWidgets.QLabel(", ".join("%s: %s" % (o.Label, " ".join(subs) or tr("whole")) for o, subs in base)
                                     or tr("(nothing selected: whole part, or pocket floors / top faces found automatically)"))
        sel_label.setWordWrap(True)
        form.addRow(tr("Geometry (selection)"), sel_label)
        index = QtWidgets.QDoubleSpinBox()
        index.setRange(-361.0, 360.0)
        index.setDecimals(3)
        index.setSuffix(" °")
        index.setSpecialValueText(tr("(none: 3 axes)"))
        index.setValue(index.minimum())
        index.setToolTip(tr("Indexed 4th axis: the part is turned to this A angle, then machined in 3 axes. Select the faces or edges on the part as it is shown."))
        index.setEnabled(bool(proj.machine.rotary.present))
        form.addRow(tr("A index (deg)"), index)
        hint = QtWidgets.QLabel(tr("Depths, passes and strategy settings are edited in the next window (tabs), with values prefilled from the cutting preset."))
        hint.setWordWrap(True)
        theme.set_role(hint, "muted")
        form.addRow(hint)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        if exec_dialog(dlg) != QtWidgets.QDialog.Accepted:
            return
        if asm.currentData() is None or preset.currentData() is None:
            _warn(tr("No tool of the right type for this strategy: click Select... to choose one or create a new one."))
            return
        lib = proj.library  # l'instantané a pu recevoir l'outil choisi
        a, tool, _h = lib.resolve_assembly(asm.currentData())
        values = tool.preset(preset.currentData()).resolve(tool)
        k = kind.currentData()
        params = default_params(k, tool, values)
        if k == "millface" and base and all(not subs for _o, subs in base):
            base = []  # pièce sélectionnée en entier : comme sans sélection (faces du dessus, sinon dessus du brut)
        explicit = bool(base)
        if not base:
            models = list(proj.job.Model.Group)  # toute la pièce : chaque objet du modèle, pas seulement le premier
            auto = opsmod.auto_geometry(k, models)
            if auto is None:
                base = [(m, []) for m in models]
            elif auto:
                base = auto
            elif k == "millface":
                # pas de face plane au sommet (surface 3D d'un STL, dessus bombé) : comme le surfaçage de Fusion,
                # le dessus du brut est surfacé jusqu'au haut de la pièce, sur tout le brut
                base = [(proj.job.Stock, [opsmod.stock_top_face(proj.job.Stock)])]
                params.update({"BoundaryShape": "Stock",
                               "FinalDepth": max(m.Shape.BoundBox.ZMax for m in models)})
            else:
                _warn(tr("Nothing to machine found automatically for this strategy: select the faces in the 3D view (click, Ctrl+click), then add the operation."))
                return
        label = name.text().strip() or tr(STRATEGIES[k]["label"]).split(" (")[0]
        parts = [(label, base)]
        # fonds de poche à plusieurs hauteurs : chacun jusqu'à son fond, comme Fusion. FreeCAD les usine jusqu'au
        # plus haut ; avec le plus bas comme profondeur finale, il descend partout (entailles de 1 mm sur le
        # disque WobbleRing, 40 mm sur le chauffage) : une opération par hauteur.
        groups = opsmod.floor_groups(base) if k in ("pocket", "pocket2d", "adaptive") else None
        if groups and len(groups) > 1:
            parts = [(tr("{name} (Z {z} mm)", name=label, z="%.2f" % z), group) for z, group in groups]
        try:
            index_deg = index.value() if index.isEnabled() and index.value() > index.minimum() else None
            added_ops = []
            for part_label, part_base in parts:
                part_params = dict(params)
                if (not explicit and k in ("pocket2d", "adaptive") and opsmod.floor_groups(part_base)
                        and not opsmod.floors_have_islands(part_base)):
                    part_params.setdefault("UseOutline", True)  # trous débouchants laissés ouverts (Fusion)
                added_ops.append(proj.add_operation(k, part_label, a.id, preset.currentData(), base=part_base,
                                                    params=part_params, index_deg=index_deg))
            with busy(tr("Computing the toolpaths..."), stoppable=proj):
                proj.compute()
        except Exception as exc:
            _warn(tr("Operation failed: {error}", error=tr_msg(exc)))
            _after_change()
            return
        skipped = []
        if not explicit:
            failed = [o for o, _r in added_ops if proj.operation_state(o) == "failed"]
            skipped = [o.Label for o in failed]
            for o in failed:
                proj.remove_operation(o)
            added_ops = [(o, r) for o, r in added_ops if o not in failed]
        if added_ops and skipped:
            _info(tr("Left out, no toolpath with this tool (too narrow?): {names}", names=", ".join(skipped)))
        if not added_ops:
            _after_change()
            fit = opsmod.largest_tool_for(base) if k in ("pocket", "pocket2d", "adaptive") else None
            if fit is not None and fit < tool.geometry.diameter:
                _warn(tr("The {d} mm tool is too large for the pockets found on the part (largest tool that fits: {fit} mm): choose a smaller tool, or select the faces to machine.",
                         d="%g" % tool.geometry.diameter, fit="%.1f" % fit))
                return
            _warn(tr("This strategy produced no toolpath on the whole part: select the faces or edges to machine, then add the operation again."))
            return
        if len(added_ops) > 1:
            _after_change()
            _info(tr("One operation per pocket depth, each down to its own floor: {names}",
                     names=", ".join(o.Label for o, _r in added_ops)))
            return
        op, rec = added_ops[0]
        if rec["warnings"]:
            _info("\n".join(tr_msg(w) for w in rec["warnings"]))
        _after_change()
        from . import opeditor

        added = (proj.doc.UndoCount, tr(self.text))  # étape d'annulation de cet ajout (encore ouverte ici)

        def on_close(accepted):
            if not accepted:
                try:
                    doc = proj.doc
                    if (doc.UndoCount, (doc.UndoNames or [None])[0]) == added:
                        doc.undo()  # rien fait depuis l'ajout : on l'annule, comme s'il n'avait pas eu lieu
                    else:
                        with undo.transaction(doc, tr("Delete")):
                            proj.remove_operation(op)
                except Exception as exc:
                    _warn(tr("Operation failed: {error}", error=tr_msg(exc)))
                _after_change()

        opeditor.open_editor(proj, op, on_close=on_close, title=tr("New operation: {name}", name=op.Label))


class WrapEngrave(_Base):
    atelier = "axis-a"
    text = "Wrapped engraving (A axis)"
    tooltip = "Engrave an unrolled drawing around the round stock: X, Z and A move together (continuous 4th axis, G93)"

    @_undoable
    def Activated(self):
        proj = _need_project()
        if proj is None:
            return
        if not proj.has_job:
            _warn(tr("Define the stock & fixture first (this creates the job)."))
            return
        open_wrap_dialog(proj)


def open_wrap_dialog(proj, op=None):
    """Création ou modification d'une gravure enroulée ; retourne l'opération ou None."""
    from .wrapdlg import WrapDialog

    selected = [s.Object for s in FreeCADGui.Selection.getSelectionEx() if s.Object.Document.Name == proj.doc.Name]
    dlg = WrapDialog(proj, FreeCADGui.getMainWindow(), selected=selected, op=op)
    if exec_dialog(dlg) != QtWidgets.QDialog.Accepted:
        return None
    try:
        with undo.transaction(proj.doc, dlg.windowTitle()):
            result = dlg.apply()
            proj.compute()
    except Exception as exc:
        _warn(tr("Operation failed: {error}", error=tr_msg(exc)))
        _after_change()
        return None
    rec = proj.registry.get(result.Name, {})
    if rec.get("warnings"):
        _info("\n".join(tr_msg(w) for w in rec["warnings"]))
    _after_change()
    return result


def _sheet_dialog(proj, dlg_cls, **kw):
    from . import sheetdlgs

    dlg = getattr(sheetdlgs, dlg_cls)(proj, FreeCADGui.getMainWindow(), **kw)
    if exec_dialog(dlg) != QtWidgets.QDialog.Accepted:
        return None
    QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
    try:
        result = dlg.apply()
        if proj.has_job:
            proj.compute()
    except Exception as exc:
        _warn(tr("Operation failed: {error}", error=tr_msg(exc)))
        return None
    finally:
        QtWidgets.QApplication.restoreOverrideCursor()
    _after_change()
    return result


class FlatDepth(_Base):
    atelier = "pocket"
    text = "Flat depth clearing (V-carve)"
    tooltip = "Clear the wide areas of a limited-depth V-carve with a flat end mill, with V-bit outline and sharp corners"

    @_undoable
    def Activated(self):
        proj = _need_project()
        if proj is None or not proj.has_job:
            return
        sel = [s.Object for s in FreeCADGui.Selection.getSelectionEx() if s.Object.Document.Name == proj.doc.Name]
        _sheet_dialog(proj, "FlatDepthDialog", selected_op=sel[0] if sel else None)


class Inlay(_Base):
    atelier = "engrave"
    text = "V inlay (male / female)"
    tooltip = "Female V pocket in this project and mirrored male plug in a new project, with glue gap"

    @_undoable
    def Activated(self):
        proj = _need_project()
        if proj is None:
            return
        if not proj.has_job:
            _warn(tr("Define the stock & fixture first (this creates the job)."))
            return
        sel = [s.Object for s in FreeCADGui.Selection.getSelectionEx() if s.Object.Document.Name == proj.doc.Name]
        res = _sheet_dialog(proj, "InlayDialog", selected=sel)
        if res:
            male = res["male_project"]
            with busy(tr("Computing the toolpaths...")):
                male.compute()
                proj.compute()
            # la femelle reste le document de travail ; le mâle est ouvert à côté (onglet)
            FreeCAD.setActiveDocument(proj.doc.Name)
            FreeCADGui.ActiveDocument = FreeCADGui.getDocument(proj.doc.Name)
            _after_change()
            failed = [o.Label for p in (proj, male) for o in p.operations() if p.operation_state(o) == "failed"]
            lines = [tr("Male plug created in the new project {name}: save it, it is machined on another board.",
                        name=male.doc.Label),
                     tr("Glue gap at the bottom: {b} mm; gap between the boards: {s} mm.",
                        b="%.2f" % res["bottom_gap"], s="%.2f" % res["surface_gap"])] + [tr_msg(n) for n in res["notes"]]
            if failed:
                lines.append(tr("Operations without a valid toolpath: {names}", names=", ".join(failed)))
                _warn("\n".join(lines))
            else:
                _info("\n".join(lines))


class Nest(_Base):
    atelier = "measure"
    text = "Nest parts on a sheet"
    tooltip = "Place the 2D drawings on a sheet of a given size (bounding rectangles, 90° rotation, copies)"

    @_undoable
    def Activated(self):
        proj = _need_project()
        if proj is None:
            return
        if proj.has_job:
            _warn(tr("Nesting is done before Stock & fixture (the job is already created)."))
            return
        rep = _sheet_dialog(proj, "NestDialog")
        if rep:
            lines = [tr("Placed: {n} part(s), sheet use {u} %.", n=len(rep["placed"]), u="%.0f" % (100 * rep["utilization"]))]
            if rep["unplaced"]:
                lines.append(tr("Not placed (no room): {parts}", parts=", ".join(rep["unplaced"])))
            lines.append(tr("Next: Stock & fixture > sheet under the 2D drawing (the sheet keeps the nesting size)."))
            _info("\n".join(lines))
            FreeCADGui.SendMsgToActiveView("ViewFit")


def default_params(kind, tool, values):
    """Paramètres initiaux d'une opération dérivés du préréglage (passe axiale, recouvrement, etc.)."""
    params = {"StepDown": values["axial_engagement_mm"]}
    stepover = max(1, min(100, int(round(100.0 * (values["radial_engagement_mm"] or tool.geometry.diameter * 0.4)
                                         / tool.geometry.diameter))))
    if kind in ("pocket", "millface", "adaptive", "helix", "rough3d"):
        params["StepOver"] = stepover
    if kind in ("adaptive", "rough3d"):
        # liaisons de l'adaptative « en zone dégagée » remontées d'une passe : à 0 (défaut FreeCAD) elles se font
        # à la profondeur de coupe, et l'adaptative en voit parfois une à travers de la matière (G0 dans 3 mm de
        # matière sur le chauffage Vz330)
        params["LiftDistance"] = values["axial_engagement_mm"]
        # hélice d'entrée comme Fusion : 0,95 x le diamètre, réduite région par région quand elle ne tient pas
        # (parallel_adaptive) ; une hélice fixe trop grande laissait 36 alvéoles pleines sur le plateau
        params["HelixDiameterLimit"] = round(0.95 * tool.geometry.diameter, 3)
    if kind == "millface":
        params["ClearEdges"] = True
    if kind == "surface3d":
        params.update({"StepOver": stepover, "CutPattern": "ZigZag", "SampleInterval": 0.05})
        params.pop("StepDown", None)  # passe unique de finition par défaut
    if kind == "waterline":
        params.update({"LayerMode": "Multi-pass", "SampleInterval": 0.5})
    if kind == "chamfer":
        params["Width"] = 1.0
    if kind == "threadmill":
        names = thread_names(DEFAULT_THREAD_TYPE)
        params["ThreadType"] = DEFAULT_THREAD_TYPE
        params["ThreadName"] = "M6 x 1" if "M6 x 1" in names else names[0]
    return params


class TwoSided(_Base):
    atelier = "stock"
    text = "Two-sided machining"
    tooltip = "Machine the part on both sides: side B is the part turned over (flip about X or Y), with dowel pins or the same corner"

    @_undoable
    def Activated(self):
        proj = _need_project()
        if proj is None:
            return
        if not proj.has_job:
            _warn(tr("Define the stock & fixture first (this creates the job)."))
            return
        from . import twosided as tsgui

        dlg = tsgui.TwoSidedDialog(proj, FreeCADGui.getMainWindow())
        if exec_dialog(dlg) != QtWidgets.QDialog.Accepted:
            return
        try:
            dlg.apply()
        except Exception as exc:
            _warn(tsgui.describe_error(exc))
            return
        _after_change()
        _info(tr("Side B created. Switch between side A and side B in the Project panel."))


class KeepOut(_Base):
    atelier = "stop"
    text = "Keep-out zones"
    tooltip = "Boxes the rapid moves go over (clamps, drawn zones); a cut entering a zone blocks the export"

    @_undoable
    def Activated(self):
        proj = _need_project()
        if proj is None:
            return
        if not proj.has_job:
            _warn(tr("Define the stock & fixture first (this creates the job)."))
            return
        from . import keepout as kogui

        dlg = kogui.KeepOutDialog(proj, FreeCADGui.getMainWindow())
        if exec_dialog(dlg) != QtWidgets.QDialog.Accepted:
            return
        with busy(tr("Computing the toolpaths...")):
            dlg.apply()
            proj.compute()
        _after_change()
        from ..project import keepout

        errors = keepout.issues(proj)
        if errors:
            _warn("\n".join(tr_msg(m) for _lvl, m in errors))


class Compute(_Base):
    icon = "cam2027-compute.svg"
    atelier = "recalculate"
    accel = "Ctrl+Shift+R"
    text = "Recompute toolpaths"
    tooltip = "Recompute every operation and refresh the summary"

    def Activated(self):
        proj = _need_project()
        if proj is None:
            return
        if not proj.has_job:
            _warn(tr("Define the stock & fixture first (this creates the job)."))
            return
        with busy(tr("Computing the toolpaths..."), stoppable=proj):
            results = proj.compute()
        bad = [r["name"] for r in results if not r["valid"] or r["commands"] == 0]
        if bad:
            _warn(tr("Operations without a valid toolpath: {names}", names=", ".join(bad)))
        _after_change()


class Export(_Base):
    icon = "cam2027-export.svg"
    atelier = "export-gcode"
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
        theme.apply(dlg)
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
        summary = QtWidgets.QTextEdit(); summary.setReadOnly(True)
        tabs.addTab(summary, tr("Summary before export"))
        tabs.addTab(preview, tr("G-code preview"))
        tabs.addTab(checks, tr("Checks"))
        tabs.addTab(sheet, tr("Setup sheet"))
        lay.addWidget(tabs)
        btns = QtWidgets.QHBoxLayout()
        b_prev = QtWidgets.QPushButton(tr("Preview"))
        b_exp = QtWidgets.QPushButton(tr("Export G-code"))
        b_exp.setIcon(theme.icon("export-gcode"))
        theme.set_role(b_exp, "primary")
        b_close = QtWidgets.QPushButton(tr("Close"))
        btns.addWidget(b_prev); btns.addWidget(b_exp); btns.addStretch(); btns.addWidget(b_close)
        lay.addLayout(btns)

        def do_preview():
            try:
                text, analysis, issues = proj.preview_gcode(post.currentText(), args.text())
            except Exception as exc:
                checks.setPlainText(tr("Post-processing failed: {error}", error=tr_msg(exc)))
                return
            preview.setPlainText(text)
            summary.setHtml(_format_summary(exportmod.export_summary(proj, analysis, issues)))
            checks.setHtml(_format_checks(analysis, issues))
            sheet.setPlainText(exportmod.prep_sheet(proj, [], analysis, issues, [out.text()]))

        def do_export():
            try:
                from ..project import twosided

                result = twosided.exporter(proj)(out.text(), post.currentText(), args.text())  # recto-verso : un fichier par face
            except ExportBlocked as exc:
                checks.setHtml(_format_checks(exc.analysis, exc.issues))
                tabs.setCurrentWidget(checks)
                _warn(tr("Export blocked by the checks: {errors}", errors="; ".join(tr_msg(m) for lvl, m in exc.issues if lvl == "error")))
                return
            except Exception as exc:
                _warn(tr("Export failed: {error}", error=tr_msg(exc)))
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


def _format_summary(rows):
    """Récapitulatif en HTML : un tableau libellé / valeur / niveau (texte + couleur)."""
    import html

    cells = []
    for label, value, level, params in rows:
        if label.startswith("Operation: "):
            label = tr("Operation: {name}", name=label[len("Operation: "):])
        else:
            label = tr(label)
        cells.append("<tr><td style='padding:2px 12px 2px 0'>%s</td><td><b>%s</b></td>"
                     "<td style='padding-left:12px;color:%s'>[%s]</td></tr>" % (
                         html.escape(label), html.escape(tr(value, **params)), theme.status_color(level),
                         html.escape(tr(level).upper())))
    return "<html><body><table>%s</table><p>%s</p></body></html>" % (
        "".join(cells), html.escape(tr("Exporting writes a file only. Nothing is sent to the machine.")))


def _format_checks(analysis, issues):
    """Contrôles en HTML : niveau en texte ET en couleur sémantique du thème (jamais la couleur seule)."""
    import html

    lines = [html.escape(tr("Lines: {n}, units: {u}, axes: {a}", n=analysis["lines"], u=analysis["units"],
                            a=" ".join(analysis["axes"]))),
             html.escape(tr("Codes: {c}", c=" ".join(analysis["codes"])))]
    for axis, (lo, hi) in sorted(analysis["bbox"].items()):
        lines.append("%s: %.3f .. %.3f mm" % (axis, lo, hi) if axis in "XYZ" else "%s: %.3f .. %.3f" % (axis, lo, hi))
    lines.append("")
    if not issues:
        lines.append("<span style='color:%s'>%s</span>" % (
            theme.status_color("ok"), html.escape(tr("No issue found among the checks performed (see the documentation for what is checked)."))))
    for level, msg in issues:
        lines.append("<span style='color:%s'><b>[%s]</b> %s</span>" % (
            theme.status_color(level), html.escape(tr(level).upper()), html.escape(tr_msg(msg))))
    return "<html><body style='font-family: Consolas, monospace'>" + "<br>".join(lines) + "</body></html>"


class Simulate(_Base):
    icon = "cam2027-simulate.svg"
    atelier = "play"
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
        for module in ("Path.Main.Gui.SimulatorGL", "Path.Main.Gui.Simulator"):  # l'atelier CAM peut être absent
            try:
                __import__(module)
            except Exception:
                pass
        commands = FreeCADGui.listCommands()
        name = next((c for c in ("CAM_SimulatorGL", "CAM_Simulator") if c in commands), None)
        if name is None:
            _warn(tr("No simulator command is available in this FreeCAD (expected CAM_SimulatorGL or CAM_Simulator)."))
            return
        proj.doc.recompute()
        FreeCADGui.Selection.clearSelection()
        FreeCADGui.Selection.addSelection(proj.job)
        if not free_task_panel():
            return
        if name == "CAM_SimulatorGL":
            excluded = start_simulator(proj)
            if excluded:
                _info(tr("Not simulated (the FreeCAD simulator ignores the A axis): {ops}", ops=", ".join(excluded)))
            return
        FreeCADGui.runCommand(name)


_simulation = None  # garde le simulateur en vie (sinon le ramasse-miettes ferme sa fenêtre)


def free_task_panel():
    """FreeCAD n'ouvre qu'un panneau de tâches à la fois : « Active task dialog found » au lancement du
    simulateur si un autre est ouvert. Le simulateur précédent est fermé ; un autre panneau (édition d'une
    opération FreeCAD...) n'est fermé qu'avec l'accord de l'utilisateur. Retourne True si la place est libre."""
    dialog = FreeCADGui.Control.activeDialog()
    if not dialog:
        return True
    previous = _simulation
    if previous is not None and getattr(previous, "taskForm", None) is not None:
        try:
            FreeCADGui.Control.closeDialog()
            QtWidgets.QApplication.processEvents()
            if not FreeCADGui.Control.activeDialog():
                return True
        except Exception:
            pass
    answer = QtWidgets.QMessageBox.question(
        FreeCADGui.getMainWindow(), "CAM2027",
        tr("Another task panel is open. Close it (unsaved changes in it are lost) and start the simulation?"),
        QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, QtWidgets.QMessageBox.No)
    if answer != QtWidgets.QMessageBox.Yes:
        return False
    FreeCADGui.Control.closeDialog()
    QtWidgets.QApplication.processEvents()
    return not FreeCADGui.Control.activeDialog()


def start_simulator(proj, play=True):
    """Simulateur d'enlèvement de matière de FreeCAD (fenêtre avec lecture / pause / pas à pas), réglé :
    opérations qui utilisent A décochées, lecture lancée. Retourne les libellés exclus."""
    global _simulation
    from Path.Main.Gui import SimulatorGL
    from ..project import indexing, wrap

    FreeCAD.setActiveDocument(proj.doc.Name)  # le simulateur liste les jobs de FreeCAD.ActiveDocument
    FreeCADGui.ActiveDocument = FreeCADGui.getDocument(proj.doc.Name)
    FreeCADGui.Selection.clearSelection()
    FreeCADGui.Selection.addSelection(proj.job)
    sim = SimulatorGL.CAMSimulation()
    sim.Activate()
    form = sim.taskForm.form
    reg = proj.registry
    excluded = []
    for i, op in enumerate(sim.operations):
        rec = reg.get(proj.base_operation(op).Name, {})
        uses_a = wrap.is_wrap_op(op) or indexing.is_index_op(op) or rec.get("index_deg") not in (None, 0, 0.0)
        if uses_a:
            form.listOperations.item(i).setCheckState(QtCore.Qt.CheckState.Unchecked)
            if not indexing.is_index_op(op):
                excluded.append(op.Label)
    _simulation = sim
    if play and form.toolButtonPlay.isEnabled():
        sim.SimPlay()
    return excluded


class MaterialCheck(_Base):
    atelier = "measure"
    text = "Material and collision check"
    tooltip = "Simulate material removal on a height map: gouges, stock left, flute length, tool holder and clamp collisions, rapids in the material"

    def Activated(self):
        proj = _need_project()
        if proj is None:
            return
        if not proj.has_job or not proj.operations():
            _warn(tr("No operation to simulate."))
            return
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            rep = proj.material_check()
            show_material_result(proj, rep)
        except Exception as exc:
            _warn(tr("Material check failed: {error}", error=tr_msg(exc)))
            return
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        _info(material_report_text(rep))


def show_material_result(proj, rep):
    """Brut simulé (gris) et entailles (rouge) dans la vue 3D ; objets hors job, remplacés à chaque contrôle."""
    import Mesh  # noqa: F401
    from ..project import sim

    doc = proj.doc
    objs = []
    for name, mesh, colour in (
            ("CAM2027SimStock", _display_mesh(sim.surface_mesh(proj.last_zmap)), (0.62, 0.66, 0.72)),
            ("CAM2027SimGouges", sim.surface_mesh(proj.last_zmap, sim.gouge_mask(proj.last_zmap, proj.last_heights,
                                                                                rep["tolerance"]), lift=0.02),
             (0.9, 0.15, 0.15))):
        obj = doc.getObject(name) or doc.addObject("Mesh::Feature", name)
        obj.Mesh = mesh
        obj.Label = tr("Simulated stock") if name == "CAM2027SimStock" else tr("Gouges")
        if FreeCAD.GuiUp and obj.ViewObject is not None:
            obj.ViewObject.ShapeColor = colour
            obj.ViewObject.Visibility = mesh.CountFacets > 0
        objs.append(obj)
    import Part

    events = [e for e in rep.get("collisions", {}).get("events", []) if e[3]]
    marker = doc.getObject("CAM2027SimCollisions") or doc.addObject("Part::Feature", "CAM2027SimCollisions")
    marker.Label = tr("Collisions")
    marker.Shape = Part.Compound([Part.makeSphere(2.0, FreeCAD.Vector(*e[3])) for e in events]) if events \
        else Part.Shape()
    if FreeCAD.GuiUp and marker.ViewObject is not None:
        marker.ViewObject.ShapeColor = (1.0, 0.1, 0.1)
        marker.ViewObject.Visibility = bool(events)
    objs.append(marker)
    doc.recompute()
    return objs


def material_report_text(rep):
    lines = [tr("Material check (height map, {res} mm grid, 3 axes)", res="%g" % rep["resolution"]),
             tr("Removed: {v} cm3", v="%.1f" % (rep["removed_volume"] / 1000.0))]
    if rep["gouge_max"] > rep["tolerance"]:
        x, y, _z = rep["gouge_at"]
        lines.append(tr("GOUGE: the tool cuts {d} mm into the part (worst at X {x} Y {y}, {n} cells)",
                        d="%.2f" % rep["gouge_max"], x="%.1f" % x, y="%.1f" % y, n=rep["gouge_cells"]))
    else:
        lines.append(tr("No gouge found on the top of the part (tolerance {t} mm)", t="%g" % rep["tolerance"]))
    if rep["part_cells"]:
        x, y, _z = rep["leftover_at"]
        lines.append(tr("Stock left on the part: max {m} mm (at X {x} Y {y}), mean {a} mm",
                        m="%.2f" % rep["leftover_max"], x="%.1f" % x, y="%.1f" % y, a="%.2f" % rep["leftover_mean"]))
    if rep["rapid_hits"]:
        lines.append(tr("RAPID MOVES IN THE MATERIAL: {n}", n=rep["rapid_hits"]))
    for label, reason in rep["skipped"]:
        lines.append(tr("Not simulated: {op} ({reason})", op=label, reason=tr_msg(reason)))
    for label, note in rep["approximations"]:
        lines.append(tr("Approximation: {op}: {note}", op=label, note=tr_msg(note)))
    col = rep.get("collisions")
    if col:
        words = {"ok": tr("OK"), "collision": tr("COLLISION"), "not_checked": tr("NOT CHECKED")}
        for key, label in (("flute_length", tr("Flute length (shank rubbing)")), ("holder", tr("Tool holder")),
                           ("clamps", tr("Clamps")), ("rapids", tr("Rapid moves"))):
            lines.append("%s : %s" % (label, words[col[key]]))
        if col["no_holder"]:
            lines.append(tr("No holder in the assembly: {ops}", ops=", ".join(col["no_holder"])))
        if not col["clamps_defined"]:
            lines.append(tr("No clamp defined: clamps not checked (Stock & fixture)."))
        kinds = {"flute_length": tr("material above the flute length"), "holder": tr("tool holder in the material"),
                 "clamp": tr("clamp"), "rapid": tr("rapid into the material"),
                 "undrilled": tr("thread milling in a hole that is not drilled (drill it first)")}
        for e in col["events"]:
            x, y, z = e[3] if e[3] else (0.0, 0.0, 0.0)
            what = kinds[e[0]] + (" %s (%s)" % (e[5], e[6]) if e[0] == "clamp" else "")
            lines.append(tr("COLLISION: {what} - {op}, command {n}, tip at X {x} Y {y} Z {z}",
                            what=what, op=e[1], n=e[2], x="%.2f" % x, y="%.2f" % y, z="%.2f" % z))
    from . import twosided as tsgui

    lines += tsgui.report_lines(rep)
    lines.append(tr("Not checked: vertical walls and undercuts (height map), A axis operations."))
    return "\n".join(lines)


class Theme(_Base):
    icon = "CAM2027.svg"
    atelier = "visibility"
    text = "Theme: system / dark / light"
    tooltip = "Cycle the CAM2027 panel theme (follows FreeCAD by default)"

    def Activated(self):
        order = list(theme.THEMES)
        nxt = order[(order.index(theme.preference()) + 1) % len(order)]
        theme.set_preference(nxt)
        panels.restyle_all()
        welcome.restyle()
        from . import prefs

        prefs.apply_scene_colors(nxt, force=prefs.launched_by_cam2027())  # nouveaux parcours
        FreeCAD.Console.PrintMessage(tr("CAM2027 theme: {name}", name=tr(nxt)) + "\n")


class Machine(_Base):
    icon = "cam2027-machine.svg"
    atelier = "settings"
    accel = "Ctrl+Shift+M"
    text = "Machine profile"
    tooltip = "Travels, feeds, spindle, controller, rotary axis (unknown values stay empty)"

    @_undoable
    def Activated(self):
        proj = _need_project()
        if proj is None:
            return
        m = proj.machine
        dlg = QtWidgets.QDialog(FreeCADGui.getMainWindow())
        theme.apply(dlg)
        dlg.setWindowTitle(tr("Machine profile"))
        outer = QtWidgets.QVBoxLayout(dlg)
        columns = QtWidgets.QHBoxLayout()
        outer.addLayout(columns)
        left = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(left)
        form.setContentsMargins(0, 0, 0, 0)
        columns.addWidget(left, 3)
        right = QtWidgets.QVBoxLayout()
        columns.addLayout(right, 2)
        widgets = {}
        from ..project.machine import FIELD_LABELS

        for key in ("name", "vendor", "model", "controller", "post_processor", "post_processor_args", "travel_x_mm",
                    "travel_y_mm", "travel_z_mm", "max_feed_xy_mm_min", "max_feed_z_mm_min", "spindle_min_rpm",
                    "spindle_max_rpm", "spindle_power_w", "collet", "notes"):
            label = FIELD_LABELS[key]
            w = QtWidgets.QLineEdit("" if getattr(m, key) is None else str(getattr(m, key)))
            w.setPlaceholderText(tr("to fill in"))
            w.setMinimumWidth(260)
            w.setCursorPosition(0)
            form.addRow(tr(label), w)
            widgets[key] = w
        rot = QtWidgets.QCheckBox(tr("Rotary axis A present (about X)"))
        rot.setChecked(bool(m.rotary.present))
        right.addWidget(rot)
        abox = QtWidgets.QGroupBox(tr("A axis (indexed 3+1 and continuous)"))
        aform = QtWidgets.QFormLayout(abox)
        direction = QtWidgets.QComboBox()
        direction.addItem(tr("to fill in"), None)
        direction.addItem(tr("Right hand: A+ counter-clockwise seen from +X"), "right_hand")
        direction.addItem(tr("Left hand: A+ clockwise seen from +X"), "left_hand")
        direction.setCurrentIndex(max(0, direction.findData(m.rotary.positive_direction)))
        aform.addRow(tr("A axis positive direction"), direction)
        centre = m.rotary.center_offset_mm or (None, None)
        a_fields = {}
        for key, label, value in (("cy", "A axis centre Y (mm)", centre[0]), ("cz", "A axis centre Z (mm)", centre[1]),
                                  ("min", "A axis min (deg)", m.rotary.min_deg), ("max", "A axis max (deg)", m.rotary.max_deg),
                                  ("feed", "A axis max feed (deg/min)", m.rotary.max_feed_deg_min)):
            w = QtWidgets.QLineEdit("" if value is None else str(value))
            w.setPlaceholderText(tr("to fill in"))
            aform.addRow(tr(label), w)
            a_fields[key] = w
        note = QtWidgets.QLabel(tr("The centre is the position of the rotation axis in the work coordinate system. Nothing is assumed: indexed operations are refused until the centre and the positive direction are filled in."))
        note.setWordWrap(True)
        theme.set_role(note, "muted")
        aform.addRow(note)
        abox.setEnabled(rot.isChecked())
        rot.toggled.connect(abox.setEnabled)
        right.addWidget(abox)
        right.addStretch(1)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        outer.addWidget(bb)
        if exec_dialog(dlg) != QtWidgets.QDialog.Accepted:
            return
        d = m.to_dict()
        numeric = ("travel_x_mm", "travel_y_mm", "travel_z_mm", "max_feed_xy_mm_min", "max_feed_z_mm_min",
                   "spindle_min_rpm", "spindle_max_rpm", "spindle_power_w")
        labels = dict(FIELD_LABELS, cy="A axis centre Y (mm)", cz="A axis centre Z (mm)", min="A axis min (deg)",
                      max="A axis max (deg)", feed="A axis max feed (deg/min)")

        def num(key, w):
            text = w.text().strip().replace(",", ".")
            if not text:
                return None
            try:
                return float(text)
            except ValueError:
                raise ValueError(tr("'{value}' is not a number: {field}", value=w.text().strip(), field=tr(labels[key])))

        try:
            for key, w in widgets.items():
                if key in numeric:
                    d[key] = num(key, w)
                else:
                    d[key] = w.text().strip() or (None if key in ("post_processor", "collet") else "")
            d["rotary"]["present"] = rot.isChecked()
            cy, cz = num("cy", a_fields["cy"]), num("cz", a_fields["cz"])
            d["rotary"]["center_offset_mm"] = (cy, cz) if cy is not None and cz is not None else None
            d["rotary"]["min_deg"] = num("min", a_fields["min"])
            d["rotary"]["max_deg"] = num("max", a_fields["max"])
            d["rotary"]["max_feed_deg_min"] = num("feed", a_fields["feed"])
            d["rotary"]["positive_direction"] = direction.currentData()
            new = MachineProfile.from_dict(d)
        except ValueError as exc:
            _warn(tr_msg(exc))
            return
        proj.set_machine(new)
        if proj.has_job and new.post_processor:
            try:
                proj.job.PostProcessor = new.post_processor
                proj.job.PostProcessorArgs = new.post_processor_args or ""
            except Exception as exc:
                _warn(tr_msg(exc))
        _after_change()


class About(_Base):
    icon = "cam2027-about.svg"
    text = "About CAM2027"
    tooltip = "Version, environment and limits"

    def Activated(self):
        env = compat.environment_report()
        text = "\n".join([
            "CAM2027 %s (pinned FreeCAD base: %s)" % (__version__, FREECAD_PINNED_TAG),
            tr("Independent fork based on FreeCAD and its CAM workbench (LGPL-2.1-or-later). Not an official FreeCAD release."),
            tr("Running on FreeCAD {v} ({build})", v=env["freecad_version"], build=env["freecad_build"]),
            tr("Tool API: {api}, OpenCamLib: {ocl}", api=env["tool_api"], ocl=env["opencamlib"]),
            tr("User config: {dir}", dir=env["user_config_dir"]),
            tr("Logs: FreeCAD.log in the user config directory (launcher starts FreeCAD with -l)."),
            "",
            tr("Not available yet: 3D surfacing in this workbench, 4th axis toolpaths, collision checks. Simulation uses the FreeCAD CAM simulator."),
        ])
        _info(text)


class AdvancedMode(_Base):
    atelier = "settings"
    text = "Advanced mode (property editor)"
    tooltip = "Show the FreeCAD property editor under the model tree"

    def GetResources(self):
        res = _Base.GetResources(self)
        res["Checkable"] = standalone.advanced_mode()
        return res

    def Activated(self, checked=None):
        on = not standalone.advanced_mode() if checked is None else bool(checked)
        standalone.apply_advanced_mode(on)


class ResetLayout(_Base):
    atelier = "origin"
    text = "Default layout"
    tooltip = "Put the CAM2027 panels and toolbars back in their default places"

    def Activated(self):
        standalone.reset_layout()


COMMANDS = [
    ("CAM2027_NewProject", NewProject),
    ("CAM2027_ImportModel", ImportModel),
    ("CAM2027_ImportRelief", ImportRelief),
    ("CAM2027_ToolLibrary", ToolLibrary),
    ("CAM2027_StockFixture", StockFixture),
    ("CAM2027_AddOperation", AddOperation),
    ("CAM2027_WrapEngrave", WrapEngrave),
    ("CAM2027_FlatDepth", FlatDepth),
    ("CAM2027_Inlay", Inlay),
    ("CAM2027_Nest", Nest),
    ("CAM2027_TwoSided", TwoSided),
    ("CAM2027_KeepOut", KeepOut),
    ("CAM2027_Compute", Compute),
    ("CAM2027_Export", Export),
    ("CAM2027_Simulate", Simulate),
    ("CAM2027_MaterialCheck", MaterialCheck),
    ("CAM2027_Machine", Machine),
    ("CAM2027_Theme", Theme),
    ("CAM2027_AdvancedMode", AdvancedMode),
    ("CAM2027_ResetLayout", ResetLayout),
    ("CAM2027_About", About),
]
#: barre d'outils groupée par étape (séparateurs) ; À propos et thème restent dans les menus
TOOLBAR = ["CAM2027_NewProject", "CAM2027_ImportModel", "CAM2027_ImportRelief", "CAM2027_ToolLibrary", "CAM2027_StockFixture", "Separator",
           "CAM2027_AddOperation", "CAM2027_Compute", "Separator", "CAM2027_Simulate", "CAM2027_MaterialCheck", "Separator", "CAM2027_Export",
           "Separator", "CAM2027_Machine"]
MENU = [name for name, _cls in COMMANDS]
#: menu « CAM2027 » en atelier dans FreeCAD complet (dans le logiciel, ces commandes vont dans Affichage / Aide)
WORKBENCH_MENU = ["CAM2027_Theme", "CAM2027_AdvancedMode", "CAM2027_ResetLayout", "Separator", "CAM2027_About"]
#: menus par étape du métier (titres anglais traduits par tr())
STAGE_MENUS = (
    ("Prepare", ["CAM2027_ImportModel", "CAM2027_ImportRelief", "CAM2027_Nest", "CAM2027_StockFixture", "CAM2027_TwoSided", "CAM2027_KeepOut", "Separator", "CAM2027_ToolLibrary",
                 "CAM2027_Machine"]),
    ("Machining", ["CAM2027_AddOperation", "Separator", "CAM2027_FlatDepth", "CAM2027_Inlay", "CAM2027_WrapEngrave",
                   "Separator", "CAM2027_Compute"]),
    ("Simulate", ["CAM2027_Simulate", "CAM2027_MaterialCheck"]),
    ("Export", ["CAM2027_Export"]),
)

_registered = False


def register():
    global _registered
    if _registered:
        return
    for name, cls in COMMANDS:
        FreeCADGui.addCommand(name, cls())
    _registered = True
