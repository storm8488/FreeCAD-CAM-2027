# SPDX-License-Identifier: LGPL-2.1-or-later
"""Familles d'opérations (« Ajouter une opération ») : chaque stratégie dans une famille, fiches traduites."""

import json
import os
import unittest

from cam2027 import i18n
from cam2027.project import families
from cam2027.project.operations import STRATEGIES


class TestFamilies(unittest.TestCase):
    def test_every_strategy_in_one_family(self):
        self.assertEqual(families.check(), [])
        listed = [k for _key, _l, _i, kinds in families.FAMILIES for k in kinds]
        self.assertEqual(sorted(listed), sorted(STRATEGIES))

    def test_primary_kinds_hide_alternatives(self):
        self.assertIn("offsetpocket", families.primary_kinds("pocket"))
        self.assertNotIn("pocket", families.primary_kinds("pocket"))  # moteur alternatif : choix secondaire
        self.assertEqual(families.info("offsetpocket")["alternatives"], ("pocket",))
        self.assertEqual(families.family_of("pocket"), "pocket")
        self.assertIsNone(families.family_of("wrap_engrave"))

    def test_labels_translated(self):
        with open(os.path.join(os.path.dirname(i18n.__file__), "i18n", "fr.json"), "r", encoding="utf-8") as fp:
            catalog = json.load(fp)
        for _key, label, _icon, _kinds in families.FAMILIES:
            self.assertIn(label, catalog, label)
        for kind, info in families.STRATEGY_INFO.items():
            for field in ("short", "usage", "selection"):
                self.assertIn(info[field], catalog, (kind, field))

    def test_tool_types(self):
        self.assertEqual(families.tool_types("vcarve")[0], "vbit")
        self.assertEqual(families.tool_types("unknown"), ())


if __name__ == "__main__":
    unittest.main()
