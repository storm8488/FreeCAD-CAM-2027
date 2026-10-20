# CAM2027 — Historique

## Non publié

- **Contrôle matière et calcul des parcours accélérés** (demande de l'utilisateur : « le simulateur et la
  génération de parcours sont bien trop lents »). Contrôle matière : balayage par paquets vectorisés
  (segments consécutifs sur leur fenêtre commune, limitée en cellules et en gaspillage), formule exacte de
  la fraise plate et de la boule sur les pentes (plus de découpe en morceaux de 0,5 mm), pré-contrôles
  vectorisés de la queue, du porte-outil et des rapides sur l'état d'avant le paquet (repli séquentiel
  exact quand ils signalent quelque chose), dessus de la pièce rastérisé par groupes de triangles et sur
  une copie sans triangulation (une finition 3D en laissait une dix fois plus dense). Mesuré sur les
  pièces de l'utilisateur : finition 3D du plateau 96 s -> 7,9 s, du chauffage 66 s -> 6,4 s, adaptative du
  plateau 21 s -> 12 s, ébauche 3D 24 s -> 19 s et 12-16 s -> 8,5 s (voir TESTS.md). Ébauche 3D (mode « modèle ») : les régions déjà connues ne sont plus comparées par une
  découpe booléenne quand leur boîte ou leur aire l'exclut (73 000 découpes -> 1 100 sur le plateau,
  calcul 78 s -> 47 s). Même résultat (tests d'équivalence paquet / séquentiel, remplissage / fenêtres ; 84 tests).
- **Plantage à la création du brut, 3e cause** : un STL resté maillage (ouvert, ou plus de 200 000 triangles,
  trop gros pour la conversion en solide) passait au job ; le clone FreeCAD d'un maillage n'a pas de forme,
  le brut bouclait jusqu'au débordement de pile. Désormais un tel maillage devient une **surface 3D**
  (faces non cousues : 14 s pour 215 552 triangles, contre 10 min cousu) qui accepte le brut et les finitions
  3D (surface 46 s, Z constant 26 s sur ce fichier, `BoundBox = Stock` imposé : l'enveloppe de FreeCAD sur
  215 000 faces prenait 18 Go) ; les autres stratégies la refusent avec un message. Un maillage ne peut plus
  être la pièce d'un job (refus explicite, FreeCAD 1.0 : conversion impossible, signalé), et le brut de
  FreeCAD ne boucle plus sur une boîte invalide (garde de réentrance). 81 tests.
- **Ébauche 3D et toutes les stratégies vérifiées sur les pièces de l'utilisateur** (matrice stratégies ×
  pièces, chaque case dans son propre CAM2027.exe, `tests/run_strategy_matrix.py`). Ébauche 3D de la pièce
  entière : mode « modèle » de FreeCAD 1.1 (plus de 15 min figé auparavant), calcul arrêtable
  (« Arrêter le calcul »), projection de tranche réparée quand FreeCAD lève « Wire is not closed »,
  liaisons remontées d'une passe (G0 dans la matière) ; sur 1.0.2, refus clair au-delà de 200 faces.
  Finition 3D échantillonnée à 0,1 mm (entaille de 1,45 mm à 0,5). Filetage sans sélection : filet choisi
  d'après les avant-trous, autres trous écartés et listés. Poche / adaptative sans sélection : fonds sous
  un surplomb écartés. Contrôle matière : tolérance de 0,05 mm au droit des parois verticales, trous
  filetés creusés au diamètre majeur, dégagements verticaux et frôlements de moins de 0,01 mm non comptés
  comme rapides dans la matière, filetage dans un trou non percé signalé comme tel. 79 tests.
- **Plantage à la création du brut corrigé** : un fichier importé deux fois donnait, une fois les corps
  fusionnés, une forme vide (0 solide, boîte invalide) ; le brut de FreeCAD (`Stock.execute` /
  `onChanged`) bouclait alors jusqu'au débordement de pile (vidages Windows : violation d'accès dans
  VCRUNTIME140, pile de 1 Mo pleine). Corps en double ignorés, fusion refusée si elle ne donne pas un
  solide plausible, forme vide refusée avant le brut, avertissement à la réimportation d'un fichier.
  Journal de plantage Python permanent (`%APPDATA%\\CAM2027\\v1-1\\crash-python.log`). 74 tests.
- **Fiabilisation de l'interface** (bugs trouvés en test par l'utilisateur) : STL fermé converti en
  solide affiné à l'import (fonds de poche plans retrouvés) ; pièce détectée pour STL et SVG (étape 1,
  Brut et montage) ; import sans projet = projet créé ; assemblage de plusieurs corps fusionné en une
  pièce (sinon chaque contour traversait les autres corps) ; « Ajouter une opération » : seuls les
  outils compatibles avec la stratégie (V-carving -> V-bit…), nom tiré de la stratégie, fonds de poche /
  dessus trouvés sans sélection, toute la pièce (plus seulement le premier objet), aucune opération vide
  créée ; panneau Tâches vide masqué ; contrôle matière / collisions mémorisé dans le document (l'export
  ne le voyait pas) et entailles bloquantes à l'export ; messages du cœur et contrôles d'export traduits
  (`Msg` / `UserError`) ; dialogues : Brut et montage n'affiche que les champs du type choisi (et propose
  bien le panneau pour un dessin seul), profil machine sur deux colonnes (tient en 800 px) avec la vitesse
  de A et les erreurs de saisie nommées, fond plat avec sa profondeur, « T1 - T1 » corrigé, matières
  traduites, outil de gravure proposé pour l'enroulement ; incrustation : marge du mâle selon la fraise
  plate, femelle laissée active ; éditeur fermé avec son document ; attente visible (import, calcul).
  Banc de scénarios `tests/gui_scenarios.py` (19 scénarios, fichiers de l'utilisateur) et
  `tests/test_ui_logic.py` (72 tests).
- **Logo validé** (étape 4.6) : proposition horizontale du dossier d'assets, symbole recadré et
  texte remplacé par « CAM2027 · FAO · USINAGE CNC » ; `scripts/make-branding.py` produit symbole,
  logos clair / sombre, petit logo, écran de démarrage et icône ; `.ico` 16 à 256 px depuis le PNG.
- **Flux 2D avancé** (étape 4.5) : V-carving à **fond plat** (fraise plate à la profondeur limite,
  contour et angles vifs au V-bit) ; **incrustation en V** mâle / femelle (mâle miroir dans un
  nouveau projet, jeux de colle affichés) ; **imbrication** des pièces 2D sur un panneau (rectangles
  englobants, rotation, copies, panneau de cette taille). Vérifiés sur la matière simulée (66 tests).
- **Contrôle de collision** (étape 4.4) : le contrôle matière vérifie aussi la longueur de coupe
  (frottement de la queue), le porte-outil (tronçons de la bibliothèque) et les brides, rapides
  compris, avec l'opération, le n° de commande et la position ; marqueurs rouges ; à l'export,
  collisions bloquantes si les parcours n'ont pas changé, sinon « non vérifiable » ; jamais « OK »
  pour un contrôle non exécuté (sans bride, sans porte-outil, axe A). 62 tests.
- **Simulation d'enlèvement de matière** (étape 4.3) : « Simuler » lance le simulateur CAM de
  FreeCAD réglé (job choisi, opérations sur A exclues et signalées, lecture lancée) ; nouveau
  « Contrôle matière » : carte de hauteur 3 axes comparée à la pièce (volume enlevé, entailles en
  rouge, matière restante, rapides dans la matière), brut simulé affiché. `test_sim.py` (59 tests).
- **4e axe continu : gravure enroulée** (étape 4.2) : un dessin déroulé est gravé autour du brut
  rond, X / Z / A simultanés en temps inverse G93 (F calculé à la longueur réelle), retour G94 ;
  aperçu 3D du trajet réel ; positionnements 3+1 recréés après l'enroulement. Contrôles d'export :
  A en coupe seulement en G93, F sur chaque mouvement G93, pas d'arc en G93, pas de fin en G93,
  vitesse angulaire contre le profil. Test `test_wrapped_4th_axis` (52 tests).
- **Relief depuis une image** (étape 4.1) : PNG / JPG / BMP en niveaux de gris → solide relief
  (largeur, hauteur, épaisseur sous le relief, inversion, lissage, résolution ; longueur selon les
  proportions de l'image), dialogue Préparer > Relief depuis une image (aussi depuis Importer) ;
  usinable par l'ébauche et la finition 3D. Test `test_relief_from_image` (51 tests).
- **Interface propre au logiciel (étape 2)** : dans `CAM2027.exe`, menus réduits au métier
  (Fichier, Édition, Affichage, Préparer, Usiner, Simuler, Exporter, Aide) ; menus Outils, Macro,
  Fenêtres, commandes de modélisation et liens FreeCAD retirés ; barres Presse-papiers, Macro,
  Structure, Aide, Vues individuelles retirées ; barre CAM2027 groupée par étape. Manipulateur
  d'ateliers FreeCAD, aucun fichier FreeCAD modifié. Menus d'étape aussi en atelier.
- **Page d'accueil CAM2027** (nouveau projet, ouvrir, démo guidée, projets récents) sur la zone
  centrale sans document ; **mode avancé** (éditeur de propriétés caché par défaut) ; commande
  **Disposition par défaut** ; position du panneau Projet mémorisée. Vérifié par le test graphique.
- **Logiciel autonome CAM2027 (étape 1)** : `scripts/build-distribution.ps1` fabrique
  `%USERPROFILE%\CAM2027` depuis FreeCAD 1.1.4 portable sans les modules inutiles (20 modules et
  leurs binaires supprimés), `branding.xml` (nom, titre, version, icône, écran de démarrage, dossier
  de réglages `%APPDATA%\CAM2027`, réglages par défaut), `CAM2027.exe` / `CAM2027Cmd.exe`, icône
  `.ico` générée, raccourcis vers le logiciel ; seul l'atelier CAM2027 reste visible. 50 tests et
  test graphique verts dans la distribution. Voir `docs/cam2027/DISTRIBUTION.md`.
- **4e axe indexé (3+1)** : profil machine A (sens positif, centre Y/Z, plage), brut rond d'axe X,
  champ « Index A » à l'ajout d'une opération et dans l'éditeur, copie exacte de la pièce tournée
  par angle, positionnements `G0 A` recréés automatiquement, contrôles d'export (A pendant une
  coupe, plage, GRBL 1.1, ordre). L'aperçu G-code recalcule désormais avant de postprocesser.
  Test `test_indexed_4th_axis` (50 tests) ; captures `project_panel_4axes.png`, `view3d_4axes.png`.
- **Finition 3D** : stratégies `surface3d` (`Path.Op.Surface`, zigzag / parallèle / décalage…) et
  `waterline` (`Path.Op.Waterline`, Z constant multi-passes), OpenCamLib, sur 1.1.4 et 1.0.2.
  Test `test_3d_finishing` (dôme : la pointe ne pénètre jamais la surface, sommet suivi, au moins
  4 niveaux en Z constant ; 49 tests). Capture `view3d_dome.png`.
- **Ébauche 3D** `rough3d` : adaptative du brut vers la pièce autour des faces en relief
  (`operations.raised_faces` si toute la pièce est sélectionnée), surépaisseur 0,5 mm par défaut ;
  testée sur le dôme (au moins 5 niveaux, jamais plus près que rayon + surépaisseur).
- **Direction artistique « Atelier »** (dossier fourni, copié dans `docs/design/`) : jetons
  sombre/clair dans `Resources/theme/tokens.json`, couche de thème `gui/theme.py` (QSS limitée aux
  widgets CAM2027, rôles sémantiques), 32 icônes sombres/claires pour les commandes, étapes,
  stratégies et actions, action principale contextuelle en bleu cobalt, commande « Thème :
  système / sombre / clair », plus aucune couleur codée en dur dans l'interface. Test
  `test_theme` (44 tests). Voir `docs/cam2027/DESIGN.md`.
- États de calcul normalisés (À calculer / Calculé / À recalculer / Avertissement / Échec /
  Inactive) lus sur l'état réel des objets FreeCAD (`operations.compute_state`), colonne « État »
  avec icône + texte + couleur ; « Recalculer les parcours (n en attente) » devient l'action
  principale dès qu'un calcul est périmé. Test `test_compute_states` (45 tests).
- Bibliothèque d'outils : colonnes T et Lc (mm), unités dans les en-têtes, icône par type
  d'outil, tri numérique par colonne (défaut : numéro T).
- Export : onglet « Récapitulatif avant export » (machine, postprocesseur, unités, repères, axes,
  état de chaque opération, bilan des contrôles, validation machine « non faite »), bouton
  principal « Exporter le G-code ». Test `test_export_summary` (46 tests).
- Données machine à renseigner affichées avec des libellés traduits (`machine.FIELD_LABELS`, partagés
  avec le dialogue Profil machine) ; À propos : mention « fork indépendant basé sur FreeCAD ».
  Test `test_machine_field_labels` (47 tests).
- Couleurs de parcours de la charte (coupe cobalt, rapide ambre, plongée, sélection) dans le
  profil du lanceur, appliquées après le pack sombre ; test `test_scene_colors` (48 tests).
- Disposition vérifiée à 1280 × 800 (capture `main_window_1280x800.png`) : actions de la
  bibliothèque regroupées (Nouveau / Dupliquer / Supprimer + menus « Plus... » et
  « Bibliothèque... »), étapes du flux sur deux lignes, proportions du séparateur conservées.
- Démonstration guidée : étapes « éditeur d'opération » et « flux 2D », outils assurés avant la
  création des projets (corrige un échec possible avec une bibliothèque sans fraise 6 mm),
  mode automatique `CAM2027_DEMO_AUTO=1`.
- Éditeur d'opération au clavier : focus sur le nom à l'ouverture, Ctrl+Entrée = OK, Échap /
  Annuler demande confirmation s'il reste des modifications non appliquées (vérifié par
  gui_smoke sur 1.1.4 et 1.0.2).
- Éditeur d'opération : onglets défilants et hauteur limitée à 85 % de l'écran (vérifié à 100 %,
  150 % et 200 % de mise à l'échelle Qt).
- Profil « FAO seule » appliqué au profil du lanceur (`gui/prefs.py`) : thème sombre FreeCAD,
  icônes 32 px, atelier CAM2027 au démarrage, autres ateliers masqués (opt-out `CamOnly`).
- Une icône SVG par commande (`Resources/icons/cam2027-*.svg`).
- Spécification déclarative des paramètres d'opération (`project/paramspec.py` : libellé,
  onglet, aide, traduits) ; lecture/écriture typée sur l'objet FreeCAD (`param_kind`,
  `read_params`, `set_params`).
- Éditeur d'opération à onglets, non modal (`gui/opeditor.py`) : création (après le
  dialogue « Ajouter une opération ») et modification (double-clic dans le panneau projet),
  valeurs du préréglage affichées, géométrie reprise de la sélection 3D.
- Projet : `update_operation`, `set_operation_base`, `set_operation_active`,
  `move_operation`, `duplicate_operation`, `remove_operation` (tests `test_operation_edits`,
  `test_param_specs` ; 32 tests).
- Panneau projet remplacé par un **panneau de flux de travail** : étapes Pièce → Brut et
  montage → Opérations → Contrôle et export avec statut et bouton, liste des opérations
  (case Actif, stratégie, outil, commandes, Z, temps ; Modifier / Monter / Descendre /
  Dupliquer / Supprimer), recalcul et simulation.
- Commande « Simuler » : lance le simulateur FreeCAD (`CAM_SimulatorGL`, sinon
  `CAM_Simulator`) sur le job du projet.
- Attaches (Holding Tags) et rampe d'entrée comme options d'une opération
  (`project/dressups.py`, onglet « Entrée, sortie et attaches » de l'éditeur) ; l'habillage
  remplace l'opération dans le job. Test `test_dressups` (33 tests sur 1.1.4 et 1.0.2).
- Perçage, hélice, filetage sans géométrie sélectionnée : tous les trous détectés par FreeCAD
  (plus grands que l'outil). Tests `test_drilling_all_holes`, `test_helix_and_engrave` (35 tests).
- Changement d'assemblage / de préréglage sur une opération existante (onglet Outil de
  l'éditeur, `Project.change_operation_tool`) : même coupant = contrôleur mis à jour, autre
  coupant = ToolBit + ToolController remplacés. Test `test_change_operation_tool` (36 tests).
- Dogbones (`Path.Dressup.DogboneII`) comme troisième habillage (contour, poche, adaptatif) ;
  test `test_dogbones` (37 tests).
- Bibliothèque : bouton « Ajouter les outils de démarrage manquants » (`merge_starter_tools`,
  fusion par nom, numéros d'outil libres ; test `test_merge_starter_tools`, 38 tests).
- Dialogue d'export : contrôles colorés (erreur rouge, avertissement orange, non vérifiable
  ambre, OK vert).
- Raccourcis clavier Ctrl+Maj+lettre pour les commandes principales.
- Tests V-carve (fond de poche, profondeur bornée) et rainure (points personnalisés) :
  `test_vcarve_and_slot` (39 tests).
- Rainure : points personnalisés, références et rayon de prolongement dans l'éditeur (champ
  vecteur X/Y/Z) ; panneau de flux de travail : temps d'usinage total.
- **Flux 2D « à la Aspire »** : dessin SVG/DXF posé sur un panneau généré (dessus à Z 0,
  épaisseur et marge réglables, semi-transparent), une face par contour fermé ; nouvelle
  stratégie « Poche 2D » (`Path.Op.PocketShape`) ; option « Panneau sous le dessin 2D » du
  dialogue Brut et montage. Test `test_sheet_from_drawing` (découpe, poche 2D, V-carving,
  gravure, export ; 40 tests).

## 0.1.3 — 2026-10-20

- Stratégies `threadmill` (`Path.Op.ThreadMilling`, nom de filet résolu depuis les tables
  FreeCAD, pas vérifié contre la plage de l'outil) et `chamfer` (`Path.Op.Deburr`) ; limites
  honnêtes de `millface`. Fraise à fileter 4 mm dans la bibliothèque de démarrage (col du
  ToolBit forcé < D). Dialogue « Ajouter une opération » : largeur de chanfrein, nom de
  filet, `ClearEdges` pour le surfaçage. Tests `test_facing`, `test_thread_milling`,
  `test_chamfer`, `test_strategy_translations` (30 tests sur 1.1.4 et 1.0.2).

## 0.1.2 — 2026-10-20

- Import Fusion validé sur un export réel (Fusion 2.16, version 37) : angle inclus = 2 × `TA`,
  longueur de jauge `assemblyGaugeLength`, sortie = `LB`, `tapered-type`, sens par `HAND`,
  `use-stepdown`/`use-stepover`, matière de préréglage, arrosage `tool-coolant` ; clés `CSP`,
  `DCX`, `shoulder-diameter`, `upper-radius` reconnues. Fixture + test
  `test_fusion_import_real_export` (26 tests).
- Bibliothèque utilisateur du lanceur pré-remplie : 11 outils Fusion (T1–T11) + outils de
  démarrage renumérotés T21–T27 ; rapport dans `fusion-import-report.txt`.

## 0.1.1 — 2026-10-20

- FreeCAD 1.1.4 portable installé à part (`%LOCALAPPDATA%\CAM2027\FreeCAD-1.1.4`, SHA256
  vérifié) ; suite de tests et vérification graphique passées sur 1.1.4 (API outils
  « assets », PySide6) et sur 1.0.2.
- Compatibilité Qt6 : `exec_dialog`, `QtGui.QFontDatabase` ; STEP/IGES via le module
  `Import` (Part.insert déprécié en 1.1). Lanceurs : priorité `FREECAD_BIN` > 1.1.4 > 1.0.2.

## 0.1.0 — 2026-10-20 (jalon A + première tranche du jalon B)

- Fork `storm8488/FreeCAD-CAM-2027` créé ; branche `cam2027` depuis le tag amont `1.1.4`
  (commit `4fd3bf32`). Audit de l'environnement et de FreeCAD 1.0.2 / 1.1.4 / 26.3rc2.
- Atelier `src/Mod/CAM2027` (Python, FreeCAD ≥ 1.0) :
  - bibliothèque d'outils : 20 types (champs de l'onglet « Coupant » de Fusion), porte-outils
    par segments, assemblages (sortie, longueur de jauge, numéro, correcteurs, changement
    manuel), préréglages multiples avec relations n/Vc et Vf/fz, recherche, filtres,
    favoris, duplication, édition groupée, import/export, instantané versionné par projet,
    import Fusion (.json/.tools) avec rapport de conversion ;
  - chaîne projet : import STEP/STL/OBJ/SVG/DXF, job, brut (marges/boîte/cylindre),
    repère G54–G59, brides visuelles, 9 stratégies FreeCAD, ToolController par opération
    avec valeurs copiées, export G-code (37 posts FreeCAD), analyse et contrôles
    (unités, codes GRBL, axes, courses, avance, broche), fiche de préparation ;
  - interface : atelier « CAM2027 », 9 commandes, panneau bibliothèque (coupant /
    données de coupe / porte-outil & assemblage, aperçu 2D coté), panneau projet,
    dialogues brut, opération, export (aperçu + contrôles + fiche), machine, à propos ;
    catalogue français complet.
- Lanceur `scripts/cam2027.cmd` (profil séparé, journal), raccourci et désinstallation
  par utilisateur, tests console `scripts/cam2027-tests.cmd`, vérification graphique
  `tests/gui_smoke.py`.
