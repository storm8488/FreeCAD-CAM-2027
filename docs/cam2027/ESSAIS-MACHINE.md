# CAM2027 — Premiers essais sur la machine

Rien n'a encore été usiné avec CAM2027. Ce guide fait passer la LUNYEE 4040 (GRBL, pilotée par CNCjs) du
premier mouvement au recto-verso, un risque à la fois. Chaque essai prouve une chose, a son fichier `.nc`, sa
fiche (`FICHE.md`) avec les cotes à relever au pied à coulisse et la valeur attendue, et a déjà été passé dans un
interpréteur GRBL 1.1 (voir « Ce qui a été vérifié sans machine »).

Fichiers : `src/Mod/CAM2027/tests/machine_trials/output/<essai>/` (`<essai>.nc`, `FICHE.md`, fiche de
préparation CAM2027 `<essai>-setup.md`), résultat du simulateur dans `output/VALIDATION.md`.

## Matériel

- 2 planches de bois tendre (pin, épicéa, peuplier) **200 × 150 × 18 mm**, chants d'équerre, dessus plan ; une
  troisième de réserve.
- Fraises de la bibliothèque de démarrage : **T1** fraise plate Ø6 2 dents, **T3** fraise boule Ø6, **T5** V-bit
  60°. Une fraise par fichier : aucun changement d'outil en cours de programme.
- Palpeur 3D (essai 01) — sans palpeur, faire l'origine à la main et sauter l'essai 01.
- 2 goujons bois Ø6 × 30 mm (essai 09), 4 vis à tête fraisée Ø4 × 30, ruban adhésif double face.
- Pied à coulisse (becs extérieurs, intérieurs, jauge de profondeur), réglet, feuille de papier (≈ 0,1 mm).
- Martyr (plateau sacrifié) surfacé : le contour (08) descend 0,2 mm dedans, les goujons (09) 5 mm.

## Une seule fois, avant le premier essai

1. **Réglages GRBL** (`$$` dans la console CNCjs) : noter `$100`–`$102` (pas/mm), `$110`–`$112` (vitesses max),
   `$120`–`$122` (accélérations), `$130`–`$132` (courses), `$20` / `$21` / `$22` (limites logicielles,
   fins de course, prise d'origine), `$30` (vitesse broche max). Les reporter dans **Machine** du projet CAM2027
   (courses, avance max, plage de broche) : tant qu'ils manquent, les fiches disent « non vérifiable ».
   Les essais demandent jusqu'à **F1800** en X/Y et **S18000** : `$110`/`$111` ≥ 1800 et `$30` ≥ 18000, sinon
   corriger le préréglage plutôt que la machine.
2. **Sens des axes**, en avance lente au clavier de CNCjs : X+ = la fraise va vers la droite (vue de face), Y+ =
   elle s'éloigne de vous, Z+ = elle monte. Un sens inversé se corrige par `$3`, pas dans le G-code.
3. **Échelle** : `G91 G1 X100 F500` puis mesurer le déplacement au réglet (100,0 ± 0,2 mm) ; idem Y et Z (Z sur
   20 mm). Un écart proportionnel à la longueur vient des pas/mm (`$100`–`$102`).
4. **Broche** : `M3 S18000` doit tourner dans le sens horaire vu de dessus et monter à sa vitesse ; `M5` l'arrête.

## Montage et origine

- Planche 1 posée X = 200 (longueur) le long de l'axe X, chant avant parallèle à X (comparateur ou réglet contre
  le chant en déplaçant X : écart < 0,1 mm sur 200).
- Tenue : double face sur toute la surface **et** 4 vis fraisées, têtes 2 mm sous la surface. Planche 1 :
  **(5 ; 60)**, **(195 ; 50)**, **(100 ; 5)**, **(195 ; 145)** (repère de la planche, mm), à 7 mm au moins de
  tous les parcours des essais 01 à 08. Planche 2 : **(30 ; 20)**, **(30 ; 130)**, **(170 ; 20)**,
  **(170 ; 130)** — symétriques par rapport à Y 75 : les mêmes trous servent après le retournement. Aucune bride
  sur le dessus (les rapides passent à Z 5) et rien autour de la planche à moins de 10 mm (l'ébauche du dôme
  sort de 3,5 mm par le chant arrière, dans le vide).
- **Origine G54 = coin avant gauche du dessus de la planche** (X0 Y0 Z0) pour tous les fichiers. Avec le palpeur :
  essai 01. À la main : fraise au-dessus du coin, feuille de papier contre le chant gauche puis le chant avant
  (X0 / Y0 décalés du rayon de la fraise), puis sur le dessus (Z0) ; `G10 L20 P1 X… Y… Z…` ou les boutons
  « Zéro » de CNCjs.
- **Après chaque changement de fraise : refaire Z0 seulement** sur le dessus de la planche (papier ou plaque de
  touche) ; ne pas toucher X0 Y0.

## Avant chaque fichier

1. Charger le `.nc` dans CNCjs : l'aperçu doit tomber dans la zone indiquée par la fiche, et la plage X/Y/Z
   affichée correspondre à « Enveloppe des mouvements » de la fiche.
2. **Contrôle `$C`** (mode vérification de GRBL : tout le G-code est lu, aucun mouvement) : taper `$C`, lancer le
   fichier, attendre la fin — **aucun `error:`** —, puis `$C` à nouveau pour sortir (GRBL se réinitialise ; les
   décalages G54 restent).
3. **Marche à vide au-dessus de la pièce** : monter la fraise à **30 mm au-dessus du dessus** et y mettre un Z0
   provisoire (`G10 L20 P1 Z0`), lancer le fichier broche coupée (ou en l'air), vitesse rapide réduite à 50 %.
   Le point le plus bas des essais est Z -23 (goujons) : la fraise reste 7 mm au-dessus du bois. Regarder que le
   parcours tient dans la zone de la fiche, loin des vis. Puis **refaire le vrai Z0** sur le dessus.
4. Aspiration, lunettes, casque ; une main près de **Pause** (`!`) et de l'arrêt d'urgence.
5. Premier passage de chaque fichier : **avance à 50 %** (réglage de vitesse de CNCjs) pendant la première minute,
   puis 100 % si le bruit est régulier, sans brûlure ni broutement.

Vitesses de départ (préréglages de la bibliothèque de démarrage, prudents pour du bois tendre) :

| Outil | Broche | Avance | Plongée | Passe | Pas latéral |
|---|---|---|---|---|---|
| T1 plate Ø6 | 18 000 tr/min | 1 800 mm/min | 600 mm/min | 3 mm (1,5 mm pour l'ébauche du dôme) | 2,4 mm (40 %) |
| T3 boule Ø6 | 18 000 tr/min | 1 500 mm/min | 500 mm/min | finition | 0,5 mm |
| T5 V-bit 60° | 18 000 tr/min | 1 200 mm/min | 400 mm/min | profondeur du V-carving (≤ 3 mm) | — |

## Ordre des essais

| # | Fichier | Ce qu'il prouve | Outil | Planche / zone | Temps estimé |
|---|---|---|---|---|---|
| 01 | `01-palpage-coin.nc` | origine X0 Y0 Z0 par le palpeur (G38.2, G10 L20) | palpeur, broche arrêtée | 1, coin avant gauche | < 1 min |
| 02 | `02-poche.nc` | poche 40 × 30 × 6 : échelle X / Y, profondeur, avance | T1 | 1 : X 15..55, Y 20..50 | 42 s |
| 03 | `03-poche-2-profondeurs.nc` | poche 50 × 40 × 3 puis 24 × 16 × 8 : reprise de Z | T1 | 1 : X 70..120, Y 15..55 | 59 s |
| 04 | `04-percage.nc` | 3 trous Ø6 × 10, entraxes 20 et 40 : positions absolues | T1 | 1 : X 137..183, Y 32..38 | 4 s |
| 05 | `05-dome-ebauche.nc` | ébauche 3D par paliers de 1,5 mm (23 000 lignes) | T1 | 1 : X 10..80, Y 75..150 | 16 min |
| 06 | `06-dome-finition.nc` | finition boule du dôme, après changement de fraise sans démonter | T3 | idem | 9 min |
| 07 | `07-vcarving-texte.nc` | V-carving « CAM2027 » : profondeur variable, 3e fraise | T5 | 1 : X 96..160, Y 118..132 | 2 min 40 s |
| 08 | `08-contour-attaches.nc` | pièce 50 × 30 R5 découpée, 4 attaches, entrée et sortie en arc | T1 | 1 : X 132..190, Y 69..107 | 1 min 05 s |
| 09 A | `09-recto-verso-A.nc` | goujons Ø6, demi-alésage Ø20, poche : face A | T1 | 2 | 53 s |
| 09 B | `09-recto-verso-B.nc` | planche retournée sur les goujons : face B | T1 | 2 retournée | 32 s |

Temps estimés par CAM2027 avec une accélération supposée de 500 mm/s² (profil machine à compléter).

Pourquoi cet ordre : le palpage fixe l'origine de tout le reste ; la poche simple vérifie échelle, profondeur et
avance avant tout le reste ; la poche à deux profondeurs ajoute la reprise de Z ; le perçage, la position
absolue de trous ; l'ébauche puis la finition 3D, un long programme (environ 16 min + 9 min) et le changement de
fraise sans démonter ; le V-carving, la troisième fraise et les profondeurs variables ; le contour **en dernier**
sur la planche 1 parce qu'il la découpe (attaches) ; le recto-verso sur une planche neuve parce qu'il la retourne.

## Ce qui prouve qu'un essai est réussi

- La machine finit le programme sans `error:` ni `ALARM` et revient à Z 5 au-dessus de la pièce.
- **Toutes les cotes de la fiche dans la tolérance** (colonne « Attendu » ; la colonne « Simulé CAM2027 » est ce
  que donne le parcours sur la matière simulée à 0,05 mm, elle confirme que l'attendu est atteignable).
- Aucune marque d'entrée en plongée verticale sur le contour (entrée en arc), aucune trace de déplacement
  rapide dans la matière, fonds et parois propres, aucune brûlure.
- Origine retrouvée : après le programme, `G0 X0 Y0` puis descendre à Z 0,5 : la fraise est au-dessus du coin.

Noter pour chaque essai : les cotes relevées, une photo, la console CNCjs s'il y a eu un message.

## En cas d'écart

| Constat | Cause probable | Que faire |
|---|---|---|
| `error:` dans CNCjs | ligne refusée par GRBL (le simulateur l'acceptait) | noter le numéro de ligne et le message, ne pas relancer ; comparer avec `VALIDATION.md`, le signaler |
| `ALARM:1` / `ALARM:2` | fin de course / limite logicielle | course insuffisante ou origine mal placée : vérifier `$130`–`$132` et l'enveloppe de la fiche |
| `ALARM:4` / `ALARM:5` (palpage) | palpeur déjà en contact / rien touché sur 25 mm | câblage du palpeur, départ trop haut (moins de 25 mm au-dessus) |
| Toutes les cotes trop grandes ou trop petites d'une même valeur (ex. poche +0,1, pièce −0,1) | diamètre réel de la fraise, faux-rond | mesurer la fraise, corriger le diamètre dans la bibliothèque |
| Écart proportionnel à la longueur (40 → 40,4 et 20 → 20,2) | pas/mm | refaire le contrôle d'échelle, corriger `$100`/`$101` |
| Profondeurs fausses d'une même valeur | Z0 mal fait, fraise qui glisse dans la pince | refaire Z0 au papier, serrer la pince, recommencer |
| Profondeurs de plus en plus fausses au fil du programme | fraise qui glisse, pas perdus en Z | serrer, réduire `$112` / `$122` |
| Décalage qui grandit au cours du programme | pas perdus en X/Y (courroie, accouplement, accélération trop forte) | réduire `$120`/`$121` et `$110`/`$111`, vérifier la mécanique |
| Tout décalé d'une même valeur | origine | refaire l'origine (essai 01 ou à la main) |
| Parois en escalier ou ondulées, bruit de broutement | passe trop forte, fraise trop sortie | sortie de fraise minimale, passe ÷ 2, avance à 70 % |
| Bois brûlé | avance trop faible pour la vitesse de broche | avance + 20 % ou broche − 20 % |
| Recto-verso : marche dans l'alésage | goujons trop lâches, planche retournée de travers | goujons ajustés, retourner autour de X (le chant gauche reste à gauche) |

Un écart qui ne s'explique pas par ce tableau : arrêter les essais, envoyer les cotes, la photo et le fichier.

## Ce qui a été vérifié sans machine

- **Génération reproductible** : `FreeCADCmd.exe -M src\Mod\CAM2027 src\Mod\CAM2027\tests\machine_trials\build.py`
  (FreeCAD 1.1.4, environ 6 min) reconstruit les 9 projets et les 10 fichiers ; chaque fichier passe l'export
  CAM2027 sans erreur et le contrôle matière sans entaille (V-carving : 0,10 mm signalé, en fait un débord de
  0,08 mm à la pointe du A et du M, voir sa fiche) ni rapide dans la matière.
- **Interpréteur GRBL 1.1** : `python src\Mod\CAM2027\tests\machine_trials\validate.py` envoie chaque fichier
  ligne par ligne, protocole ok / error, au simulateur GRBL 1.1h du dépôt cncjs
  (`cncjs\grbl-simulator\grbl-simulator.js`, lu sans modification, horloge simulée : moins d'une seconde pour les
  10 fichiers). Résultat : **0 `error:`, 0 `ALARM`** sur les 10 fichiers ; chaque position de fin de mouvement,
  la position finale et l'enveloppe (arcs compris) identiques au parcours CAM2027 (calculé sur les opérations,
  avant postprocesseur) à **0,0005 mm** près (tolérance demandée : 0,01 mm).
- Le simulateur accepte des codes que GRBL refuse : chaque ligne passe aussi le filtre de GRBL (commentaires,
  espaces) et ses règles (codes et lettres de GRBL 1.1, groupes modaux, mots répétés, nombres, 80 caractères).
- Palpage : le simulateur touche une surface fictive ; le fichier 01 est en plus exécuté contre la planche par le
  GRBL de palpage des tests (`test_jour4_c5.TestProbeTrial`) : origine exactement au coin depuis deux départs.
- **Non vérifié** : courses et fins de course (profil machine sans courses), temps réel (accélérations),
  comportement réel de la broche, axe A (absent du simulateur ; les essais 4e axe ne sont vérifiés que par les
  contrôles de l'export CAM2027 — il n'y en a pas dans cette série).
- Test automatique : `test_jour4_c5` (ignoré si Node ou le simulateur sont absents ; reconstruction complète avec
  `CAM2027_TRIALS_REBUILD=1`).

## Valeurs du palpeur

Le profil d'essai suppose un palpeur à pointe **Ø 2 mm**, sans plaque, 100 mm/min, course 25 mm. Avec un autre
palpeur : corriger ces valeurs dans `PROBE` en tête de `build.py` (ou dans **Machine > Palpeur** pour un projet
à soi), régénérer et revalider avant l'essai 01.
