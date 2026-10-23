# Essai 08-contour-attaches

- Fichier : `08-contour-attaches.nc` (161 lignes ; codes : G0, G1, G17, G2, G21, G3, G54, G90, M2, M3, M5)
- Zone : X 135..185, Y 72..102 (milieu droit) : pièce 50 x 30 R5 découpée, 4 attaches
- Outil : 6 mm flat end mill 2F
- Temps estimé par CAM2027 : 1 min 05 s
- Enveloppe des mouvements : X 132,00..189,90, Y 69,00..106,90, Z -18,20..5,00
- Contrôle matière CAM2027 : entaille 0,00 mm, rapides dans la matière : 0
- Origine : G54 au coin avant gauche du dessus de la planche (X0 Y0 Z0) ; Z0 refait au dessus de la planche après chaque changement d'outil
- Fiche de préparation CAM2027 : `08-contour-attaches-setup.md`

## Mesures

| Cote | Comment | Attendu | Tolérance | Simulé CAM2027 |
|---|---|---|---|---|
| Pièce découpée : longueur | becs extérieurs (après avoir coupé les attaches) | 50,00 | ± 0,15 | 50,00 |
| Pièce découpée : largeur | becs extérieurs | 30,00 | ± 0,15 | 30,00 |
| Épaisseur des attaches | pied à coulisse sur le reste d'attache, depuis le dessous de la planche (attache de 4 mm au-dessus du fond de coupe, qui est 0,2 mm sous la planche) | 3,80 | ± 0,30 | — |

Réussi si toutes les cotes sont dans la tolérance, aucune marque d'entrée ni de rapide dans la matière, et le bruit de coupe reste régulier. Sinon : voir « En cas d'écart » dans `docs/cam2027/ESSAIS-MACHINE.md`.
