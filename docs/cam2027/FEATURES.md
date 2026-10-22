# CAM2027 — Matrice des fonctions et feuille de route

Référence détaillée des cibles : [REFERENCE-fusion-aspire.md](REFERENCE-fusion-aspire.md)
(documentation officielle Fusion / Aspire 12.5, points non vérifiés marqués).

Statut : **absent** / **partiel** / **disponible**. Validation : **impl.** (implémenté),
**auto** (testé automatiquement), **visuel** (vérifié visuellement), **machine** (validé sur
machine). Composant = ce qui est réutilisé dans FreeCAD.

## Bibliothèque d'outils (cible : Fusion)

| Fonction cible | Statut | Composant | Validation | Travail restant / test d'acceptation |
|---|---|---|---|---|
| 20 types d'outils avec champs de l'onglet Coupant | disponible | `tools/model.py` | auto (`test_every_type_builds`) | Formes FreeCAD exactes pour taper/facemill/slot/lollipop/barrel/lens/ogive (jalon C) |
| Géométrie : D, corps, L totale, sous porte-outil, épaulement, dent, rayon, pointe, dépouille, profil… | disponible | idem | auto | — |
| Queue et porte-outil par segments | disponible | `Segment`, `Holder` | auto | Éditeur graphique des segments (actuel : texte) |
| Conditions de coupe complètes (broche, Vc, rampe, avances entrée/sortie/transition/rampe/plongée, par tour, ap/ae, arrosage) | disponible | `CuttingPreset` | auto (`test_preset_relations`) | Mode expressions général |
| Relations n/Vc, Vf/fz avec grandeur pilote | disponible | `CuttingPreset.resolve` | auto | Détection de cycles pour expressions libres |
| Données de sortie (n°, correcteurs, changement manuel, propriétés post) | disponible | `OutputData` | auto | Utilisation des correcteurs par les posts FreeCAD (vérifier) |
| Plusieurs préréglages par outil | disponible | `ToolDefinition.presets` | auto | — |
| Séparation définition / assemblage / préréglage / valeurs d'opération | disponible | registre projet | auto (`test_full_chain`) | — |
| Instantané versionné par projet | disponible | `LibrarySnapshot` | auto (`test_snapshot_is_frozen`) | Diff / mise à jour contrôlée depuis la bibliothèque courante (interface) |
| Recherche, filtres, favoris, duplication, édition groupée | disponible | `ToolLibrary` | auto | — |
| Import/export | partiel | JSON `.cam2027tools`, import Fusion `.json`/`.tools` | auto (export réel 2.16 : 11 outils, 4 types) | types non couverts par l'export réel (voir LIMITS), expressions Fusion, export vers Fusion absent |
| Aperçu 3D coté | partiel | `gui/preview.py` (2D coté) + ToolBit 3D | visuel | Cotes dans la vue 3D |

## Opérations 2D / 2,5D (cible : Fusion + Aspire)

| Fonction cible | Statut | Composant | Validation | Travail restant |
|---|---|---|---|---|
| Surfaçage | disponible | `Path.Op.MillFace` | auto (`test_facing`) | — |
| Comparer et modifier plusieurs opérations | disponible | Usiner > Comparer et modifier des opérations (`project/bulkedit.py`, `gui/bulkedit.py`) : paramètres communs × opérations, différences en gras, filtre, valeur appliquée à toutes puis recalcul | auto (`test_nuit_s3.py` : hauteur de dégagement de 3 opérations) + scénario `bulk-edit` | outil / avances / géométrie non comparés |
| Contour 2D | disponible | `Path.Op.Profile` | auto | entrées/sorties inline, attaches (habillage) |
| Poche | disponible | `Path.Op.Pocket` | auto | — |
| Ébauche adaptative / trochoïdale | partiel | `Path.Op.Adaptive` (2D, monothread) | impl. | tests, perf, reprise 3D |
| Rainure | disponible | `Path.Op.Slot` (arêtes/sommets ou points personnalisés) | auto (`test_vcarve_and_slot`) | — |
| Gravure | disponible | `Path.Op.Engrave` | auto (`test_helix_and_engrave`) | — |
| Chanfreinage | disponible | `Path.Op.Deburr` (clé `chamfer`) | auto (`test_chamfer`) | contrôle de collision avec les parois voisines ; largeur seule dans le dialogue |
| Perçage (cycles, débourrage) | disponible | `Path.Op.Drilling` ; sans sélection, tous les trous détectés | auto (`test_drilling_all_holes`) | — |
| Perçage intelligent (reconnaissance des trous, pointage, perçage, chanfrein, filetage) | disponible | `project/holes.py`, Usiner > Perçage intelligent ; cycles simulés au contrôle matière | auto (`test_nuit_s2.TestHoles` : 6 trous de 3 tailles reconnus, 7 opérations, carte de hauteur, chanfrein) + scénario `s2-holes` | taraudage (pas de type taraud), trous inclinés, lamages à la fraise |
| Alésage hélicoïdal | disponible | `Path.Op.Helix` | auto (`test_helix_and_engrave`) | — |
| Fraisage de filets | partiel | `Path.Op.ThreadMilling` (clé `threadmill`), tables de filets FreeCAD | auto (`test_thread_milling`) | nombre de dents inutilisé par FreeCAD, crête à 0, filets extérieurs et impériaux non testés |
| Attaches, rampes, dogbones | disponible | habillages FreeCAD `Path.Dressup.Tags`, `RampEntry`, `DogboneII` via `project/dressups.py`, onglet « Entrée, sortie et attaches » de l'éditeur | auto (`test_dressups`, `test_dogbones`) + visuel | positions d'attaches dans l'éditeur (actuellement panneau FreeCAD) |
| Motifs de parcours (grille, cercle, moins de changements d'outil) | disponible | habillage CAM2027 `project/patterns.py` (principe de `Path.Dressup.Array`), Usiner > Motif | auto (`test_nuit_s2.TestPatterns` : 3 × 2 poches dans la carte de hauteur, cercle, ordre par outil) + scénario `s2-pattern` | motif commun copie par copie, miroir, réglages dans l'éditeur |
| Entrées / sorties en arc (horizontal, vertical, droite) | disponible | habillage `LeadInOut` (1.0 et 1.1) via `project/leads.py`, contrôle de collision et départ déplacé (1.1) | auto (`test_nuit_s2.TestLeads` : arc R3 tangent, aucune entaille, 1.0 / 1.1) + scénario `s2-leads` | arc vertical et balayage ≠ 90° sur 1.0 |

## Opérations 3D

| Fonction cible | Statut | Composant | Travail restant |
|---|---|---|---|
| Ébauche volumique | partiel | `Path.Op.Adaptive` autour des faces en relief (clé `rough3d`, faces choisies automatiquement si toute la pièce est sélectionnée) | auto (`test_3d_finishing` : niveaux, surépaisseur respectée) | marches entre niveaux (pas de reprise des marches), ébauche depuis le brut restant |
| Reprise depuis le brut restant | partiel | `project/rest.py` : brut = carte de hauteur simulée des opérations précédentes, coupes gardées où la fraise rencontre plus de « Ignorer moins de » (Fusion), liaisons recalculées (`project/trim.py`) ; ébauche 3D, adaptative, poche, poche 2D ; onglet « Reprise et zone » | auto (`test_nuit_s1` : plaque à rainure étroite) + scénario `s1-rest-area` + disque WobbleRing (7,3 % de l'ébauche, aucune entaille) | entrées en hélice dans les zones reprises (plongées verticales), calcul limité aux zones restantes (l'opération complète est calculée puis découpée), sources « depuis un fichier / des corps » |
| Finition parallèle / Z constant | disponible | `Path.Op.Surface` (clé `surface3d`), `Path.Op.Waterline` (clé `waterline`), OpenCamLib | auto (`test_3d_finishing` : pas de pénétration, sommet suivi, niveaux Z) + visuel | reprise depuis une ébauche, ébauche volumique |
| Hauteur de crête, reprise des creux, pentu/peu incliné, guidé par courbes, ébavurage | absent | — | jalons C–F |
| Finition des zones plates (Flat) | disponible | stratégie `flat3d` (`project/flatfinish.py`) : plats accessibles trouvés seuls, passes décalées à la hauteur exacte de chaque plat, fraise contenue | auto (`test_nuit_s1` : 3 hauteurs à ±0,02 mm, fraise contenue, fond percé, dôme sans plat) + scénario `s1-flat` + disque WobbleRing (0,00 mm, aucune entaille) | type Parallel, entrées en rampe, plats inclinés |
| Reprise des angles (Pencil) | disponible | stratégie `pencil` (`project/pencil.py`) : zones laissées par une boule de référence, passes le long des angles, pas réduit sur les pentes, hauteurs OpenCamLib | auto (`test_nuit_s1` : congés R2, boule Ø8 puis Ø2, -97 %, aucune entaille) + scénario `s1-pencil` | angles laissés par une fraise plate ou torique de référence, passe unique « crayon » seule |

## Dessin et fonctions Aspire

| Fonction cible | Statut | Composant | Travail restant |
|---|---|---|---|
| Import SVG / DXF / STEP / STL / OBJ | disponible | Draft `importSVG`, `Import.readDXF`, Part, Mesh | auto (`test_import`) | — |
| Usinage d'un dessin 2D dans un panneau (découpe, poche, V-carving, gravure) | disponible | `project/sheet.py` + `Path.Op.PocketShape` | auto (`test_sheet_from_drawing`) + visuel | brut depuis panneau réel non rectangulaire ; sélection d'un contour par clic sur le dessin (actuellement sélection de ses arêtes/face) |
| Édition vectorielle (nœuds, texte, booléens, calques) | partiel | menu Dessin (`project/vectors.py`, `gui/vectors.py`) : texte droit / sur arc / sur vecteur, décalage, union / soustraction / intersection, miroir, copies circulaires ; calques lus à l'import SVG | auto (`test_nuit_s5` : aires des booléens et décalages, texte sur arc, poche 2D sur le texte décalé de 2 mm dans la zone) + scénario `s5-vectors` | édition de nœuds, formes de base (rectangle, cercle), texte modifiable |
| Modèles de parcours (enregistrer / appliquer, correspondance par calque puis par nom) | disponible | `project/templates.py`, Usiner > Enregistrer / Appliquer un modèle de parcours (comportement Aspire) | auto (`test_nuit_s5` : modèle découpe + poche + V-carve appliqué à un 2e SVG, 3 opérations calculées, poche dans les formes) + scénario `s5-templates` | habillages non enregistrés |
| V-carving profondeur variable | disponible | `Path.Op.Vcarve` | auto (`test_vcarve_and_slot`) | FreeCAD démarre la gravure au sommet du modèle, pas à la hauteur de la face |
| V-carving à fond plat (2e outil) | disponible | Usiner > Fond plat (`project/inlay.py`) : poche à la profondeur limite dans la zone plate (face réduite de la portée du V-bit), contour de la zone plate au V-bit, angles vifs le long des bissectrices (le V-carving limité de FreeCAD les laisse trop peu profonds) | auto (`test_flat_depth_clearing` sur la matière simulée : fond plat, flancs en V exacts jusqu'au bord, angles vifs, rien hors du dessin) | angles rentrants arrondis au rayon de la fraise plate |
| Incrustations mâle/femelle | disponible | Usiner > Incrustation en V : femelle (V-carving + fond plat) dans le projet, mâle en miroir réduit de la profondeur de départ dans un nouveau projet ; jeux de colle et entre planches affichés | auto (`test_male_female_fit` : cartes de hauteur femelle et mâle retourné, aucune interférence, flancs en contact, jeux 2 / 2 mm) | angles rentrants de la forme (le bouchon y est vif, la cavité arrondie : à éviter ou à arrondir) |
| Dégagement multi-outils | partiel | fond plat (fraise plate + V-bit) | auto | reprise avec plusieurs diamètres de fraise plate |
| Recto-verso, repères de retournement | disponible | Préparer > Usinage recto-verso (`project/twosided.py`, `gui/twosided.py`) : face B = second job, pièce retournée autour de X / Y par le centre du brut, bascule A / B dans le panneau, goujons sur l'axe ou même coin, contrôle matière enchaîné, un fichier et une fiche par face | auto (`test_nuit_s3.py` : retournement, deux poches, carte finale = pièce à 0,05 mm, goujons refusés hors de l'axe / dans la pièce, export A / B) + scénario `two-sided` | brides par face, retournement d'un brut non parallélépipédique, pièce modifiée après coup (`resync`) |
| Placement / imbrication | partiel | Préparer > Imbriquer (`project/nesting.py`) : rectangles englobants, ligne d'horizon au meilleur ajustement, rotation 90°, copies, espacement, marge ; panneau de cette taille à la création du job | auto (`test_inlay.py` : aucun chevauchement, espacement, pièces non placées rapportées, utilisation, brut = panneau) | sens du fil ; **forme réelle et plusieurs panneaux** : faits (S3, `nesting.shape_pack`, `test_nuit_s3.py` : 20 L sur 300 × 300 = +25 % d'utilisation, écart ≥ espacement ; scénario `nest-shapes`) |
| Relief depuis une image (carte de hauteur) | disponible | `cam2027/project/relief.py` : PNG / JPG / BMP en niveaux de gris, largeur, hauteur, épaisseur, inversion, lissage, résolution → solide (surface B-spline exacte aux points de la grille) ; Préparer > Relief depuis une image | auto (`test_relief_from_image` : fidélité ± 0,15 mm, inversion, JPG en console, ébauche et finition 3D sans pénétration) + visuel | composants, combinaison, sculpture ; l'interpolation peut dépasser l'image près des bords francs (avertissement : augmenter le lissage) |
| Reliefs (composants, combinaison, sculpture) | absent | — | jalon F |
| Moulure, cannelures, texture, prisme (Aspire) | disponible | Usiner > Moulure / Cannelures / Texture / Prisme (`project/decor.py`, `Path.Op.Custom`) | auto (`test_nuit_s5` : quart-de-rond R10 boule 6 mm, section à 0,014 mm sur la carte simulée, aucune entaille ; rampes des cannelures à 0,05 mm ; texture : rien hors de la zone, profondeur maximale respectée, graine reproductible ; prisme : biseau à 0,05 mm, aucune entaille) + scénario `s5-decor` | sections dessinées, prisme en creux |
| Vectorisation d'image (Trace Bitmap) | disponible | Dessin > Vectoriser une image (`project/bitmap.py`, marching squares + Douglas-Peucker) | auto (`test_nuit_s5` : 3 contours fermés aux aires des pixels, poche 2D sur le tracé avec le trou respecté) + scénario `s5-bitmap` | courbes lissées, couleurs |
| Photo V-Carve | disponible | Usiner > Photo V-Carve (`project/bitmap.py`, `Path.Op.Custom`) | auto (`test_nuit_s5` : carte de hauteur simulée, profondeur = 2 × sombre à 0,1 mm, rien sous la profondeur maximale, blanc intact) + scénario `s5-bitmap` | angle des lignes, lignes croisées |

## 4e axe (XYZ+A)

| Fonction cible | Statut | Composant | Travail restant |
|---|---|---|---|
| Profil machine avec axe A (orientation, sens, centre, limites, mandrin, contre-pointe) | disponible | `RotaryAxis` + bloc « Axe A » du dialogue Profil machine (sens positif, centre Y/Z, min/max) | mandrin et contre-pointe non utilisés par les calculs |
| Indexation 3+1 | disponible | `project/indexing.py` : copie exacte de la pièce tournée par angle, opérations 3 axes, positionnements `G0 A` automatiques ; brut rond d'axe X ; champ « Index A » à l'ajout et dans l'éditeur | auto (`test_indexed_4th_axis`) + visuel | collisions mandrin / contre-pointe, vue des parcours dans le repère de l'index |
| Enroulement cylindrique (gravure) | disponible | `project/wrap.py` : dessin déroulé (X le long de l'axe, Y = longueur d'arc) gravé à profondeur constante en plusieurs passes, X / Z / A simultanés en temps inverse G93, aperçu 3D du trajet réel ; Usiner > Gravure enroulée | auto (`test_wrapped_4th_axis` : points sur le dessin à 0,02 mm, vitesse réelle = avance du préréglage à 2 %, niveaux, aperçu, réouverture) + visuel | poches et contours décalés enroulés, compensation du rayon d'outil |
| Rotatif continu, XYZA simultané | partiel | gravure enroulée (XZA) ; `Path.Op.RotarySurface` amont non utilisé (non stable) | usinage 3D rotatif, Y simultané |
| Contrôles G93/G94, 0/360, tours multiples | partiel | `export.verify` : A sans axe déclaré, A en coupe refusé hors G93, F obligatoire sur chaque mouvement G93, arcs en G93 refusés, fin de programme en G93 refusée, vitesse angulaire de A contre le profil (non vérifiable si inconnue), plage A, GRBL 1.1 sans axe A, ordre des positionnements | tours multiples au-delà de la plage, vitesse linéaire réelle recalculée depuis le G-code |

## Simulation, export, intégration

| Fonction cible | Statut | Composant | Travail restant |
|---|---|---|---|
| Découpe de parcours sans recalcul (Limiter à une zone) | disponible | `project/trim.py` : rectangle ou contour fermé, dedans / dehors, liaisons recalculées ; onglet « Reprise et zone » | auto (`test_nuit_s1` : contour coupé par un rectangle, moteur seul) + scénario `s1-rest-area` | limite par un plan (Z), plusieurs zones, garder les deux côtés en deux opérations |
| Temps d'usinage avec accélération, fiche de préparation PDF | disponible | `project/timing.py` (trapèzes, vitesse en virage GRBL, passage avant / arrière), champ « Accélération » du profil machine, section de la fiche ; Exporter > Fiche de préparation (PDF) | auto (`test_nuit_s5` : 10 mm à 1000 mm/min et 500 mm/s² = L/v + v/a > 0,6 s, triangle, ligne découpée sans arrêt, demi-tour, angle droit, fiche avec le temps) + scénario `s5-setup-pdf` | accélérations par axe, temps de changement d'outil |
| Affichage des trajectoires | disponible | vue 3D FreeCAD (Path) | visuel | — |
| Enlèvement de matière | disponible | Simuler : simulateur CAM de FreeCAD (`CAM_SimulatorGL`, fenêtre avec lecture / pause / pas à pas / vitesse) lancé réglé, opérations sur A exclues ; Simuler > Contrôle matière : carte de hauteur (`project/sim.py`, grille 0,5 mm, fraises plate / boule / torique / conique) comparée à la pièce : volume enlevé, entailles (rouge), matière restante, rapides dans la matière | auto (`test_sim.py` : rainures plate / boule / V exactes, arcs, rapide, dessus de pièce ; surfaçage juste = 0 entaille et 5376 mm³ ; surfaçage 1 mm trop bas = entaille 1,0 mm ; dôme fini sans entaille) + visuel (fenêtre du simulateur, brut simulé) | 4e axe non simulé, parois verticales et contre-dépouilles non contrôlées |
| Zones interdites (keep-out) | disponible | Préparer > Zones interdites (`project/keepout.py`, `gui/keepout.py`) : boîtes dessinées et brides évitées par les rapides (montée au-dessus + marge), coupe dans une zone = erreur d'export avec position | auto (`test_nuit_s3.py` : bride entre deux poches, coupes identiques, contrôle des brides OK ; zone sur une poche : export bloqué) + scénario `keep-out` | zones non rectangulaires, rapides ajoutés par les habillages FreeCAD (attaches, entrées) non relevés |
| Collisions (outil, porte-outil, brides) | disponible | Simuler > Contrôle matière et collisions (`project/sim.py`) : enveloppe de l'assemblage (partie taillée, queue jusqu'à la sortie, tronçons du porte-outil) ; matière au-dessus de la longueur de coupe, porte-outil dans la matière (brut restant + pièce), brides (boîtes du montage, rapides compris), rapides dans la matière ; opération, n° de commande et position de la pointe ; marqueurs rouges ; erreurs bloquantes à l'export si les parcours n'ont pas changé, sinon « non vérifiable » | auto (`test_sim.py` : collisions connues de chaque type, projet propre, « non contrôlé » sans bride / sans porte-outil, export bloqué puis non vérifiable) | parois verticales et contre-dépouilles, 4e axe, brides non rectangulaires, tronçons coniques au rayon maximal |
| Postprocesseur identifié, unités, axes, commandes autorisées | disponible | `export.py` | auto | listes de codes pour autres contrôleurs |
| Aperçu G-code, fiche de préparation | disponible | dialogue Export | visuel | PDF |
| Palpage de l'origine (surface Z, coin, centre de trou) | disponible | `project/probe.py` (G38.2, G10 L20 / G92), Usiner > Palper l'origine, contrôles dans `export.verify` | auto (`test_nuit_s2.TestProbe*` : G-code ligne à ligne avant et après postprocesseur, refus sans palpeur / broche en marche / sans avance) + scénario `s2-probe` | coin intérieur, mesure du diamètre, inspection |
| Transfert volontaire vers CNCjs | disponible (manuel) | fichier `.nc` | — | aucun envoi automatique (voulu) |
| Sauvegarde / réouverture | disponible | `.FCStd` + `CAM2027Project` | auto | tests de migration de données |

## Feuille de route (jalons)

- **A. Audit, base épinglée, fork, démarrage reproductible** — fait (fork, tag 1.1.4,
  lanceur, tests). Reste : compilation du fork (outils absents).
- **B. Chaîne 3 axes + bibliothèque d'outils + interface** — première tranche livrée
  (cette version). Reste : formes exactes des types approximés, validation import Fusion
  réel, exposer surfaçage/filetage/chanfrein avec tests, vérification sur 1.1.4.
- **C. Bois/aluminium et réglages avancés** — attaches, rampes, entrées/sorties, incrustations,
  dégagement multi-outils, expressions, 3D sur relief (OCL).
- **D. Indexation et montages 4e axe** — profil A complet, 3+1, recto-verso, repères.
- **E. Rotatif continu et XYZA** — enroulement, G93/G94, stratégies validées.
- **F. Reliefs, simulation étendue, optimisations mesurées** — matière, collisions,
  benchmarks sur corpus fixe.

Domaines recensés mais hors des premières versions : tournage, 5 axes, découpe,
imbrication, fabrication additive.
