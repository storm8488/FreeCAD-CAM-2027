# CAM2027 — FAO libre pour CNC (version alpha)

> ⚠️ **Version alpha, en test.** Le logiciel calcule de vrais parcours et du vrai G-code, mais il n'a pas encore
> usiné grand-chose. Vérifiez chaque parcours (simulation, contrôle matière, marche à vide au-dessus de la pièce)
> avant de couper. Vos retours décident de la suite : **[signaler un bug](https://github.com/storm8488/FreeCAD-CAM-2027/issues/new?template=1-cam2027-bug.yml)**
> · **[proposer une idée](https://github.com/storm8488/FreeCAD-CAM-2027/issues/new?template=2-cam2027-idea.yml)**.

CAM2027 est un logiciel de FAO (CAM) **libre et gratuit** pour fraiseuses CNC de loisir et d'atelier : bois,
plastiques, aluminium, 3 axes et 4e axe. Il est construit sur le moteur CAM de **FreeCAD 1.1** (parcours,
post-processeurs, OpenCamLib) avec une interface pensée pour l'usinage, en français, inspirée de Fusion 360 et
d'Aspire. Ce n'est pas une version officielle de FreeCAD : c'est un fork indépendant (LGPL-2.1-or-later).

*English: CAM2027 is a free, open-source CAM for hobby and workshop CNC routers, built on FreeCAD 1.1's CAM engine
with a machining-first UI (French first, English strings in the code). It is in **alpha**: bug reports and feature
ideas in English are welcome.*

## Ce qu'il sait faire

- **Projet guidé** : import STEP / STL / SVG / DXF / image, brut et montage (plaque, bloc, brides, zones
  interdites), origine, profil machine (post-processeurs de FreeCAD : GRBL, Marlin, LinuxCNC…), bibliothèque d'outils avec vitesses par matière.
- **2D** : contour (attaches, entrées / sorties), poches à plusieurs profondeurs, surfaçage, perçage, hélice,
  filetage à la fraise, chanfrein, gravure, **V-carving** et incrustations (inlay), reprise de matière.
- **3D** : ébauche, finition parallèle / Z constant / crayon / scallop, reliefs depuis une image (niveaux de
  gris, formes gonflées, profondeur estimée par IA, en local).
- **Dessin et images** : rectangle, cercle, polygone, texte modifiable, vectorisation d'image, Photo V-Carve,
  moulures, cannelures, textures, imbrication de pièces sur un panneau, recto-verso avec goujons.
- **4e axe** : enroulement, usinage rotatif.
- **Contrôles** : simulation, contrôle matière (entailles, reste, collisions porte-outil / brides, rapides dans la
  matière), vérification du G-code avant export (courses de la machine, brut, collisions, zones interdites).

Ce qui n'est pas encore fait : [LIMITS.md](../docs/cam2027/LIMITS.md). Historique : [CHANGELOG.md](../docs/cam2027/CHANGELOG.md).

## Essayer (Windows, FreeCAD 1.1)

1. Installez **FreeCAD 1.1** (version officielle : <https://www.freecad.org/downloads.php>).
2. Téléchargez ce dépôt : bouton **Code > Download ZIP** sur la branche `cam2027`, puis décompressez.
3. Copiez le dossier `src/Mod/CAM2027` dans le dossier des modules de FreeCAD :
   `%APPDATA%\FreeCAD\v1-1\Mod\` (créez `Mod` s'il n'existe pas).
4. Lancez FreeCAD et choisissez l'atelier **CAM2027** dans la liste des ateliers.

Testé sur Windows 11 avec FreeCAD 1.1.4. Linux et macOS : non testés, retours bienvenus.
Logiciel autonome (sans les ateliers de modélisation) : [DISTRIBUTION.md](../docs/cam2027/DISTRIBUTION.md).

## Donner un retour

- Dans le logiciel : menu **Aide > Signaler un bug** / **Proposer une idée**, ou les liens à côté du repère
  **ALPHA** dans la barre d'état. Le formulaire GitHub s'ouvre avec les versions déjà remplies.
- Un bug se corrige vite avec **le fichier qui le reproduit** (projet `.FCStd` zippé, modèle, image, G-code) et
  une capture d'écran.
- Les idées qui viennent d'un vrai usinage (votre pièce, votre machine, ce qui vous fait perdre du temps) sont les
  plus utiles.

## Soutenir le projet

CAM2027 est gratuit et le restera. Si le logiciel vous sert, vous pouvez offrir un café au développeur :
**[buymeacoffee.com/damouse8482](https://buymeacoffee.com/damouse8482)** ☕ — les retours de test aident tout autant.

## Licence

LGPL-2.1-or-later, comme FreeCAD. Basé sur FreeCAD (<https://www.freecad.org>) et son atelier CAM.
