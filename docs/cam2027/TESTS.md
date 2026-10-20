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
| `test_tools.py` | 18 | unités (mm/in, mm/min, rad/deg) ; construction des 20 types ; conventions d'angles (cône V 60° = hauteur calculée, rejet 180°) ; validations (dent > totale, rayon > D/2, dents < 1) ; relations n/Vc et Vf/fz dans les deux sens pilotes ; assemblage (sortie > L, taillé dans le porte-outil, alésage ≠ queue) ; duplication (nouveaux ids) ; bibliothèque : aller-retour JSON + révision, recherche/filtres/favoris, édition groupée atomique, suppression protégée, instantané figé, refus d'une version future, import Fusion synthétique (champs inconnus rapportés, pouces convertis, outil non supporté ignoré) ; fusion des outils de démarrage manquants (par nom, numéros libres, porte-outil réutilisé, idempotent) |
| `test_pipeline.py` | 24 | **chaîne complète** : bibliothèque → projet → STEP (plaque 80×60×10 avec poche, îlot et avant-trou Ø6,8) → brut à marges (84×64, Z max 11) → G54 + bride → poche (face du fond) + contour extérieur → recalcul (commandes > 10, XYZ seulement, Z min 4 / 0, avance 1800 copiée dans le ToolController, modification du préréglage sans effet) → export GRBL (G21, G54, enveloppe, F1800, S18000, statut « non vérifiable » pour les courses inconnues, fiche avec tableau d'outils) → sauvegarde → réouverture (instantané, machine, 2 opérations, registre, mêmes commandes, même enveloppe) ; export **bloqué** si la course X est dépassée ; rejet des mots A/B/C sans axe, des pouces (G20) et des codes non GRBL ; ToolBit FreeCAD pour chaque outil de la bibliothèque de démarrage (diamètre, angle inclus, angle de pointe foret) ; **surfaçage** de la face supérieure (passe 1 mm, Z min 9, centre outil hors de la pièce avec `ClearEdges`) ; **fraisage de filet** M8 × 1,25 dans l'avant-trou avec la fraise à fileter 4 mm (diamètres résolus depuis la table FreeCAD 6H à 50 % : 8,17 / 6,7795, pas 1,25, G3, Z min 0, rayon de la dernière passe autour du centre du trou ; refus d'un pas hors plage outil, d'un outil non fileteur, d'un filet inconnu) ; **chanfrein** 1 mm + 0,5 des arêtes supérieures avec le V-bit 90° (Z 8,5, contour décalé de 0,55, G2) ; libellés/limites des stratégies tous traduits et `missing_translations('fr')` vide ; **specs de paramètres** (chaque propriété exposée a un libellé/onglet/aide traduits ; genres, énumérations, lecture/écriture typées sur une opération) ; **modification d'opérations** (mise à jour + registre, ordre, activation, duplication juste après l'original, changement de désignation de filet, suppression avec ToolController/ToolBit, géométrie) ; **habillages** (attaches : 4 positions, remontées au sommet des attaches, une seule occurrence du contour dans le G-code ; rampe : plus de plongée verticale ; retrait et retour à l'opération nue) ; **perçage** sans sélection (trou détecté automatiquement, G83, centre du trou) ; **hélice** dans l'avant-trou (G2/G3, rayon dans le trou) et **gravure** des arêtes supérieures (Z 9,5, enveloppe 80×60) ; **changement d'outil** (préréglage : avance 600 dans le même contrôleur ; coupant 3 mm : nouveau contrôleur, ancien supprimé, contour décalé de 1,5 ; outil non fileteur refusé sur un filetage) ; **dogbones** sur la poche (centre outil au-delà du décalage de paroi dans les angles, retour au parcours nu après retrait) ; **V-carve** du fond de poche (axe médian dans la poche, Z min = profondeur finale imposée) et **rainure** entre deux points personnalisés (Z 8, X 10..70) ; **flux 2D** : SVG, panneau 12 mm (Z 0 / -12), découpe extérieure du rectangle (décalage 3), poche 2D du cercle (Z -3, dans le cercle), V-carving du rectangle (Z -4), gravure du cercle, export sans erreur ; **états de calcul** (à calculer, calculé, à recalculer après modification, inactive, avertissement, échec sans mouvement de coupe) ; **récapitulatif avant export** (unités, repère, état des opérations, contrôles jamais « ok » quand des données machine manquent, opération à recalculer signalée) ; libellé traduit pour chaque champ machine / axe A ; **finition 3D** d'un dôme (surface : aucun point de coupe sous la surface, sommet atteint ; Z constant : au moins 4 niveaux ; ébauche 3D : faces en relief choisies automatiquement, au moins 5 niveaux, distance au dôme ≥ rayon outil + surépaisseur) ; **4e axe indexé** (barreau sur l'axe A, brut rond d'axe X : refus sans centre / sens, refus « toute la pièce », poche du dessus à A0 et du flanc à A90 au même Z 10 et dans X 25..55 / Y -5..5, `G0 A0` puis `G0 A90` avant les bonnes opérations, aucune erreur, avertissement GRBL, réordonnancement et réindexation, positionnement manquant détecté, plage A dépassée refusée et signalée, A pendant une coupe refusé) ; **relief depuis une image** (bosse gaussienne connue en PNG 80×60 px → solide 60×45×9 valide ; 56 points : matière 0,15 mm sous la hauteur attendue, vide 0,15 mm au-dessus ; inversion = creux ; JPG lu en console ; finition 3D boule 6 mm : aucun point sous la surface, sommet suivi ; ébauche 3D : au moins 4 niveaux, aucune matière au-dessus de Z sous le disque de la fraise) ; **4e axe continu** (gravure enroulée d'un rectangle presque un tour et d'une hélice sur un brut rond R20 : refus sans axe A, G93 présent, A en coupe uniquement en G93, F sur chaque mouvement, retour G94, aucune erreur, A 0..360, plus de 100 points de coupe ramenés sur le dessin à 0,02 mm, vitesse réelle = avance du préréglage à 2 %, niveaux -0,25 / -0,5, aperçu 3D sur le dessin, vitesse angulaire au-delà du profil refusée, F manquant et fin en G93 refusés, dessin plus long que la circonférence signalé, régénération identique après réouverture) |
| `test_sim.py` | 12 | **contrôle matière** : rainure fraise plate (volume à 2 %, fond et bord exacts), profils boule et V 90° exacts au centre des colonnes, profil torique, arc G2 découpé sur son rayon, descente rapide dans la matière comptée (dégagement vertical vers le haut jamais compté), dessus d'une boîte et d'une sphère ; paroi verticale pile sur les centres des colonnes (fraise tangente : aucune entaille ; 0,6 mm dans la paroi : entaille) ; **filetage sans sélection** de la plaque (M6 demandé, M8 × 1,25 retenu pour l'avant-trou de 6,8 mm, filet compté jusqu'au diamètre majeur : aucune entaille, un seul défaut « trou pas percé ») ; projets : surfaçage à Z 10 de la plaque (aucune entaille, 5376 mm³ enlevés à 3 %, 6 mm de reste dans la poche non usinée), puis à Z 9 (entaille 1,0 mm, plus de 1000 cellules) ; finition boule d'un dôme (aucune entaille, reste moyen < 0,3 mm) ; **collisions** : enveloppe d'un assemblage (taillé 0-5, queue 5-8, porte-outil ER20 8-28 Ø28 / 28-43 Ø34), matière au-dessus de la queue (4 mm), bride touchée à 2,9 mm et pas à 3,1 mm, porte-outil au-dessus / dans la hauteur d'une bride ; contour en passe de 10 mm avec une fraise taillée sur 5 mm (frottement > 4 mm, opération et n° de commande), sortie 8 mm (porte-outil sous le dessus de la plaque), bride sur le trajet (touchée d'abord par le porte-outil), sans bride = « non contrôlé » ; export bloqué par ces collisions, puis « non vérifiable » après modification ; projet propre = tout « OK » ; assemblage sans porte-outil = « non contrôlé » |
| `test_inlay.py` | 4 | **fond plat** (rectangle 40×20, V 60° limité à 2 mm, fraise 3 mm : ordre des opérations, 4 angles vifs, fraise plate hors de la bande du V-bit ; matière simulée : fond à -2, flancs z = -d / tan 30° sur les deux côtés, angles sur la diagonale, rien hors du dessin ; forme trop étroite refusée) ; **incrustation** (femelle 4, départ mâle 2, mâle 4 : profondeurs incohérentes refusées, 4 + 4 opérations valides, mâle retourné sur la femelle simulée à 0,1 mm : interférence < 0,12, flancs en contact, colle 2 mm au fond, 2 mm entre planches) ; **imbrication** (ligne d'horizon : 6 rectangles dans 280×180 sans chevauchement à 5 mm, bande tournée, pièce trop grande rapportée ; projet : 3 copies + disque + triangle dans 300×200, contours sans intersection, utilisation exacte, panneau 300×200 repris à la création du job, refus après le job, 4 pièces sur 6 quand la surface ne permet pas plus) |
| `test_ui_logic.py` | 11 | logique derrière l'interface (bugs trouvés en test utilisateur) : outil compatible par stratégie (V-carving refuse la fraise plate, chaque stratégie a un outil de démarrage), fonds de poche et dessus trouvés sans sélection (fond sous un surplomb de rainure en T écarté), réglages initiaux (échantillonnage 3D, liaisons de l'adaptative), repli de la projection du mode « modèle » quand `concatenate` échoue, STL fermé converti en solide (6 faces pour un cube, maillage gardé masqué, un seul candidat), brut / clone / bride exclus des pièces, fusion d'un assemblage empilé (aucune entaille au contour), contrôle retrouvé après relecture du projet et après réouverture du fichier, messages traduits (`Msg`, `UserError`, imbriqués) ; **plantage du brut** : fichier importé deux fois (avertissement, doublons reconnus, fusion jamais vide, forme vide refusée avant le brut, brut créé) et le STEP réel de l'utilisateur importé deux fois (fusion brute refusée, 2 corps uniques, brut de 47 mm) |
| `test_theme.py` | 5 | jetons : mêmes rôles dans les deux thèmes, chaque rôle et niveau d'état utilisé par l'interface existe ; chaque icône référencée existe en sombre et en clair ; feuille de style résolue (aucun gabarit restant, accolades équilibrées) ; préférence de thème ; couleurs de scène converties en RGBA FreeCAD, rien d'écrit hors du lanceur |
| `test_import.py` | 5 | STEP (volume), STL (maillage puis solide), SVG (3 contours fermés), DXF (ligne + cercle, lecteur C++ en console), extensions inconnues / fichier absent |

**Dernier résultat (2026-10-20) : 79 tests, 0 échec, sur FreeCAD 1.1.4 portable (API
outils « assets », PySide6) et sur FreeCAD 1.0.2 (API « legacy », PySide2).** Le lanceur
de tests choisit la 1.1.4 si elle est installée ; `FREECAD_BIN` force une version.

## Scénarios utilisateur (`tests/gui_scenarios.py`)

```bat
set CAM2027_SCENARIO_FILES=C:\chemin\piece.stl;C:\chemin\assemblage.step
%USERPROFILE%\CAM2027\bin\CAM2027.exe Mod\CAM2027\tests\gui_scenarios.py
```

Les **vraies commandes** sont appelées comme par les boutons ; dialogues de fichier, saisies, boîtes
modales et éditeur d'opération sont remplis par un pilote. Relevé : exceptions, messages (tout message
en anglais est une erreur), étapes du panneau Projet, panneau Tâches vide, résultat attendu. Rapport
`tests/screenshots/gui_scenarios.txt` (finit par `OK` sans aucune ligne `PROBLEM`) et capture de chaque
dialogue dans `tests/screenshots/dialogs/`. 19 scénarios : commandes sans projet, STEP / STL (contour,
poche, adaptative, surfaçage), import sans projet, flux 2D SVG (imbrication, panneau, contour, poche,
V-carving, gravure, fond plat, export), relief PNG, boutons du panneau, simulateur, bibliothèque
d'outils (toutes les actions, export / import), éditeur (passe, outil, abandon), profil machine (axe A,
saisie invalide), brut rond et gravure enroulée, incrustation, même fichier importé deux fois puis brut
(le plantage signalé), et chaque fichier de l'utilisateur.

Dernier passage (2026-10-20) : **0 problème** dans la distribution (avec `bitTray3030+v7.stl` et un STEP
d'assemblage de l'utilisateur) et sur FreeCAD 1.0.2 ; l'export de l'assemblage est **bloqué à raison**
(le nez du porte-outil touche la pièce de 47 mm).

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
(6 onglets, passe axiale appliquée et relue sur l'objet, préréglage changé depuis l'onglet Outil : avance 600 dans le contrôleur), parcours visible dans la vue 3D,
G-code prévisualisé, projet sauvegardé, FreeCAD fermé sans erreur ; onglet « Entrée, sortie et
attaches » : 3 attaches ajoutées depuis l'éditeur. Même résultat sur 1.0.2 (PySide2, profil
temporaire : 19 ateliers masqués, thème sombre « FreeCAD Dark.qss »).

## Démonstration guidée

```bat
scripts\cam2027.cmd src\Mod\CAM2027\tests\gui_demo.py
```

Dix étapes commentées (bibliothèque, projet, brut, surfaçage, poche et contour, chanfrein,
filetage, export, éditeur d'opération, flux 2D). Avec `CAM2027_DEMO_AUTO=1`, les boîtes ne
s'affichent pas, le journal est écrit dans `tests/screenshots/gui_demo.txt` (doit finir par
`OK`) et FreeCAD se ferme. Dernier passage automatique (2026-10-20, 1.1.4, profil temporaire) :
10 étapes, `OK`.

## Matrice stratégies × pièces (`tests/run_strategy_matrix.py`)

```bat
python src\Mod\CAM2027\tests\run_strategy_matrix.py --files "plate;dome;C:\chemin\piece.stl" --timeout 400
```

Chaque case (15 stratégies × pièces) tourne dans **son propre CAM2027.exe**, avec une limite de temps : un
plantage ou une interface figée n'arrête pas les autres cases. Les vraies commandes sont appelées
(import, Brut et montage, « Ajouter une opération » sans sélection : outil compatible, géométrie
automatique), puis recalcul et contrôle matière / collisions. Une case est en défaut sur plantage,
dépassement de temps, exception, opération en échec, refus sans message, entaille de plus de 0,05 mm ou
collision (sauf le filetage seul, où « trou pas encore percé » est le défaut attendu). Rapport
`matrix.txt` / `matrix.json`.

Défauts trouvés et corrigés (2026-10-20, plaque, dôme, `bitTray3030+v7.stl`, chauffage Vz330) :
ébauche 3D figée plus de 15 min (mode « modèle »), puis sans parcours sur le chauffage (projection
FreeCAD « Wire is not closed ») et G0 à travers 3 mm de matière (liaisons à la profondeur de coupe) ;
finition 3D : entaille de 1,45 mm (échantillonnage 0,5 mm) ; filetage M6 dans des trous de 4,1 à 9 mm
(entaille de 13 mm) ; adaptative : fond sous un surplomb usiné à travers le surplomb ; faux positifs du
contrôle : parois verticales sur la grille (25 mm « d'entaille » sur la poche du plateau), filet compté
comme entaille, dégagement vertical compté comme rapide dans la matière. Restent, à raison : porte-outil
et queue au contact sur le chauffage (pièce de 47 mm, sortie de 35 mm) et le plateau (alvéoles de 25 mm).

## Non couvert

- Interface : dialogues (brut, opération, export, machine) non exercés automatiquement ;
  vérifiés visuellement seulement via les captures.
- FreeCAD 26.3rc2 (candidate) non testée.
- Aucune validation sur machine.

## Benchmarks

Pas encore de corpus fixe ni de mesures. Prévu (jalon F) : corpus = poche aluminium
avec îlots, contour avec attaches, incrustation en V, relief 3D, pièce indexée, parcours
rotatif, cas XYZA ; mesures de temps/mémoire à précision géométrique constante.
