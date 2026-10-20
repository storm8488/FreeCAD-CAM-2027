# CAM2027 — Installation et démarrage

## Ce qui est livré

- `src/Mod/CAM2027/` : l'atelier (module Python FreeCAD) — bibliothèque d'outils, chaîne
  projet → pièce → brut/montage → opérations → export, interface Qt en français.
- `scripts/cam2027.cmd` : lanceur Windows (profil FreeCAD séparé, journal activé).
- `scripts/install-shortcut.ps1` / `scripts/uninstall.ps1` : raccourci Bureau + menu
  Démarrer, désinstallation par utilisateur (les projets sont conservés).
- `scripts/cam2027-tests.cmd` : tests automatiques en mode console.

**État actuel :** l'atelier s'exécute sur une **distribution officielle FreeCAD** :
la 1.1.4 portable (archive `FreeCAD_1.1.4-Windows-x86_64-py311.7z`, SHA256 vérifié,
extraite dans `%LOCALAPPDATA%\CAM2027\FreeCAD-1.1.4`) ou la 1.0.2 installée dans
`C:\Program Files\FreeCAD 1.0`. Ce n'est **pas** un exécutable compilé depuis ce fork
(aucun compilateur C++ ni CMake n'est présent sur la machine). La base épinglée du fork
est le tag `1.1.4` (commit `4fd3bf32`), voir [ARCHITECTURE.md](ARCHITECTURE.md).

Ordre de recherche des lanceurs : variable `FREECAD_BIN`, puis la 1.1.4 portable, puis la 1.0.2.
Pour (ré)installer la 1.1.4 portable sans 7-Zip (bsdtar de Windows 11 lit le 7z) :

```bat
gh release download 1.1.4 -R FreeCAD/FreeCAD -p "FreeCAD_1.1.4-Windows-x86_64-py311.7z*" -D %LOCALAPPDATA%\CAM2027\downloads
```

```bat
tar -xf %LOCALAPPDATA%\CAM2027\downloads\FreeCAD_1.1.4-Windows-x86_64-py311.7z -C %LOCALAPPDATA%\CAM2027\FreeCAD-1.1.4
```

## Prérequis

- Windows 10/11 64 bits.
- FreeCAD 1.0.x ou 1.1.x (distribution officielle, installateur ou 7z portable).
  Si FreeCAD n'est pas dans `C:\Program Files\FreeCAD 1.0\bin`, définir la variable
  d'environnement `FREECAD_BIN` vers le dossier `bin`.

## Logiciel autonome CAM2027 (recommandé)

```bat
powershell -ExecutionPolicy Bypass -File scriptsuild-distribution.ps1
powershell -ExecutionPolicy Bypass -File scripts\install-shortcut.ps1
```

Fabrique le logiciel CAM2027 séparé dans `%USERPROFILE%\CAM2027` (sans les ateliers de modélisation,
nom et icône CAM2027, réglages dans `%APPDATA%\CAM2027`) et crée les raccourcis vers `CAM2027.exe`.
Détails : [DISTRIBUTION.md](DISTRIBUTION.md).

## Lanceur de développement (atelier dans FreeCAD complet)

```bat
scripts\cam2027.cmd
```

Le lanceur :

1. crée `%LOCALAPPDATA%\CAM2027\home` (préférences, macros, journal `FreeCAD.log`) ;
2. y copie `scripts\user.cfg.template` au premier lancement (langue française, atelier
   CAM2027 au démarrage, postprocesseur GRBL par défaut) ;
3. démarre `FreeCAD.exe -l -M <dépôt>\src\Mod\CAM2027` avec `FREECAD_USER_HOME` pointant
   sur ce profil. Votre installation et vos préférences FreeCAD habituelles ne sont pas
   touchées.

À la première activation de l'atelier dans ce profil (et seulement quand FreeCAD a été lancé
par `cam2027.cmd`, variable `CAM2027_HOME`), le **profil « FAO seule »** est appliqué
(`cam2027/gui/prefs.py`) : thème sombre « FreeCAD Dark » (pack de préférences livré avec
FreeCAD), icônes de barre d'outils en 32 px, atelier CAM2027 au démarrage, page de démarrage
fermée, et tous les autres ateliers FreeCAD masqués dans le sélecteur (préférence
`Workbenches/Disabled`). Pour retrouver les autres ateliers : Édition > Préférences >
Ateliers (ils restent installés), ou mettre le paramètre `BaseApp/Preferences/CAM2027/CamOnly`
à faux. Le profil n'est réappliqué que si sa version change (`ProfileVersion`), vos réglages
ultérieurs sont conservés.

Raccourcis clavier des commandes CAM2027 : Ctrl+Maj+N nouveau projet, Ctrl+Maj+I importer,
Ctrl+Maj+T bibliothèque d'outils, Ctrl+Maj+B brut et montage, Ctrl+Maj+O ajouter une opération,
Ctrl+Maj+R recalculer, Ctrl+Maj+E exporter, Ctrl+Maj+S simuler, Ctrl+Maj+M profil machine.

Raccourci Bureau + menu Démarrer (par utilisateur) :

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-shortcut.ps1
```

Désinstallation (supprime raccourcis et profil ; sauvegarde la bibliothèque d'outils dans
`Documents\CAM2027-library-backup`, ne touche jamais aux projets `.FCStd`/`.nc`) :

```powershell
powershell -ExecutionPolicy Bypass -File scripts\uninstall.ps1
```

## Parcours dans l'interface

Barre d'outils **CAM2027** : Nouveau projet → Importer une pièce → Bibliothèque d'outils →
Brut et montage → Ajouter une opération → Recalculer → Exporter le G-code → Profil machine →
À propos.

1. **Nouveau projet** : crée un document avec une copie figée de la bibliothèque.
2. **Importer** : STEP/STL/OBJ/SVG/DXF.
3. **Brut et montage** : crée le job CAM, le brut (boîte à marges, boîte, cylindre) et le
   repère (G54…).
4. **Ajouter une opération** : stratégie, assemblage d'outil (T n°), préréglage ; la
   sélection courante (faces/arêtes) sert de géométrie.
5. **Exporter** : aperçu G-code, contrôles, fiche de préparation ; écriture du `.nc` et
   du `-setup.md`. Rien n'est envoyé à CNCjs : chargez le fichier vous-même.

## Tests

```bat
scripts\cam2027-tests.cmd
```

Voir [TESTS.md](TESTS.md) pour le détail et les résultats.

## Fichiers et données

- Bibliothèque utilisateur : `%APPDATA%\FreeCAD\CAM2027\library.cam2027tools` (profil
  FreeCAD du lanceur : `%LOCALAPPDATA%\CAM2027\home\CAM2027\library.cam2027tools`).
- Projets : où vous les enregistrez (`.FCStd`), G-code à côté (`.nc` + `-setup.md`).
- Journal : `FreeCAD.log` dans le dossier de profil.

## Reconstruction depuis les sources (fork)

Non réalisable sur cette machine aujourd'hui : il manque Visual Studio Build Tools, CMake
et le LibPack FreeCAD. La procédure amont est documentée sur
<https://wiki.freecad.org/Compile_on_Windows>. Tant que la compilation n'est pas en place,
toute modification se fait dans `src/Mod/CAM2027` (Python) et s'exécute sur la
distribution officielle.
