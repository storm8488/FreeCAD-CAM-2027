# Essai 05-dome-ebauche

- Fichier : `05-dome-ebauche.nc` (23079 lignes ; codes : G0, G1, G17, G21, G54, G90, M2, M3, M5)
- Zone : X 10..80, Y 75..150 (arrière gauche) : cuvette 70 x 75 x 10 ouverte sur le chant arrière, dôme R40 au milieu (sommet au ras du dessus)
- Outil : 6 mm flat end mill 2F
- Temps estimé par CAM2027 : 15 min 58 s
- Enveloppe des mouvements : X 6,00..84,00, Y 78,50..153,50, Z -9,00..5,00
- Contrôle matière CAM2027 : entaille 0,00 mm, rapides dans la matière : 0
- Origine : G54 au coin avant gauche du dessus de la planche (X0 Y0 Z0) ; Z0 refait au dessus de la planche après chaque changement d'outil
- Fiche de préparation CAM2027 : `05-dome-ebauche-setup.md`

> L'ébauche est limitée à un rectangle autour de la cuvette (habillage « Limiter à une zone ») : sans lui elle contournerait toute la planche à chaque palier, dans le vide.

> L'ébauche laisse des marches de 1,5 mm et 0,5 mm de surépaisseur : au pied du dôme, la boule enlève jusqu'à ~2 mm. Lancer la finition sans démonter la planche (même origine X Y), seul Z0 est refait.

## Mesures

| Cote | Comment | Attendu | Tolérance | Simulé CAM2027 |
|---|---|---|---|---|
| Cuvette après ébauche : côté (X), près du bord arrière | becs intérieurs, à 5 mm sous le dessus | 69,00 | ± 0,20 | 69,00 |
| Fond de la cuvette après ébauche (coin avant gauche) | jauge de profondeur à 4 mm des parois | 9,00 | ± 0,10 | 9,00 |
| Sommet du dôme après ébauche | règle posée sur la planche : aucun jour | 0,00 | ± 0,10 | 0,00 |

Réussi si toutes les cotes sont dans la tolérance, aucune marque d'entrée ni de rapide dans la matière, et le bruit de coupe reste régulier. Sinon : voir « En cas d'écart » dans `docs/cam2027/ESSAIS-MACHINE.md`.
