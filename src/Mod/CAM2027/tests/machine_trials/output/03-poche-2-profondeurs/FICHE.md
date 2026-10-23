# Essai 03-poche-2-profondeurs

- Fichier : `03-poche-2-profondeurs.nc` (152 lignes ; codes : G0, G1, G17, G21, G54, G90, M2, M3, M5)
- Zone : X 70..120, Y 15..55 (avant milieu)
- Outil : 6 mm flat end mill 2F
- Temps estimé par CAM2027 : 0 min 59 s
- Enveloppe des mouvements : X 73,00..117,00, Y 18,00..52,00, Z -8,00..5,00
- Contrôle matière CAM2027 : entaille 0,00 mm, rapides dans la matière : 0
- Origine : G54 au coin avant gauche du dessus de la planche (X0 Y0 Z0) ; Z0 refait au dessus de la planche après chaque changement d'outil
- Fiche de préparation CAM2027 : `03-poche-2-profondeurs-setup.md`

## Mesures

| Cote | Comment | Attendu | Tolérance | Simulé CAM2027 |
|---|---|---|---|---|
| Grande poche : longueur (X) | becs intérieurs, entre 0 et -3 | 50,00 | ± 0,15 | 50,00 |
| Grande poche : largeur (Y) | becs intérieurs, entre 0 et -3 | 40,00 | ± 0,15 | 40,00 |
| Grande poche : profondeur | jauge de profondeur sur la marche | 3,00 | ± 0,10 | 3,00 |
| Petite poche : longueur (X) | becs intérieurs, sous la marche | 24,00 | ± 0,15 | 24,00 |
| Petite poche : largeur (Y) | becs intérieurs, sous la marche | 16,00 | ± 0,15 | 16,00 |
| Petite poche : profondeur depuis le dessus | jauge de profondeur depuis le dessus de la planche | 8,00 | ± 0,10 | 8,00 |

Réussi si toutes les cotes sont dans la tolérance, aucune marque d'entrée ni de rapide dans la matière, et le bruit de coupe reste régulier. Sinon : voir « En cas d'écart » dans `docs/cam2027/ESSAIS-MACHINE.md`.
