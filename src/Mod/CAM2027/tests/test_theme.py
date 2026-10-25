# SPDX-License-Identifier: LGPL-2.1-or-later
"""Couche de thème « Atelier » : jetons complets, icônes présentes dans les deux thèmes, QSS résolue.

Pas de vérification de couleurs précises (elles viennent du fichier de jetons) : on vérifie que
chaque rôle et chaque icône référencés par le code existent, et que la feuille de style est
entièrement résolue pour les deux thèmes.
"""

import os
import re
import unittest

from cam2027.gui import theme

GUI = os.path.join(os.path.dirname(theme.__file__))


def _referenced(pattern):
    found = set()
    for name in os.listdir(GUI):
        if name.endswith(".py"):
            with open(os.path.join(GUI, name), "r", encoding="utf-8") as fp:
                found.update(re.findall(pattern, fp.read()))
    return found


class TestTheme(unittest.TestCase):
    def test_roles_in_both_themes(self):
        t = theme.tokens()
        dark, light = set(t["themes"]["dark"]), set(t["themes"]["light"])
        self.assertEqual(dark, light)
        for role in set(theme._STATUS_ROLES.values()) | _referenced(r'theme\.color\("([a-zA-Z]+)"'):
            self.assertIn(role, dark, role)
        for level in _referenced(r'status_color\("([a-z]+)"'):
            self.assertIn(level, theme._STATUS_ROLES, level)

    def test_icons_exist_in_both_themes(self):
        names = set(_referenced(r'theme\.icon\("([a-z0-9-]+)"')) | set(_referenced(r'atelier = "([a-z0-9-]+)"'))
        with open(os.path.join(GUI, "commands.py"), "r", encoding="utf-8") as fp:
            src = fp.read()
        names |= set(re.findall(r'"[a-z0-9]+": "([a-z0-9-]+)"', src[src.index("STRATEGY_ICONS"):src.index("class _Base")]))
        with open(os.path.join(GUI, "navigator.py"), "r", encoding="utf-8") as fp:
            nav = fp.read()
        names |= set(re.findall(r'"[a-z]+": "([a-z0-9-]+)"', nav[nav.index("_STATE_ICONS"):nav.index("COL_NAME")]))
        names |= set(re.findall(r'"(cmd-[a-z0-9-]+|origin|recalculate|play|export-gcode|visibility|visibility-off|axis-a|settings|redo|delete|new-project|open-project)"', nav))
        from cam2027.gui import shell
        from cam2027.project import families

        names |= {icon for _k, _l, icon in shell.SPACES} | {icon for _k, _l, icon, _s in families.FAMILIES}
        with open(os.path.join(GUI, "panels.py"), "r", encoding="utf-8") as fp:
            src = fp.read()
        names |= set(re.findall(r'"[a-z]+": "([a-z0-9-]+)"', src[src.index("TOOL_TYPE_ICONS = {"):src.index("class ToolLibraryPanel")]))
        # chaque type d'outil du modèle a une icône
        from cam2027.tools.model import TOOL_TYPES
        mapped = set(re.findall(r'"([a-z]+)": "[a-z0-9-]+"', src[src.index("TOOL_TYPE_ICONS = {"):src.index("class ToolLibraryPanel")]))
        self.assertEqual(set(TOOL_TYPES) - mapped, set())
        self.assertGreater(len(names), 10)
        for name in names:
            for th in ("dark", "light"):
                self.assertTrue(os.path.isfile(theme.icon_path(name, th)), (name, th))

    def test_stylesheet_resolved(self):
        for th in ("dark", "light"):
            qss = theme.stylesheet(th)
            self.assertIsNone(re.search(r"\{[a-zA-Z_]+\}", qss), th)
            self.assertIn('QPushButton[role="primary"]', qss)
            self.assertEqual(qss.count("{"), qss.count("}"))

    def test_scene_colors(self):
        """Couleurs de parcours de la charte converties au format RGBA des préférences FreeCAD."""
        from cam2027.gui import prefs

        self.assertEqual(prefs._rgba("#215ED6"), ((0x21 * 256 + 0x5E) * 256 + 0xD6) * 256 + 255)
        for th in ("dark", "light"):
            colors = prefs.scene_colors(th)
            self.assertEqual(set(colors), {"DefaultNormalPathColor", "DefaultRapidPathColor", "DefaultPathMarkerColor",
                                           "DefaultHighlightPathColor", "DefaultBBoxSelectionColor",
                                           "DefaultBBoxNormalColor"})
            self.assertNotEqual(colors["DefaultNormalPathColor"], colors["DefaultRapidPathColor"])
        # hors lanceur CAM2027 : rien n'est écrit dans les préférences FreeCAD
        import os
        saved = os.environ.pop("CAM2027_HOME", None)
        try:
            self.assertIsNone(prefs.apply_scene_colors("dark"))
        finally:
            if saved is not None:
                os.environ["CAM2027_HOME"] = saved

    def test_resolve_preference(self):
        self.assertEqual(theme.resolve("dark"), "dark")
        self.assertEqual(theme.resolve("light"), "light")
        self.assertIn(theme.resolve("system"), ("dark", "light"))
        with self.assertRaises(ValueError):
            theme.set_preference("neon")


if __name__ == "__main__":
    unittest.main()
