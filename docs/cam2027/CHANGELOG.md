# CAM2027 — Historique

## Non publié

- **[B4]** Correctif : **temps d'usinage des opérations rotatives** (G93, temps inverse) faux. L'estimation lisait
  l'avance d'un mouvement G93 (inverse de sa durée) comme une vitesse en mm/s sur la seule longueur X Y Z : rotation
  pure comptée 0 s, autres mouvements faux (11,0 s estimées au lieu de 4,0 s sur le cas d'essai). Chaque mouvement
  G93 compte maintenant pour 1 / F (sans modèle d'accélération) ; test `test_jour3_b4.TestTiming`.
- **[B4]** Correctif : **zones interdites ignorées par les motifs et par « Limiter à une zone »**. Seuls les rapides
  des opérations étaient relevés ; les copies d'un motif (rapides de l'original déplacés) et les liaisons recalculées
  d'une découpe (à la hauteur de dégagement) traversaient une zone plus haute (cas d'essai : rapide à Z 16 dans une
  zone de 30 mm). Les deux habillages relèvent maintenant leurs rapides comme les opérations (rayon de l'outil de
  l'opération de base). La reprise de matière (`rest.py`, même moteur de découpe) n'est pas encore corrigée.
- **[B4]** **Palpage d'un coin intérieur** (poche, butée de montage) : Usiner > Palper l'origine, « coin intérieur »,
  palpeur descendu dans la poche à 10 mm des deux parois ; X puis Y palpés vers les parois (rayon de la bille
  compté), Z non touché, retour au point de départ. Test : programme exécuté par un GRBL simulé contre les parois
  d'une poche, origine exacte aux 4 coins en G10 L20 et en G92 (le coin extérieur, vérifié de la même façon, est
  exact aussi).
- **[B4]** **Finition 3D rotative en spirale** : choix « Motif » du dialogue Usinage rotatif (lignes le long de l'axe
  ou spirale). A tourne sans arrêt pendant que X avance d'un pas par tour (un tour à X constant à chaque bout) :
  une seule passe continue, sans les remontées de fin de ligne ; niveaux d'ébauche parcourus dans un sens puis dans
  l'autre (A ne revient pas en arrière). Refusée avec un message si la course de l'axe A du profil machine ne
  contient pas tous les tours. Test : carte radiale = pièce à ± 0,05 mm, aucune entaille, A croissant, vitesse
  réelle = avance à 2 %, export sans erreur.
- **[B4]** Correctif : **perçage intelligent limité au premier corps du job**. Le dialogue ne cherchait les trous
  que dans `Model.Group[0]` : sur une pièce en plusieurs corps (le chauffage Vz330 de l'utilisateur en a deux),
  les trous des autres corps étaient ignorés sans message. Les trous de tous les corps sont trouvés
  (`holes.find_job_holes`) et chaque opération prend les faces de chaque trou sur son propre corps ; le départ au-dessus
  du brut de l'alésage hélicoïdal vérifie la colonne du trou dans tous les corps.
- **[B4]** Correctif : **entaille de la finition à crête constante (`scallop`) au bord des parois verticales**
  (0,053 mm sur l'ER16 de l'utilisateur, non analysée cette nuit). Ce n'était pas une fausse alerte du contrôle :
  deux points voisins d'une passe (0,1 mm en XY) sont l'un sur l'arête de la paroi (boule posée sur le bord),
  l'autre 16 mm plus bas au pied de la paroi, et la droite qui les relie entre dans l'arête. Une coupe plus raide
  que 2/1 dont le milieu passe sous la hauteur OpenCamLib devient une marche (palier à la plus haute des deux
  hauteurs, puis verticale ; un seul lot OpenCamLib pour toutes). Test : marche de 10 mm, pénétration exacte de la
  boule 0,0125 mm avant, < 0,005 mm après.
- **[B4]** Correctif : **entaille de la finition 3D rotative au bord des parois plus profondes que le rayon de la
  boule** (gorge, poche, épaulement). Même défaut que `scallop` : deux points voisins d'une ligne (0,25 mm) sont l'un
  sur l'arête, l'autre au fond, et la droite qui les relie entre dans l'arête : **0,26 mm** mesurés sur une gorge de
  6 mm avec la boule de 6 (le test de la nuit ne regardait la carte radiale que loin des parois, sur une poche de
  2 mm). Deux points voisins plus écartés en hauteur que 2 fois leur distance sont maintenant reliés par une marche
  (palier à la plus haute des deux hauteurs, puis montée ou descente seule), en lignes comme en spirale.
- **[B4]** Correctif : **finition à crête constante (`scallop`) refusée sur les grandes pièces** (plateau 220 × 220 mm
  de l'utilisateur : « 4 840 801 points de surface, augmentez l'intervalle d'échantillonnage »). La grille ne porte
  que la distance le long de la surface (chaque point des passes est recalculé par OpenCamLib à l'intervalle
  demandé) : au-delà de 4 millions de points, elle grossit jusqu'à pas / 4 au lieu de refuser (correctif préparé
  par S4 cette nuit, non vérifié alors).
- **[B4]** Correctif : **finition des plats à travers un corps posé dessus** (pièce en plusieurs corps). Un plat n'était
  jugé accessible qu'au regard de son propre corps : le dessus d'un corps sous un autre était fini en entier,
  à travers l'autre corps (entaille de **5 mm** sur le chauffage Vz330 de l'utilisateur, 10 mm sur le cas d'essai).
  Les plats de chaque corps sont maintenant privés de l'empreinte, vue de dessus, des autres corps au-dessus d'eux
  (sections aux hauteurs des sommets), puis réduits du rayon de la fraise comme avant.
- **[B4]** Correctif : **perçage intelligent sous un autre corps**. Un trou d'un corps couvert par un autre corps posé
  dessus était proposé : le foret traversait le corps du dessus. Ces trous sont écartés, avec un message dans le
  dialogue (« N trou(s) sous un autre corps de la pièce laissé(s) de côté »).
- **[B4]** Optimisation : **ordre des passes de `scallop`** par un arbre des points de départ (même règle et mêmes
  égalités que la recherche exhaustive d'avant, comparées dans un test). ER16 : 17,0 s → 0,23 s pour l'ordre (calcul
  complet 42–50 s → 25–29 s, mêmes 536 205 commandes, même volume enlevé), disque : 1,7 s → 0,04 s ; ordre identique sur les deux. Sur le plateau (34 000 passes)
  l'ancien ordre ne finissait pas en 25 minutes.
- **[B4]** Garde-fou : **finition à crête constante refusée au-delà de 2,5 millions de points de parcours**, avec un
  message qui dit quoi changer (crête, intervalle, zone). Mesuré : chauffage Vz330 2,2 millions de commandes, calcul
  143 s, sous 6 Go ; plateau 220 × 220 mm à 0,02 mm de crête 4,3 millions, **8,6 Go à 86 s** (arrêté) — refusé
  maintenant après 38 s. Avec la grande grille et l'ordre des passes ci-dessus, le chauffage, qui ne donnait aucun
  résultat cette nuit (plus de 25 min), est calculé.
- **[B4]** Correctif : **le cylindre extérieur d'un tube (entretoise) reconnu comme un trou** par le perçage
  intelligent. Le test « centre vide » tombait dans l'alésage du tube : l'alésage hélicoïdal Ø10 usinait
  l'entretoise (entaille de 2,3 mm sur les quatre entretoises du chauffage Vz330 de l'utilisateur). La matière est
  maintenant cherchée aussi juste à l'intérieur du rayon (8 points à 0,95 R) : seul l'alésage du tube reste un trou.
- **[S1]** **Limiter à une zone** (découpe de parcours sans recalcul, Fusion « Toolpath trimming ») : onglet
  « Reprise et zone » de l'éditeur, rectangle ou contour fermé sélectionné, garder dedans ou dehors
  (`project/trim.py`, habillage CAM2027). Les mouvements de coupe sont échantillonnés et coupés au bord (dichotomie),
  les arcs entièrement gardés restent des arcs, les rapides d'origine sont gardés entre deux morceaux continus ;
  ailleurs remontée à la hauteur de dégagement, rapide, descente à la hauteur de sécurité, plongée en avance
  verticale. `Path.Dressup.Boundary` de FreeCAD (booléens avec un solide, différent entre 1.0 et 1.1) n'est pas
  utilisé. Contour de la plaque coupé par un rectangle : aucune coupe au-delà du bord (coupé pile au bord),
  aucun rapide en XY sous la hauteur de sécurité, complément exact en « garder dehors », opération non recalculée.
- **[S1]** **Reprise des angles** (stratégie `pencil`, Fusion « Pencil », fraise boule) : angles intérieurs où une
  boule de référence (diamètre de la finition précédente, 3 fois l'outil par défaut) ne descend pas et où la
  boule de reprise descend plus bas (`project/pencil.py` : carte de hauteur fine de la pièce, profils de boule par
  `scipy.ndimage`, passes = courbes de niveau de la distance au bord de la zone par `contourpy`, hauteurs exactes
  par OpenCamLib sur la pièce triangulée). Pas mesuré le long de la surface (réduit du cosinus de la pente) : une
  boule ne touche un congé qu'en un point, et un pas constant en XY laissait 307 mm³ sur la partie raide des
  congés. Poche à congés R2 finie à la boule Ø8 puis reprise boule Ø2 : matière dans les congés 626 -> 20 mm³
  (-97 %), aucune entaille, 3,5 s ; plateau de test (angles vifs, boule Ø6) : 72 passes, aucune entaille.
- **[S1]** **Finition des zones plates** (stratégie `flat3d`, Fusion « Flat », type Offset, plusieurs
  profondeurs) : faces planes horizontales accessibles par le dessus (dessus de la pièce, fonds de poche dégagés)
  trouvées seules, regroupées par hauteur, une série de passes décalées par hauteur à la hauteur exacte du plat,
  fraise contenue dans la zone, surépaisseurs 0 par défaut (`project/flatfinish.py`, opération Python dérivée de
  `Path.Op.Base`). Les décalages d'OpenCascade étant faux sur les fonds percés à bords B-spline (fond hexagonal
  du disque WobbleRing : 54,9 mm² « réduit » depuis 26,5), contours discrétisés, chaque contour décalé seul et
  résultat refusé s'il sort de la face. Disque WobbleRing, fraise Ø1 : dessus, rainures et logements finis à
  0,00 mm sur la carte de hauteur (grille 0,1 mm, 70 208 / 7 104 / 9 559 colonnes), aucune entaille, calcul
  2,8 s ; Ø2 : logements (anneau de 1,1 mm) signalés trop étroits. Dôme sans plat : rien à faire, refus clair.
- **[S1]** **Reprise de matière depuis les opérations précédentes** (Fusion « Rest machining », source « From
  previous operation(s) », « Ignore stock less than » 0,1 mm par défaut) sur ébauche 3D, adaptative, poche et
  poche 2D : onglet « Reprise et zone » de l'éditeur d'opération. Le brut de départ est la carte de hauteur
  simulée des opérations actives placées avant (`project/rest.py`, `sim.simulate_paths`) ; l'opération est
  calculée normalement, puis un habillage CAM2027 ne garde que les coupes où la fraise rencontre plus de
  « Ignorer moins de » de matière, liaisons recalculées (`project/trim.py`). Disque WobbleRing, ébauche 3D
  Ø6 puis reprise Ø3 : 828 mm³ repris = 7,3 % des 11 327 mm³ de l'ébauche (reprise complète : 828 mm³ aussi),
  1 314 mm de coupe gardés sur 17 431, aucune entaille, aucun rapide dans la matière, 0,5 s de calcul de la
  reprise (rapport affiché dans l'onglet). Plaque à rainure étroite : 220 points de coupe gardés sur 3 380,
  même volume enlevé que la reprise complète.
- **[S2]** **Palper l'origine** (Fusion *Probe WCS*) : Usiner > Palper l'origine ajoute en tête du programme une
  opération de palpage GRBL : surface Z, coin (avant/arrière, gauche/droite : Z, puis X et Y par l'extérieur) ou
  centre de trou (un contact par axe et le diamètre nominal : GRBL n'a pas de variables pour faire la moyenne de
  deux contacts). Déplacements relatifs (G91) tant que l'axe n'est pas connu, `G38.2` avec avance et course,
  origine fixée par `G10 L20 P1..P6` (repère G54..G59 enregistré) ou `G92`, en tenant compte du rayon de la
  bille et de l'épaisseur de la plaque de touche, broche arrêtée (M5). Réglages du palpeur dans le profil
  machine (`probe` : présence, diamètre de bille, plaque, avance, course, numéro d'outil), saisis dans le
  dialogue ; le palpeur apparaît comme un outil dans la fiche. `export.verify` refuse un palpage sur un profil
  sans palpeur, broche en marche, sans avance, ou un `G10` sans L2/L20 et P1..P6, et signale une course plus
  longue que celle du palpeur ; le contrôle matière ne simule pas le palpage. G-code vérifié ligne à ligne en
  test, après le postprocesseur GRBL.
- **[S2]** **Perçage intelligent** (Fusion *Hole Recognition*) : Usiner > Perçage intelligent reconnaît les
  trous verticaux ouverts par le dessus (faces cylindriques regroupées par axe et rayon, tour complet, centre
  vide : diamètre, haut, fond, débouchant ou borgne, chanfrein d'entrée = cône coaxial) et les regroupe par
  taille. Séquence proposée, une opération par étape et par taille, dans l'ordre pointage → perçage → chanfrein →
  filetage : pointage à l'outil en V à 90° (diamètre 0,9 × trou), foret au diamètre à 0,02 mm (G83 au-delà de
  3 D, pas = D ; débouchant : pointe entière sous le fond + 0,5 mm ; borgne : pointe au fond) ou, sans foret,
  alésage hélicoïdal à la plus grosse fraise qui passe, chanfrein par plongée d'un outil en V du même angle
  jusqu'au diamètre du chanfrein, filetage à la fraise à fileter si un filet est choisi pour la taille. Les
  trous sans outil sont signalés. Un alésage hélicoïdal sous le dessus du brut commence au-dessus du brut
  quand la colonne du trou ne contient que du brut (l'hélice de FreeCAD descend sinon en rapide dans le brut
  restant : 10 rapides dans la matière sur le disque WobbleRing, 36 sur le chauffage, 0 maintenant). Un lamage
  posé sur un trou plus petit a un fond (pas « débouchant », vu sur le chauffage). Le contrôle matière simule maintenant les cycles de perçage (G73/G81/G82/G83,
  G98/G99) : ils n'enlevaient rien avant. Plaque de test à 3 diamètres (3 débouchant, 5 borgne, 8 débouchant
  chanfreiné) : 7 opérations, trous au bon diamètre et à la bonne profondeur dans la carte de hauteur, chanfrein
  à 45° à 0,05 mm, aucune entaille.
- **[S2]** **Motifs de parcours** (Aspire *Array Copy Toolpath*, Fusion *Pattern*) : Usiner > Motif copie le
  parcours calculé d'une ou plusieurs opérations en grille (colonnes, lignes, distance entre colonnes / lignes,
  ordre en serpentin) ou en cercle (nombre de copies, centre, angle total ; 360° = tour complet sans doublon).
  Habillage CAM2027 `<op>_DressupPattern` (`project/patterns.py`, même principe que `Path.Dressup.Array` de
  FreeCAD 1.1 : chaque copie transformée par `PathUtils.applyPlacementToPath`, arcs compris), disponible aussi
  sur 1.0 (FreeCAD 1.0 n'a pas cet habillage), toujours au-dessus des autres habillages, remontée à la hauteur de
  dégagement entre deux copies. Plusieurs opérations : « Moins de changements d'outil » (coché par défaut, comme
  Aspire) regroupe les opérations par outil. Plaque de test, poche 20 × 14 répétée 3 × 2 : les 6 poches au fond
  dans la carte de hauteur, rien entre elles, volume = 6 × celui de la poche, aucune entaille, un seul
  changement d'outil dans le G-code ; trois opérations 6 / 3 / 6 mm : ordre 6, 6, 3 (1 changement au lieu de 2).
- **[S2]** **Entrées et sorties en arc** (Fusion : rayon horizontal, angle de balayage, arc vertical) : nouvelle
  case « Entrée et sortie » dans l'onglet « Entrée, sortie et attaches » des contours et rainures (et de la
  passe de profil d'une poche = contour intérieur sur le fond). Type d'entrée / de sortie (arc horizontal, arc
  vertical, droite tangente ou perpendiculaire), rayon, angle de balayage. Habillage `LeadInOut` de FreeCAD,
  encapsulé dans `project/leads.py` (propriétés 1.1 `StyleIn/RadiusIn/AngleIn`, traduites en `StyleOn/Length`
  sur 1.0 ; arc vertical et angle ≠ 90° demandent 1.1). Les entrées restent au-dessus des attaches et de la
  rampe. Contrôle des collisions : chaque mouvement ajouté est vérifié contre la carte de hauteur du dessus de
  la pièce sur la zone des entrées (aucune colonne plus haute que la pointe à moins d'un rayon d'outil ; 1,1 s
  sur le chauffage Vz330, 1 523 commandes) ; sur 1.1, le point de départ est déplacé le long
  du parcours avec recouvrement (`OffsetIn/OffsetOut`) tant qu'un arc toucherait la pièce, sinon refus avec la
  position. La poche en zigzag n'en a pas (arcs dans les parois : entaille de 4,2 mm mesurée). Plaque de test,
  contour R3 : premier mouvement de coupe = arc de R3 tangent au contour à chaque passe, aucune entaille.
- **[S3]** **Comparer et modifier plusieurs opérations** (Usiner > Comparer et modifier des opérations, bouton du
  panneau Projet) : tableau dont les colonnes sont les opérations cochées et les lignes leurs paramètres communs
  (libellés de l'éditeur), lignes différentes en gras, filtre « Différences seulement » ; une valeur saisie dans la
  dernière colonne est écrite sur toutes (registre compris, comme depuis l'éditeur), puis les parcours sont
  recalculés ; une étape d'annulation. Test et scénario : hauteur de dégagement passée à 33 mm sur un contour, une
  adaptative et une poche d'un coup.

- **[S3]** **Imbrication par forme réelle** (défaut de Préparer > Imbriquer) : silhouette de chaque dessin (contours
  extérieurs, trous bouchés) décalée de la moitié de l'espacement (`Part.makeOffset2D`), rotations par pas de 15°
  (ou 90°), grille prudente (toute cellule touchée par la silhouette est occupée) et positions libres trouvées par
  corrélation FFT (numpy) ; la pièce va là où son dessus est le plus bas. Plusieurs panneaux (posés à droite du
  premier, le job prend le premier). Les rectangles englobants restent au choix (« rapide »). Test : 20 pièces en L
  sur 300 × 300 : 20 posées (utilisation 44,4 %) contre 16 en rectangles (35,6 %), soit +25 %, en 5 s, aucune
  silhouette à moins de 5 mm d'une autre.

- **[S3]** **Zones interdites** (« keep-out zones » d'Aspire 12) : Préparer > Zones interdites dessine des boîtes
  (vue de dessus + Z du dessus) ; option « les rapides évitent aussi les brides ». À la fin du calcul de chaque
  opération, un rapide qui passerait au-dessus d'une zone plus bas que son dessus + marge (2 mm par défaut, outil
  compris vu de dessus) monte, traverse et redescend ; le premier déplacement d'une opération (départ inconnu)
  passe au-dessus de toutes les zones. Les coupes ne sont jamais modifiées : une coupe qui entre dans une zone est
  une erreur bloquante à l'export (opération, n° de commande, position). Les zones comptent comme des brides au
  contrôle de collision. Test : bride entre deux poches, rapides au travers avant, aucun après, coupes identiques,
  contrôle des brides « OK ».

- **[S3]** **Usinage recto-verso** (comme le « Double Sided » d'Aspire) : Préparer > Usinage recto-verso crée la
  face B, pièce retournée de 180° autour de X ou de Y par le centre du brut (même brut, même repère G54), dans un
  second job du document ; boutons « Face A / Face B » dans le panneau Projet (ajout, recalcul, aperçu et export
  portent sur la face affichée). Repérage « même coin » ou **goujons** : deux trous percés depuis la face A sur
  l'axe de retournement, à travers le brut et dans le martyr (opération placée en tête de la face A, positions
  par défaut dans la marge, refus hors de l'axe, hors du brut ou dans la pièce). Contrôle matière **enchaîné** : la
  carte de hauteur de la face A retournée sert de brut à la face B. Export : un fichier et une fiche par face
  (`-A.nc`, `-B.nc`), fiche complétée par le retournement, les goujons et l'ordre. Test : plaque à une poche
  ronde de chaque côté, aucune entaille, dessus et dessous finals = pièce à 0,05 mm hors du pied des parois.

- **[S5]** **Prisme** (Aspire « Prism ») : Usiner > Prisme biseaute au V-bit un vecteur fermé depuis son contour
  (profondeur au contour, pente du flanc vers l'intérieur : crête là où les biseaux se rejoignent, dessus plat
  sinon). La pointe suit les décalages intérieurs (angles vifs) à `z = −p + s / tan(α/2)`, plat de pointe
  compris : le flanc du V-bit est exactement le biseau. Rectangle 40 × 20, V-bit 90°, 3 mm : biseau à
  0,05 mm sur la carte simulée, aucune entaille ; profondeur au-delà de la longueur coupante refusée.
- **[S5]** **Texture** (Aspire « Texture Toolpath ») : Usiner > Texture remplit un vecteur fermé de coups de
  gouge courts en rangées décalées (boule ou V-bit), longueur et profondeur tirées au hasard autour des valeurs
  (numéro de motif = graine : même texture à chaque calcul), chaque coup plongeant en arc ; près du bord, un
  coup est coupé là où la fraise ne resterait plus entière dans la zone. Disque R18 au V-bit 60° : rien coupé
  hors du disque (carte simulée à 0,1 mm), jamais plus profond que la profondeur maximale tirée.
- **[S5]** **Moulure et cannelures** (Aspire « Moulding » et « Fluting ») : Usiner > Moulure balaie à la fraise
  boule une section (quart-de-rond, gorge, chanfrein, doucine ; largeur, profondeur, côté) le long d'un vecteur
  du dessin, en passes parallèles au rail au pas latéral demandé, paliers d'ébauche en option ; la hauteur de
  chaque passe est calculée en 2D comme une boule posée sur la section (jamais dessous), la boule débordant
  d'un rayon côté bord pour finir le flanc raide. Usiner > Cannelures suit des vecteurs avec rampes de
  profondeur au début et à la fin (boule ou V-bit). Opérations `Path.Op.Custom` simulées par le contrôle
  matière : quart-de-rond R10 à la boule de 6 mm, section à 0,014 mm sur la carte de hauteur (hors congé de
  pied de R3), aucune entaille.
- **[S5]** **Temps d'usinage avec l'accélération et fiche de préparation en PDF** : nouveau champ
  « Accélération (mm/s²) » du profil machine ; le temps estimé (fiche, section « Estimated machining time »,
  par opération et total) suit un profil de vitesse trapézoïdal par segment avec la limite de vitesse en
  virage du planificateur de GRBL (*junction deviation* 0,01 mm) et un passage avant / arrière. Accélération
  inconnue : 500 mm/s² supposés ; rapides à l'avance maximale XY, sinon 3000 mm/min supposés ; les
  suppositions sont écrites sur la fiche. Exporter > Fiche de préparation (PDF) écrit la fiche en PDF A4
  (`QTextDocument` + `QPdfWriter` de Qt, sans dépendance). Planificateur vectorisé (passes avant / arrière
  en minimums cumulés, identiques à la boucle) : 0,74 s pour 200 000 commandes ; export du plateau
  `bitTray3030+v7.stl` (finition 3D, 69 000 commandes) : 1,96 → 2,14 s (+9 %), estimation 58 min 19 s.
- **[S5]** **Vectorisation d'image et Photo V-Carve** (comme Aspire « Trace Bitmap » et « Photo V-Carving ») :
  Dessin > Vectoriser une image seuille l'image en niveaux de gris (seuil, inversion, tolérance du contour,
  taches ignorées) par *marching squares* au sous-pixel, chaîne les contours fermés (trous gardés) et les
  simplifie (Douglas-Peucker) : un vecteur du dessin, usinable en poche, contour ou V-carving. `potrace`
  n'existe pas dans FreeCAD : contours polygonaux. Usiner > Photo V-Carve grave une photo au V-bit en lignes
  horizontales aller-retour, profondeur = profondeur maximale × sombre (gamma réglable), écart entre lignes
  par défaut = largeur du V-bit à la profondeur maximale ; les zones plus claires que 0,05 mm de profondeur
  sont sautées. Opération `Path.Op.Custom` (avances converties en mm/s comme la gravure enroulée), simulée
  par le contrôle matière.
- **[S5]** **Dessin vectoriel dans l'atelier** (menu et barre d'outils Dessin, dialogues CAM2027, comme les
  outils de dessin d'Aspire) : texte (police TrueType, hauteur, espacement) en ligne droite, sur un arc ou le
  long d'un vecteur ; décalage d'un vecteur fermé (angles ronds ou vifs, formes qui se recouvrent soudées) ;
  union, soustraction, intersection de deux vecteurs ; miroir ; copies circulaires. Géométrie Part de FreeCAD
  (`makeWireString`, moteur de `Draft.ShapeString` ; `makeOffset2D`, moteur de `Draft.make_offset` ;
  booléens Part sur des prismes de 1 mm, ceux des faces planes découpant sans réunir). Les contours de police
  sont des polygones à 0,01 mm (les B-splines des glyphes faisaient échouer le décalage OCC). Un vecteur
  dessiné après le panneau reçoit sa face et ses clones dans le modèle du job. La poche 2D, le V-carving et
  les autres stratégies à faces prennent maintenant **toutes** les faces d'un vecteur (un texte importé ou
  dessiné n'était usiné que sur sa première lettre).
- **[S5]** **Modèles de parcours** (Aspire « Toolpath Templates ») : Usiner > Enregistrer un modèle de parcours
  écrit les opérations du projet 2D (stratégie, outil par nom, préréglage par nom, réglages, calque et nom du
  vecteur ciblé) dans un fichier `.cam2027template` ; Usiner > Appliquer un modèle de parcours les recrée sur
  un autre dessin : vecteurs du même calque (calque Inkscape ou groupe SVG, calque DXF), sinon du même nom,
  puis calcul. Une opération sans cible ou sans outil est rapportée et non créée. Les calques SVG sont lus à
  l'import (propriété `CAM2027Layer` des vecteurs).
- **[S4]** **Projeter sur la pièce** (Usiner > Projeter sur la pièce, `project/projection.py`, comme Fusion
  « Project ») : une gravure, un contour ou un V-carving calculés à plat sont reportés sur la surface 3D,
  chaque point de coupe à `S(x, y) - (Zref - z)` (surface lue par OpenCamLib sous l'axe de l'outil, `Zref` =
  profondeur de départ de l'opération : la profondeur demandée, variable en V-carving, est gardée sous la
  surface) ; pas réduit là où la surface s'écarte de la corde de plus de 0,005 mm ; rapides au-dessus du
  point le plus haut de la pièce. Habillage qui remplace l'opération dans le job, retiré par le même
  dialogue. Texte « S4 » gravé à 0,5 mm au V-bit 90° sur le dôme : chaque point à 0,5 mm sous la surface
  (± 0,01), profondeur mesurée sur la carte de hauteur 0,499 à 0,522 mm le long de tout le texte, rien
  d'enlevé hors de la portée du V-bit.
- **[S4]** **Usinage rotatif continu** (Usiner > Usinage rotatif, `project/rotary.py`) : contour et poche
  enroulés d'un dessin déroulé, la compensation du rayon d'outil faite au rayon de chaque niveau (dessin
  ramené au plan réel `Y × r / R`, décalé, puis redéroulé), et finition 3D rotative comme Fusion « Rotary
  parallel » : une ligne le long de l'axe par angle, pièce tournée à cet angle et hauteur de la pointe par
  OpenCamLib (fraise pointée vers l'axe), niveaux d'ébauche radiaux optionnels. X, Z et A simultanés en G93
  (avance réelle au rayon de coupe), aperçu 3D du trajet réel. Cylindre R20 avec une poche (fond R18) et une
  bosse sphérique, brut R21, boule 6 puis plate 3 : carte radiale déroulée simulée = pièce à ± 0,05 mm (fond
  de poche, cylindre, bosse), aucune entaille, vitesse réelle = avance à 2 %, export vérifié sans erreur ;
  finition 3D 6,7 s, poche 0,2 s.
- **[S4]** **Finition 3D à crête constante, pentu / peu incliné** (stratégie `scallop`, comme Fusion
  « Scallop » et « Steep and Shallow ») : « Hauteur de crête maximale » -> pas 3D déduit du rayon de la boule
  (`2 sqrt(h (2R - h))`, plus la partie plate d'une torique) ; hauteurs de la pointe par OpenCamLib
  (`BatchDropCutter`, comme `surface3d`) sur une grille, passes = courbes de niveau de la distance
  géodésique depuis la limite le long de la surface du centre de l'outil (décalages successifs, pas 3D
  constant), passes ajoutées sur les lignes de crête restées à plus d'un demi-pas, chaque point final
  recalculé par OpenCamLib (aucune hauteur interpolée), liaisons courtes le long de la surface. Mode pentu /
  peu incliné : Z constant au-dessus de l'angle limite (défaut 45°, pas vertical `s sin(angle)`), crête
  constante en dessous, dans la même opération. Dôme, boule 6 mm, crête 0,02 mm : crête mesurée (carte de
  hauteur à 0,05 mm, normale à la sphère) 0,017-0,018 mm sur le dôme, 0,020 mm sur le plat, aucune entaille,
  7,2 s (finition 3D de FreeCAD aux réglages par défaut : 6,4 s). Utilise `scipy` et `contourpy`, fournis
  avec FreeCAD 1.0 et 1.1.
- **Poches à plusieurs profondeurs, chacune jusqu'à son fond** (comme Fusion) : FreeCAD usine des fonds
  sélectionnés ensemble jusqu'au plus haut d'entre eux ; sur le disque WobbleRing, les logements d'écrou
  (141,57) restaient à la hauteur des rainures (142,58). Poche, poche 2D et adaptative : une opération par
  hauteur de fond (« Poche 2D 1 (Z 141.57 mm) »...). Le fond le plus bas comme profondeur finale faisait
  descendre FreeCAD partout (entailles de 1 mm sur le disque, 40 mm sur le chauffage, trouvées par la
  matrice). La poche 2D trouve maintenant les fonds seule, comme la poche. Un fond percé d'un trou
  débouchant est usiné par son contour extérieur (`UseOutline`, le trou reste ouvert : l'anneau de 1,1 mm
  autour du trou n'accepte pas une fraise de 3 mm), jamais quand un îlot de matière y dépasse. Une profondeur
  où la fraise ne passe pas est signalée (« Laissé de côté... »). Un îlot est cherché dans toute la colonne
  au-dessus du trou (un îlot en anneau, vide en son centre, donnait une entaille de 1,6 mm sur le chauffage).
  Disque, fraise de 3 mm : poche 0,21 -> 0,68 cm³, poche 2D refusée -> 0,69 cm³, adaptative 0,15 -> 0,69 cm³ ;
  disque, chauffage, plaque, plateau : aucune entaille.
- **Reste après l'ébauche 3D** (3,2 mm signalé sur le disque) : pas un défaut. Bande de 0,5 mm de
  surépaisseur latérale le long des parois des logements (le contrôle la compte à la hauteur de la paroi),
  rainures de 3,1 mm plus étroites que fraise + surépaisseur, coins des hexagones. Surépaisseurs à 0 : cellules
  à plus de 1 mm 1 262 -> 385 (rainures). Essayé et non gardé : un niveau de plus à la hauteur de chaque face
  plane (« zones plates » de Fusion) : reste moyen 0,658 -> 0,657 mm, calcul 17 s -> 266 s, entaille de 1,7 mm
  (coupe juste au-dessus d'un plat, projection fausse).
- **Ébauche 3D sur une pièce aux nombreuses petites faces** (disque WobbleRing de l'utilisateur, STEP de
  181 faces) : « aucun parcours sur la pièce entière ». Quatre défauts de FreeCAD/OpenCascade, l'un après
  l'autre : projection des faces sur XY en échec (« Wire is not closed », même face par face), contour d'une
  lamelle d'aire nulle introuvable (« EdgeWalker has no edges »), discrétisation d'un fil ouvert qui plante
  (« Access violation »), et une poche aux fils mal orientés dont le « trou » était le bossage voisin :
  l'adaptative vidait le bossage (entaille de 1,5 mm trouvée par le contrôle matière). Corrigé : ombre de
  secours d'une face (polygone de son bord si elle est plane, sinon sa triangulation à 0,01 mm), contour de
  secours, discrétisation arête par arête, poches nettoyées (une face dont l'aire n'est pas « contour moins
  trous » ne garde que son plus petit contour : au pire de la matière reste, jamais d'entaille). Pièce
  entière : 15 000 commandes, 9,0 cm³, aucune entaille, 11 s.
- **Poche trop étroite pour la fraise** : la poche, la poche 2D et l'adaptative sur la pièce entière
  disaient « sélectionnez les faces » ; elles disent maintenant que la fraise est trop grande et la plus
  grande qui passe (5,7 mm sur les logements d'écrou du disque, fraise de 6 mm proposée).
- **Annuler / Rétablir (Ctrl+Z, Ctrl+Y)** : « Annuler » restait grisé, CAM2027 n'ouvrait aucune transaction
  FreeCAD. Chaque action est maintenant une étape d'annulation : import, brut et montage, ajout d'une
  opération, modification dans l'éditeur, activer/désactiver, déplacer, dupliquer, supprimer, fond plat,
  incrustation, gravure enroulée, imbrication, profil machine. Piège de FreeCAD trouvé au passage : la forme
  d'un ToolBit est copiée d'un document temporaire aussitôt fermé ; dans l'interface, les objets créés ensuite
  dans la même transaction n'étaient plus enregistrés (l'opération et son ToolController restaient après
  « Annuler »). La fermeture de ce document attend la fin de la transaction. Un ajout annulé dans l'éditeur
  ne laisse pas d'étape ; « OK » sans modification non plus. Après Annuler, les opérations rétablies restent
  « calculées » (parcours rétablis avec elles) et la liste suit.
- **Surfaçage avec une fraise à surfacer, y compris sur un STL** : le surfaçage refusait la pièce issue d'un
  maillage (« surface 3D », fichier ER16 de l'utilisateur) et proposait une fraise droite. Il usine maintenant
  le dessus du brut jusqu'au haut de la pièce (limite = brut) quand il n'y a pas de face plane du dessus, et la
  pièce entière sélectionnée vaut sans sélection. Types d'outils par stratégie revus d'après l'usage Fusion :
  surfaçage -> fraise à surfacer d'abord (puis fraise droite, torique) ; perçage -> foret (fraise droite
  admise) ; finition 3D -> boule, torique, boule conique, droite ; ébauche 3D -> droite, torique, boule ;
  chanfrein -> fraise à chanfreiner, V-bit, gravure. Au changement de stratégie, l'outil le plus adapté est
  repris (sauf outil choisi par l'utilisateur et compatible).
- **Choix de l'outil comme Fusion** : plus d'« assemblage d'outil » dans l'interface. Dans une opération (ajout,
  éditeur, fond plat, incrustation, gravure enroulée) : « Outil [Sélectionner…] [Éditer…] » et la liste des
  outils déjà utilisés dans le document. « Sélectionner… » ouvre la bibliothèque : tableau (#n - Ø, nom, type,
  rayon de bout, diamètre, longueur de dent), recherche, type, « seulement les outils adaptés à la stratégie »,
  aperçu dynamique et « Nouvel outil… » (type, diamètre, corps, dents, longueurs, rayon, angle, avec aperçu).
  « Éditer… » ouvre l'outil dans la bibliothèque, dont l'onglet « Assemblage » devient « Porte-outil »
  (porte-outil, longueur sous le porte-outil, numéro). En interne chaque outil garde un jeu porte-outil +
  sortie créé automatiquement (contrôle des collisions, numéro d'outil).
- **Une fraise créée dans la bibliothèque est proposée tout de suite** : elle n'apparaissait pas dans
  « Ajouter une opération » (fraise à surfacer de l'utilisateur), pour deux raisons. Une fraise neuve n'avait
  ni préréglage de coupe ni assemblage : elle en reçoit un par défaut (12 000 tr/min, 600 mm/min, à ajuster ;
  numéro libre, premier porte-outil). Et un projet travaille sur une copie de la bibliothèque figée à sa
  création : les outils ajoutés depuis y sont maintenant **ajoutés** à l'ouverture du dialogue (les outils
  déjà présents et les opérations existantes ne changent pas ; un outil identique sous un autre identifiant
  n'est pas dupliqué).
- **Aperçu d'outil dynamique, comme Fusion** : la silhouette (fraise à surfacer large sur un corps fin, V-bit,
  boule...) se redessine à chaque saisie dans la fiche, à l'échelle, sans enregistrer ; cote du diamètre du
  corps (Ds) ; valeur incohérente signalée sous l'aperçu ; titre traduit. Fraise à surfacer : dépouille de 0°
  acceptée (elle était refusée, « demi-angle de cône requis »).
- **Toutes les poches vidées par l'ébauche 3D et l'adaptative** : l'hélice d'entrée de FreeCAD (environ 3/4 de
  la fraise) ne tenait pas dans une poche étroite et la région était sautée (36 alvéoles de 14 x 11,2 mm
  laissées pleines sur le plateau, comparé à Fusion qui entre en hélice dans chacune). Hélice comme Fusion :
  0,95 x le diamètre, puis deux fois plus petite région par région tant qu'elle ne tient pas (jusqu'à 10 % du
  diamètre). Plateau : 0 alvéole oubliée, 618 cm³ enlevés au lieu de 512, 13,6 s, 294 000 commandes (477 000
  avec une hélice fixe de 2 mm). Référence des stratégies de Fusion : notes de session
  `fusion-cam-reference.md` (Autodesk ne publie presque aucune valeur par défaut).
- **Liste des opérations lisible et réordonnable** : quatre colonnes (Opération, État, Outil, Temps) qui
  tiennent dans le dock, stratégie / commandes / Z en infobulle, opération inactive grisée, plus de barre
  bleue devant chaque cellule de la ligne choisie (elles semblaient se chevaucher). Ordre d'usinage par
  **glisser-déposer** des lignes ou **Alt+Haut / Alt+Bas**, en plus de Monter / Descendre.
- **Simulateur** : « Active task dialog found » quand un panneau de tâches était déjà ouvert (simulateur
  précédent, édition d'une opération FreeCAD). Le simulateur précédent est fermé ; un autre panneau n'est
  fermé qu'après confirmation.
- **Poche 3D sur tous les cœurs, interface qui répond** : sur le plateau à 135 alvéoles, la poche passait
  26 s dans les booléens d'OpenCascade, interface figée. La découpe de l'enveloppe des fonds par la pièce et
  les intersections avec les fonds (volume par volume) ainsi que la découpe en niveaux (`Path.Area`, niveau
  par niveau) sont faites dans des processus Python de FreeCAD (`parallel_pocket`) : 26 s -> 6 s, même
  volume à enlever, même parcours que le calcul en série, aucune entaille. Le cercle du plan de travail est
  refait dans chaque processus : relu en BREP, il changeait légèrement les niveaux.
- **Ébauche 3D sur tous les cœurs, interface qui répond** (demande de l'utilisateur : « le logiciel ne
  répond plus » pendant une ébauche 3D). Les régions de chaque niveau (ombre, silhouette, poches : booléens
  OpenCascade) sont préparées dans des processus Python de FreeCAD (`parallel_levels`, formes en BREP) et
  les adaptatives indépendantes des régions y sont calculées aussi (`parallel_adaptive`, le TODO de
  FreeCAD). Plateau 47 s -> 11,8 s, chauffage 52 s -> 19,7 s, mêmes résultats au contrôle matière.
  L'interface est rafraîchie toutes les 0,2 s pendant la préparation, l'attente des processus et la
  finition 3D : plus de « Ne répond pas », « Arrêter le calcul » arrête les processus. Une ombre « maison »
  plus rapide a été essayée puis retirée (entaille de 3,4 mm sur le chauffage, introuvable dans la
  projection de FreeCAD).
- **Fluidité et affichage** : statistiques de parcours mises en cache (le panneau Projet relisait deux fois
  chaque parcours de 350 000 commandes à chaque rafraîchissement) ; brut simulé affiché simplifié au-delà
  de 100 000 triangles (0,01 mm, 10 fois moins) ; gros STL affiché par son maillage, la surface 3D et son
  clone restent masqués (import du casse-noix dans l'interface : 43 s -> 21 s) ; accents des menus gardés quand
  FreeCAD reconstruit la barre (« PrÃ©parer ») ; étapes du panneau Projet sur deux lignes fixes avec « … »
  (elles se chevauchaient dans un dock étroit) ; onglet « Assemblage » de la bibliothèque d'outils (le
  libellé long était tronqué) ; nom de stratégie traduit dans les refus. 86 tests ; matrice de 75 cas
  (5 pièces, 15 stratégies) sans plantage, dépassement ni entaille ; scénarios utilisateur 3 fois de suite
  sans problème.
- **Finition 3D échantillonnée à 0,05 mm par défaut** (0,1 mm laissait 0,07 mm d'entaille sur le casse-noix).
  Mesuré : casse-noix 39,8 -> 43,3 s, sans entaille ; plateau 11,7 -> 18,6 s ; chauffage 35,6 -> 59,7 s ;
  plaque 1,1 -> 1,7 s ; aucune entaille sur ces pièces.
- **Entailles vérifiées en 3D** : la carte de hauteur transformait un contact latéral de 0,05 mm contre une
  paroi raide en entaille de toute la hauteur de la paroi (5,09 puis 1,85 mm signalés sur le casse-noix de
  l'utilisateur, export bloqué). Les colonnes signalées sont maintenant vérifiées sur la pièce triangulée
  (distance du point coupé à la surface, dedans / dehors par parité) et les colonnes du bord de la
  silhouette ne sont plus comptées. Casse-noix : 0,069 mm réels (0,070 mesurés indépendamment, boule-
  maillage) ; plaque à 0,5 mm d'échantillonnage : 0,25 mm réels, toujours bloquant. 85 tests.
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
