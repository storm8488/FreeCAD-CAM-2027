# SPDX-License-Identifier: LGPL-2.1-or-later
"""Règles de la coquille (pures) : largeur et panneaux, espace proposé, menus = espaces, commandes nommées par
le navigateur toutes enregistrées, chaînes du navigateur et de la coquille traduites."""

import json
import os
import re
import unittest

from cam2027 import i18n
from cam2027.gui import shell

GUI = os.path.dirname(os.path.abspath(shell.__file__))


class TestShellRules(unittest.TestCase):
    def test_one_panel_only_below_narrow_width(self):
        self.assertTrue(shell.one_panel_only(1280))
        self.assertTrue(shell.one_panel_only(shell.NARROW_WIDTH - 1))
        self.assertFalse(shell.one_panel_only(shell.NARROW_WIDTH))
        self.assertFalse(shell.one_panel_only(1920))
        # à 1280 px, navigateur ou panneau de tâche seul : la vue centrale garde plus de la moitié
        self.assertGreater(1280 - max(shell.NAVIGATOR_WIDTH, shell.INSPECTOR_WIDTH), 1280 / 2)
        # à 1600 px et plus, les deux panneaux ouverts laissent encore la moitié à la vue
        self.assertGreaterEqual(shell.NARROW_WIDTH - shell.NAVIGATOR_WIDTH - shell.INSPECTOR_WIDTH, shell.NARROW_WIDTH / 2)

    def test_default_space(self):
        self.assertEqual(shell.default_space(False, False, False), "prepare")
        self.assertEqual(shell.default_space(True, False, False), "prepare")
        self.assertEqual(shell.default_space(True, True, False), "machine")
        self.assertEqual(shell.default_space(True, True, True), "machine")

    def test_menus_match_spaces(self):
        from cam2027.gui import commands

        self.assertEqual([title for title, _names in commands.STAGE_MENUS], [label for _k, label, _i in shell.SPACES])
        registered = {name for name, _cls in commands.COMMANDS}
        for _title, names in commands.STAGE_MENUS:
            for name in names:
                if name != "Separator":
                    self.assertIn(name, registered, name)

    def test_navigator_commands_registered(self):
        from cam2027.gui import commands

        registered = {name for name, _cls in commands.COMMANDS} | {"Std_Open"}
        with open(os.path.join(GUI, "navigator.py"), "r", encoding="utf-8") as fp:
            used = set(re.findall(r'"((?:CAM2027|Std)_[A-Za-z0-9]+)"', fp.read())) - {"CAM2027_Navigator"}  # nom du widget
        self.assertTrue(used)
        self.assertEqual(sorted(used - registered), [])

    def test_shell_strings_translated(self):
        with open(os.path.join(os.path.dirname(i18n.__file__), "i18n", "fr.json"), "r", encoding="utf-8") as fp:
            catalog = json.load(fp)
        for _key, label, _icon in shell.SPACES:
            self.assertIn(label, catalog, label)
        self.assertEqual(i18n.missing_translations("fr"), [])


if __name__ == "__main__":
    unittest.main()
