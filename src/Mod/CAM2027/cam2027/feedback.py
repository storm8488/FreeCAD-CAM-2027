# SPDX-License-Identifier: LGPL-2.1-or-later
"""Retours des testeurs (version alpha) : formulaires GitHub du dépôt, préremplis avec l'environnement.

Les formulaires sont dans ``.github/ISSUE_TEMPLATE`` du dépôt ; GitHub remplit un champ d'après le paramètre
d'adresse qui porte son ``id`` (ici ``environment``). Rien n'est envoyé par le logiciel : l'adresse s'ouvre
dans le navigateur et le testeur relit et envoie lui-même.
"""

import platform
from urllib.parse import urlencode

from .version import __version__, RELEASE_STAGE, REPOSITORY_URL

#: formulaire GitHub par genre de retour
TEMPLATES = {"bug": "1-cam2027-bug.yml", "idea": "2-cam2027-idea.yml"}


def environment():
    """« CAM2027 0.1.3 alpha, FreeCAD 1.1.4, Windows 10.0.26300 » : versions utiles au tri d'un bug (Python
    nomme « Windows-10 » aussi Windows 11 : le numéro de build, lui, les distingue)."""
    import FreeCAD

    v = FreeCAD.Version()
    system = "Windows %s" % platform.version() if platform.system() == "Windows" else platform.platform()
    return "CAM2027 %s %s, FreeCAD %s.%s.%s, %s" % (__version__, RELEASE_STAGE, v[0], v[1], v[2], system)


def issue_url(kind):
    """Adresse du formulaire GitHub ``kind`` (``bug`` ou ``idea``), environnement prérempli."""
    return "%s/issues/new?%s" % (REPOSITORY_URL, urlencode({"template": TEMPLATES[kind], "environment": environment()}))
