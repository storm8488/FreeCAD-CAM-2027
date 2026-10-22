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
  V-carving, alésage hélicoïdal, rainure, fraisage de filets, chanfreinage, poche 2D,
  **finition 3D de surface et en Z constant** (OpenCamLib, 3 axes : balayage rotatif non exposé ;
  échantillonnage par défaut 0,05 mm : à 0,5 mm les segments entre échantillons coupaient le haut des
  parois (0,25 mm d'entaille réelle sur la plaque de test), à 0,1 mm encore 0,07 mm sur le casse-noix ;
  **ébauche 3D** = adaptative niveau par niveau ; pièce entière sur FreeCAD 1.1 : mode « modèle » (pièce
  et brut tranchés à chaque niveau, calcul arrêtable ; quand la réunion des projections d'une tranche
  échoue dans FreeCAD, « Wire is not closed », la réunion face par face est gardée) ; sur 1.0.2 : autour
  des faces en relief, refusée au-delà de 200 faces (calcul de plusieurs minutes), avec des marches
  entre niveaux ; sur un relief depuis une image, seule la surface du dessus sert de base),
  pas de reprise, pas de 4e axe, pas d'attaches/dogbones/rampes
  inline (les habillages FreeCAD restent utilisables dans l'atelier CAM standard sur le
  même document).
- Ébauche 3D (mode « modèle ») et adaptatives à plusieurs régions : calculées dans des processus Python de
  FreeCAD (`bin/python.exe`, au plus 12 ; `CAM2027_PARALLEL_LEVELS=0` / `CAM2027_PARALLEL_ADAPTIVE=0` pour les
  garder dans FreeCAD). L'adaptative de FreeCAD n'est **pas déterministe** : deux calculs identiques ne
  donnent pas exactement les mêmes points (vérifié dans un même processus), le contrôle matière donne les
  mêmes résultats. Pendant le calcul, la vue 3D n'affiche plus la progression des trajets en direct.
- Poche 3D sur des faces traitées collectivement (fonds d'alvéoles choisis automatiquement) : découpe de
  l'enveloppe, intersections et niveaux calculés dans des processus Python de FreeCAD (`parallel_pocket`,
  `CAM2027_PARALLEL_POCKET=0` pour les garder dans FreeCAD ; installé seulement sur le code FreeCAD attendu,
  1.0.2 et 1.1.4). La poche de FreeCAD n'est **pas exactement reproductible** non plus sur une grosse pièce :
  sur le plateau à 135 alvéoles, le calcul en série donne d'une fois à l'autre 21 561 ou 21 545 commandes
  (739,8 ou 739,3 cm³ enlevés au contrôle, liaisons à la profondeur de coupe), sans entaille ; le calcul en
  processus retombe sur ces mêmes parcours. « Arrêter le calcul » n'arrête pas la poche (FreeCAD ne le
  prévoit pas pour elle) ; l'interface reste rafraîchie.
- Adaptative et ébauche 3D : entrée en hélice seulement (pas de rampe ni de plongée) ; l'hélice démarre à
  0,95 x le diamètre et se réduit région par région jusqu'à 10 % du diamètre ; une région plus étroite que la
  fraise reste pleine (trou de 4 mm pour une fraise de 6). Fraise à coupe au centre conseillée.
- Ébauche 3D (mode « modèle ») : une face que FreeCAD ne sait pas projeter sur XY a une ombre approchée à
  0,01 mm (triangulation) ; une poche aux fils incohérents (découpe d'OpenCascade sur une pièce aux nombreuses
  petites faces) est réduite à son plus petit contour : de la matière peut rester pour la finition.
- Adaptative et ébauche 3D : liaisons « en zone dégagée » remontées d'une passe (`LiftDistance` = passe ;
  0 dans FreeCAD, l'adaptative en faisait parfois une à travers la matière). Le Z constant (OpenCamLib) ne
  s'arrête pas en cours de calcul : sur une grande pièce l'interface reste occupée (39 s sur le chauffage
  de test à 0,5 mm d'échantillonnage).
- Sans sélection, poche et adaptative usinent les fonds de poche : faces planes horizontales entre le dessous
  et le dessus **sans matière au-dessus** (un fond sous un surplomb est écarté : FreeCAD l'extruderait à
  travers le surplomb). Un fond partiellement couvert est écarté en entier : le sélectionner à la main.
- La poche FreeCAD (décalage/zigzag) **n'est pas** adaptative ; « adaptative » est
  l'opération Adaptive de FreeCAD (engagement contrôlé 2D, monothread).
- Poches à plusieurs profondeurs (fonds trouvés ou sélectionnés) : une opération par hauteur de fond (poche,
  poche 2D, adaptative). Le contour extérieur seul (trous débouchants ouverts) n'est pris que sans sélection,
  pour la poche 2D et l'adaptative. Ébauche 3D : pas de passe à la hauteur des plats ;
  un fond à moins de la surépaisseur sous un niveau garde jusqu'à un pas de matière.
- Surfaçage : faces planes (la pièce entière sélectionnée vaut sans sélection : faces du dessus, sinon dessus du
  brut) ; avec `ClearEdges` (activé par le dialogue) le centre de
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
  pré-percé (aucune opération de dégagement liée ; le contrôle matière le dit : « filetage dans un trou pas
  encore percé »). Sans sélection, seuls les trous percés pour un même filet sont gardés (diamètre mineur de
  la table à 0,15 mm près) : le filet demandé s'il en a, sinon celui qui en a le plus parmi ceux que l'outil
  peut fraiser (les autres trous sont listés). Testé automatiquement : filet intérieur
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
- Simulation = le simulateur CAM de FreeCAD (commande « Simuler », `CAM_SimulatorGL`, repli
  `CAM_Simulator`) : CAM2027 choisit le job, décoche les opérations qui utilisent A (le simulateur
  ignore A : indexées hors A0, enroulées) en le signalant, puis lance la lecture ; sa fenêtre (lecture,
  pause, pas à pas, vitesse) et son panneau sont ceux de FreeCAD. Vérifié par le test graphique
  (fenêtre ouverte et capturée), pas le contenu de son rendu.
- Collisions (même commande) : à chaque mouvement, avant d'enlever sa matière, la queue (de la longueur
  de coupe à la sortie) et chaque tronçon du porte-outil sont comparés à la matière restante (brut +
  pièce) dans leur rayon ; l'assemblage entier est comparé aux brides (boîtes englobantes), rapides
  compris. Première collision de chaque type par opération, avec son n° de commande et la position
  de la pointe. Tronçons coniques pris à leur rayon maximal (prudent). Sans bride déclarée, sans
  porte-outil dans l'assemblage ou avec des opérations non simulées (axe A), le contrôle concerné est
  « non contrôlé », jamais « OK ». À l'export : collisions du dernier contrôle = erreurs bloquantes
  tant que les parcours sont identiques ; contrôle absent ou périmé = « non vérifiable ».
- Contrôle matière (Simuler > Contrôle matière et collisions) : carte de hauteur 3 axes à 0,5 mm ; une colonne ne
  voit que le dessus : parois verticales, contre-dépouilles et collisions porte-outil / brides ne sont
  pas contrôlées (dit dans le rapport). Fraises autres que plate / boule / torique / conique simulées
  comme plates (signalé). Brut rond (4e axe) refusé. Une entaille est un écart de plus de 0,02 mm sous
  le dessus de la pièce au centre d'une colonne, ou à 0,05 mm de lui (colonne pile sur une paroi
  verticale) ; les trous filetés sont comptés creusés jusqu'au diamètre majeur du filet. Un rapide compte
  dans la matière au-delà de 0,01 mm ; le dégagement vertical vers le haut n'est jamais compté.
  Chaque colonne signalée (les 4 000 plus profondes) est vérifiée en 3D sur la pièce triangulée : l'entaille
  retenue est la distance du point coupé à la surface (nulle sous un surplomb), pas la hauteur de paroi
  qu'une fraise tangente fait perdre à la colonne ; une colonne sur le bord de la silhouette (pièce absente
  à 0,05 mm) n'est pas contrôlée.
  Balayage : fraise plate et boule exactes sur les pentes (disque et sphère balayés le long du segment 3D) ;
  torique et conique prises au point le plus proche sur des morceaux de 0,5 mm / 0,05 mm de dénivelé.
  Segments traités par paquets vectorisés (pré-contrôles de la queue, du porte-outil et des rapides sur
  l'état d'avant le paquet, repli séquentiel quand ils signalent quelque chose : même résultat qu'un à un).
  Ordre de grandeur : 10 à 20 000 commandes par seconde.
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

## Import et pièce

- Maillages (STL, OBJ...) : fermé et jusqu'à 200 000 triangles -> solide affiné ; ouvert ou plus gros ->
  **surface 3D** (faces du maillage, non cousues) : brut, surfaçage (dessus du brut jusqu'au haut de la pièce,
  limite = brut) et finitions 3D (surface, Z constant) seulement, avec `BoundBox = Stock` ; contour, poche, adaptative, ébauche 3D, perçage, gravure... refusés sur une
  surface. Sur FreeCAD 1.0 (pas de conversion sans couture), un tel maillage reste un maillage et ne peut pas
  être usiné (dit à l'import et au brut). Une surface de 215 000 faces pèse dans la vue 3D et dans le fichier.
- Annuler (Ctrl+Z) : les actions CAM2027 et celles de FreeCAD ; « Calculer » seul et les modifications de la
  bibliothèque d'outils ne sont pas des étapes. Après Annuler, les parcours ne sont pas
  recalculés : ceux d'avant l'action sont rétablis. Un ajout annulé reste dans « Rétablir ».
- Un fichier importé deux fois est signalé ; ses corps en double sont ignorés par « Brut et montage ».
  Une fusion qui ne donne pas un solide plausible est refusée (corps laissés séparés) : une forme vide
  fait boucler le brut de FreeCAD jusqu'au plantage.
- Plusieurs corps importés (assemblage STEP) : « Brut et montage » sans sélection les **fusionne** en une
  seule pièce jusqu'à 20 000 faces (environ 1 s pour 300 faces, 1 min pour 37 000) ; au-delà, ils restent
  séparés et le message le dit. Sélectionner les corps voulus avant « Brut et montage » pour n'en usiner
  que certains.
- Sans sélection, « Ajouter une opération » prend toute la pièce ; poche et adaptative prennent les fonds
  de poche (faces planes horizontales entre le dessous et le dessus), surfaçage le dessus ; rien de
  pertinent : l'opération n'est pas créée et le message dit quoi sélectionner.

## Flux 2D avancé

- **Fond plat** : la zone plate est la face réduite de la portée du V-bit (rayon de pointe + profondeur ×
  tan(demi-angle)) ; ses angles rentrants gardent le rayon de la fraise plate. À recréer si la
  profondeur du V-carving change (les trois opérations sont figées à leur création).
- **Incrustation** : géométrie d'Aspire (départ du mâle réduit la forme de Ps × tan(demi-angle)) ;
  vérifiée sur un rectangle par simulation des deux faces. Formes à angles rentrants : la cavité
  y est arrondie (diagonale du V-carving) alors que le bouchon y est vif, risque d'interférence
  non contrôlé automatiquement. Le mâle est un projet séparé, à enregistrer.
- **Imbrication** : par rectangles englobants seulement (une pièce en L ne reçoit rien dans son
  creux) ; un seul panneau ; pièces non placées rapportées. À faire avant « Brut et montage ».

## 4e axe

- **Indexé 3+1 seulement** : pour chaque angle A, la pièce est copiée et tournée exactement autour
  de l'axe A (droite parallèle à X passant par le centre renseigné), les opérations sont calculées en
  3 axes sur cette copie, et une opération « Index A… » (`G0 Z` dégagement puis `G0 A…`) est recréée
  automatiquement devant chaque changement d'angle. A ne bouge jamais pendant une coupe (contrôlé :
  erreur à l'export hors G93).
- **Continu : gravure enroulée seulement** (Usiner > Gravure enroulée). Le dessin est tracé à
  plat dans le repère déroulé (X le long de l'axe, Y = longueur d'arc sur le brut, Y 0 à A 0, un
  tour = 2πR) ; la fraise suit les traits à profondeur constante. Pas de compensation du rayon
  d'outil, pas de poche ni de contour décalé enroulés, pas d'usinage 3D rotatif. Les coupes sont
  en G93 (F = 1 / durée en minutes, calculée à la longueur réelle au rayon de coupe) puis G94.
  Le brut rond doit être centré sur l'axe A du profil. La vue des parcours de FreeCAD ignore A :
  l'opération est masquée et remplacée par un aperçu « (preview) » du trajet réel sur la pièce.
- FreeCAD 1.0 replie A dans ±180° avant le postprocesseur, même pour un placement neutre
  (`PathUtils.getPathWithPlacement` → `Command.transform`). Pendant l'export, CAM2027 applique la
  règle de FreeCAD 1.1 (parcours rendu tel quel si le placement est neutre) ; un saut de A de plus
  de 45° dans un seul mouvement de coupe est refusé à l'export, quelle qu'en soit la cause.
- Rien n'est supposé : sans centre de l'axe A ni sens positif dans le profil machine, les opérations
  indexées sont refusées. Sens « main droite » = A positif antihoraire vu depuis +X (RS274) ;
  « main gauche » inverse le signe écrit.
- Une opération indexée exige une géométrie sélectionnée (faces / arêtes choisies sur la pièce
  affichée, reportées sur la copie tournée), sauf perçage / hélice / filetage (trous détectés sur la
  copie) et ébauche 3D (faces en relief). Les copies tournées sont figées : réindexer (éditeur,
  champ « Index A ») si la pièce change. Elles restent hors du modèle du job : les opérations
  « toute la pièce » ne voient que la pièce réelle.
- Vue 3D : les parcours sont tracés en coordonnées machine ; ceux d'un index s'affichent donc sur la
  pièce telle qu'elle est à A0 (masquer les autres opérations pour les examiner).
- GRBL 1.1 standard n'a pas d'axe A : l'export le signale (firmware 4 axes nécessaire, ex. grblHAL).
  Le postprocesseur `grbl` de FreeCAD écrit bien les mots A.
- Poche 3D (`pocket`) sur une copie tournée : le dernier niveau peut manquer si la profondeur finale
  est exactement celle du fond (cause FreeCAD non identifiée) ; utiliser la poche 2D ou une
  profondeur finale 0,001 mm plus basse.
- Pas de contrôle de collision avec le mandrin, les mors ou la contre-pointe (champs du profil non
  exploités).

## Flux Aspire : modèles, dessin, images (nuit 2, S5)

- **Modèles de parcours** : seules les opérations posées sur des vecteurs du dessin 2D sont enregistrées
  (pas celles sur « toute la pièce », ni le fond plat, l'incrustation ou la gravure enroulée, générés). Une
  opération recréée prend **tous** les vecteurs du calque ciblé ; sans calque, les vecteurs du même nom
  (identifiant SVG). L'outil est cherché par nom, sinon par type et diamètre, dans la bibliothèque du
  projet ; les habillages (attaches, rampes) ne sont pas enregistrés. Calques DXF : seulement quand l'import
  de l'interface les crée (groupes / calques Draft) ; en console, le lecteur DXF ne les garde pas.
- **Dessin vectoriel** : pas d'édition de nœuds ni de dessin à main levée (rectangles, cercles, polylignes :
  importer un SVG / DXF) ; le texte est figé à la création (changer le texte = le redessiner). Contours de
  police approchés par des polygones à 0,01 mm (sortie en G1). Le texte sur courbe suit le côté gauche du
  vecteur (inverser le vecteur pour passer de l'autre côté) ; une courbe à plusieurs arêtes est approchée par
  une B-spline. Les booléens et le décalage travaillent sur les contours **fermés** seulement. Polices
  proposées : celle de FreeCAD (osifont) et les polices Windows courantes présentes.
- **Vectorisation d'image** : contours polygonaux (pas de courbes de Bézier, pas de `potrace`) ; image
  rééchantillonnée à 400 pixels au plus sur le grand côté ; un seul seuil (pas de couleurs séparées). Le
  bord d'une zone touchant le bord de l'image est fermé sur le bord.
- **Photo V-Carve** : lignes horizontales seulement (pas d'angle de lignes ni de lignes croisées), profondeur
  proportionnelle au sombre (correction gamma), V-bit seulement. L'opération est générée (`Path.Op.Custom`) :
  pour changer l'image ou les réglages, la supprimer et la recréer ; elle n'est pas dupliquée ni enregistrée
  dans un modèle de parcours.
- **Temps estimé** : profil trapézoïdal par segment, vitesse en virage selon la *junction deviation* de GRBL
  (0,01 mm) et planificateur à anticipation complète (GRBL n'anticipe que 16 blocs : sur des milliers de
  segments très courts, la machine peut être plus lente que l'estimation). Une seule accélération pour tous
  les axes ; temps de changement d'outil, de mise en route de la broche et de pause non comptés. Accélération
  inconnue : 500 mm/s² supposés ; rapides : avance maximale XY du profil, sinon 3000 mm/min supposés (écrit
  sur la fiche).
- **Fiche PDF** : produite depuis l'interface seulement (Qt `QPdfWriter` exige une application graphique) ;
  mise en page simple (texte et tableaux de la fiche Markdown), sans image de la pièce.

