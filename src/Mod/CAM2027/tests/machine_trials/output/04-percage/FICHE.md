# Essai 04-percage

- Fichier : `04-percage.nc` (23 lignes ; codes : G0, G1, G17, G21, G54, G90, M2, M3, M5)
- Zone : X 137..183, Y 32..38 (avant droite)
- Outil : 6 mm flat end mill 2F
- Temps estimé par CAM2027 : 0 min 04 s
- Enveloppe des mouvements : X 140,00..180,00, Y 35,00..35,00, Z -10,00..5,00
- Contrôle matière CAM2027 : entaille 0,00 mm, rapides dans la matière : 0
- Origine : G54 au coin avant gauche du dessus de la planche (X0 Y0 Z0) ; Z0 refait au dessus de la planche après chaque changement d'outil
- Fiche de préparation CAM2027 : `04-percage-setup.md`

## Mesures

| Cote | Comment | Attendu | Tolérance | Simulé CAM2027 |
|---|---|---|---|---|
| Diamètre du trou 1 | becs intérieurs (fraise plate en plongée : 6,0 à 6,1) | 6,00 | ± 0,15 | 6,00 |
| Entraxe trous 1-2 | bord à bord extérieur moins un diamètre | 20,00 | ± 0,10 | 20,00 |
| Entraxe trous 1-3 | idem | 40,00 | ± 0,10 | 40,00 |
| Profondeur (trou 2) | jauge de profondeur au centre | 10,00 | ± 0,10 | 10,00 |

Réussi si toutes les cotes sont dans la tolérance, aucune marque d'entrée ni de rapide dans la matière, et le bruit de coupe reste régulier. Sinon : voir « En cas d'écart » dans `docs/cam2027/ESSAIS-MACHINE.md`.
