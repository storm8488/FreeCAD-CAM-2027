# SPDX-License-Identifier: LGPL-2.1-or-later
"""Pages de l'espace Préparer dans le panneau contextuel : brut et repère (création du job), profil machine.
Mêmes réglages et mêmes règles que les anciens dialogues ; un seul formulaire pour chaque réglage, ouvert
depuis le résumé du navigateur ou depuis les autres espaces."""

import FreeCADGui

from .qt import QtWidgets
from ..i18n import tr, tr_msg
from ..project import undo
from ..project.machine import MachineProfile
from . import state, theme
from .inspector import Page

#: au-delà, la fusion des corps d'un assemblage est trop lente (STEP de 37 000 faces : environ 1 min)
MERGE_MAX_FACES = 20000


class StockPage(Page):
    """Type et dimensions du brut, repère (G54…) ; crée le job s'il n'existe pas."""

    def __init__(self, proj, parent=None):
        super(StockPage, self).__init__(tr("Stock and fixture"), parent)
        self.proj = proj
        body = self.scrolled_body()
        form = QtWidgets.QFormLayout(body)
        form.setContentsMargins(10, 8, 10, 8)
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.ExpandingFieldsGrow)
        kind = self.kind = QtWidgets.QComboBox()
        kind.addItem(tr("Box around the model with margins"), "box_margins")
        kind.addItem(tr("Explicit box"), "box")
        kind.addItem(tr("Cylinder (rotary / round stock)"), "cylinder")
        kind.addItem(tr("Sheet under the 2D drawing (top at Z 0)"), "sheet")
        kind.addItem(tr("Round bar along X on the A axis (4th axis)"), "cylinder_x")
        from ..project import sheet as sheetmod

        if not proj.has_job and sheetmod.vector_objects(proj.doc) and not proj.model_candidates():
            kind.setCurrentIndex(kind.findData("sheet"))  # seulement des dessins 2D : panneau
        form.addRow(tr("Stock type"), kind)
        current = {}
        if proj.has_job:
            try:
                current = dict(proj.job.Proxy.stock_spec) if hasattr(proj.job.Proxy, "stock_spec") else {}
            except Exception:
                current = {}

        def spin(lo, hi, value, decimals=2):
            w = QtWidgets.QDoubleSpinBox()
            w.setRange(lo, hi)
            w.setDecimals(decimals)
            w.setValue(value)
            w.setSuffix(" mm")
            return w

        self.xy = spin(0, 1000, 2.0)
        self.ztop = spin(0, 1000, 0.0)
        self.zbot = spin(0, 1000, 0.0)
        form.addRow(tr("XY margin (mm)"), self.xy)
        form.addRow(tr("Top margin (mm)"), self.ztop)
        form.addRow(tr("Bottom margin (mm)"), self.zbot)
        self.length = spin(0.1, 5000, 100)
        self.width = spin(0.1, 5000, 100)
        self.height = spin(0.1, 5000, 20)
        self.radius = spin(0.1, 5000, 25)
        form.addRow(tr("Length X (mm)"), self.length)
        form.addRow(tr("Width Y (mm)"), self.width)
        form.addRow(tr("Height Z (mm)"), self.height)
        form.addRow(tr("Radius (mm)"), self.radius)
        self.thickness = spin(0.1, 500, 18.0)
        self.sheet_margin = spin(0, 1000, 10.0)
        form.addRow(tr("Sheet thickness (mm)"), self.thickness)
        form.addRow(tr("Sheet margin around the drawing (mm)"), self.sheet_margin)
        self.fixture = QtWidgets.QComboBox()
        self.fixture.addItems(["G54", "G55", "G56", "G57", "G58", "G59"])
        if proj.has_job and proj.job.Fixtures:
            self.fixture.setCurrentText(proj.job.Fixtures[0])
        form.addRow(tr("Work coordinate system"), self.fixture)
        origin = QtWidgets.QLabel(tr("Origin: the work offset above is the part origin set on the machine (X Y at the stock corner or centre, Z on the stock top). Unknown values are never replaced by zero."))
        origin.setWordWrap(True)
        theme.set_role(origin, "muted")
        form.addRow(origin)
        self.form = form
        # seulement les champs du type de brut choisi
        self.fields = {"box_margins": (self.xy, self.ztop, self.zbot), "box": (self.length, self.width, self.height),
                       "cylinder": (self.radius, self.height), "sheet": (self.thickness, self.sheet_margin),
                       "cylinder_x": (self.radius, self.xy)}
        kind.currentIndexChanged.connect(self._show_fields)
        self._show_fields()
        self.add_buttons(tr("Apply"), tr("Cancel"))
        theme.apply(self)
        self._snapshot = self._state()

    def _show_fields(self, _i=None):
        all_fields = {w for ws in self.fields.values() for w in ws}
        wanted = set(self.fields.get(self.kind.currentData(), ()))
        for w in all_fields:
            w.setVisible(w in wanted)
            label = self.form.labelForField(w)
            if label is not None:
                label.setVisible(w in wanted)

    def _state(self):
        return (self.kind.currentData(), self.fixture.currentText(),
                tuple(w.value() for ws in self.fields.values() for w in ws))

    def has_unsaved_changes(self):
        return self._state() != self._snapshot

    def apply(self):
        from .commands import busy, _after_change, _info, _warn

        proj = self.proj
        k = self.kind.currentData()
        with undo.transaction(proj.doc, tr("Stock and fixture")):
            if k == "sheet":
                try:
                    if proj.has_job:
                        _warn(tr("The project already has a job: the sheet is only available for a new 2D project."))
                        return False
                    with busy(tr("Stock and fixture")) as b:
                        proj.create_sheet_job(thickness=self.thickness.value(), margin=self.sheet_margin.value(),
                                              fixtures=[self.fixture.currentText()])
                    if b.stopped:
                        return False
                except Exception as exc:
                    _warn(tr_msg(exc))
                    return False
                FreeCADGui.SendMsgToActiveView("ViewFit")
                _after_change()
                return True
            if k == "cylinder_x":
                centre = proj.machine.rotary.center_offset_mm
                if centre is None:
                    _warn(tr("Fill in the A axis centre in the machine profile first."))
                    return False
                models = [o for o in FreeCADGui.Selection.getSelection() if getattr(o, "Shape", None)] or \
                    proj.model_candidates()
                if proj.has_job:
                    models = [c for c in proj.job.Model.Group]
                if not models:
                    _warn(tr("Select or import a solid model first."))
                    return False
                box = models[0].Shape.BoundBox
                for o in models[1:]:
                    box.add(o.Shape.BoundBox)
                spec = {"kind": k, "radius": self.radius.value(), "length": box.XLength + 2 * self.xy.value(),
                        "x_start": box.XMin - self.xy.value(), "center": tuple(centre)}
            elif k == "box_margins":
                spec = {"kind": k, "xy": self.xy.value(), "z_top": self.ztop.value(), "z_bottom": self.zbot.value()}
            elif k == "box":
                spec = {"kind": k, "length": self.length.value(), "width": self.width.value(), "height": self.height.value()}
            else:
                spec = {"kind": k, "radius": self.radius.value(), "height": self.height.value()}
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
                                with busy(tr("Merging the {n} bodies into one part...", n=len(sel))) as b:
                                    merged = proj.merge_models(sel, proj.doc.Label)
                                if b.stopped:
                                    return False
                                if merged is not None:
                                    sel = [merged]
                                else:
                                    _info(tr("The {n} bodies could not be merged into one solid: they are machined as separate parts.", n=len(sel)))
                            else:
                                _info(tr("{n} bodies ({f} faces): too large to merge, they are machined as separate parts. To machine only some of them, select them before Stock and fixture.",
                                         n=len(sel), f=faces))
                    if not sel:
                        from ..project import sheet as sheetmod

                        if sheetmod.vector_objects(proj.doc):
                            _warn(tr("The project only has 2D drawings: choose the stock type 'Sheet under the 2D drawing'."))
                        else:
                            _warn(tr("Import a part (STEP, STL, OBJ) or a drawing (SVG, DXF) first."))
                        return False
                    with busy(tr("Stock and fixture")) as b:
                        proj.create_job(sel, stock=spec, fixtures=[self.fixture.currentText()])
                    if b.stopped:
                        return False
                else:
                    proj.set_stock(spec)
                    from ..project.stock import set_fixtures

                    set_fixtures(proj.job, [self.fixture.currentText()])
            except Exception as exc:
                _warn(tr_msg(exc))
                return False
            _after_change()
        return True


class MachinePage(Page):
    """Courses, avances, broche, contrôleur, postprocesseur, axe A (les valeurs inconnues restent vides)."""

    def __init__(self, proj, parent=None):
        super(MachinePage, self).__init__(tr("Machine profile"), parent)
        self.proj = proj
        m = proj.machine
        body = self.scrolled_body()
        outer = QtWidgets.QVBoxLayout(body)
        outer.setContentsMargins(10, 8, 10, 8)
        form = QtWidgets.QFormLayout()
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.ExpandingFieldsGrow)
        outer.addLayout(form)
        self.widgets = {}
        from ..project.machine import FIELD_LABELS

        for key in ("name", "vendor", "model", "controller", "post_processor", "post_processor_args", "travel_x_mm",
                    "travel_y_mm", "travel_z_mm", "max_feed_xy_mm_min", "max_feed_z_mm_min", "acceleration_mm_s2", "spindle_min_rpm",
                    "spindle_max_rpm", "spindle_power_w", "collet", "notes"):
            label = FIELD_LABELS[key]
            w = QtWidgets.QLineEdit("" if getattr(m, key) is None else str(getattr(m, key)))
            w.setPlaceholderText(tr("to fill in"))
            w.setCursorPosition(0)
            form.addRow(tr(label), w)
            self.widgets[key] = w
        self.rot = QtWidgets.QCheckBox(tr("Rotary axis A present (about X)"))
        self.rot.setChecked(bool(m.rotary.present))
        outer.addWidget(self.rot)
        abox = QtWidgets.QGroupBox(tr("A axis (indexed 3+1 and continuous)"))
        aform = QtWidgets.QFormLayout(abox)
        aform.setFieldGrowthPolicy(QtWidgets.QFormLayout.ExpandingFieldsGrow)
        self.direction = QtWidgets.QComboBox()
        self.direction.addItem(tr("to fill in"), None)
        self.direction.addItem(tr("Right hand: A+ counter-clockwise seen from +X"), "right_hand")
        self.direction.addItem(tr("Left hand: A+ clockwise seen from +X"), "left_hand")
        self.direction.setCurrentIndex(max(0, self.direction.findData(m.rotary.positive_direction)))
        aform.addRow(tr("A axis positive direction"), self.direction)
        centre = m.rotary.center_offset_mm or (None, None)
        self.a_fields = {}
        for key, label, value in (("cy", "A axis centre Y (mm)", centre[0]), ("cz", "A axis centre Z (mm)", centre[1]),
                                  ("min", "A axis min (deg)", m.rotary.min_deg), ("max", "A axis max (deg)", m.rotary.max_deg),
                                  ("feed", "A axis max feed (deg/min)", m.rotary.max_feed_deg_min)):
            w = QtWidgets.QLineEdit("" if value is None else str(value))
            w.setPlaceholderText(tr("to fill in"))
            aform.addRow(tr(label), w)
            self.a_fields[key] = w
        note = QtWidgets.QLabel(tr("The centre is the position of the rotation axis in the work coordinate system. Nothing is assumed: indexed operations are refused until the centre and the positive direction are filled in."))
        note.setWordWrap(True)
        theme.set_role(note, "muted")
        aform.addRow(note)
        abox.setEnabled(self.rot.isChecked())
        self.rot.toggled.connect(abox.setEnabled)
        outer.addWidget(abox)
        outer.addStretch(1)
        self.add_buttons(tr("Apply"), tr("Cancel"))
        theme.apply(self)
        self._snapshot = self._state()

    def _state(self):
        return (tuple(w.text() for w in self.widgets.values()), self.rot.isChecked(), self.direction.currentIndex(),
                tuple(w.text() for w in self.a_fields.values()))

    def has_unsaved_changes(self):
        return self._state() != self._snapshot

    def apply(self):
        from .commands import _after_change, _warn
        from ..project.machine import FIELD_LABELS

        m = self.proj.machine
        d = m.to_dict()
        numeric = ("travel_x_mm", "travel_y_mm", "travel_z_mm", "max_feed_xy_mm_min", "max_feed_z_mm_min", "acceleration_mm_s2",
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
            for key, w in self.widgets.items():
                if key in numeric:
                    d[key] = num(key, w)
                else:
                    d[key] = w.text().strip() or (None if key in ("post_processor", "collet") else "")
            d["rotary"]["present"] = self.rot.isChecked()
            cy, cz = num("cy", self.a_fields["cy"]), num("cz", self.a_fields["cz"])
            d["rotary"]["center_offset_mm"] = (cy, cz) if cy is not None and cz is not None else None
            d["rotary"]["min_deg"] = num("min", self.a_fields["min"])
            d["rotary"]["max_deg"] = num("max", self.a_fields["max"])
            d["rotary"]["max_feed_deg_min"] = num("feed", self.a_fields["feed"])
            d["rotary"]["positive_direction"] = self.direction.currentData()
            new = MachineProfile.from_dict(d)
        except ValueError as exc:
            _warn(tr_msg(exc))
            return False
        with undo.transaction(self.proj.doc, tr("Machine profile")):
            self.proj.set_machine(new)
            if self.proj.has_job and new.post_processor:
                try:
                    self.proj.job.PostProcessor = new.post_processor
                    self.proj.job.PostProcessorArgs = new.post_processor_args or ""
                except Exception as exc:
                    _warn(tr_msg(exc))
        _after_change()
        return True


def open_stock(proj):
    from . import shell

    shell.show_space("prepare")
    return shell.inspector().show_page(StockPage(proj))


def open_machine(proj):
    from . import shell

    shell.show_space("prepare")
    return shell.inspector().show_page(MachinePage(proj))
