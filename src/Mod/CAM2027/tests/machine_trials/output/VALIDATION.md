# Validation dans le simulateur GRBL 1.1 (cncjs)

Résultat : **tout accepté** — 10 fichiers, simulateur `grbl-simulator.js` de cncjs (Grbl 1.1h), Node v24.20.0, positions comparées au parcours CAM2027 à ± 0,01 mm.

| Fichier | Lignes | error: | ALARM | Positions comparées | Écart max (mm) | Position finale X Y Z | Résultat |
|---|---|---|---|---|---|---|---|
| 01-palpage-coin | 31 | 0 | 0 | 2 | 0,000 | 0,000 0,000 — | OK |
| 02-poche | 100 | 0 | 0 | 91 | 0,000 | 18,300 47,000 5,000 | OK |
| 03-poche-2-profondeurs | 152 | 0 | 0 | 140 | 0,000 | 86,000 39,153 5,000 | OK |
| 04-percage | 23 | 0 | 0 | 12 | 0,000 | 180,000 35,000 5,000 | OK |
| 05-dome-ebauche | 23079 | 0 | 0 | 22004 | 0,001 | 76,500 149,950 5,000 | OK |
| 06-dome-finition | 9528 | 0 | 0 | 9521 | 0,000 | 76,997 146,580 5,000 | OK |
| 07-vcarving-texte | 1278 | 0 | 0 | 1268 | 0,001 | 156,561 118,036 5,000 | OK |
| 08-contour-attaches | 161 | 0 | 0 | 154 | 0,000 | 189,897 102,654 5,000 | OK |
| 09-recto-verso-A | 141 | 0 | 0 | 125 | 0,000 | 43,665 117,000 5,000 | OK |
| 09-recto-verso-B | 89 | 0 | 0 | 75 | 0,000 | 133,665 117,000 5,000 | OK |

Contrôles en plus de ceux du simulateur (qui accepte sans erreur G81, M6, les mots A, ne lit pas les commentaires) : filtre de ligne de GRBL (commentaires, espaces), codes et lettres de GRBL 1.1, groupes modaux, mots répétés, mots inutilisés, format des nombres, 80 caractères. Palpage : le simulateur touche une surface fictive vers Z -3 et ignore `G10 L20` ; les positions qui dépendent d'un contact sont exclues des deux côtés (axe inconnu jusqu'au mouvement absolu suivant). Non vérifié : courses et fins de course (profil machine sans courses), axe A (absent du simulateur).
