# CAM2027 — Tests et benchmarks

## Tests automatiques (console)

```bat
scripts\cam2027-tests.cmd            # tout
scripts\cam2027-tests.cmd test_tools # un module
```

Exécutés par `FreeCADCmd.exe -M src\Mod\CAM2027 tests\run_all.py` (unittest). Résultat
détaillé dans `src/Mod/CAM2027/tests/last-run.txt`.

| Module | Tests | Ce qui est vérifié |
|---|---|---|
| `test_tools.py` | 17 | unités (mm/in, mm/min, rad/deg) ; construction des 20 types ; conventions d'angles (cône V 60° = hauteur calculée, rejet 180°) ; validations (dent > totale, rayon > D/2, dents < 1) ; relations n/Vc et Vf/fz dans les deux sens pilotes ; assemblage (sortie > L, taillé dans le porte-outil, alésage ≠ queue) ; duplication (nouveaux ids) ; bibliothèque : aller-retour JSON + révision, recherche/filtres/favoris, édition groupée atomique, suppression protégée, instantané figé, refus d'une version future, import Fusion synthétique (champs inconnus rapportés, pouces convertis, outil non supporté ignoré) |
| `test_pipeline.py` | 11 | **chaîne complète** : bibliothèque → projet → STEP (plaque 80×60×10 avec poche, îlot et avant-trou Ø6,8) → brut à marges (84×64, Z max 11) → G54 + bride → poche (face du fond) + contour extérieur → recalcul (commandes > 10, XYZ seulement, Z min 4 / 0, avance 1800 copiée dans le ToolController, modification du préréglage sans effet) → export GRBL (G21, G54, enveloppe, F1800, S18000, statut « non vérifiable » pour les courses inconnues, fiche avec tableau d'outils) → sauvegarde → réouverture (instantané, machine, 2 opérations, registre, mêmes commandes, même enveloppe) ; export **bloqué** si la course X est dépassée ; rejet des mots A/B/C sans axe, des pouces (G20) et des codes non GRBL ; ToolBit FreeCAD pour chaque outil de la bibliothèque de démarrage (diamètre, angle inclus, angle de pointe foret) ; **surfaçage** de la face supérieure (passe 1 mm, Z min 9, centre outil hors de la pièce avec `ClearEdges`) ; **fraisage de filet** M8 × 1,25 dans l'avant-trou avec la fraise à fileter 4 mm (diamètres résolus depuis la table FreeCAD 6H à 50 % : 8,17 / 6,7795, pas 1,25, G3, Z min 0, rayon de la dernière passe autour du centre du trou ; refus d'un pas hors plage outil, d'un outil non fileteur, d'un filet inconnu) ; **chanfrein** 1 mm + 0,5 des arêtes supérieures avec le V-bit 90° (Z 8,5, contour décalé de 0,55, G2) ; libellés/limites des stratégies tous traduits et `missing_translations('fr')` vide ; **specs de paramètres** (chaque propriété exposée a un libellé/onglet/aide traduits ; genres, énumérations, lecture/écriture typées sur une opération) ; **modification d'opérations** (mise à jour + registre, ordre, activation, duplication juste après l'original, changement de désignation de filet, suppression avec ToolController/ToolBit, géométrie) ; **habillages** (attaches : 4 positions, remontées au sommet des attaches, une seule occurrence du contour dans le G-code ; rampe : plus de plongée verticale ; retrait et retour à l'opération nue) |
| `test_import.py` | 5 | STEP (volume), STL (maillage puis solide), SVG (3 contours fermés), DXF (ligne + cercle, lecteur C++ en console), extensions inconnues / fichier absent |

**Dernier résultat (2026-10-20) : 33 tests, 0 échec, sur FreeCAD 1.1.4 portable (API
outils « assets », PySide6) et sur FreeCAD 1.0.2 (API « legacy », PySide2).** Le lanceur
de tests choisit la 1.1.4 si elle est installée ; `FREECAD_BIN` force une version.

## Vérification graphique

```bat
"C:\Program Files\FreeCAD 1.0\bin\FreeCAD.exe" -M src\Mod\CAM2027 src\Mod\CAM2027\tests\gui_smoke.py
```

Active l'atelier, déroule la chaîne par l'API, ouvre les panneaux, capture
`tests/screenshots/*.png` et `gui_smoke.txt` (doit finir par `OK`), puis quitte.
Dernier résultat (2026-10-20, sur 1.1.4 avec un profil de lanceur temporaire, `CAM2027_HOME`
défini) : atelier activé, profil « FAO seule » appliqué (thème sombre, 20 ateliers masqués),
10 commandes enregistrées, barre d'outils présente, interface en français, panneaux
bibliothèque (3 onglets, aperçu coté) et flux de travail rendus (4 étapes, liste des
opérations, duplication et déplacement d'une opération), éditeur d'opération ouvert
(5 onglets, passe axiale appliquée et relue sur l'objet), parcours visible dans la vue 3D,
G-code prévisualisé, projet sauvegardé, FreeCAD fermé sans erreur. 1.0.2 : dernier passage
avant le panneau de flux de travail et l'éditeur (à refaire).

## Non couvert

- Interface : dialogues (brut, opération, export, machine) non exercés automatiquement ;
  vérifiés visuellement seulement via les captures.
- FreeCAD 26.3rc2 (candidate) non testée.
- Aucune validation sur machine.

## Benchmarks

Pas encore de corpus fixe ni de mesures. Prévu (jalon F) : corpus = poche aluminium
avec îlots, contour avec attaches, incrustation en V, relief 3D, pièce indexée, parcours
rotatif, cas XYZA ; mesures de temps/mémoire à précision géométrique constante.
