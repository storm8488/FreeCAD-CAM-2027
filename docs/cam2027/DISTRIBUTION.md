# CAM2027 — logiciel autonome (étape 1 : distribution sans compilation)

CAM2027 est un **logiciel séparé**, fabriqué à partir de la distribution FreeCAD 1.1.4 portable :
il garde la base CAM de FreeCAD (moteur de parcours, postprocesseurs, OpenCamLib) et **n'installe
pas** les ateliers de modélisation et les autres modules. Aucun FreeCAD installé n'est modifié ; les
deux coexistent.

## Fabriquer et installer

```bat
powershell -ExecutionPolicy Bypass -File scripts\build-distribution.ps1
powershell -ExecutionPolicy Bypass -File scripts\install-shortcut.ps1
```

- Résultat : `%USERPROFILE%\CAM2027\` (≈ 2 Go), exécutables `bin\CAM2027.exe` (interface) et
  `bin\CAM2027Cmd.exe` (console). Raccourcis « CAM2027 » sur le Bureau et dans le menu Démarrer.
- Réglages et bibliothèque d'outils : `%APPDATA%\CAM2027\v1-1\` (séparé de FreeCAD).
- Désinstaller : `scripts\uninstall.ps1 -RemoveApp` (bibliothèques d'outils copiées d'abord dans
  `Documents\CAM2027-library-backup`, projets jamais supprimés).
- Pourquoi `%USERPROFILE%` et pas `%LOCALAPPDATA%` : depuis l'application Claude, `%LOCALAPPDATA%`
  est virtualisé (les processus ne voient pas le même dossier) ; le dossier du profil est réel.

## Identité (sans recompiler)

FreeCAD lit `bin\branding.xml` au démarrage (`src/App/Application.cpp`, `src/App/Branding.cpp`).
Source : `src/Mod/CAM2027/Resources/branding/`.

| Clé | Valeur |
|---|---|
| `ExeName`, `ExeVendor`, `Application`, `WindowTitle` | CAM2027 |
| `ExeVersion` | version de `cam2027/version.py` (titre « CAM2027 0.1.3 ») |
| `WindowIcon`, `ProgramLogo`, `SplashScreen`, `AboutImage` | SVG de `branding/` (icône, logo de secours, écran de démarrage) |
| `StartWorkbench` | `CAM2027Workbench` |
| `AppDataSkipVendor` | dossier de réglages `%APPDATA%\CAM2027` |
| `UserParameterTemplate` | `branding/user.cfg` : français, écran de démarrage, postprocesseur GRBL |

Au démarrage du logiciel, `cam2027/gui/standalone.py` retire du sélecteur tous les ateliers sauf
CAM2027 (les modules gardés comme bibliothèques en déclarent un), supprime le sélecteur d'atelier
(barre « Workbench » et Affichage > Sélecteur d'atelier, mémorisé masqué) et maintient le titre
« … - CAM2027 <version> » (FreeCAD y remet sa propre version à chaque document). `branding/cam2027.ico`
(16 à 256 px) est généré depuis le SVG par `scripts/make-icon.py` avec le Qt de la distribution.

## Interface propre au logiciel (étape 2)

Dans le logiciel autonome seulement, `standalone.install_manipulator()` (appelé au chargement de
`InitGui.py`) enregistre un manipulateur d'ateliers FreeCAD (`FreeCADGui.addWorkbenchManipulator`) :
FreeCAD le réapplique à chaque reconstruction des menus, sans modifier ses fichiers.

| Menu | Contenu |
|---|---|
| Fichier | Nouveau projet, Ouvrir, Fichiers récents, Importer une pièce, Fermer, Enregistrer (sous, copie, tout), Quitter |
| Édition | Annuler, Rétablir, Recalculer, Préférences |
| Affichage | caméra, vues standard, style, zoom, axes, visibilité, transparence, barres d'outils, panneaux, barre d'état, thème CAM2027 |
| Préparer | Importer, Brut et montage, Bibliothèque d'outils, Profil machine |
| Usiner | Ajouter une opération, Recalculer les parcours |
| Simuler / Exporter | Simuler, Exporter le G-code |
| Aide | À propos de CAM2027 |

Retirés : menus Outils, Macro et Fenêtres ; commandes de modélisation (couper/coller, placement,
alignement, sélection avancée…), impression, import/export génériques, liens vers le site, le forum
et l'aide de FreeCAD. Barres d'outils retirées : Presse-papiers, Macro, Structure, Aide, Vues
individuelles, sélecteur d'atelier. La barre CAM2027 est groupée par étape (séparateurs).
Les menus Préparer / Usiner / Simuler / Exporter existent aussi en atelier dans FreeCAD complet ;
FreeCAD relisant leur titre en Latin-1, `standalone.fix_menu_titles()` rétablit les accents.

## Modules : supprimés / gardés (preuve par les tests)

Supprimés (dossier `Mod\` absent, binaires `lib\*.pyd` retirés) : AddonManager, Assembly, BIM,
Fem, Help, Idf, Inspection, OpenSCAD, Plot, Points, ReverseEngineering, Robot, Start, Surface,
Test, Tux, Web, ainsi que les ateliers TechDraw, Spreadsheet et Measure.

Gardés **sans atelier visible** :

| Module | Pourquoi |
|---|---|
| CAM | moteur de parcours, postprocesseurs, simulateur |
| Part, Import | géométrie de base, lecture STEP |
| Mesh, MeshPart | STL, maillage pour OpenCamLib (3D) |
| Draft | import SVG / DXF |
| Sketcher, PartDesign, Show | formes des fraises FreeCAD (`Tools/Shape/*.fcstd`) — à remplacer pour les supprimer (prompt, étape suivante) |
| Material | matières des outils (API « assets » 1.1) |
| `lib\TechDraw.pyd`, `lib\Spreadsheet.pyd`, `lib\Measure.pyd` (binaires seuls) | l'ébauche adaptative appelle `TechDraw.findShapeOutline` ; `TechDraw.pyd` est lié à `Spreadsheet.pyd` et `Measure.pyd` (prouvé : sans eux, « DLL load failed while importing TechDraw ») |

Vérification (2026-10-20) : `bin\CAM2027Cmd.exe Mod\CAM2027\tests\run_all.py` → **50 tests OK** dans
la distribution ; `bin\CAM2027.exe Mod\CAM2027\tests\gui_smoke.py` → **OK** (atelier unique
CAM2027, titre CAM2027, 3D, 4e axe, simulateur enregistré) ; lancement réel : réglages dans
`%APPDATA%\CAM2027\v1-1`, interface en français, seul atelier CAM2027.

## Limites de cette étape

- Taille ≈ 2 Go : les bibliothèques partagées (Qt, OpenCascade, VTK/SMESH des modules supprimés…)
  sont encore copiées ; leur tri demande une analyse de dépendances DLL (à faire, avec tests).
- L'icône du fichier `CAM2027.exe` dans l'Explorateur reste celle de FreeCAD (ressource compilée
  dans l'exécutable) ; la fenêtre, la barre des tâches et les raccourcis utilisent l'icône CAM2027.
  Corrigé seulement par la compilation (étape 3) ou un éditeur de ressources (outil à télécharger).
- Les panneaux ancrés (arborescence, propriétés, rapport, console Python) restent ceux de FreeCAD,
  accessibles par Affichage > Panneaux ; pas encore de page d'accueil propre à CAM2027.
- Distribution fabriquée sur FreeCAD 1.1.4 seulement (1.0.2 reste testé en atelier).
- Logo : logo typographique de secours ; le logo définitif reste à choisir.
