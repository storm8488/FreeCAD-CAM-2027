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
| Rainure | disponible | `Path.Op.Slot` | impl. | test auto |
| Gravure | disponible | `Path.Op.Engrave` | auto (`test_helix_and_engrave`) | — |
| Chanfreinage | disponible | `Path.Op.Deburr` (clé `chamfer`) | auto (`test_chamfer`) | contrôle de collision avec les parois voisines ; largeur seule dans le dialogue |
| Perçage (cycles, débourrage) | disponible | `Path.Op.Drilling` ; sans sélection, tous les trous détectés | auto (`test_drilling_all_holes`) | — |
| Alésage hélicoïdal | disponible | `Path.Op.Helix` | auto (`test_helix_and_engrave`) | — |
| Fraisage de filets | partiel | `Path.Op.ThreadMilling` (clé `threadmill`), tables de filets FreeCAD | auto (`test_thread_milling`) | nombre de dents inutilisé par FreeCAD, crête à 0, filets extérieurs et impériaux non testés |
| Attaches, rampes | partiel | habillages FreeCAD `Path.Dressup.Tags` et `RampEntry` via `project/dressups.py`, onglet « Entrée, sortie et attaches » de l'éditeur | auto (`test_dressups`) + visuel | dogbones, entrées/sorties (LeadInOut), positions d'attaches dans l'éditeur (actuellement panneau FreeCAD) |

## Opérations 3D

| Fonction cible | Statut | Composant | Travail restant |
|---|---|---|---|
| Ébauche volumique | absent | `Path.Op.Surface` (OCL, présent dans 1.0.2) | exposer, tester sur relief |
| Reprise depuis le brut restant | absent | — | nécessite simulation matière (jalon F) |
| Finition parallèle / Z constant | absent | `Surface`, `Waterline` | exposer |
| Hauteur de crête, reprise des creux, pentu/peu incliné, guidé par courbes, ébavurage | absent | — | jalons C–F |

## Dessin et fonctions Aspire

| Fonction cible | Statut | Composant | Travail restant |
|---|---|---|---|
| Import SVG / DXF / STEP / STL / OBJ | disponible | Draft `importSVG`, `Import.readDXF`, Part, Mesh | auto (`test_import`) | — |
| Édition vectorielle (nœuds, texte, booléens, calques) | absent | Draft / Sketcher FreeCAD | outil dédié dans l'atelier |
| V-carving profondeur variable | disponible | `Path.Op.Vcarve` | impl. | test auto, fond plat avec 2e outil |
| Incrustations mâle/femelle | absent | — | jalon C |
| Dégagement multi-outils | absent | — | jalon C |
| Recto-verso, repères de retournement | absent | — | jalon D |
| Placement / imbrication | absent | — | feuille de route |
| Reliefs (import carte de hauteur, composants, combinaison, sculpture) | absent | — | jalon F |

## 4e axe (XYZ+A)

| Fonction cible | Statut | Composant | Travail restant |
|---|---|---|---|
| Profil machine avec axe A (orientation, sens, centre, limites, mandrin, contre-pointe) | partiel | `RotaryAxis` (champs présents, valeurs à renseigner) | interface dédiée |
| Indexation 3+1 | absent | — | jalon D |
| Enroulement cylindrique | absent | — | jalon E |
| Rotatif continu, XYZA simultané | absent | `Path.Op.RotarySurface` (main amont, non stable) | jalon E |
| Contrôles G93/G94, 0/360, tours multiples | partiel | `export.verify` rejette A/B/C sans axe | jalon D/E |

## Simulation, export, intégration

| Fonction cible | Statut | Composant | Travail restant |
|---|---|---|---|
| Affichage des trajectoires | disponible | vue 3D FreeCAD (Path) | visuel | — |
| Enlèvement de matière | absent | simulateur CAM FreeCAD (non intégré) | jalon F |
| Collisions (outil, porte-outil, brides) | absent | — | jalon F ; brides visuelles seulement |
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
