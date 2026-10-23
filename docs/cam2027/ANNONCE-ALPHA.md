# Annonce de la version alpha (Discord, forums)

Textes prêts à coller. Discord : moins de 2 000 caractères (limite d'un message). Joindre 2 ou 3 captures
(un V-carving, une simulation, le panneau Projet).

## Discord — français

**CAM2027 — une FAO libre et gratuite pour vos CNC, en alpha : testeurs recherchés 🛠️**

Salut ! Je développe **CAM2027**, un logiciel de FAO open source (LGPL) pour fraiseuses CNC de loisir et d'atelier : bois, plastique, alu, 3 axes et 4e axe. Il repose sur le moteur CAM de FreeCAD 1.1, avec une interface pensée pour l'usinage (français ou anglais), inspirée de Fusion 360 et d'Aspire.

**Ce qu'il fait déjà**
• Import STEP / STL / SVG / DXF / image, brut et montage (brides, zones interdites), bibliothèque d'outils
• 2D : contour avec attaches, poches, perçage, hélice, chanfrein, gravure, V-carving, incrustations
• 3D : ébauche, finitions, reliefs depuis une image (dont profondeur estimée par IA, en local)
• Dessin vectoriel, vectorisation d'image, Photo V-Carve, imbrication sur panneau, recto-verso
• Simulation et contrôle matière (entailles, collisions porte-outil / brides) avant l'export G-code (GRBL…)

⚠️ **C'est une alpha** : vérifiez toujours en simulation et en marche à vide avant de couper.

**Ce que je cherche** : des gens qui l'essaient sur leurs vraies pièces et leurs vraies machines. Bugs, plantages, parcours bizarres, fonctions qui manquent, étapes trop longues : tout m'intéresse.

**Essayer** (Windows, un zip à décompresser, rien à installer) 👉 https://github.com/storm8488/FreeCAD-CAM-2027/releases/latest

**Faire un retour** : dans le logiciel, menu **Aide > Signaler un bug / Proposer une idée** (ou les liens à côté du repère ALPHA, en bas à droite). Le formulaire GitHub s'ouvre avec vos versions déjà remplies. Joignez si possible le fichier qui pose problème, ça fait gagner un temps fou.
Pas de compte GitHub ? Répondez simplement ici 🙂

Le logiciel est gratuit ; pour soutenir le projet : ☕ https://buymeacoffee.com/damouse8482

Merci d'avance ! 🙏

## Discord — English

**CAM2027 — free, open-source CAM for your CNC, alpha testers wanted 🛠️**

Hi! I'm building **CAM2027**, an open-source (LGPL) CAM for hobby and workshop CNC routers: wood, plastics, aluminium, 3-axis and 4th axis. It runs on FreeCAD 1.1's CAM engine with a machining-first UI inspired by Fusion 360 and Aspire, in English or French.

**What it already does**
• Import STEP / STL / SVG / DXF / images, stock and setup (clamps, keep-out zones), tool library
• 2D: profile with tabs, pockets, drilling, helix, chamfer, engraving, V-carving, inlays
• 3D: roughing, finishing, reliefs from an image (including local AI depth estimation)
• Vector drawing, image tracing, Photo V-Carve, sheet nesting, two-sided jobs
• Simulation and material check (gouges, holder / clamp collisions) before G-code export (GRBL…)

⚠️ **This is an alpha**: always simulate and dry-run before cutting.

**What I'm looking for**: people trying it on real parts and real machines. Bugs, crashes, odd toolpaths, missing features, tedious steps: all welcome.

**Try it** (Windows, unzip and run, nothing to install) 👉 https://github.com/storm8488/FreeCAD-CAM-2027/releases/latest

**Give feedback**: in the app, **Help > Report a bug / Suggest a feature** (or the links next to the ALPHA badge, bottom right). The GitHub form opens with your versions filled in. Attaching the file that shows the problem helps a lot.
No GitHub account? Just reply here 🙂

It's free; to support the project: ☕ https://buymeacoffee.com/damouse8482

Thanks! 🙏

## Reddit — English (r/hobbycnc, r/CNC, r/FreeCAD, r/opensource)

**Title:** I'm building a free, open-source CAM for hobby CNC routers on top of FreeCAD 1.1 — alpha testers wanted

**Body:**

Hi all! For the past months I've been building **CAM2027**, a free and open-source (LGPL) CAM aimed at hobby and workshop CNC routers (wood, plastics, aluminium, 3-axis and 4th axis). It uses FreeCAD 1.1's CAM engine (toolpaths, post-processors, OpenCamLib) with a machining-first UI inspired by Fusion 360 and Aspire.

What works today:

- Guided project: import STEP / STL / SVG / DXF / images, stock and setup (clamps, keep-out zones), machine profile, tool library with feeds per material
- 2D: profile with tabs and lead-in/out, multi-depth pockets, facing, drilling, helix, thread milling, chamfer, engraving, V-carving, inlays, rest machining
- 3D: roughing, parallel / waterline / pencil / scallop finishing, reliefs from an image (grey levels, inflated shapes, local AI depth estimation)
- Vector drawing, image tracing, Photo V-Carve, mouldings, flutes, textures, sheet nesting, two-sided jobs with dowels
- Simulation and material check (gouges, leftover, holder / clamp collisions, rapids into stock), G-code checked before export

**It's an alpha.** It produces real G-code, but it hasn't cut much yet: always simulate and dry-run above the part first. The UI is in English and French (it follows Windows; View > Language switches it).

What I'd love from you: try it on a real part and a real machine, and tell me what breaks, what's missing and what's tedious. In the app, Help > Report a bug / Suggest a feature opens a GitHub form with your versions already filled in; attaching the file that shows the problem helps a lot. Comments here are fine too.

Download (Windows, unzip and run): https://github.com/storm8488/FreeCAD-CAM-2027/releases/latest (source: https://github.com/storm8488/FreeCAD-CAM-2027)

It's free and will stay free. If it helps you: https://buymeacoffee.com/damouse8482 ☕

## Forums français (usinage, CNC amateur)

**Titre :** CAM2027 : une FAO libre et gratuite pour fraiseuses CNC (bois, alu, 4e axe), recherche testeurs (alpha)

Bonjour à tous,

Je développe **CAM2027**, un logiciel de FAO libre et gratuit (licence LGPL) pour les fraiseuses CNC de loisir et d'atelier : bois, plastiques, aluminium, 3 axes et 4e axe. Il s'appuie sur le moteur CAM de FreeCAD 1.1 (calcul des parcours, post-processeurs, OpenCamLib), avec une interface pensée pour l'usinage, en français ou en anglais, dans l'esprit de Fusion 360 et d'Aspire.

**Ce qu'il fait aujourd'hui**
- Projet guidé : import STEP / STL / SVG / DXF / image, brut et montage (brides, zones interdites), profil machine, bibliothèque d'outils avec vitesses par matière.
- 2D : contour avec attaches et entrées / sorties, poches à plusieurs profondeurs, surfaçage, perçage, hélice, filetage à la fraise, chanfrein, gravure, V-carving, incrustations, reprise de matière.
- 3D : ébauche, finitions parallèle / Z constant / crayon / scallop, reliefs depuis une image (niveaux de gris, formes gonflées, profondeur estimée par IA, calculée sur votre PC).
- Dessin vectoriel, vectorisation d'image, Photo V-Carve, moulures, cannelures, textures, imbrication sur panneau, recto-verso avec goujons.
- Simulation et contrôle matière (entailles, reste, collisions porte-outil et brides, rapides dans la matière), G-code vérifié avant export (GRBL, etc.).

**C'est une version alpha** : le G-code est réel, mais le logiciel a encore peu usiné. Simulez et faites une marche à vide au-dessus de la pièce avant chaque usinage.

**Ce que je cherche** : des retours sur de vraies pièces et de vraies machines. Bugs, plantages, parcours étranges, fonctions qui manquent, étapes trop longues. Dans le logiciel, **Aide > Signaler un bug / Proposer une idée** ouvre un formulaire GitHub avec vos versions déjà remplies ; joindre le fichier qui pose problème aide énormément. Les réponses ici sont aussi les bienvenues, je passe régulièrement.

**Essayer** (Windows, un zip à décompresser, rien à installer) : https://github.com/storm8488/FreeCAD-CAM-2027/releases/latest

Le logiciel est et restera gratuit. Pour soutenir le projet : https://buymeacoffee.com/damouse8482

Merci d'avance pour vos essais !

## Forum FreeCAD — sous-forum CAM (English)

**Title:** CAM2027: a machining-first UI on top of the CAM workbench (alpha, LGPL) — feedback welcome

Hi everyone,

I've been working on **CAM2027**, an independent LGPL fork built on FreeCAD 1.1.4 and its CAM workbench. It doesn't change FreeCAD's C++ or Python sources: it's a workbench (also usable as a stripped-down standalone build) that wraps the CAM operations in a guided, machining-first UI for hobby routers (project > part > stock and setup > operations > check and export), plus some extra operations (V-carve inlays, reliefs from images, sheet nesting, two-sided jobs, rotary) and a Z-map material check.

Along the way I found a few things in the CAM workbench that might be worth upstreaming, for example in `Path/Op/Vcarve.py`: `isPartOfDomain` rebuilds its classifier on every Voronoi vertex (25 min on a traced drawing; an even-odd test on the diagram's own segments gives byte-identical G-code in 16 s), and depth is interpolated linearly along Voronoi edges touching a corner, where the true distance dips mid-edge (up to 0.8 mm overcut on a traced image). I'd be happy to open issues or PRs if that's useful.

It's an alpha, with an English and French UI. Feedback from people who know the CAM workbench would be very valuable: https://github.com/storm8488/FreeCAD-CAM-2027

Thanks to everyone who built the CAM workbench — CAM2027 would not exist without it.
