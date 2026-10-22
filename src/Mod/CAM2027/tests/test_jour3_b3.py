# SPDX-License-Identifier: LGPL-2.1-or-later
"""Flux B3 (jour 3, interface et stabilité) : ce qui se vérifie sans interface. Les scénarios pilotés comme un
utilisateur sont dans ``gui_scenarios_b3.py`` (double-clic dans l'arbre, réouverture, panneau, longue session)."""

import json
import os
import tempfile
import unittest

import FreeCAD

from cam2027.project import undo
from cam2027.project.project import Project, attach_job_view
from cam2027.project.machine import MachineProfile
from cam2027.tools.library import starter_library
from tests.test_pipeline import make_part


def _state(proj):
    """Objets du document et registre des opérations (ce que Ctrl+Z doit remettre exactement)."""
    return (sorted(o.Name for o in proj.doc.Objects),
            [(o.Name, o.Label, proj.base_operation(o).Active) for o in proj.operations()],
            json.dumps(proj.registry, sort_keys=True))


class TestUndoProjectActions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="cam2027-b3-")
        cls.step = os.path.join(cls.tmp, "plate.step")
        make_part(cls.step)
        FreeCAD.ConfigSet("SuppressRecomputeRequiredDialog", "True")

    def setUp(self):
        self.proj = Project.create("B3Undo", starter_library(), MachineProfile(
            "test", controller="grbl", post_processor="grbl", post_processor_args="--no-show-editor --precision=3"))
        self.doc = self.proj.doc
        self.doc.UndoMode = 1  # FreeCADCmd : annulation désactivée par défaut
        part = self.proj.import_model(self.step).objects[0]
        self.proj.create_job([part], stock={"kind": "box_margins", "xy": 2.0, "z_top": 1.0, "z_bottom": 0.0})
        lib = self.proj.library
        tool = lib.search("6 mm flat end mill")[0]
        self.asm = lib.assemblies_for_tool(tool.id)[0]
        self.preset = tool.presets[0].id
        self.base = [(self.proj.job.Model.Group[0], [])]
        for label in ("Contour A", "Contour B"):
            with undo.transaction(self.doc, "Add operation"):
                self.proj.add_operation("profile", label, self.asm.id, self.preset, base=self.base)
        self.proj.compute()
        self.doc.clearUndos()

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)

    def _check(self, name, action):
        """``action`` en une étape ; Ctrl+Z revient à l'état d'avant, Ctrl+Y à celui d'après."""
        before = _state(self.proj)
        n0 = self.doc.UndoCount
        with undo.transaction(self.doc, name):
            action()
            self.proj.compute()
        after = _state(self.proj)
        self.assertNotEqual(before, after, name)
        self.assertEqual((self.doc.UndoCount - n0, self.doc.UndoNames[0]), (1, name))
        self.doc.undo()
        self.assertEqual(_state(self.proj), before, name)
        self.doc.redo()
        self.assertEqual(_state(self.proj), after, name)

    def test_panel_actions_undo_in_one_step(self):
        ops = self.proj.operations
        self._check("Duplicate", lambda: self.proj.duplicate_operation(ops()[0]))
        self._check("Move the operation", lambda: self.proj.move_operation(ops()[1], -1))
        self._check("Enable or disable the operation", lambda: self.proj.set_operation_active(ops()[0], False))
        self._check("Edit the operation", lambda: self.proj.update_operation(ops()[0], {"StepDown": 1.5}))
        self._check("Delete", lambda: self.proj.remove_operation(ops()[-1]))

    def test_attach_job_view_without_gui(self):
        """Sans interface (FreeCADCmd, export en ligne de commande) : rien à poser, aucune erreur."""
        self.assertFalse(attach_job_view(self.proj.job))
        self.assertFalse(attach_job_view(None))


if __name__ == "__main__":
    unittest.main()
