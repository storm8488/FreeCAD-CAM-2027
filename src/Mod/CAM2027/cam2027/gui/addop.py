# SPDX-License-Identifier: LGPL-2.1-or-later
"""Page « Ajouter une opération » du panneau contextuel : famille par résultat → stratégie (nom court, usage,
sélection attendue, outils compatibles) → moteur alternatif (choix secondaire) → outil et préréglage → nom.

« Créer l'opération » crée l'opération avec les valeurs du préréglage, calcule, puis ouvre **le même éditeur**
à la même place : plus de dialogue de création suivi d'un autre dialogue. La création reste une étape
d'annulation ; fermer l'éditeur sans l'accepter retire l'opération (comme avant).
"""

import FreeCADGui

from .qt import QtCore, QtWidgets
from ..i18n import tr, tr_msg
from ..project import families, undo
from ..project.operations import STRATEGIES
from . import state, theme
from .inspector import Page
from .labels import preset_label


class AddOperationPage(Page):
    def __init__(self, proj, base, parent=None):
        super(AddOperationPage, self).__init__(tr("Add operation"), parent)
        self.proj = proj
        self.base = base  # [(objet, [sous-éléments])] : sélection au moment de l'ouverture
        self.kind = None
        self._build()
        theme.apply(self)

    # -- construction --------------------------------------------------------------------------------

    def _build(self):
        from ..project import operations as opsmod
        from .toolpicker import ToolField

        body = self.scrolled_body()
        lay = QtWidgets.QVBoxLayout(body)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(8)
        step1 = QtWidgets.QLabel(tr("1. What result do you want?"))
        theme.set_role(step1, "section")
        lay.addWidget(step1)
        self.family_buttons = {}
        grid = QtWidgets.QGridLayout()
        grid.setSpacing(4)
        self.family_group = QtWidgets.QButtonGroup(self)
        self.family_group.setExclusive(True)
        for i, (key, label, icon, _kinds) in enumerate(families.FAMILIES):
            b = QtWidgets.QToolButton()
            b.setText(tr(label))
            b.setIcon(theme.icon(icon))
            b.setCheckable(True)
            b.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
            b.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            b.setProperty("family", key)
            b.clicked.connect(lambda _c=False, k=key: self._pick_family(k))
            self.family_group.addButton(b)
            grid.addWidget(b, i // 2, i % 2)
            self.family_buttons[key] = b
        lay.addLayout(grid)

        step2 = QtWidgets.QLabel(tr("2. Strategy"))
        theme.set_role(step2, "section")
        lay.addWidget(step2)
        self.kind_list = QtWidgets.QListWidget()
        self.kind_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.kind_list.setMaximumHeight(150)
        self.kind_list.currentItemChanged.connect(lambda cur, _prev: self._pick_kind(cur.data(QtCore.Qt.UserRole) if cur else None))
        lay.addWidget(self.kind_list)
        self.usage = QtWidgets.QLabel()
        self.usage.setWordWrap(True)
        lay.addWidget(self.usage)
        self.selection_hint = QtWidgets.QLabel()
        self.selection_hint.setWordWrap(True)
        theme.set_role(self.selection_hint, "muted")
        lay.addWidget(self.selection_hint)
        engine_row = QtWidgets.QHBoxLayout()
        self.engine_label = QtWidgets.QLabel(tr("Engine"))
        self.engine = QtWidgets.QComboBox()
        self.engine.setToolTip(tr("Alternative engine for the same result; the engine of an existing operation is never changed silently."))
        self.engine.currentIndexChanged.connect(self._pick_engine)
        engine_row.addWidget(self.engine_label)
        engine_row.addWidget(self.engine, 1)
        lay.addLayout(engine_row)
        self.limits = QtWidgets.QLabel()
        self.limits.setWordWrap(True)
        theme.set_role(self.limits, "muted")
        lay.addWidget(self.limits)

        step3 = QtWidgets.QLabel(tr("3. Tool and cutting preset"))
        theme.set_role(step3, "section")
        lay.addWidget(step3)
        form = QtWidgets.QFormLayout()
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.ExpandingFieldsGrow)
        self.asm = ToolField(self.proj)  # comme Fusion : Sélectionner… / Éditer…, outils du document en liste
        form.addRow(tr("Tool"), self.asm)
        self.tool_note = QtWidgets.QLabel()
        self.tool_note.setWordWrap(True)
        theme.set_role(self.tool_note, "warning")
        form.addRow(self.tool_note)
        self.preset = QtWidgets.QComboBox()
        form.addRow(tr("Cutting preset"), self.preset)
        self.compatible = QtWidgets.QLabel()
        self.compatible.setWordWrap(True)
        theme.set_role(self.compatible, "muted")
        form.addRow(tr("Compatible tools"), self.compatible)
        lay.addLayout(form)

        step4 = QtWidgets.QLabel(tr("4. Name and geometry"))
        theme.set_role(step4, "section")
        lay.addWidget(step4)
        form2 = QtWidgets.QFormLayout()
        form2.setFieldGrowthPolicy(QtWidgets.QFormLayout.ExpandingFieldsGrow)
        self.name = QtWidgets.QLineEdit()
        self.name.setProperty("auto", True)
        self.name.textEdited.connect(lambda _t: self.name.setProperty("auto", False))  # nom tapé : ne plus le remplacer
        form2.addRow(tr("Name"), self.name)
        self.sel_label = QtWidgets.QLabel(", ".join("%s: %s" % (o.Label, " ".join(subs) or tr("whole")) for o, subs in self.base)
                                          or tr("(nothing selected: whole part, or pocket floors / top faces found automatically)"))
        self.sel_label.setWordWrap(True)
        form2.addRow(tr("Geometry (selection)"), self.sel_label)
        self.index = QtWidgets.QDoubleSpinBox()
        self.index.setRange(-361.0, 360.0)
        self.index.setDecimals(3)
        self.index.setSuffix(" °")
        self.index.setSpecialValueText(tr("(none: 3 axes)"))
        self.index.setValue(self.index.minimum())
        self.index.setToolTip(tr("Indexed 4th axis: the part is turned to this A angle, then machined in 3 axes. Select the faces or edges on the part as it is shown."))
        self.index.setEnabled(bool(self.proj.machine.rotary.present))
        if self.proj.machine.rotary.present:
            form2.addRow(tr("A index (deg)"), self.index)
        else:
            self.index.setVisible(False)
        lay.addLayout(form2)
        hint = QtWidgets.QLabel(tr("Depths, passes and strategy settings are set next, in this panel, with values prefilled from the cutting preset."))
        hint.setWordWrap(True)
        theme.set_role(hint, "muted")
        lay.addWidget(hint)
        lay.addStretch(1)
        self.asm.changed.connect(self._fill_presets)
        self.add_buttons(tr("Create the operation"), tr("Cancel"))
        self._opsmod = opsmod
        first = families.FAMILIES[0][0]
        if self.base and all(subs for _o, subs in self.base):
            # faces / arêtes sélectionnées : le contour est le résultat le plus courant
            first = "contour"
        self._pick_family(first)

    # -- choix ---------------------------------------------------------------------------------------

    def _pick_family(self, key):
        self.family_buttons[key].setChecked(True)
        self.kind_list.blockSignals(True)
        self.kind_list.clear()
        for kind in families.primary_kinds(key):
            info = families.info(kind)
            item = QtWidgets.QListWidgetItem(tr(info["short"]))
            item.setData(QtCore.Qt.UserRole, kind)
            item.setToolTip(tr(STRATEGIES[kind]["label"]))
            self.kind_list.addItem(item)
        self.kind_list.blockSignals(False)
        self.kind_list.setCurrentRow(0)
        self._pick_kind(self.kind_list.item(0).data(QtCore.Qt.UserRole) if self.kind_list.count() else None)

    def _pick_kind(self, kind):
        """Stratégie principale choisie : fiche, moteurs alternatifs, outil adapté, nom proposé."""
        if kind is None:
            return
        self.engine.blockSignals(True)
        self.engine.clear()
        info = families.info(kind)
        self.engine.addItem(tr("{engine} (recommended)", engine=info["engine"]), kind)
        for alt in info["alternatives"]:
            self.engine.addItem(tr(families.info(alt)["short"]), alt)
        self.engine.blockSignals(False)
        has_alt = bool(info["alternatives"])
        self.engine.setVisible(has_alt)
        self.engine_label.setVisible(has_alt)
        self._set_kind(kind)

    def _pick_engine(self, _i=None):
        kind = self.engine.currentData()
        if kind:
            self._set_kind(kind)

    def _set_kind(self, kind):
        self.kind = kind
        info = families.info(kind)
        self.usage.setText(tr(info["usage"]))
        self.selection_hint.setText(tr("Selection: {what}", what=tr(info["selection"])))
        self.limits.setText(tr(STRATEGIES[kind]["limits"]) or "")
        self.limits.setVisible(bool(STRATEGIES[kind]["limits"]))
        from ..tools.model import TOOL_TYPES

        self.compatible.setText(", ".join(tr(TOOL_TYPES[t][0]) for t in families.tool_types(kind) if t in TOOL_TYPES) or "-")
        self.asm.blockSignals(True)
        self.asm.set_kind(kind)
        self.asm.blockSignals(False)
        self._fill_presets()
        if self.name.property("auto"):
            label = tr(info["short"])
            used = {o.Label for o in self.proj.operations()}
            n = 1
            while ("%s %d" % (label, n)) in used:
                n += 1
            self.name.setText("%s %d" % (label, n))

    def select_strategy(self, kind):
        """Choisit la stratégie ``kind`` (famille, liste, moteur) ; utilisé par les scénarios."""
        family = families.family_of(kind)
        if family is None:
            raise ValueError("unknown strategy %r" % kind)
        self._pick_family(family)
        primaries = families.primary_kinds(family)
        if kind in primaries:
            self.kind_list.setCurrentRow(primaries.index(kind))
        else:
            owner = next(k for k in primaries if kind in families.info(k)["alternatives"])
            self.kind_list.setCurrentRow(primaries.index(owner))
            self.engine.setCurrentIndex(self.engine.findData(kind))
        return self.kind == kind

    def _fill_presets(self):
        self.preset.clear()
        tool = self.asm.tool()
        ok = tool is not None and self._opsmod.tool_fits(self.kind, tool)
        if tool is not None:
            for p in tool.presets:
                self.preset.addItem(preset_label(p), p.id)
        self.tool_note.setText("" if ok else tr("No tool of the right type for this strategy: click Select... to choose one or create a new one."))
        self.tool_note.setVisible(not ok)

    # -- création ------------------------------------------------------------------------------------

    def apply(self):
        from . import commands

        if self.asm.currentData() is None or self.preset.currentData() is None:
            commands._warn(tr("No tool of the right type for this strategy: click Select... to choose one or create a new one."))
            return False
        index_deg = self.index.value() if self.index.isEnabled() and self.index.value() > self.index.minimum() else None
        with undo.transaction(self.proj.doc, tr("Add operation")):
            return create_operation(self.proj, self.kind, self.name.text().strip(), self.asm.currentData(),
                                    self.preset.currentData(), list(self.base), index_deg)


def create_operation(proj, k, label, asm_id, preset_id, base, index_deg=None):
    """Crée l'opération (géométrie automatique, une par fond de poche), calcule, ouvre l'éditeur ; retourne True
    si une page d'édition a été ouverte ou un message donné (la page de création peut se fermer)."""
    from . import commands, opeditor, panels
    from .commands import busy, _after_change, _info, _warn, default_params, helix_refusal

    opsmod = __import__("cam2027.project.operations", fromlist=["*"])
    lib = proj.library  # l'instantané a pu recevoir l'outil choisi
    a, tool, _h = lib.resolve_assembly(asm_id)
    values = tool.preset(preset_id).resolve(tool)
    params = default_params(k, tool, values)
    if k == "millface" and base and all(not subs for _o, subs in base):
        base = []  # pièce sélectionnée en entier : comme sans sélection (faces du dessus, sinon dessus du brut)
    explicit = bool(base)
    if not base:
        models = list(proj.job.Model.Group)  # toute la pièce : chaque objet du modèle, pas seulement le premier
        with busy(tr("Computing the toolpaths...")) as b:
            auto = opsmod.auto_geometry(k, models)  # fonds des alvéoles d'un plateau : 0,5 s
        if b.stopped:
            return True
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
            return False
    if not label:
        label = tr(families.info(k)["short"]) if k in families.STRATEGY_INFO else tr(STRATEGIES[k]["label"]).split(" (")[0]
    parts = [(label, base)]
    # fonds de poche à plusieurs hauteurs : chacun jusqu'à son fond, comme Fusion. FreeCAD les usine jusqu'au
    # plus haut ; avec le plus bas comme profondeur finale, il descend partout (entailles de 1 mm sur le
    # disque WobbleRing, 40 mm sur le chauffage) : une opération par hauteur.
    groups = opsmod.floor_groups(base) if k in ("pocket", "pocket2d", "adaptive") else None
    if groups and len(groups) > 1:
        parts = [(tr("{name} (Z {z} mm)", name=label, z="%.2f" % z), group) for z, group in groups]
    try:
        added_ops = []
        for part_label, part_base in parts:
            part_params = dict(params)
            if (not explicit and k in ("pocket2d", "adaptive") and opsmod.floor_groups(part_base)
                    and not opsmod.floors_have_islands(part_base)):
                part_params.setdefault("UseOutline", True)  # trous débouchants laissés ouverts (Fusion)
            added_ops.append(proj.add_operation(k, part_label, a.id, preset_id, base=part_base,
                                                params=part_params, index_deg=index_deg))
        with busy(tr("Computing the toolpaths..."), stoppable=proj) as b:
            proj.compute()
    except Exception as exc:
        _warn(tr("Operation failed: {error}", error=tr_msg(exc)))
        _after_change()
        return True
    if b.stopped:  # opérations gardées, parcours incomplet (message de busy) ; pas de recalcul
        panels.refresh_project_panel()
        return True
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
            return False
        why = helix_refusal(base, tool.geometry.diameter) if k == "helix" else None
        if why:
            _warn(why)
            return False
        _warn(tr("This strategy produced no toolpath on the whole part: select the faces or edges to machine, then add the operation again."))
        return False
    if len(added_ops) > 1:
        _after_change()
        _info(tr("One operation per pocket depth, each down to its own floor: {names}",
                 names=", ".join(o.Label for o, _r in added_ops)))
        return True
    op, rec = added_ops[0]
    if rec["warnings"]:
        _info("\n".join(tr_msg(w) for w in rec["warnings"]))
    _after_change()
    added = (proj.doc.UndoCount, tr("Add operation"))  # étape d'annulation de cet ajout (encore ouverte ici)

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
    return True


def open_page(proj):
    """Ouvre la page de création dans le panneau contextuel (sélection 3D du moment) ; retourne la page."""
    from . import shell

    sel = FreeCADGui.Selection.getSelectionEx()
    base = []
    ignored = {proj.job.Name, getattr(proj.job.Stock, "Name", "")}
    for s in sel:
        if s.Object.Document.Name == proj.doc.Name and getattr(s.Object, "Shape", None) \
                and s.Object.Name not in ignored:
            base.append((s.Object, list(s.SubElementNames)))
    page = AddOperationPage(proj, base)
    shell.show_space("machine")
    return shell.inspector().show_page(page)
