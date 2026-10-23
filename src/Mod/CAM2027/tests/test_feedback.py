# SPDX-License-Identifier: LGPL-2.1-or-later
"""Version alpha : formulaires GitHub de bug et d'idée (adresses, champs préremplis, fichiers du dépôt)."""

import os
import unittest
from urllib.parse import parse_qs, urlparse

from cam2027 import feedback
from cam2027.version import __version__, RELEASE_STAGE, REPOSITORY_URL

#: dossier des formulaires GitHub du dépôt (absent quand le module est installé seul)
TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".github", "ISSUE_TEMPLATE")


class TestFeedback(unittest.TestCase):
    def test_issue_urls(self):
        for kind in ("bug", "idea"):
            url = urlparse(feedback.issue_url(kind))
            self.assertEqual("%s://%s%s" % (url.scheme, url.netloc, url.path), REPOSITORY_URL + "/issues/new")
            query = parse_qs(url.query)
            self.assertEqual(query["template"], [feedback.TEMPLATES[kind]])
            env = query["environment"][0]
            self.assertIn("CAM2027 %s %s" % (__version__, RELEASE_STAGE), env)
            self.assertIn("FreeCAD 1.", env)

    def test_alpha_stage(self):
        from cam2027.gui import standalone

        self.assertEqual(RELEASE_STAGE, "alpha")
        self.assertEqual(standalone.window_title(), "CAM2027 %s alpha" % __version__)

    @unittest.skipUnless(os.path.isdir(TEMPLATES_DIR), "module installed without the repository")
    def test_templates_exist_with_environment_field(self):
        """Le formulaire nommé dans l'adresse existe et porte le champ ``environment`` prérempli."""
        for name in feedback.TEMPLATES.values():
            path = os.path.join(TEMPLATES_DIR, name)
            self.assertTrue(os.path.isfile(path), path)
            with open(path, encoding="utf-8") as fp:
                self.assertIn("id: environment", fp.read())


if __name__ == "__main__":
    unittest.main()
