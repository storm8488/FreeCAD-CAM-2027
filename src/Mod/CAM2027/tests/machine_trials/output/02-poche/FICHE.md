# Essai 02-poche

- Fichier : `02-poche.nc` (100 lignes ; codes : G0, G1, G17, G21, G54, G90, M2, M3, M5)
- Zone : X 15..55, Y 20..50 (avant gauche)
- Outil : 6 mm flat end mill 2F
- Temps estimé par CAM2027 : 0 min 42 s
- Enveloppe des mouvements : X 18,00..52,00, Y 23,00..47,00, Z -6,00..5,00
- Contrôle matière CAM2027 : entaille 0,00 mm, rapides dans la matière : 0
- Origine : G54 au coin avant gauche du dessus de la planche (X0 Y0 Z0) ; Z0 refait au dessus de la planche après chaque changement d'outil
- Fiche de préparation CAM2027 : `02-poche-setup.md`

## Mesures

| Cote | Comment | Attendu | Tolérance | Simulé CAM2027 |
|---|---|---|---|---|
| Longueur intérieure (X) | becs intérieurs du pied à coulisse, à mi-profondeur | 40,00 | ± 0,15 | 40,00 |
| Largeur intérieure (Y) | becs intérieurs, à mi-profondeur | 30,00 | ± 0,15 | 30,00 |
| Profondeur | jauge de profondeur, au centre | 6,00 | ± 0,10 | 6,00 |
| Rayon des angles | comparer à la fraise : rayon = 3 mm (rayon de la fraise) | 3,00 | ± 0,20 | — |

Réussi si toutes les cotes sont dans la tolérance, aucune marque d'entrée ni de rapide dans la matière, et le bruit de coupe reste régulier. Sinon : voir « En cas d'écart » dans `docs/cam2027/ESSAIS-MACHINE.md`.
