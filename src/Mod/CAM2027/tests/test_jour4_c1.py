# SPDX-License-Identifier: LGPL-2.1-or-later
"""Flux C1 du jour 4 : bugs connus après la chasse aux bugs, chacun reproduit par un test avant sa correction."""

import os
import tempfile
import unittest

import FreeCAD
import Part

from cam2027.project.machine import MachineProfile
from cam2027.project.project import Project
from cam2027.tools.library import starter_library

V = FreeCAD.Vector
PROBE = {"present": True, "tip_diameter_mm": 2.0, "plate_thickness_mm": 0.0, "feed_mm_min": 100.0, "travel_mm": 25.0}


def machine(**kw):
    return MachineProfile("test", controller="grbl", post_processor="grbl",
                          post_processor_args="--no-show-editor --precision=3", **kw)


class _PartCase(unittest.TestCase):
    """Pièce STEP synthétique (``make``) importée dans un projet, brut à 2 mm de marge."""

    @classmethod
    def make(cls):
        return Part.makeBox(60, 40, 10)

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="cam2027-c1-")
        cls.step = os.path.join(cls.tmp, "%s.step" % cls.__name__)
        cls.make().exportStep(cls.step)
        FreeCAD.ConfigSet("SuppressRecomputeRequiredDialog", "True")

    def project(self, name, stock=None, **mkw):
        lib = starter_library()
        proj = Project.create(name, lib, machine(**mkw))
        part = proj.import_model(self.step, label="Part").objects[0]
        job = proj.create_job([part], stock=stock or {"kind": "box_margins", "xy": 2.0, "z_top": 1.0, "z_bottom": 0.0})
        name = proj.doc.Name
        self.addCleanup(lambda: name in FreeCAD.listDocuments() and FreeCAD.closeDocument(name))
        return proj, proj.library, job.Model.Group[0]

    def tool(self, lib, name):
        t = [t for t in lib.search(name) if t.tool_type == "endmill"][0]
        return lib.assemblies_for_tool(t.id)[0].id, t.presets[0].id


class TestProbeReopen(_PartCase):
    def test_same_toolpath_after_reopening(self):
        """Palpage d'un coin : 29 commandes à la création, 28 après enregistrement et réouverture (B3, ``s2-probe``).
        FreeCAD relit le parcours enregistré comme du G-code et y efface ``G21`` (unités) ; le libellé « Probe the
        origin (corner) » donnait en plus un commentaire à parenthèses imbriquées, relu autrement."""
        from cam2027.project import probe

        proj, _lib, _clone = self.project("Probe reopen", probe=dict(PROBE))
        for mode, kw in (("corner", {"corner": "front-left"}), ("z", {}), ("hole", {"hole_diameter": 8.0}),
                         ("inner_corner", {"corner": "back-right"})):
            probe.add_probe(proj, mode, **kw)
        proj.compute()
        before = {o.Name: [c.toGCode() for c in o.Path.Commands] for o in proj.operations()}
        self.assertEqual(len(before), 4)
        for op in proj.operations():
            self.assertNotIn("(", op.Label)  # libellé sans parenthèses : commentaire du parcours relu tel quel
        path = os.path.join(self.tmp, "probe-reopen.FCStd")
        proj.save(path)
        proj.close()
        proj = Project.open(path)
        self.addCleanup(FreeCAD.closeDocument, proj.doc.Name)
        after = {o.Name: [c.toGCode() for c in o.Path.Commands] for o in proj.operations()}
        self.assertEqual(after, before)
        for op in proj.operations():
            op.touch()
        proj.doc.recompute()
        self.assertEqual({o.Name: [c.toGCode() for c in o.Path.Commands] for o in proj.operations()}, before)
        # le programme exporté reste en millimètres (G21 du postprocesseur) et palpe toujours
        text, analysis, issues = proj.preview_gcode()
        self.assertIn("G21", text)
        self.assertEqual(text.count("G38.2"), 3 + 1 + 2 + 2)
        self.assertFalse([m for lvl, m in issues if lvl == "error"])


if __name__ == "__main__":
    unittest.main()
