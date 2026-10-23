# SPDX-License-Identifier: LGPL-2.1-or-later
"""Version de l'atelier CAM2027 et des formats de données."""

__version__ = "0.1.3"
#: phase de test : affichée dans le titre de la fenêtre, la barre d'état et « À propos »
RELEASE_STAGE = "alpha"
#: dépôt public : formulaires de bug et d'idée (``cam2027.feedback``)
REPOSITORY_URL = "https://github.com/storm8488/FreeCAD-CAM-2027"
#: soutien du projet (menu Aide > Soutenir le projet)
SUPPORT_URL = "https://buymeacoffee.com/damouse8482"

# Version du schéma JSON (bibliothèque d'outils, instantané de projet, profil machine).
# Toute modification incompatible incrémente ce nombre et ajoute une migration
# dans cam2027.tools.library.migrate().
DATA_VERSION = 1

# Base FreeCAD épinglée pour le fork (tag + commit). L'atelier reste exécutable
# sur FreeCAD 1.0.2 (distribution officielle installée) grâce à cam2027.compat.
FREECAD_PINNED_TAG = "1.1.4"
FREECAD_PINNED_COMMIT = "4fd3bf320d9566a27e60069fc8387448aaa3a094"
FREECAD_MIN_VERSION = (1, 0, 0)
