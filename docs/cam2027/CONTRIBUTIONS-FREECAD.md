# Contributions de CAM2027 au CAM de FreeCAD

But : rendre à FreeCAD les correctifs du moteur CAM trouvés en développant CAM2027, un par un, à la manière du
projet FreeCAD. CAM2027 est une version de FreeCAD réduite au CAM pour l'usage de son auteur (et de ceux qui ont le
même besoin) ; ses avancées sur le moteur CAM sont partagées avec FreeCAD.

## Règles de FreeCAD à respecter (lues sur `main` le 2026-10-23)

- [AI_POLICY.md](https://github.com/FreeCAD/FreeCAD/blob/main/AI_POLICY.md) : **aucun texte écrit par une IA** dans les
  tickets, les PR, leurs commentaires et les messages de commit. Ils sont écrits par toi. Un anglais imparfait est
  accepté ; si tu traduis avec un outil, ajoute le texte original en français.
- Le code assisté par IA est accepté s'il est **déclaré** : une phrase dans la description de la PR, et dans chaque
  message de commit la ligne `Assisted-by: Claude Opus 5.5 (claude-opus-5-5)`. Tu dois comprendre le code et en
  prendre la responsabilité (explications ci-dessous).
- Le modèle de PR contient une case obligatoire : « This PR is not unverified AI output, I take responsibility for it,
  and all communication from my side in this PR, including PR description, comments and commit messages is done by
  me personally. »
- [CONTRIBUTING.md](https://github.com/FreeCAD/FreeCAD/blob/main/CONTRIBUTING.md) : d'abord un **ticket** qui décrit le
  problème (complet, sans renvoyer ailleurs, sans comparaison avec d'autres logiciels), puis une PR liée au ticket,
  sur `main`, avec des tests, rebasée, commits regroupés.
- Les PR des nouveaux contributeurs sont examinées de près : petites, propres, une seule chose à la fois.

## Ordre conseillé

1. Ticket n° 1 (lenteur du V-carving), attendre une réaction (un jour ou deux).
2. PR n° 1 si l'accueil est bon (« I have a fix ready, would you like a PR? » dans le ticket, avec tes mots).
3. Ticket n° 2 (morsure dans les coins), puis PR n° 2.
4. Les autres correctifs de CAM2027 seulement après, et seulement s'ils sont encore utiles sur `main` (à vérifier
   un par un : poches à plusieurs fonds, fusion des fonds, finition 3D, ébauche adaptative, habillages).

---

## N° 1 — V-carving très lent sur les dessins à beaucoup d'arêtes

**Faits mesurés** (FreeCAD de développement 27.1.0, préversion du 2026-10-21, Windows 11)

| Sommets du contour | Calcul du V-carving (avant) | Après le correctif |
|---|---|---|
| 250 | 0,8 s | — |
| 500 | 2,7 s | — |
| 1 000 | 10,2 s | — |
| 2 000 | 39 à 62 s | 0,3 s |
| dessin vectorisé d'une image (≈ 10 000 arêtes, FreeCAD 1.1.4) | 1 505 s (25 min) | 16 s |

- Le temps est multiplié par 4 quand le nombre de sommets double (comportement quadratique).
- **G-code identique octet pour octet** avant / après sur 4 formes (polygones de 250 et 2 000 sommets, étoile, L).
- Fichiers de reproduction : `C:\Users\damou\CAM2027-release\freecad-issues\vcarve_slow_250.FCStd` et
  `vcarve_slow_2000.FCStd` (ouvrir, sélectionner l'opération Vcarve, recalculer).

**Cause** (fichier `src/Mod/CAM/Path/Op/Vcarve.py`, fonction `buildMedialWires`) : pour savoir quelles arêtes du
diagramme de Voronoï sont hors de la face, FreeCAD appelle pour **chaque sommet** du diagramme `is_exterior()`, qui
appelle `face.isPartOfDomain(u, v)`. Cette fonction reconstruit à chaque appel un « classificateur » de la face, dont
le coût grandit avec le nombre d'arêtes. Nombre de sommets × nombre d'arêtes → quadratique.

**Correctif** (branche locale `cam-vcarve-fast-exterior`, dossier `C:\Users\damou\Documents\claude\freecad-upstream`)

- `insert_many_wires()` garde les polygones qu'elle donne déjà au diagramme (les mêmes points).
- Nouvelle classe `_PolygonDomain` : le test « pair-impair » classique. Depuis le point, on compte combien de côtés
  des polygones (contour et trous) une demi-droite horizontale traverse ; impair = dedans. Un point sur un côté (à la
  précision de FreeCAD près) compte comme dedans, comme `isPartOfDomain`. Calcul vectorisé avec numpy (déjà utilisé
  dans le CAM, par `MillFace.py`).
- Utilisée seulement pour les faces planes horizontales (`_isHorizontalPlane`) ; les autres gardent l'ancien test.
- Test ajouté : `test20` compare `_PolygonDomain` à `isPartOfDomain` sur 9 005 points d'une face trouée, points sur
  les bords compris.

**Vérifié** : les 16 tests V-carving de FreeCAD passent ; suite CAM complète (`freecadcmd -t TestCAMApp`) : 2 094 tests OK, comme sans le correctif (2 093 + le nouveau).

---

## N° 2 — Le V-bit mord le bord du dessin près des coins

**Faits mesurés** (même préversion ; dépassement = rayon du V à la profondeur du point moins sa distance au bord)

| Forme (V-bit 60°) | Dépassement avant | Après | Commandes avant → après |
|---|---|---|---|
| polygone ondulé 120 sommets (outil de test FreeCAD, Ø 10) | 0,128 mm | 0 | 428 → 587 |
| polygone ondulé 250 sommets (outil Ø 10) | 0,102 mm | 0 | 913 → 936 |
| polygone ondulé 250 sommets (outil Ø 12,7) | 0,151 mm | — | — |
| L (outil Ø 10) | 0 | 0 | 32 → 24 |
| dessin vectorisé d'une image (FreeCAD 1.1.4) | 0,83 mm | 0,025 mm (mesure) | — |

- Même défaut en 1.1.4 et en développement.
- Fichier de reproduction : `C:\Users\damou\CAM2027-release\freecad-issues\vcarve_overcut_wavy250.FCStd`.

**Cause** (`_getPartEdge`) : la profondeur est calculée aux deux bouts de chaque arête du diagramme, puis
`edge.toShape(zBegin, zEnd)` la fait varier **en ligne droite** entre les deux. C'est juste entre deux côtés du
dessin (la distance au bord varie alors linéairement), mais pas le long d'une arête qui touche un **coin** du
dessin : arc de parabole (entre un coin et un côté) ou médiatrice (entre deux coins). Là, la distance au bord est plus
petite au milieu qu'aux bouts : la ligne droite descend trop, le V est trop large et mord le bord. Un dessin fait de
beaucoup de petits côtés (image vectorisée, texte) a beaucoup de coins.

**Correctif** (branche locale `cam-vcarve-exact-depth`, dossier `C:\Users\damou\Documents\claude\freecad-upstream-depth`)

- `_getPartEdges` : les arêtes entre deux côtés restent comme avant ; celles qui touchent un coin passent par
  `_getExactPartEdges`.
- `_getExactPartEdges` : points tous les 0,2 mm le long de l'arête, profondeur de chaque point calculée d'après sa
  vraie distance au coin (`_siteDistance` : distance au point ou au segment source de la cellule de Voronoï). On ne
  garde ensuite que les points nécessaires : un segment droit est accepté tant qu'il ne descend nulle part plus bas que
  la profondeur permise, à la tolérance de l'opération près (propriété `Tolerance`, 0,01 mm par défaut). D'où peu de
  commandes en plus.
- Test ajouté : `test21`, V-carving d'un polygone ondulé de 120 sommets ; **échoue sans le correctif** (0,128 mm),
  passe avec (0).

**Vérifié** : les 16 tests V-carving de FreeCAD passent ; suite CAM complète (`freecadcmd -t TestCAMApp`) : 2 094 tests OK, comme sans le correctif (2 093 + le nouveau).

---

## Faire les PR (quand tu es prêt)

Les deux branches sont locales, non commitées : le message de commit doit venir de toi. Pour chacune :

```bash
cd C:/Users/damou/Documents/claude/freecad-upstream
```

```bash
git add src/Mod/CAM/Path/Op/Vcarve.py src/Mod/CAM/CAMTests/TestPathVcarve.py
```

```bash
git commit
```

Dans l'éditeur : ton message (en anglais, avec tes mots, commençant par `CAM:`), puis une ligne vide et
`Assisted-by: Claude Opus 5.5 (claude-opus-5-5)`. Ensuite :

```bash
git push origin cam-vcarve-fast-exterior
```

puis sur GitHub « Compare & pull request » vers `FreeCAD/FreeCAD`, branche `main` : cocher la case de la politique
IA, lier le ticket (« Fixes #… »), décrire avec tes mots, dire que le code a été écrit avec l'aide de Claude Opus 5.5.
Même chose pour `cam-vcarve-exact-depth` dans `C:/Users/damou/Documents/claude/freecad-upstream-depth`.
