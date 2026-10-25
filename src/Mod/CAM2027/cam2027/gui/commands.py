# SPDX-License-Identifier: LGPL-2.1-or-later
"""Commandes de l'atelier (barre d'outils et menu)."""

import os

import FreeCAD
import FreeCADGui

from .qt import QtCore, QtGui, QtWidgets, exec_dialog
from ..i18n import tr, tr_msg
from .labels import preset_label
from .. import compat
from ..version import __version__, FREECAD_PINNED_TAG, SUPPORT_URL
from ..project.project import Project, ExportBlocked
from ..project.operations import STRATEGIES, DEFAULT_THREAD_TYPE, thread_names
from ..project.importers import SUPPORTED_EXTENSIONS
from ..project import export as exportmod
from ..project import undo
from ..project import operations as opsmod
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
    """Curseur d'attente + fenêtre de progression avec « Arrêter le calcul » pendant une action longue (import,
    calcul...). L'interface garde la main toutes les 0,1 s (``opsmod.GuiTicker``) ; la fenêtre est modale :
    seuls son bouton et le rafraîchissement passent.

    « Arrêter » lève ``ComputationStopped`` dans le calcul, retenue à la sortie du bloc (``stopped`` vrai, le
    code qui suit le bloc ne doit pas utiliser un résultat incomplet). ``stoppable`` (projet) : l'adaptative de
    FreeCAD s'arrête aussi quand ``StopProcessing`` passe à vrai."""

    def __init__(self, message, stoppable=None):
        self.message = message
        self.project = stoppable
        self.dialog = None
        self.stopped = False
        self.ticker = None

    def __enter__(self):
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            FreeCADGui.getMainWindow().statusBar().showMessage(self.message)
        except Exception:
            pass
        parent = QtWidgets.QApplication.activeModalWidget() or FreeCADGui.getMainWindow()
        self.dialog = QtWidgets.QProgressDialog(self.message, tr("Stop the computation"), 0, 0, parent)
        self.dialog.setWindowTitle("CAM2027")
        self.dialog.setMinimumDuration(0)
        self.dialog.setWindowModality(QtCore.Qt.WindowModal)
        self.dialog.canceled.connect(self.stop)
        self.dialog.show()
        self.ticker = opsmod.GuiTicker()
        self.ticker.__enter__()  # avant de traiter les événements : un rafraîchissement en attente est différé
        QtWidgets.QApplication.processEvents()
        return self

    def stop(self):
        self.stopped = True
        opsmod.GuiTicker.stop()
        try:
            for op in self.project.operations() if self.project is not None else ():
                base = self.project.base_operation(op)
                if "StopProcessing" in base.PropertiesList:
                    base.StopProcessing = True
        except Exception:
            pass

    def __exit__(self, exc_type, *_exc):
        if self.ticker is not None:
            self.ticker.__exit__()
        if self.dialog is not None:
            self.dialog.canceled.disconnect(self.stop)
            self.dialog.close()
            self.dialog.deleteLater()
        QtWidgets.QApplication.restoreOverrideCursor()
        try:
            FreeCADGui.getMainWindow().statusBar().clearMessage()
        except Exception:
            pass
        stopped_here = exc_type is not None and issubclass(exc_type, opsmod.ComputationStopped)
        self.stopped = self.stopped or stopped_here
        if self.stopped and self.project is not None:
            opsmod.hold_stopped(self.project.doc)
        if self.stopped:
            _warn(tr("Computation stopped: the operations concerned have an incomplete toolpath (recompute them later).")
                  if self.project is not None else tr("Computation stopped."))
        return stopped_here


#: au-delà, le brut simulé affiché est simplifié (erreur 0,01 mm, ``sim.display_mesh``) : 700 000 triangles
#: alourdissaient la vue 3D
DISPLAY_MESH_MAX_FACETS = 100000


def _after_change():
    if FreeCAD.ActiveDocument:
        FreeCAD.ActiveDocument.recompute()
    panels.refresh_project_panel()


#: stratégie -> icône « Atelier »
STRATEGY_ICONS = {
    "profile": "contour", "pocket": "pocket", "pocket2d": "pocket", "offsetpocket": "pocket", "adaptive": "pocket", "drilling": "drill",
    "millface": "surface", "engrave": "engrave", "vcarve": "engrave", "chamfer": "engrave", "helix": "drill",
    "slot": "contour", "threadmill": "drill", "surface3d": "surface", "waterline": "surface", "rough3d": "pocket",
    "scallop": "surface",
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
    atelier = "cmd-new-project"
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
    atelier = "cmd-import-model"
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
            with busy(tr("Importing {file}...", file=os.path.basename(path))) as b:
                res = proj.import_model(path)
        except Exception as exc:  # erreurs OCC / lecteurs
            _warn(tr("Import failed: {error}", error=tr_msg(exc)))
            return
        if b.stopped:
            panels.refresh_project_panel()  # pas de recalcul : il referait ce qui vient d'être arrêté
            return
        FreeCADGui.SendMsgToActiveView("ViewFit")
        _after_change()
        shown = [o.Label for o in res.objects if o.TypeId.startswith(("Part::", "Mesh::"))]  # pas les repères du STEP
        lines = [tr("Imported: {objects}", objects=", ".join(shown) or "-")]
        if res.kind == "vector":
            lines.append(tr("2D drawing: next, Stock and fixture > Sheet under the 2D drawing."))
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
    atelier = "cmd-import-relief"
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
    atelier = "cmd-tool-library"
    accel = "Ctrl+Shift+T"
    text = "Tool library"
    tooltip = "Tools, holders, assemblies and cutting presets"

    def Activated(self):
        panels.show_tool_library()


#: au-delà, la fusion des corps d'un assemblage est trop lente (STEP de 37 000 faces : environ 1 min)
MERGE_MAX_FACES = 20000


class StockFixture(_Base):
    icon = "cam2027-stock.svg"
    atelier = "cmd-stock"
    accel = "Ctrl+Shift+B"
    text = "Stock and fixture"
    tooltip = "Create the job (if needed), define the stock and the work coordinate system"

    def Activated(self):
        proj = _need_project()
        if proj is None:
            return
        from . import preparepages

        preparepages.open_stock(proj)


class AddOperation(_Base):
    icon = "cam2027-add-operation.svg"
    atelier = "cmd-add-operation"
    accel = "Ctrl+Shift+O"
    text = "Add operation"
    tooltip = "Add a machining operation: family, strategy, tool and cutting preset, then the editor"

    def Activated(self):
        proj = _need_project()
        if proj is None:
            return
        if not proj.has_job:
            _warn(tr("Define the stock and fixture first (this creates the job)."))
            return
        # outils créés dans la bibliothèque depuis la création du projet : ajoutés à son instantané
        user = state.library()
        if any(user.ensure_usable(tid, tr("New preset")) for tid in list(user.tools)):
            try:
                user.save()
            except (ValueError, OSError):
                pass
        proj.merge_library(user)
        from . import addop

        addop.open_page(proj)


class WrapEngrave(_Base):
    atelier = "cmd-wrap-engrave"
    text = "Wrapped engraving (A axis)"
    tooltip = "Engrave an unrolled drawing around the round stock: X, Z and A move together (continuous 4th axis, G93)"

    @_undoable
    def Activated(self):
        proj = _need_project()
        if proj is None:
            return
        if not proj.has_job:
            _warn(tr("Define the stock and fixture first (this creates the job)."))
            return
        open_wrap_dialog(proj)


class RotaryMachining(_Base):
    atelier = "cmd-rotary"
    text = "Rotary machining (A axis)"
    tooltip = "Wrapped contour or pocket of an unrolled drawing, or rotary 3D finishing of the part: X, Z and A move together (continuous 4th axis, G93)"

    @_undoable
    def Activated(self):
        proj = _need_project()
        if proj is None:
            return
        if not proj.has_job:
            _warn(tr("Define the stock and fixture first (this creates the job)."))
            return
        open_wrap_dialog(proj, rotary=True)


class ProjectOnPart(_Base):
    atelier = "cmd-project-on-part"
    text = "Project on the part"
    tooltip = "Carry an engraving, contour or V-carving computed flat onto the 3D part surface, at the same depth below it"

    @_undoable
    def Activated(self):
        proj = _need_project()
        if proj is None:
            return
        if not proj.has_job:
            _warn(tr("Define the stock and fixture first (this creates the job)."))
            return
        from .projectiondlg import ProjectionDialog

        dlg = ProjectionDialog(proj, FreeCADGui.getMainWindow())
        if exec_dialog(dlg) != QtWidgets.QDialog.Accepted:
            return
        try:
            dlg.apply()
            proj.compute()
        except Exception as exc:
            _warn(tr("Operation failed: {error}", error=tr_msg(exc)))
        _after_change()


def open_wrap_dialog(proj, op=None, rotary=False):
    """Création ou modification d'une gravure enroulée (``rotary`` : contour, poche ou finition 3D rotatifs) ;
    retourne l'opération ou None."""
    from .wrapdlg import WrapDialog
    from ..project import rotary as rotarymod

    selected = [s.Object for s in FreeCADGui.Selection.getSelectionEx() if s.Object.Document.Name == proj.doc.Name]
    if rotary or (op is not None and proj.registry.get(op.Name, {}).get("kind") in rotarymod.KINDS):
        from .rotarydlg import RotaryDialog

        dlg = RotaryDialog(proj, FreeCADGui.getMainWindow(), selected=selected, op=op)
    else:
        dlg = WrapDialog(proj, FreeCADGui.getMainWindow(), selected=selected, op=op)
    if exec_dialog(dlg) != QtWidgets.QDialog.Accepted:
        return None
    result = None
    try:
        with undo.transaction(proj.doc, dlg.windowTitle()):
            with busy(tr("Computing the toolpaths..."), stoppable=proj) as b:
                result = dlg.apply()
                proj.compute()
    except Exception as exc:
        _warn(tr("Operation failed: {error}", error=tr_msg(exc)))
        _after_change()
        return None
    if b.stopped:
        panels.refresh_project_panel()  # pas de recalcul : il referait ce qui vient d'être arrêté
        return result
    if result is None:
        _after_change()
        return result
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
    try:
        with busy(tr("Computing the toolpaths..."), stoppable=proj if proj.has_job else None) as b:
            result = dlg.apply()
            if proj.has_job:
                proj.compute()
    except Exception as exc:
        _warn(tr("Operation failed: {error}", error=tr_msg(exc)))
        return None
    if b.stopped:
        panels.refresh_project_panel()  # pas de recalcul : il referait ce qui vient d'être arrêté
        return None
    _after_change()
    return result


class FlatDepth(_Base):
    atelier = "cmd-flat-depth"
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
    atelier = "cmd-inlay"
    text = "V inlay (male / female)"
    tooltip = "Female V pocket in this project and mirrored male plug in a new project, with glue gap"

    @_undoable
    def Activated(self):
        proj = _need_project()
        if proj is None:
            return
        if not proj.has_job:
            _warn(tr("Define the stock and fixture first (this creates the job)."))
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
    atelier = "cmd-nest"
    text = "Nest parts on a sheet"
    tooltip = "Place the 2D drawings on sheets of a given size (true shape or bounding rectangles, rotations, copies)"

    @_undoable
    def Activated(self):
        proj = _need_project()
        if proj is None:
            return
        if proj.has_job:
            _warn(tr("Nesting is done before Stock and fixture (the job is already created)."))
            return
        rep = _sheet_dialog(proj, "NestDialog")
        if rep:
            lines = [tr("Placed: {n} part(s), sheet use {u} %.", n=len(rep["placed"]), u="%.0f" % (100 * rep["utilization"]))]
            if rep.get("sheets", 1) > 1:
                lines.append(tr("Sheets used: {n} (laid to the right of the first one).", n=rep["sheets"]))
            for group in rep.get("groups", []):  # [C4]
                lines.append(tr("Kept together: {parts}", parts=" + ".join(group)))
            if rep["unplaced"]:
                lines.append(tr("Not placed (no room): {parts}", parts=", ".join(rep["unplaced"])))
            lines.append(tr("Next: Stock and fixture > sheet under the 2D drawing (the sheet keeps the nesting size)."))
            _info("\n".join(lines))
            FreeCADGui.SendMsgToActiveView("ViewFit")


def helix_refusal(base, diameter):
    """Pourquoi l'hélice n'a rien donné sur la pièce entière (message traduit), ``None`` si ce n'est pas la taille
    des trous. FreeCAD n'y garde que les trous ronds verticaux plus larges que la fraise (``Drillable``) : disque
    WobbleRing, Ø6 → trous de 4,5 mm ; plateau STL → aucun trou rond (un maillage n'a pas de cylindres)."""
    import FreeCAD
    import Part
    import Path.Base.Drillable as Drillable

    sizes = []
    for obj, _subs in base or []:
        for _o, sub in Drillable.getDrillableTargets(obj, ToolDiameter=0, vector=FreeCAD.Vector(0, 0, 1)):
            face = obj.Shape.getElement(sub)
            if isinstance(face.Surface, Part.Cylinder):
                sizes.append(2.0 * face.Surface.Radius)
    if not sizes:
        return tr("The helix found no round vertical hole on the part (a mesh imported from STL has none): use a pocket or the adaptive clearing.")
    if max(sizes) <= diameter + 1e-6:
        return tr("The holes of the part are smaller than the {d} mm tool (largest: {fit} mm): choose a smaller tool.",
                  d="%g" % diameter, fit="%g" % round(max(sizes), 2))
    return None


def default_params(kind, tool, values):
    """Paramètres initiaux d'une opération dérivés du préréglage (passe axiale, recouvrement, etc.)."""
    params = {"StepDown": values["axial_engagement_mm"]}
    stepover = max(1, min(100, int(round(100.0 * (values["radial_engagement_mm"] or tool.geometry.diameter * 0.4)
                                         / tool.geometry.diameter))))
    if kind in ("pocket", "millface", "adaptive", "helix", "rough3d", "stockrough", "offsetpocket"):
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
    if kind == "scallop":
        params.pop("StepDown", None)  # finition : crête maximale, pas de passe axiale
    if kind == "chamfer":
        params["Width"] = 1.0
    if kind == "stockrough":
        params["StockToLeave"] = 0.5
    if kind == "flat3d":
        params = {"StepOver": stepover}  # une seule passe, à la hauteur de chaque plat
    if kind == "pencil":
        params = {}  # passes le long des angles : pas de passe axiale
    if kind == "threadmill":
        names = thread_names(DEFAULT_THREAD_TYPE)
        params["ThreadType"] = DEFAULT_THREAD_TYPE
        params["ThreadName"] = "M6 x 1" if "M6 x 1" in names else names[0]
    return params


class TwoSided(_Base):
    atelier = "cmd-two-sided"
    text = "Two-sided machining"
    tooltip = "Machine the part on both sides: side B is the part turned over (flip about X or Y), with dowel pins or the same corner"

    @_undoable
    def Activated(self):
        proj = _need_project()
        if proj is None:
            return
        if not proj.has_job:
            _warn(tr("Define the stock and fixture first (this creates the job)."))
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
    atelier = "cmd-keep-out"
    text = "Keep-out zones"
    tooltip = "Boxes the rapid moves go over (clamps, drawn zones); a cut entering a zone blocks the export"

    @_undoable
    def Activated(self):
        proj = _need_project()
        if proj is None:
            return
        if not proj.has_job:
            _warn(tr("Define the stock and fixture first (this creates the job)."))
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


class BulkEdit(_Base):
    atelier = "cmd-bulk-edit"
    text = "Compare and edit operations"
    tooltip = "Table of the parameters shared by several operations: show the differences, change a value on all of them at once"

    @_undoable
    def Activated(self):
        proj = _need_project()
        if proj is None:
            return
        from ..project import bulkedit
        from . import bulkedit as bulkgui

        if len(bulkedit.editable_operations(proj) if proj.has_job else []) < 2:
            _warn(tr("At least two operations are needed to compare them."))
            return
        selected = [s.Object for s in FreeCADGui.Selection.getSelectionEx() if s.Object.Document.Name == proj.doc.Name]
        dlg = bulkgui.BulkEditDialog(proj, selected if len(selected) > 1 else None, FreeCADGui.getMainWindow())
        if exec_dialog(dlg) != QtWidgets.QDialog.Accepted:
            return
        try:
            changes = dlg.changes()
            ops = dlg.operations()
            ignored = {}
            with busy(tr("Computing the toolpaths...")):
                ignored = dlg.apply()
                proj.compute()
        except ValueError as exc:
            _warn(tr_msg(exc))
            return
        _after_change()
        if changes:
            lines = [tr("{n} parameter(s) written to {m} operation(s), toolpaths recomputed.", n=len(changes), m=len(ops))]
            for label, names in ignored.items():
                lines.append(tr("{op}: not changed: {names}", op=label, names=", ".join(names)))
            _info("\n".join(lines))


class Compute(_Base):
    icon = "cam2027-compute.svg"
    atelier = "cmd-compute"
    accel = "Ctrl+Shift+R"
    text = "Recompute toolpaths"
    tooltip = "Recompute every operation and refresh the summary"

    def Activated(self):
        proj = _need_project()
        if proj is None:
            return
        if not proj.has_job:
            _warn(tr("Define the stock and fixture first (this creates the job)."))
            return
        with busy(tr("Computing the toolpaths..."), stoppable=proj) as b:
            results = proj.compute()
        if b.stopped:
            panels.refresh_project_panel()  # pas de recalcul : il referait ce qui vient d'être arrêté
            return
        bad = [r["name"] for r in results if not r["valid"] or r["commands"] == 0]
        if bad:
            _warn(tr("Operations without a valid toolpath: {names}", names=", ".join(bad)))
        _after_change()


class Export(_Base):
    icon = "cam2027-export.svg"
    atelier = "cmd-export"
    accel = "Ctrl+Shift+E"
    text = "Export G-code"
    tooltip = "Post-process, check and write the G-code and the setup sheet"

    def Activated(self):
        proj = _need_project()
        if proj is None or not proj.has_job:
            if proj is not None:
                _warn(tr("No job to export."))
            return
        from . import exportpage

        exportpage.open_page(proj)


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
    atelier = "cmd-simulate"
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
    atelier = "cmd-material-check"
    text = "Material and collision check"
    tooltip = "Simulate material removal on a height map: gouges, stock left, flute length, tool holder and clamp collisions, rapids in the material"

    def Activated(self):
        proj = _need_project()
        if proj is None:
            return
        if not proj.has_job or not proj.operations():
            _warn(tr("No operation to simulate."))
            return
        try:
            with busy(tr("Material and collision check...")) as b:
                rep = proj.material_check()
                show_material_result(proj, rep)
        except Exception as exc:
            _warn(tr("Material check failed: {error}", error=tr_msg(exc)))
            return
        if b.stopped:
            return
        from . import shell
        from .verification import VerificationPage

        shell.show_space("verify")
        shell.inspector().show_page(VerificationPage(rep, material_report_text(rep)))


def show_material_result(proj, rep):
    """Brut simulé (gris) et entailles (rouge) dans la vue 3D ; objets hors job, remplacés à chaque contrôle."""
    import Mesh  # noqa: F401
    from ..project import sim

    doc = proj.doc
    objs = []
    if rep.get("rotary"):  # [C4] brut rond : carte de rayon enroulée autour de l'axe A
        st = proj.last_rotary
        stock = st.surface_mesh(rep["center"])
        if stock.CountFacets > DISPLAY_MESH_MAX_FACETS:  # affichage seulement, comme sim.display_mesh
            try:
                stock.decimate(0.01, 0.9)
            except Exception:
                pass
        meshes = (stock, st.surface_mesh(rep["center"], st.gouge_mask(rep["tolerance"]), lift=0.02))
    else:
        meshes = (sim.display_mesh(proj.last_zmap, DISPLAY_MESH_MAX_FACETS),
                  sim.surface_mesh(proj.last_zmap, sim.gouge_mask(proj.last_zmap, proj.last_heights, rep["tolerance"]),
                                   lift=0.02))
    for name, mesh, colour in (
            ("CAM2027SimStock", meshes[0], (0.62, 0.66, 0.72)),
            ("CAM2027SimGouges", meshes[1], (0.9, 0.15, 0.15))):
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
    lines = [tr("Material check (radius map around the A axis, {res} mm grid)", res="%g" % rep["resolution"])
             if rep.get("rotary") else tr("Material check (height map, {res} mm grid, 3 axes)", res="%g" % rep["resolution"]),
             tr("Removed: {v} cm3", v="%.1f" % (rep["removed_volume"] / 1000.0))]
    if not rep.get("simulated"):  # tout sauté (axe A, palpage, outil inconnu) : rien n'a été contrôlé
        lines.append(tr("No operation simulated: gouges not checked"))
    elif rep["gouge_max"] > rep["tolerance"]:
        x, y, _z = rep["gouge_at"]
        lines.append(tr("GOUGE: the tool cuts {d} mm into the part (worst at X {x} Y {y}, {n} cells)",
                        d="%.2f" % rep["gouge_max"], x="%.1f" % x, y="%.1f" % y, n=rep["gouge_cells"]))
    else:
        lines.append(tr("No gouge found on the top of the part (tolerance {t} mm)", t="%g" % rep["tolerance"]))
    bone = rep.get("dogbone_overcut") or {}
    if bone.get("max", 0.0) > rep["tolerance"]:
        lines.append(tr("Intended dogbone overcut (not counted as a gouge): up to {d} mm, {n} bone(s)",
                        d="%.2f" % bone["max"], n=bone["bones"]))
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
            lines.append(tr("No clamp defined: clamps not checked (Stock and fixture)."))
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
    lines.append(tr("Not checked: undercuts seen from the A axis, tool holder and clamps (round stock).") if rep.get("rotary")
                 else tr("Not checked: vertical walls and undercuts (height map), A axis operations."))
    return "\n".join(lines)


class Theme(_Base):
    icon = "CAM2027.svg"
    atelier = "cmd-theme"
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
        refresh_icons()
        FreeCAD.Console.PrintMessage(tr("CAM2027 theme: {name}", name=tr(nxt)) + "\n")


class Language(_Base):
    atelier = "cmd-language"
    text = "Language: English / Français"
    tooltip = "Language of the interface, applied at the next start"

    def Activated(self):
        from .. import i18n

        codes = list(i18n.INTERFACE_LANGUAGES)
        labels = {"en": "English", "fr": "Français"}
        current = codes.index(i18n.language()) if i18n.language() in codes else 0
        label, ok = QtWidgets.QInputDialog.getItem(FreeCADGui.getMainWindow(), "CAM2027", tr("Interface language:"),
                                                   [labels[c] for c in codes], current, False)
        if not ok:
            return
        code = codes[[labels[c] for c in codes].index(label)]
        i18n.save_interface_language(code)
        if code != i18n.language():
            # message dans la langue choisie : elle ne s'applique qu'au redémarrage
            _info({"en": "Restart CAM2027 to switch the interface to English.",
                   "fr": "Redémarrez CAM2027 pour passer l'interface en français."}[code])


class Machine(_Base):
    icon = "cam2027-machine.svg"
    atelier = "cmd-machine"
    accel = "Ctrl+Shift+M"
    text = "Machine profile"
    tooltip = "Travels, feeds, spindle, controller, rotary axis (unknown values stay empty)"

    def Activated(self):
        proj = _need_project()
        if proj is None:
            return
        from . import preparepages

        preparepages.open_machine(proj)


class About(_Base):
    icon = "cam2027-about.svg"
    text = "About CAM2027"
    atelier = "cmd-about"
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
            tr("Alpha version: check every toolpath (simulation, material check, dry run above the part) before cutting."),
            tr("Found a bug or have an idea? Help > Report a bug / Suggest a feature, or the links in the status bar."),
            tr("Support the project: {url}", url=SUPPORT_URL),
        ])
        _info(text)


def open_feedback(kind):
    """Ouvre dans le navigateur le formulaire GitHub de bug ou d'idée (environnement prérempli)."""
    from .. import feedback

    QtGui.QDesktopServices.openUrl(QtCore.QUrl(feedback.issue_url(kind)))


class ReportBug(_Base):
    atelier = "cmd-report-bug"
    text = "Report a bug"
    tooltip = "Open the bug form of the CAM2027 GitHub repository (versions filled in)"

    def Activated(self):
        open_feedback("bug")


class SuggestFeature(_Base):
    atelier = "cmd-suggest-feature"
    text = "Suggest a feature"
    tooltip = "Open the idea form of the CAM2027 GitHub repository"

    def Activated(self):
        open_feedback("idea")


class SupportProject(_Base):
    atelier = "cmd-support"
    text = "Support the project"
    tooltip = "Buy the developer a coffee (Buy Me a Coffee page)"

    def Activated(self):
        QtGui.QDesktopServices.openUrl(QtCore.QUrl(SUPPORT_URL))


class AdvancedMode(_Base):
    atelier = "cmd-advanced"
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
    atelier = "cmd-reset-layout"
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
    ("CAM2027_RotaryMachining", RotaryMachining),
    ("CAM2027_ProjectOnPart", ProjectOnPart),
    ("CAM2027_FlatDepth", FlatDepth),
    ("CAM2027_Inlay", Inlay),
    ("CAM2027_Nest", Nest),
    ("CAM2027_Pattern", __import__("cam2027.gui.patterns", fromlist=["PatternCommand"]).PatternCommand),
    ("CAM2027_Holes", __import__("cam2027.gui.holes", fromlist=["HoleCommand"]).HoleCommand),
    ("CAM2027_Probe", __import__("cam2027.gui.probe", fromlist=["ProbeCommand"]).ProbeCommand),
    ("CAM2027_TwoSided", TwoSided),
    ("CAM2027_KeepOut", KeepOut),
    ("CAM2027_BulkEdit", BulkEdit),
    ("CAM2027_Compute", Compute),
    ("CAM2027_Export", Export),
    ("CAM2027_Simulate", Simulate),
    ("CAM2027_MaterialCheck", MaterialCheck),
    ("CAM2027_Machine", Machine),
    ("CAM2027_Theme", Theme),
    ("CAM2027_Language", Language),
    ("CAM2027_AdvancedMode", AdvancedMode),
    ("CAM2027_ResetLayout", ResetLayout),
    ("CAM2027_About", About),
    ("CAM2027_ReportBug", ReportBug),
    ("CAM2027_SuggestFeature", SuggestFeature),
    ("CAM2027_SupportProject", SupportProject),
]
from . import aspirecmds  # noqa: E402  (S5 : modèles de parcours, dessin, images, décors)
COMMANDS += aspirecmds.COMMANDS
#: barre d'outils groupée par étape (séparateurs) ; À propos et thème restent dans les menus
TOOLBAR = ["CAM2027_NewProject", "CAM2027_ImportModel", "CAM2027_ImportRelief", "Separator",
           "CAM2027_StockFixture", "CAM2027_ToolLibrary", "CAM2027_Machine", "Separator",
           "CAM2027_AddOperation", "CAM2027_Compute", "Separator", "CAM2027_Simulate", "CAM2027_MaterialCheck", "Separator",
           "CAM2027_Export"]
MENU = [name for name, _cls in COMMANDS]
#: menu « CAM2027 » en atelier dans FreeCAD complet (dans le logiciel, ces commandes vont dans Affichage / Aide)
WORKBENCH_MENU = ["CAM2027_Theme", "CAM2027_Language", "CAM2027_AdvancedMode", "CAM2027_ResetLayout", "Separator", "CAM2027_ReportBug",
                  "CAM2027_SuggestFeature", "CAM2027_SupportProject", "CAM2027_About"]
#: menus par étape du métier (titres anglais traduits par tr())
#: un menu par espace : Préparer / Dessiner / Usiner / Vérifier et exporter (mêmes noms que la barre)
STAGE_MENUS = (
    ("Prepare", ["CAM2027_ImportModel", "CAM2027_ImportRelief", "CAM2027_Nest", "CAM2027_StockFixture", "CAM2027_TwoSided", "CAM2027_KeepOut",
                 "CAM2027_Probe", "Separator", "CAM2027_ToolLibrary", "CAM2027_Machine"]),
    ("Draw", aspirecmds.DRAWING_MENU),
    ("Machining", ["CAM2027_AddOperation", "CAM2027_BulkEdit", "Separator", "CAM2027_FlatDepth", "CAM2027_Inlay", "CAM2027_WrapEngrave",
                 "CAM2027_RotaryMachining", "CAM2027_ProjectOnPart", "CAM2027_Pattern", "CAM2027_Holes", "Separator", "CAM2027_Compute"] + aspirecmds.MACHINING_MENU),
    ("Check and export", ["CAM2027_Simulate", "CAM2027_MaterialCheck", "Separator", "CAM2027_Export"] + aspirecmds.EXPORT_MENU),
)

#: commandes FreeCAD gardées dans les barres du logiciel -> icône « Atelier » (même style que CAM2027)
STD_ICONS = {
    "Std_Open": "std-open", "Std_Save": "std-save", "Std_Undo": "std-undo", "Std_Redo": "std-redo",
    "Std_Refresh": "std-refresh", "Std_ViewFitAll": "std-fit-all", "Std_ViewFitSelection": "std-fit-selection",
    "Std_ViewGroup": "std-views", "Std_AlignToSelection": "std-align",
}


def refresh_icons():
    """Icônes accordées au fond réel des barres d'outils sur les commandes CAM2027 (et, dans le logiciel, sur les
    commandes FreeCAD de ses barres) : au démarrage et quand le thème change (le chemin donné par ``GetResources`` est
    figé à l'enregistrement)."""
    items = [(name, getattr(cls, "atelier", "")) for name, cls in COMMANDS]
    if standalone.is_standalone():
        items += list(STD_ICONS.items())
    window = theme.chrome()  # fond réel des barres, pas le thème des panneaux
    for name, atelier in items:
        if not atelier:
            continue
        try:
            command = FreeCADGui.Command.get(name)
            actions = command.getAction() if command is not None else []
            icon = theme.icon(atelier, window)
        except Exception:  # commande absente de cette version de FreeCAD, icône manquante
            continue
        for action in actions or []:
            action.setIcon(icon)


_registered = False


def register_task_pages():
    """Pages de tâches FreeCAD des stratégies propres à CAM2027 (crête constante, plats, angles), posées dans
    leur module : le fournisseur de vue d'une opération rouverte les y cherche au double-clic. Elles n'étaient
    créées qu'à l'ajout d'une opération : projet rouvert dans une nouvelle session, double-clic sans effet
    (AttributeError ``TaskPanelOpPage``). Leur filtre de sélection est celui de la finition 3D de FreeCAD
    (``Selection.select`` ne connaît que ses opérations : KeyError, aucune page, même dans la session)."""
    import importlib
    import Path.Op.Gui.Selection as PathSelection
    from ..project import operations as opsmod

    if not getattr(PathSelection.select, "cam2027", False):
        known = PathSelection.select

        def select(op_name):
            try:
                return known(op_name)
            except KeyError:
                return PathSelection.surfaceselect

        select.cam2027 = True
        PathSelection.select = select
    for kind, meta in STRATEGIES.items():
        if meta["module"].startswith("cam2027."):
            try:
                opsmod._own_strategy_resources(importlib.import_module(meta["module"]), kind)
            except Exception as exc:
                FreeCAD.Console.PrintWarning("CAM2027: task page of %s not registered: %s\n" % (kind, exc))


def patch_task_panel_cancel():
    """Annuler sur la page de tâches FreeCAD d'une opération : l'annulation de la transaction a déjà tout remis en
    l'état, mais l'ouverture de la page avait marqué l'opération « à recalculer » : FreeCAD recalculait tout le
    parcours, interface figée (45 s pour une reprise des angles). L'opération qui était à jour avant l'ouverture
    le redevient."""
    import Path.Op.Gui.Base as PathOpGui

    panel = PathOpGui.TaskPanel
    if getattr(panel, "cam2027", False):
        return
    init, reject, cleanup = panel.__init__, panel.reject, panel.cleanup

    def __init__(self, obj, *args, **kw):
        self.cam2027_was_touched = "Touched" in (obj.State or [])
        init(self, obj, *args, **kw)

    def reject_(self, *args, **kw):
        self.cam2027_cancel = True
        return reject(self, *args, **kw)

    def cleanup_(self, resetEdit):
        if getattr(self, "cam2027_cancel", False) and not getattr(self, "cam2027_was_touched", True):
            try:
                self.obj.purgeTouched()
            except Exception:
                pass  # opération supprimée (création annulée)
        return cleanup(self, resetEdit)

    panel.__init__, panel.reject, panel.cleanup = __init__, reject_, cleanup_
    panel.cam2027 = True


def register():
    global _registered
    if _registered:
        return
    for name, cls in COMMANDS:
        FreeCADGui.addCommand(name, cls())
    register_task_pages()
    patch_task_panel_cancel()
    _registered = True
