# SPDX-License-Identifier: LGPL-2.1-or-later
"""Défauts trouvés à l'intégration de la chasse aux bugs du 2026-10-22 (entre deux flux)."""

import os
import tempfile
import unittest

import FreeCAD
import Part

from cam2027.project.machine import MachineProfile
from cam2027.project.project import Project
from cam2027.tools.library import starter_library


class TestRestKeepOut(unittest.TestCase):
    def tearDown(self):
        for name in list(FreeCAD.listDocuments()):
            FreeCAD.closeDocument(name)

    def test_rest_links_hop_over_zone(self):
        """Reprise de matière d'une poche (Ø6 puis Ø3 : coins et bords restent) : les liaisons recalculées d'un
        coin à l'autre passaient à la hauteur de dégagement à travers une zone interdite posée au-dessus du milieu
        de la poche (correctif fait pour « Limiter à une zone » et les motifs, pas pour la reprise)."""
        from cam2027.project import keepout, rest, sim

        path = os.path.join(tempfile.mkdtemp(prefix="cam2027-int3-"), "plate.step")
        Part.makeBox(100, 40, 10).cut(Part.makeBox(60, 20, 4, FreeCAD.Vector(20, 10, 6))).exportStep(path)
        lib = starter_library()
        proj = Project.create("Rest keep-out", lib, MachineProfile("test", controller="grbl", post_processor="grbl",
                                                                   post_processor_args="--no-show-editor --precision=3"))
        part = proj.import_model(path, label="Plate").objects[0]
        proj.create_job([part], stock={"kind": "box_margins", "xy": 2.0, "z_top": 0.0, "z_bottom": 0.0})
        clone = proj.job.Model.Group[0]
        floor = next("Face%d" % (i + 1) for i, f in enumerate(clone.Shape.Faces)
                     if f.BoundBox.ZLength < 1e-6 and abs(f.BoundBox.ZMin - 6.0) < 1e-6)
        big, small = lib.search("6 mm flat end mill")[0], lib.search("3 mm flat end mill")[0]
        proj.add_operation("pocket", "Rough", lib.assemblies_for_tool(big.id)[0].id, big.presets[0].id,
                           base=[(clone, [floor])], params={})
        op, _r = proj.add_operation("pocket", "Rest", lib.assemblies_for_tool(small.id)[0].id, small.presets[0].id,
                                    base=[(clone, [floor])], params={})
        zone = keepout.add_zone(proj.doc, 42.0, 18.0, 58.0, 22.0, 30.0, 12.0, label="Zone")  # au-dessus du brut (Z 10)
        dress = rest.set_rest(proj, op, ignore_below=0.1)
        proj.compute()
        segs, _pos = sim.path_segments(dress.Path.Commands)
        cuts = [s for s in segs if not s[0] and max(s[1][2], s[2][2]) <= 10.0]  # dans la matière (pas les sauts)
        self.assertTrue(cuts)
        boxes = [(zone.Label, zone.Shape.BoundBox)]
        # liaisons (rapides horizontaux) : aucune ne traverse la zone
        crossing = [(p0, p1) for rapid, p0, p1 in segs if rapid and abs(p0[2] - p1[2]) < 1e-6
                    and keepout.blocking_top(p0, p1, boxes, 3.0, 0.0) is not None]
        self.assertEqual(crossing, [])
        self.assertEqual(keepout.issues(proj), [])


if __name__ == "__main__":
    unittest.main()
