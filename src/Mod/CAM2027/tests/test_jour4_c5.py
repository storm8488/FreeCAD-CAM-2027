# SPDX-License-Identifier: LGPL-2.1-or-later
"""Jour 4, flux C5 : validation machine sans machine (essais de ``tests/machine_trials``).

Les G-code d'essai livrés passent dans le simulateur GRBL 1.1 de cncjs (0 error, 0 ALARM, positions = parcours
CAM2027 à 0,01 mm) ; ignoré si Node ou le simulateur sont absents. La reconstruction complète des essais (~6 min)
ne tourne qu'avec ``CAM2027_TRIALS_REBUILD=1`` ; par défaut un seul essai est reconstruit et comparé au fichier livré.
Deux défauts trouvés hors de la zone C5 sont prouvés par des tests ``expectedFailure`` (voir le bilan C5).
"""

import json
import os
import re
import shutil
import tempfile
import unittest

import FreeCAD
import Part

from tests.machine_trials import reference as refmod
from tests.machine_trials import validate as valmod

HERE = os.path.dirname(os.path.abspath(__file__))
TRIALS = os.path.join(HERE, "machine_trials", "output")
NODE = valmod.node_executable()
SIM_OK = NODE is not None and os.path.isfile(valmod.simulator_path())
V = FreeCAD.Vector


def gcode_body(text):
    """G-code sans commentaires ni lignes vides (l'heure et les libellés du postprocesseur ne comptent pas)."""
    out = []
    for line in text.splitlines():
        line = re.sub(r"\(.*?\)", "", line).strip()
        if line:
            out.append(line)
    return out


class TestReference(unittest.TestCase):
    """Positions attendues calculées sur les commandes Path, et comparaison avec un passage simulé."""

    def test_drill_cycle_and_arc(self):
        ref = refmod.reference([
            ("G0", {"Z": 5.0}), ("G0", {"X": 10.0, "Y": 10.0}), ("G98", {}),
            ("G81", {"X": 10.0, "Y": 10.0, "Z": -4.0, "R": 2.0}),  # G98 : retour à Z5 (plus haut que R)
            ("G99", {}), ("G81", {"X": 20.0, "Y": 10.0, "Z": -4.0, "R": 2.0}),  # G99 : retour à R
            ("G0", {"X": 30.0, "Y": 0.0, "Z": 2.0}),
            ("G3", {"X": 30.0, "Y": 20.0, "I": 0.0, "J": 10.0}),  # demi-cercle par X 40 (antihoraire depuis le bas)
        ])
        self.assertEqual(ref["cycles"], 2)
        self.assertEqual(ref["points"][:6], [[None, None, 5.0], [10.0, 10.0, 5.0], [10.0, 10.0, 2.0],
                                             [10.0, 10.0, -4.0], [10.0, 10.0, 5.0], [20.0, 10.0, 5.0]])
        self.assertEqual(ref["points"][6:9], [[20.0, 10.0, 2.0], [20.0, 10.0, -4.0], [20.0, 10.0, 2.0]])
        self.assertEqual(ref["envelope"]["X"], [10.0, 40.0])  # point le plus à droite de l'arc
        self.assertEqual(ref["final"], [30.0, 20.0, 2.0])
        with self.assertRaises(ValueError):  # débourrage : non développé, refusé plutôt que deviné
            refmod.reference([("G0", {"X": 0.0, "Y": 0.0, "Z": 5.0}), ("G83", {"X": 0.0, "Y": 0.0, "Z": -4.0, "R": 2.0, "Q": 1.0})])

    def test_probe_positions_unknown(self):
        """Après un palpage ou G10, l'axe est inconnu jusqu'au mouvement absolu suivant ; G91 hors liste."""
        ref = refmod.reference([("G91", {}), ("G38.2", {"Z": -25.0}), ("G10", {"L": 20.0, "P": 1.0, "Z": 0.0}),
                                ("G0", {"Z": 2.0}), ("G90", {}), ("G0", {"X": 0.0, "Y": 0.0}), ("G0", {"Z": 5.0})])
        self.assertEqual(ref["points"], [[0.0, 0.0, None], [0.0, 0.0, 5.0]])

    def test_compare(self):
        ref = {"points": [[0.0, 0.0, 5.0], [10.0, 0.0, 5.0], [10.0, 0.0, -1.0], [10.0004, 0.0012, -1.0]],
               "envelope": {"X": [0.0, 10.0004], "Y": [0.0, 0.0012], "Z": [-1.0, 5.0]}, "final": [10.0004, 0.0012, -1.0]}
        # arrondi du G-code à 0,001 : le dernier point fusionne d'un côté et pas de l'autre
        sim = {"points": [[0.0, 0.0, 5.0], [10.0, 0.0, 5.0], [10.0, 0.0, -1.0], [10.0, 0.001, -1.0]],
               "envelope": {"X": [0.0, 10.0], "Y": [0.0, 0.001], "Z": [-1.0, 5.0]}, "final": [10.0, 0.001, -1.0]}
        problems, worst, matched = refmod.compare(ref, sim)
        self.assertEqual(problems, [])
        self.assertLess(worst, 0.001)
        self.assertEqual(matched, 4)
        bad = dict(sim, points=[[0.0, 0.0, 5.0], [10.02, 0.0, 5.0], [10.0, 0.0, -1.0]])
        problems, _w, _m = refmod.compare(ref, bad)
        self.assertTrue(any("position 2" in p for p in problems), problems)
        bad = dict(sim, envelope={"X": [0.0, 10.0], "Y": [0.0, 0.001], "Z": [-1.02, 5.0]})
        self.assertTrue(any("enveloppe Z" in p for p in refmod.compare(ref, bad)[0]))


@unittest.skipUnless(SIM_OK, "Node ou le simulateur GRBL de cncjs absent")
class TestGrblSimulator(unittest.TestCase):
    """Le banc ``grbl_check.js`` : ce que GRBL 1.1 refuse est compté comme error, le reste est simulé."""

    def run_lines(self, text):
        tmp = tempfile.mkdtemp(prefix="cam2027-c5-")
        self.addCleanup(shutil.rmtree, tmp, True)
        nc = os.path.join(tmp, "t.nc")
        with open(nc, "w", encoding="utf-8") as fp:
            fp.write(text)
        return valmod.run_simulator([nc], os.path.join(tmp, "out.json"))[0]

    def test_rejected_by_grbl(self):
        rep = self.run_lines("(Pocket 40x30)\nG21 G90\nG81 X1 Y1 Z-1 R1 F100\nG1 X1 X2 F100\n( M6 T2 )\nM6 T2\n"
                             "G0 A10\nG1 X1.2.3\nG1 X3 R5 F100\nG2 X10 Y0 I5 J0 F100\nG1 X5 F100 ; fin\n")
        codes = [e["response"].split(" ")[0] for e in rep["errors"]]
        self.assertEqual(codes, ["error:20", "error:25", "error:20", "error:20", "error:1", "error:36"], rep["errors"])
        # commentaire « (Pocket 40x30) » ôté comme par GRBL : pas de mouvement X30 ; arc et mouvement simulés
        self.assertEqual(rep["points"], [[10.0, 0.0, None], [5.0, 0.0, None]])
        self.assertEqual(rep["alarms"], [])

    def test_probe_and_dwell(self):
        rep = self.run_lines("G21\nG90\nG54\nM5\nG91\nG38.2 Z-25 F100\nG10 L20 P1 Z0\nG0 Z2\nG90\nG0 X0 Y0\nG4 P0.5\n"
                             "G0 Z5\nM2\n")
        self.assertEqual(rep["errors"], [])
        self.assertEqual(len(rep["probes"]), 1)
        self.assertEqual(rep["points"], [[0.0, 0.0, None], [0.0, 0.0, 5.0]])
        self.assertEqual(rep["state"], "Idle")


@unittest.skipUnless(SIM_OK, "Node ou le simulateur GRBL de cncjs absent")
class TestTrialsInSimulator(unittest.TestCase):
    def test_delivered_trials(self):
        """Tous les G-code d'essai livrés : 0 error, 0 ALARM, positions, position finale et enveloppe = parcours
        CAM2027 à 0,01 mm ; un seul outil par fichier (aucune pause), aucune entaille au contrôle matière."""
        with open(os.path.join(TRIALS, "trials.json"), encoding="utf-8") as fp:
            manifest = json.load(fp)
        self.assertEqual(len(manifest["trials"]), 10)
        tmp = tempfile.mkdtemp(prefix="cam2027-c5-")
        self.addCleanup(shutil.rmtree, tmp, True)
        for name in os.listdir(TRIALS):  # les fichiers livrés ne sont pas réécrits par le test
            src = os.path.join(TRIALS, name)
            (shutil.copytree if os.path.isdir(src) else shutil.copy)(src, os.path.join(tmp, name))
        ok, summary = valmod.validate(tmp)
        self.assertTrue(ok, [(s["id"], s["problems"], s["errors"], s["alarms"]) for s in summary if not s["ok"]])
        for s in summary:
            self.assertGreater(s["positions"], 1, s["id"])
            self.assertLess(s["max_difference_mm"], 0.01, s["id"])
        for t in manifest["trials"]:
            self.assertEqual(t["pauses"], 0, t["id"])
            self.assertLessEqual(len(t["tools"]), 1, t["id"])
            limit = 0.11 if t["id"].startswith("07") else 0.0  # V-carving : voir la fiche de l'essai 07
            self.assertLessEqual(t["check"]["gouge_max"], limit, t["id"])
            self.assertEqual(t["check"]["rapid_hits"], 0, t["id"])
            for m in t["measures"]:
                if m["nominal"] is not None and m["simulated"] is not None:
                    self.assertLessEqual(abs(m["nominal"] - m["simulated"]), m["tol"], (t["id"], m))


class TestProbeTrial(unittest.TestCase):
    def test_corner_origin(self):
        """Le fichier de palpage livré, exécuté contre la planche 200 x 150 x 18 (GRBL de palpage de
        ``test_jour3_b4``, pointe Ø2 du profil d'essai) depuis deux départs : origine au coin avant gauche du dessus."""
        from tests.test_jour3_b4 import run_probe

        with open(os.path.join(TRIALS, "01-palpage-coin", "01-palpage-coin.nc"), encoding="utf-8") as fp:
            lines = [l for l in fp.read().splitlines() if l.strip() and not l.startswith("(")]
        board = (0.0, 0.0, -18.0, 200.0, 150.0, 0.0)
        for start in ((10.0, 10.0, 5.0), (13.0, 8.0, 2.0)):
            origin = run_probe(lines, start, [board], 2.0)
            for got, want in zip(origin, (0.0, 0.0, 0.0)):
                self.assertAlmostEqual(got, want, places=6, msg=start)


class TestTrialsRebuild(unittest.TestCase):
    def test_rebuild(self):
        """Essais reconstruits par le script : mêmes mouvements que les fichiers livrés (commentaires exceptés).
        Par défaut l'essai 02 seul ; tous avec ``CAM2027_TRIALS_REBUILD=1`` (puis validation dans le simulateur)."""
        from tests.machine_trials import build

        full = os.environ.get("CAM2027_TRIALS_REBUILD") == "1"
        tmp = tempfile.mkdtemp(prefix="cam2027-c5-")
        self.addCleanup(shutil.rmtree, tmp, True)
        saved = build.TRIALS
        if not full:
            build.TRIALS = [build.trial_pocket]
        try:
            manifest = build.build_all(tmp, log=lambda *_a: None)
        finally:
            build.TRIALS = saved
        for t in manifest["trials"]:
            with open(os.path.join(tmp, t["nc"]), encoding="utf-8") as fp:
                new = gcode_body(fp.read())
            with open(os.path.join(TRIALS, t["nc"]), encoding="utf-8") as fp:
                old = gcode_body(fp.read())
            self.assertEqual(new, old, "%s : les essais livrés ne sont plus à jour, relancer "
                                       "tests/machine_trials/build.py puis validate.py" % t["id"])
        if full and SIM_OK:
            ok, summary = valmod.validate(tmp)
            self.assertTrue(ok, [(s["id"], s["problems"]) for s in summary if not s["ok"]])


# -- défauts trouvés hors de la zone C5 (bilan C5) -------------------------------------------------------


def _project(shape, name):
    from tests.machine_trials import build

    tmp = tempfile.mkdtemp(prefix="cam2027-c5-")
    proj, clone = build.new_project(name, shape, tmp)
    return proj, clone, tmp


class TestPocketWalls(unittest.TestCase):
    """Poche par défaut (réglages initiaux de l'interface, motif zigzag de FreeCAD) : aucune passe le long des
    parois, festons de ~0,5 mm entre les allers-retours ; la poche 40 x 30 sort à 39,55 mm au milieu des parois."""

    def _inner_length(self, **extra):
        from tests.machine_trials import build

        shape = build.board().cut(Part.makeBox(40, 30, 6, V(15, 20, -6)))
        proj, clone, tmp = _project(shape, "C5 pocket walls")
        self.addCleanup(shutil.rmtree, tmp, True)
        self.addCleanup(proj.close)
        build.add_op(proj, "pocket", "Pocket", "flat", base=[(clone, [build.planar_face(clone, -6.0)])], **extra)
        proj.compute()
        text = "\n".join(g for _n, g in __import__("cam2027.project.export", fromlist=["x"]).postprocess(proj.job))
        flat = build.tool(proj.library, "flat")[0]
        zm = build.carve([(text, flat)], (10, 15, 60, 55), 0.05)
        return build.run_length(zm, "X", 35.0, 35.0, -0.02)[0], build.run_length(zm, "Y", 35.0, 35.0, -0.02)[0]

    @unittest.expectedFailure
    def test_default_pocket_walls(self):
        length, width = self._inner_length()
        self.assertAlmostEqual(length, 40.0, delta=0.1)  # 39,55 sur 25562b8
        self.assertAlmostEqual(width, 30.0, delta=0.1)

    def test_zigzag_offset_walls(self):
        """Le réglage des essais (zigzag puis passe de paroi) donne la cote."""
        length, width = self._inner_length(ClearingPattern="ZigZagOffset")
        self.assertAlmostEqual(length, 40.0, delta=0.1)
        self.assertAlmostEqual(width, 30.0, delta=0.1)


class TestRough3dEnclosed(unittest.TestCase):
    """Ébauche 3D « pièce entière » (mode modèle de FreeCAD 1.1) d'un relief dans une cuvette fermée au ras du
    dessus du brut (dôme dans une planche, cas Aspire courant) : aucun mouvement de coupe, sans message."""

    @unittest.expectedFailure
    def test_dome_in_closed_recess(self):
        from tests.machine_trials import build

        recess = Part.makeBox(70, 70, 10, V(10, 75, -10))
        dome = Part.makeSphere(40.0, V(45.0, 110.0, -40.0)).common(recess)
        shape = build.board().cut(recess).fuse(dome).removeSplitter()
        proj, clone, tmp = _project(shape, "C5 rough3d closed recess")
        self.addCleanup(shutil.rmtree, tmp, True)
        self.addCleanup(proj.close)
        op = build.add_op(proj, "rough3d", "Rough", "flat", base=[(clone, [])], StockToLeave=0.5, FinalDepth=-10.0)
        proj.compute()
        cuts = [c for c in op.Path.Commands if c.Name in ("G1", "G2", "G3")]
        self.assertGreater(len(cuts), 100)  # 0 sur 25562b8 (2 commandes)


if __name__ == "__main__":
    unittest.main()
