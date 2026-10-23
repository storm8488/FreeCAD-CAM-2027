# Essai 01-palpage-coin

- Fichier : `01-palpage-coin.nc` (31 lignes ; codes : G0, G10, G17, G21, G38.2, G54, G90, G91, M2, M5)
- Zone : coin avant gauche de la planche 1 (palpeur posé au-dessus de la planche, à 10 mm des deux bords)
- Outil : palpeur (broche arrêtée)
- Temps estimé par CAM2027 : 0 min 03 s
- Enveloppe des mouvements : X 0,00..10,00, Y 0,00..0,00
- Contrôle matière CAM2027 : entaille 0,00 mm, rapides dans la matière : 0
- Origine : G54 au coin avant gauche du dessus de la planche (X0 Y0 Z0) ; Z0 refait au dessus de la planche après chaque changement d'outil
- Fiche de préparation CAM2027 : `01-palpage-coin-setup.md`

## Mesures

| Cote | Comment | Attendu | Tolérance | Simulé CAM2027 |
|---|---|---|---|---|
| Écart X entre l'origine palpée et l'origine à la feuille de papier | après le palpage : G0 Z5 puis G0 X0 Y0 ; descendre à Z0,5 au pas de 0,1 mm, comparer au coin (réglet contre le chant, ou feuille de papier) ; lire aussi WCO dans CNCjs avant / après | 0,00 | ± 0,10 | — |
| Écart Y | idem sur le chant avant | 0,00 | ± 0,10 | — |
| Écart Z (dessus de la planche) | feuille de papier sous la fraise à Z0 : elle accroche à peine | 0,00 | ± 0,10 | — |

Réussi si toutes les cotes sont dans la tolérance, aucune marque d'entrée ni de rapide dans la matière, et le bruit de coupe reste régulier. Sinon : voir « En cas d'écart » dans `docs/cam2027/ESSAIS-MACHINE.md`.
