# Essai 07-vcarving-texte

- Fichier : `07-vcarving-texte.nc` (1278 lignes ; codes : G0, G1, G17, G21, G54, G90, M2, M3, M5)
- Zone : X 96..160, Y 118..131 (arrière droite) : texte « CAM2027 »
- Outil : 60° V-bit
- Temps estimé par CAM2027 : 2 min 40 s
- Enveloppe des mouvements : X 96,38..159,58, Y 117,98..131,33, Z -1,71..5,00
- Contrôle matière CAM2027 : entaille 0,10 mm, rapides dans la matière : 0
- Origine : G54 au coin avant gauche du dessus de la planche (X0 Y0 Z0) ; Z0 refait au dessus de la planche après chaque changement d'outil
- Fiche de préparation CAM2027 : `07-vcarving-texte-setup.md`

> Le contrôle matière CAM2027 signale une petite entaille (0,10 mm à la résolution 0,5 mm). Analyse fine (carte 0,05 mm, test exact dans les lettres) : le V-bit déborde d'au plus 0,08 mm hors du dessin, à la pointe du A et du M (discrétisation du V-carving) ; invisible dans le bois, non bloquant.

## Mesures

| Cote | Comment | Attendu | Tolérance | Simulé CAM2027 |
|---|---|---|---|---|
| Longueur totale du texte (bord gauche du C au bord droit du 7) | becs extérieurs du pied à coulisse, à la surface | 63,27 | ± 0,20 | 63,25 |
| Hauteur du C | becs extérieurs, à la surface | 13,37 | ± 0,20 | 13,40 |
| Profondeur la plus forte (traits les plus larges) | jauge de profondeur (pointe fine) ou comparaison visuelle | 1,71 | ± 0,10 | 1,71 |

Réussi si toutes les cotes sont dans la tolérance, aucune marque d'entrée ni de rapide dans la matière, et le bruit de coupe reste régulier. Sinon : voir « En cas d'écart » dans `docs/cam2027/ESSAIS-MACHINE.md`.
