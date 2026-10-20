# SPDX-License-Identifier: LGPL-2.1-or-later
"""Lance tous les tests CAM2027 dans FreeCADCmd.

    FreeCADCmd.exe -M <chemin>/src/Mod/CAM2027 <chemin>/src/Mod/CAM2027/tests/run_all.py

Code de retour : 0 si tous les tests passent (FreeCADCmd le propage via sys.exit).
Les résultats sont aussi écrits dans ``tests/last-run.txt``.
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
if MOD not in sys.path:
    sys.path.insert(0, MOD)

import FreeCAD  # noqa: E402

FreeCAD.ConfigSet("SuppressRecomputeRequiredDialog", "True")

names = [n[:-3] for n in sorted(os.listdir(HERE)) if n.startswith("test_") and n.endswith(".py")]
only = [a for a in sys.argv[1:] if a.startswith("test_")]
if only:
    names = [n for n in names if n in only]

suite = unittest.TestSuite()
loader = unittest.TestLoader()
for name in names:
    module = __import__("tests." + name, fromlist=["*"])
    suite.addTests(loader.loadTestsFromModule(module))

stream = open(os.path.join(HERE, "last-run.txt"), "w", encoding="utf-8")


class Tee(object):
    def write(self, data):
        sys.stdout.write(data)
        stream.write(data)

    def flush(self):
        sys.stdout.flush()
        stream.flush()


result = unittest.TextTestRunner(stream=Tee(), verbosity=2).run(suite)
stream.close()
print("CAM2027 TESTS: run=%d failures=%d errors=%d skipped=%d"
      % (result.testsRun, len(result.failures), len(result.errors), len(result.skipped)))
sys.exit(0 if result.wasSuccessful() else 1)
