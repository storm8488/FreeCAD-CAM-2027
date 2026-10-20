# CAM2027 — Limites connues (version 0.1.0)

Statuts utilisés : **implémenté** / **testé automatiquement** / **vérifié visuellement** /
**validé sur machine**. Rien n'est validé sur machine à ce jour.

## Base et exécution

- L'atelier tourne sur FreeCAD **1.0.2** (distribution officielle). La branche d'API 1.1.x
  (`tool_api() == "assets"`) est écrite mais **non exécutée** : 1.1.4 n'est pas installé.
- Pas de compilation du fork (ni MSVC, ni CMake, ni LibPack). Aucun exécutable « CAM2027 »
  compilé : le lanceur démarre le FreeCAD installé avec l'atelier.
- Les postprocesseurs, le simulateur et toutes les stratégies sont ceux de FreeCAD CAM.

## Bibliothèque d'outils

- Les 20 types stockent la géométrie Fusion complète, mais seuls endmill, ballend,
  bullnose, chamfer/V-bit/engrave, drill, dovetail, threadmill (et radius/taperedball
  sur 1.1) ont une forme FreeCAD exacte. Taper, facemill, lollipop, slot, barrel, lens,
  ogive, taperbarrel, form sont **approximés** (fraise cylindrique ou sphérique, signalé
  dans `warnings`) : aucune stratégie FreeCAD n'exploite ces profils.
- L'aperçu coté est **2D** (profil de révolution, cotes D / Lc / L / sortie). L'aperçu 3D
  (bouton « Afficher en 3D ») n'est pas coté.
- Import Fusion : **non validé sur un export réel**. Mapping des clés JSON (`DC`, `SFDM`,
  `OAL`, `LB`, `LCF`, `RE`, `TA`, `SIG`, `NOF`, presets `n`/`v_f`/`f_z`…) d'après la
  structure connue ; rapport de conversion listant les champs inconnus. Fournir un export
  `.json`/`.tools` réel pour valider.
- Expressions entre paramètres : seulement les deux relations `n = 1000·Vc/(π·D)` et
  `Vf = n·z·fz` avec grandeur pilote déclarée. Pas de moteur d'expressions général,
  pas de détection de cycles (jalon C).
- Pas de matières/assemblages de matières au sens Fusion (préréglages étiquetés par
  matière et usage uniquement).

## Projet, brut, montage

- Brut : boîte à marges, boîte, cylindre. Pas de brut depuis un solide ni depuis le
  « brut restant » d'une opération précédente.
- Montage : repère G54–G59 + brides **visuelles** (boîtes). Les brides ne sont **pas**
  prises en compte par une détection de collision (il n'y en a pas).
- Un seul job par projet, un seul repère actif par job dans l'interface.

## Opérations

- Stratégies exposées : contour, poche, adaptative 2D, perçage, surfaçage, gravure,
  V-carving, alésage hélicoïdal, rainure. Pas de 3D (Surface/Waterline d'OCL), pas de
  reprise, pas de 4e axe, pas d'attaches/dogbones/rampes inline (les habillages FreeCAD
  restent utilisables dans l'atelier CAM standard sur le même document).
- La poche FreeCAD (décalage/zigzag) **n'est pas** adaptative ; « adaptative » est
  l'opération Adaptive de FreeCAD (engagement contrôlé 2D, monothread).
- Le dialogue « Ajouter une opération » expose profondeur finale, passe axiale, côté et
  dérive le recouvrement du préréglage ; les autres propriétés se règlent dans l'éditeur
  de propriétés FreeCAD de l'opération.
- Les paramètres non pris en charge par une stratégie sont listés (`ignored_params`) et
  affichés dans le panneau projet.

## Export et contrôles

- Contrôles statiques : unités (G21), codes autorisés (liste GRBL 1.1 uniquement ; autres
  contrôleurs « non vérifiable »), mots A/B/C vs axe rotatif déclaré, enveloppe XYZ vs
  courses, avance max, plage broche, Z sous le brut, présence d'un repère. Toute donnée
  machine inconnue produit « non vérifiable », jamais un « OK ».
- Pas de simulation d'enlèvement de matière, pas de contrôle de collision outil /
  porte-outil / brides, pas de cinématique.
- Fiche de préparation en Markdown (pas de PDF).

## Interface

- Thèmes clair/sombre et HiDPI : hérités de FreeCAD/Qt (non testés spécifiquement).
- Pas de recherche de commandes propre (celle de FreeCAD, « What's This / Ctrl+F » selon
  version, reste disponible), pas de sauvegarde de récupération propre (autosave FreeCAD).
- Annulation/rétablissement : ceux du document FreeCAD ; les actions de la bibliothèque
  d'outils (hors document) ne sont pas annulables.
- Vérification visuelle : captures `tests/screenshots/` produites par `tests/gui_smoke.py`.

## 4e axe

- Seuls le profil machine (champs `RotaryAxis`, tous à renseigner) et les contrôles
  d'export (rejet des mots A/B/C sans axe déclaré) existent. Aucune stratégie rotative,
  aucun enroulement, aucune indexation.
