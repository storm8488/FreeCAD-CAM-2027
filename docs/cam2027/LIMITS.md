# CAM2027 — Limites connues (version 0.1.0)

Statuts utilisés : **implémenté** / **testé automatiquement** / **vérifié visuellement** /
**validé sur machine**. Rien n'est validé sur machine à ce jour.

## Base et exécution

- L'atelier tourne sur les distributions officielles FreeCAD **1.0.2** et **1.1.4**
  (tests console et vérification graphique passés sur les deux). 26.3rc2 non testée.
- Pas de compilation du fork (ni MSVC, ni CMake, ni LibPack). Aucun exécutable « CAM2027 »
  compilé : le lanceur démarre le FreeCAD installé avec l'atelier.
- Les postprocesseurs, le simulateur et toutes les stratégies sont ceux de FreeCAD CAM.

## Bibliothèque d'outils

- Les 20 types stockent la géométrie Fusion complète, mais seuls endmill, ballend,
  bullnose, chamfer/V-bit/engrave, drill, dovetail, threadmill (et radius/taperedball
  sur 1.1) ont une forme FreeCAD exacte. Taper, facemill, lollipop, slot, barrel, lens,
  ogive, taperbarrel, form sont **approximés** (fraise cylindrique ou sphérique, signalé
  dans `warnings`) : aucune stratégie FreeCAD n'exploite ces profils.
- L'aperçu coté est **2D** (profil de révolution, cotes D / Lc / L / sortie). L'aperçu 3D
  (bouton « Afficher en 3D ») n'est pas coté.
- Import Fusion : **validé sur un export réel** (Fusion 2.16, `tools.json` version 37,
  11 outils : fraises deux tailles, à surfacer, à chanfreiner/graver, conique torique)
  — fixture `tests/fixtures/fusion-library-lunyee.tools`, aucun champ inconnu, aucun
  outil ignoré. Non vérifié sur export réel : porte-outils et queues par segments
  (absents de cet export), sphérique/torique/tonneau/lentille/ogive/queue d'aronde/
  lollipop/rainurer/rayonner/tarauder/forets, unités pouces, autres versions de Fusion.
  Les `expressions` Fusion (formules liant les champs) ne sont pas importées.
- Expressions entre paramètres : seulement les deux relations `n = 1000·Vc/(π·D)` et
  `Vf = n·z·fz` avec grandeur pilote déclarée. Pas de moteur d'expressions général,
  pas de détection de cycles (jalon C).
- Pas de matières/assemblages de matières au sens Fusion (préréglages étiquetés par
  matière et usage uniquement).

## Projet, brut, montage

- Brut : boîte à marges, boîte, cylindre. Pas de brut depuis un solide ni depuis le
  « brut restant » d'une opération précédente.
- Montage : repère G54–G59 + brides **visuelles** (boîtes). Les brides ne sont **pas**
  prises en compte par une détection de collision (il n'y en a pas).
- Un seul job par projet, un seul repère actif par job dans l'interface.

## Opérations

- Stratégies exposées : contour, poche, adaptative 2D, perçage, surfaçage, gravure,
  V-carving, alésage hélicoïdal, rainure, fraisage de filets, chanfreinage. Pas de 3D
  (Surface/Waterline d'OCL), pas de reprise, pas de 4e axe, pas d'attaches/dogbones/rampes
  inline (les habillages FreeCAD restent utilisables dans l'atelier CAM standard sur le
  même document).
- La poche FreeCAD (décalage/zigzag) **n'est pas** adaptative ; « adaptative » est
  l'opération Adaptive de FreeCAD (engagement contrôlé 2D, monothread).
- Surfaçage : faces planes ; avec `ClearEdges` (activé par le dialogue) le centre de
  l'outil dépasse juste les bords de la face (la fraise déborde d'un rayon + 0,1 mm).
- Fraisage de filets (`Path.Op.ThreadMilling`) : un nom de filet (`ThreadName`) est résolu
  en diamètres/pas depuis les tables CSV de FreeCAD (`Mod/CAM/Data/Threads`) comme le fait
  le panneau FreeCAD ; le pas demandé doit rester dans la plage `pitch_min`..`pitch` de
  l'outil, sinon refus. **Approximations** : le nombre de dents de l'outil (`thread_teeth`)
  n'est pas exploité par le générateur FreeCAD (l'hélice parcourt toute la longueur du
  filet) ; la crête de l'outil est prise à 0 ; le col du ToolBit est forcé à
  min(queue, 0,8 × D) pour que l'esquisse FreeCAD se résolve ; sur 1.0.2 l'esquisse du
  ToolBit à fileter signale une arête nulle (crête 0) : forme 3D de l'outil dégradée,
  parcours inchangé (il n'utilise que les propriétés Diameter/Crest) ; le trou doit être
  pré-percé (aucune opération de dégagement liée). Testé automatiquement : filet intérieur
  métrique 6H ; filets extérieurs et impériaux **non vérifiés**.
- Chanfreinage (`Path.Op.Deburr`) : arêtes sélectionnées (ou contour d'une face plane) avec
  une fraise à chanfreiner ou un V-bit ; la profondeur découle de l'angle de l'outil
  (largeur / tan(angle/2) + surprofondeur). Pas de contrôle de collision avec les parois
  voisines, pas de chanfrein « 2D » à largeur constante avec une fraise cylindrique.
- « Ajouter une opération » = nom, stratégie, assemblage, préréglage, géométrie
  sélectionnée, puis l'**éditeur d'opération** à onglets (Outil / Géométrie / Hauteurs et
  profondeurs / Passes / Stratégie / Filetage), non modal, généré depuis
  `project/paramspec.py` et les propriétés de l'objet FreeCAD ; il sert aussi à modifier une
  opération existante (double-clic dans le panneau projet). Annuler à la création supprime
  l'opération. Onglet Outil : changer de préréglage met à jour le ToolController, changer de
  coupant le remplace (ToolBit + ToolController) en conservant les réglages de stratégie ;
  rien ne change tant que l'utilisateur ne l'a pas demandé. Les propriétés non listées dans
  `STRATEGIES[...]["params"]` restent accessibles dans l'éditeur de propriétés FreeCAD.
  L'éditeur est exercé par `gui_smoke` (onglets, application d'une passe axiale) ; la
  sélection 3D dans l'onglet Géométrie n'est vérifiée que visuellement.
- Les paramètres non pris en charge par une stratégie sont listés (`ignored_params`) et
  affichés dans le panneau projet.
- Habillages : attaches (contours fermés seulement), rampe d'entrée et dogbones. L'habillage
  **remplace** l'opération dans le groupe « Operations » du job (sinon FreeCAD exporterait
  le parcours deux fois) ; l'opération de base reste dans le document et le registre reste
  indexé par son nom. Positions des attaches réparties automatiquement (nombre, largeur,
  hauteur, angle, rayon réglables ; déplacement individuel = panneau FreeCAD « Holding
  Tags » dans l'atelier CAM standard). Dogbones : angles détectés sur le parcours calculé
  (styles dogbone / T-bone, longueur adaptative, fixe ou personnalisée). Pas d'entrées/sorties
  en arc (LeadInOut : propriétés différentes entre 1.0 et 1.1, non exposé), pas de rampe sur
  perçage/hélice/filetage. Dupliquer une opération ne copie
  pas ses habillages.

- Dessin 2D dans un panneau : le dessin doit être plan ; il est posé à Z 0 (dessus du
  panneau), le panneau est une boîte englobant le dessin + marge (pas de forme de panneau
  quelconque). Les faces générées (`<vecteur>_Face`) servent à la poche 2D et au V-carving ;
  les contours et gravures se font sur les arêtes du vecteur. Contours ouverts : gravure seulement.
  Un projet a soit une pièce 3D, soit un dessin 2D dans un panneau (un seul job).

## Export et contrôles

- Contrôles statiques : unités (G21), codes autorisés (liste GRBL 1.1 uniquement ; autres
  contrôleurs « non vérifiable »), mots A/B/C vs axe rotatif déclaré, enveloppe XYZ vs
  courses, avance max, plage broche, Z sous le brut, présence d'un repère. Toute donnée
  machine inconnue produit « non vérifiable », jamais un « OK ».
- Simulation = le simulateur CAM de FreeCAD lancé sur le job (commande « Simuler »,
  `CAM_SimulatorGL` en 1.1, repli `CAM_Simulator`) ; son panneau est celui de FreeCAD
  (en anglais ou dans la langue de FreeCAD), vérifié seulement par l'enregistrement de la
  commande (gui_smoke), pas visuellement. Pas de contrôle de collision outil /
  porte-outil / brides, pas de cinématique.
- Fiche de préparation en Markdown (pas de PDF).

## Interface

- Thème sombre = pack « FreeCAD Dark » de FreeCAD, appliqué au profil du lanceur seulement
  (vérifié visuellement sur 1.1.4 ; 1.0.2 non vérifié). HiDPI : hérité de FreeCAD/Qt (non
  testé). Les barres d'outils FreeCAD standard (fichier, macro, structure) restent visibles.
- « FAO seule » = ateliers masqués dans le sélecteur, pas supprimés : les menus FreeCAD
  génériques (Édition, Affichage, Outils, Macro) restent ceux de FreeCAD.
- Pas de recherche de commandes propre (celle de FreeCAD, « What's This / Ctrl+F » selon
  version, reste disponible), pas de sauvegarde de récupération propre (autosave FreeCAD).
- Annulation/rétablissement : ceux du document FreeCAD ; les actions de la bibliothèque
  d'outils (hors document) ne sont pas annulables.
- Vérification visuelle : captures `tests/screenshots/` produites par `tests/gui_smoke.py`.

## 4e axe

- Seuls le profil machine (champs `RotaryAxis`, tous à renseigner) et les contrôles
  d'export (rejet des mots A/B/C sans axe déclaré) existent. Aucune stratégie rotative,
  aucun enroulement, aucune indexation.
