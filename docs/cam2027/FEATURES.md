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
| Contour 2D | disponible | `Path.Op.Profile` | auto | entrées/sorties inline, attaches (habillage) |
| Poche | disponible | `Path.Op.Pocket` | auto | — |
| Ébauche adaptative / trochoïdale | partiel | `Path.Op.Adaptive` (2D, monothread) | impl. | tests, perf, reprise 3D |
| Rainure | disponible | `Path.Op.Slot` (arêtes/sommets ou points personnalisés) | auto (`test_vcarve_and_slot`) | — |
| Gravure | disponible | `Path.Op.Engrave` | auto (`test_helix_and_engrave`) | — |
| Chanfreinage | disponible | `Path.Op.Deburr` (clé `chamfer`) | auto (`test_chamfer`) | contrôle de collision avec les parois voisines ; largeur seule dans le dialogue |
| Perçage (cycles, débourrage) | disponible | `Path.Op.Drilling` ; sans sélection, tous les trous détectés | auto (`test_drilling_all_holes`) | — |
| Alésage hélicoïdal | disponible | `Path.Op.Helix` | auto (`test_helix_and_engrave`) | — |
| Fraisage de filets | partiel | `Path.Op.ThreadMilling` (clé `threadmill`), tables de filets FreeCAD | auto (`test_thread_milling`) | nombre de dents inutilisé par FreeCAD, crête à 0, filets extérieurs et impériaux non testés |
| Attaches, rampes, dogbones | disponible | habillages FreeCAD `Path.Dressup.Tags`, `RampEntry`, `DogboneII` via `project/dressups.py`, onglet « Entrée, sortie et attaches » de l'éditeur | auto (`test_dressups`, `test_dogbones`) + visuel | entrées/sorties en arc (LeadInOut), positions d'attaches dans l'éditeur (actuellement panneau FreeCAD) |

## Opérations 3D

| Fonction cible | Statut | Composant | Travail restant |
|---|---|---|---|
| Ébauche volumique | partiel | `Path.Op.Adaptive` autour des faces en relief (clé `rough3d`, faces choisies automatiquement si toute la pièce est sélectionnée) | auto (`test_3d_finishing` : niveaux, surépaisseur respectée) | marches entre niveaux (pas de reprise des marches), ébauche depuis le brut restant |
| Reprise depuis le brut restant | partiel | `project/rest.py` : brut = carte de hauteur simulée des opérations précédentes, coupes gardées où la fraise rencontre plus de « Ignorer moins de » (Fusion), liaisons recalculées (`project/trim.py`) ; ébauche 3D, adaptative, poche, poche 2D ; onglet « Reprise et zone » | auto (`test_nuit_s1` : plaque à rainure étroite) + scénario `s1-rest-area` + disque WobbleRing (7,3 % de l'ébauche, aucune entaille) | entrées en hélice dans les zones reprises (plongées verticales), calcul limité aux zones restantes (l'opération complète est calculée puis découpée), sources « depuis un fichier / des corps » |
| Finition parallèle / Z constant | disponible | `Path.Op.Surface` (clé `surface3d`), `Path.Op.Waterline` (clé `waterline`), OpenCamLib | auto (`test_3d_finishing` : pas de pénétration, sommet suivi, niveaux Z) + visuel | reprise depuis une ébauche, ébauche volumique |
| Hauteur de crête, reprise des creux, pentu/peu incliné, guidé par courbes, ébavurage | absent | — | jalons C–F |

## Dessin et fonctions Aspire

| Fonction cible | Statut | Composant | Travail restant |
|---|---|---|---|
| Import SVG / DXF / STEP / STL / OBJ | disponible | Draft `importSVG`, `Import.readDXF`, Part, Mesh | auto (`test_import`) | — |
| Usinage d'un dessin 2D dans un panneau (découpe, poche, V-carving, gravure) | disponible | `project/sheet.py` + `Path.Op.PocketShape` | auto (`test_sheet_from_drawing`) + visuel | brut depuis panneau réel non rectangulaire ; sélection d'un contour par clic sur le dessin (actuellement sélection de ses arêtes/face) |
| Édition vectorielle (nœuds, texte, booléens, calques) | absent | Draft / Sketcher FreeCAD | outil dédié dans l'atelier |
| V-carving profondeur variable | disponible | `Path.Op.Vcarve` | auto (`test_vcarve_and_slot`) | FreeCAD démarre la gravure au sommet du modèle, pas à la hauteur de la face |
| V-carving à fond plat (2e outil) | disponible | Usiner > Fond plat (`project/inlay.py`) : poche à la profondeur limite dans la zone plate (face réduite de la portée du V-bit), contour de la zone plate au V-bit, angles vifs le long des bissectrices (le V-carving limité de FreeCAD les laisse trop peu profonds) | auto (`test_flat_depth_clearing` sur la matière simulée : fond plat, flancs en V exacts jusqu'au bord, angles vifs, rien hors du dessin) | angles rentrants arrondis au rayon de la fraise plate |
| Incrustations mâle/femelle | disponible | Usiner > Incrustation en V : femelle (V-carving + fond plat) dans le projet, mâle en miroir réduit de la profondeur de départ dans un nouveau projet ; jeux de colle et entre planches affichés | auto (`test_male_female_fit` : cartes de hauteur femelle et mâle retourné, aucune interférence, flancs en contact, jeux 2 / 2 mm) | angles rentrants de la forme (le bouchon y est vif, la cavité arrondie : à éviter ou à arrondir) |
| Dégagement multi-outils | partiel | fond plat (fraise plate + V-bit) | auto | reprise avec plusieurs diamètres de fraise plate |
| Recto-verso, repères de retournement | absent | — | jalon D |
| Placement / imbrication | partiel | Préparer > Imbriquer (`project/nesting.py`) : rectangles englobants, ligne d'horizon au meilleur ajustement, rotation 90°, copies, espacement, marge ; panneau de cette taille à la création du job | auto (`test_inlay.py` : aucun chevauchement, espacement, pièces non placées rapportées, utilisation, brut = panneau) | imbrication par forme réelle, plusieurs panneaux, sens du fil |
| Relief depuis une image (carte de hauteur) | disponible | `cam2027/project/relief.py` : PNG / JPG / BMP en niveaux de gris, largeur, hauteur, épaisseur, inversion, lissage, résolution → solide (surface B-spline exacte aux points de la grille) ; Préparer > Relief depuis une image | auto (`test_relief_from_image` : fidélité ± 0,15 mm, inversion, JPG en console, ébauche et finition 3D sans pénétration) + visuel | composants, combinaison, sculpture ; l'interpolation peut dépasser l'image près des bords francs (avertissement : augmenter le lissage) |
| Reliefs (composants, combinaison, sculpture) | absent | — | jalon F |

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
| Affichage des trajectoires | disponible | vue 3D FreeCAD (Path) | visuel | — |
| Enlèvement de matière | disponible | Simuler : simulateur CAM de FreeCAD (`CAM_SimulatorGL`, fenêtre avec lecture / pause / pas à pas / vitesse) lancé réglé, opérations sur A exclues ; Simuler > Contrôle matière : carte de hauteur (`project/sim.py`, grille 0,5 mm, fraises plate / boule / torique / conique) comparée à la pièce : volume enlevé, entailles (rouge), matière restante, rapides dans la matière | auto (`test_sim.py` : rainures plate / boule / V exactes, arcs, rapide, dessus de pièce ; surfaçage juste = 0 entaille et 5376 mm³ ; surfaçage 1 mm trop bas = entaille 1,0 mm ; dôme fini sans entaille) + visuel (fenêtre du simulateur, brut simulé) | 4e axe non simulé, parois verticales et contre-dépouilles non contrôlées |
| Collisions (outil, porte-outil, brides) | disponible | Simuler > Contrôle matière et collisions (`project/sim.py`) : enveloppe de l'assemblage (partie taillée, queue jusqu'à la sortie, tronçons du porte-outil) ; matière au-dessus de la longueur de coupe, porte-outil dans la matière (brut restant + pièce), brides (boîtes du montage, rapides compris), rapides dans la matière ; opération, n° de commande et position de la pointe ; marqueurs rouges ; erreurs bloquantes à l'export si les parcours n'ont pas changé, sinon « non vérifiable » | auto (`test_sim.py` : collisions connues de chaque type, projet propre, « non contrôlé » sans bride / sans porte-outil, export bloqué puis non vérifiable) | parois verticales et contre-dépouilles, 4e axe, brides non rectangulaires, tronçons coniques au rayon maximal |
| Postprocesseur identifié, unités, axes, commandes autorisées | disponible | `export.py` | auto | listes de codes pour autres contrôleurs |
| Aperçu G-code, fiche de préparation | disponible | dialogue Export | visuel | PDF |
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
