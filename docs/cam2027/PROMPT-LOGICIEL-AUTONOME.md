# Prompt — CAM2027 devient un logiciel de FAO autonome (fork de FreeCAD)

> À relire et valider par l'utilisateur avant tout travail. Rien n'est commencé.

## Correction de cap

Jusqu'ici, CAM2027 est un **atelier** chargé dans FreeCAD complet : le lanceur ouvre FreeCAD sur
l'atelier CAM2027 et masque les autres ateliers, mais ils restent installés, les menus FreeCAD
(Macro, Outils, Édition…) restent ceux de FreeCAD et le programme s'appelle toujours FreeCAD.
**Ce n'est pas ce qui a été demandé.**

Demande réelle : **un nouveau logiciel de FAO**, forké de FreeCAD, qui garde la base CAM de FreeCAD
(moteur de parcours, postprocesseurs, OpenCamLib, outils) comme fondation de travail, mais qui
**supprime tout le reste** et se présente comme une application à part entière : son nom, son icône,
son écran d'accueil, ses menus, son dossier de réglages, son installateur.

## Objectif

Livrer **CAM2027**, application Windows de FAO « Aspire open source avec des réglages à la Fusion
360 », interface simple et moderne selon la direction artistique « Atelier » (`docs/design/`).

- On lance `CAM2027.exe`, pas FreeCAD. Le titre, l'icône, l'écran de démarrage et « À propos »
  disent CAM2027 (« fork indépendant basé sur FreeCAD et son atelier CAM », sans le présenter comme
  une version officielle de FreeCAD).
- Aucun atelier de modélisation visible ni installé quand il n'est pas indispensable : pas de
  PartDesign, BIM, FEM, TechDraw, Assembly, Robot, OpenSCAD… dans l'interface.
- Une seule interface : celle de CAM2027 (navigation **Préparer / Usiner / Simuler / Exporter**,
  vue 3D au centre, panneaux à gauche et à droite, barre d'état), pas les menus génériques de
  FreeCAD.
- Les réglages et la bibliothèque d'outils de CAM2027 vivent dans leur propre dossier
  (`%APPDATA%\CAM2027`), séparé de FreeCAD.

## Base existante à réutiliser (ne pas jeter)

Branche `cam2027` du fork `storm8488/FreeCAD-CAM-2027` (base FreeCAD 1.1.4) : le module
`src/Mod/CAM2027` (bibliothèque d'outils, projet, 17 stratégies dont 3D et 4e axe indexé,
habillages, flux 2D, éditeur d'opération, panneau de flux, thème « Atelier », 50 tests console + test
graphique). Il devient le cœur de l'application. Lire `docs/cam2027/ARCHITECTURE.md`,
`FEATURES.md`, `LIMITS.md`, `DESIGN.md` avant de commencer.

## Contraintes vérifiées dans le dépôt

- FreeCAD lit `bin/branding.xml` au démarrage (`src/App/Application.cpp`, `src/App/Branding.cpp`) :
  `ExeName`, `ExeVendor`, `WindowTitle`, `WindowIcon`, `ProgramLogo`, `ProgramIcons`,
  `SplashScreen`, `StartWorkbench`, `AppDataSkipVendor`… → nom, icône, écran d'accueil, atelier de
  départ et dossier de données propres **sans recompiler**.
- Les sources ont une option CMake par module (`BUILD_FEM`, `BUILD_BIM`, `BUILD_TECHDRAW`,
  `BUILD_ASSEMBLY`, `BUILD_ROBOT`, `BUILD_OPENSCAD`, `BUILD_PART_DESIGN`, `BUILD_SKETCHER`…) →
  une compilation peut exclure physiquement les modules.
- Aucun compilateur sur le PC (ni MSVC, ni CMake, ni LibPack). La compilation demande d'installer
  Visual Studio Build Tools 2022 + CMake + le LibPack FreeCAD (plusieurs Go) : **à faire seulement
  avec l'accord explicite de l'utilisateur**.
- Le module CAM de FreeCAD dépend au minimum de `Part`, `Mesh`, `MeshPart`, `Draft` (import SVG,
  géométrie), `Import` (STEP), et probablement de `Sketcher` / `PartDesign` pour les formes d'outils
  (`Tools/Shape/*.fcstd`). **Chaque suppression de module doit être prouvée par les tests**, pas
  supposée ; un module requis mais sans intérêt pour l'utilisateur reste installé et invisible.
- Règle validée par l'utilisateur : **supprimer physiquement** tout module non indispensable (il
  n'est plus installé dans CAM2027) ; garder les dépendances du moteur CAM (Part, Mesh, MeshPart,
  Import, Draft…) comme bibliothèques **sans atelier ni menu visible** ; chercher à remplacer
  Sketcher / PartDesign (formes des fraises générées par CAM2027) pour pouvoir les supprimer aussi.
  Le FreeCAD officiel éventuellement installé n'est jamais modifié.

## Étapes

### Étape 1 — Distribution autonome sans compilation (faisable tout de suite)

1. Script `scripts/build-distribution.ps1` qui fabrique `dist/CAM2027/` à partir de FreeCAD 1.1.4
   portable (SHA256 vérifié) : copie, suppression des modules inutiles dans `Mod/` (liste établie par
   essais), ajout du module CAM2027, `bin/branding.xml`, renommage de l'exécutable en
   `CAM2027.exe`, icône `.ico`, écran de démarrage CAM2027, réglages par défaut (thème, unités mm,
   postprocesseur GRBL, langue française).
2. Liste des modules gardés / supprimés avec la preuve (tests console et graphique qui passent
   après suppression). Taille avant / après.
3. Installateur ou archive zip + raccourcis Bureau / menu Démarrer + désinstallation propre (sans
   toucher aux projets ni à un FreeCAD déjà installé). Test : FreeCAD officiel et CAM2027 coexistent.
4. Critère de fin : on lance CAM2027.exe, le titre et l'icône sont CAM2027, aucun atelier de
   modélisation n'est proposé, les 50 tests et le test graphique passent dans la distribution.

### Étape 2 — Interface propre à CAM2027 (sans menus FreeCAD)

1. Fenêtre principale réorganisée au démarrage (module Python, sans modifier FreeCAD amont) :
   menus et barres d'outils FreeCAD retirés ou réduits à Fichier (nouveau, ouvrir, enregistrer,
   récents), Édition (annuler / rétablir), Affichage (vues, thème), Aide / À propos ; navigation
   Préparer / Usiner / Simuler / Exporter ; arbre FreeCAD remplacé par l'arbre du projet CAM2027 ;
   éditeur de propriétés FreeCAD caché (accessible en mode « avancé »).
2. Page d'accueil CAM2027 (nouveau projet, ouvrir, récents, démo) à la place de la page FreeCAD.
3. Disposition mémorisée et commande « disposition par défaut ».
4. Critère de fin : captures 1280 × 800 et 1600 × 1000 sans aucun élément FreeCAD générique
   visible hors besoin ; tests graphiques automatisés ; aucune régression des 50 tests.

### Étape 3 — Compilation du fork (seulement après accord pour installer les outils)

1. Installer la chaîne de compilation, compiler le fork avec les modules inutiles désactivés
   (`BUILD_*=OFF`), nom d'exécutable et ressources CAM2027 intégrés.
2. Comparer avec la distribution de l'étape 1 (taille, démarrage, tests).
3. Critère de fin : `CAM2027.exe` compilé depuis le fork, mêmes tests verts.

### Étape 4 — Fonctions manquantes (dans cet ordre, une par lot testé)

1. **Relief depuis une image** (carte de hauteur, cœur d'Aspire 3D) : import PNG/JPG, taille,
   hauteur, inversion, lissage → solide relief → ébauche et finition 3D existantes. Test : relief
   connu, parcours sans pénétration.
2. **4e axe continu et enroulement (XYZA simultané)** : enroulement d'un parcours 2D sur un
   cylindre (X le long de l'axe, angle A pour la circonférence), avances G93 si nécessaires,
   contrôles. Ne jamais l'annoncer avant qu'il soit calculé, postprocessé et testé.
3. **Vraie simulation d'enlèvement de matière** : intégrer le simulateur CAM de FreeCAD dans
   l'onglet Simuler (lecture / pause / pas à pas), vérifier sa fenêtre, capture.
4. **Contrôle de collision** outil, porte-outil (segments de la bibliothèque) et brides, avec
   position dans le parcours ; un contrôle non exécuté n'est jamais affiché comme réussi.
5. **Incrustations** (mâle / femelle), **dégagement à fond plat avec un second outil après le
   V-carving**, **imbrication** de pièces 2D sur un panneau.
6. **Logo validé et fichier icône** : intégrer le logo choisi par l'utilisateur (les deux PNG du
   dossier sont des propositions non validées), produire `.ico` multi-résolutions (16 à 256 px) et
   l'écran de démarrage. Demander à l'utilisateur quel logo valider.
7. **Exécutable compilé** : couvert par l'étape 3.

## Règles de travail

- Répondre à l'utilisateur **en français**.
- Fichiers FreeCAD amont : modifiés seulement si l'étape 3 l'exige, chaque modification listée.
- Chaînes du code en anglais, traduites via `tr()` et `i18n/fr.json` (`missing_translations` vide).
- Unités internes mm, mm/min, tr/min, degrés.
- Tests : `scripts\cam2027-tests.cmd` sur 1.1.4 et 1.0.2 (puis sur la distribution / le binaire
  compilé), test graphique avec captures. Ne jamais annoncer un résultat non vérifié ; dire
  exactement ce qui reste non vérifié.
- Commits petits et compréhensibles sur `cam2027` ; **pas de push, pas de téléchargement ni
  d'installation d'outils sans accord explicite**.
- Aucune donnée machine inventée ; aucune fonction annoncée si elle n'est pas réellement calculée.
- Fin de chaque étape : résumé fait / testé automatiquement / vérifié visuellement / non vérifié.

## Questions à trancher par l'utilisateur avant de commencer

1. Ordre : étape 1 puis 2 puis 4, et l'étape 3 (compilation) plus tard — d'accord ?
2. Autorises-tu le téléchargement et l'installation des outils de compilation (étape 3) ?
3. Quel logo : la proposition horizontale, le symbole, ou un autre fichier que tu fournis ?
4. Installateur `.exe` (Inno Setup, à télécharger) ou simple archive zip + raccourcis pour commencer ?
