# Essai 09-recto-verso-A

- Fichier : `09-recto-verso-A.nc` (141 lignes ; codes : G0, G1, G17, G2, G21, G54, G90, M2, M3, M5)
- Zone : planche 2 entière : goujons Ø6 à X 10 et X 190 (Y 75), alésage Ø20 traversant fait moitié par face, une poche 30 x 20 x 3 sur chaque face
- Outil : 6 mm flat end mill 2F
- Temps estimé par CAM2027 : 0 min 53 s
- Enveloppe des mouvements : X 10,00..190,00, Y 75,00..117,00, Z -23,00..5,00
- Contrôle matière CAM2027 : entaille 0,00 mm, rapides dans la matière : 0
- Origine : G54 au coin avant gauche du dessus de la planche (X0 Y0 Z0) ; Z0 refait au dessus de la planche après chaque changement d'outil
- Fiche de préparation CAM2027 : `09-recto-verso-A-setup.md`

## Mesures

| Cote | Comment | Attendu | Tolérance | Simulé CAM2027 |
|---|---|---|---|---|
| Marche dans l'alésage Ø20 (décalage entre les deux moitiés) | doigt ou jauge : aucune marche sensible ; becs intérieurs en haut et en bas : même valeur | 0,00 | ± 0,20 | — |
| Diamètre de l'alésage (face A puis face B) | becs intérieurs | 20,00 | ± 0,15 | — |
| Poche face A : distance au chant gauche (X) | jauge de profondeur ou réglet depuis le chant gauche | 40,00 | ± 0,20 | — |
| Poche face B : distance au chant gauche (X), planche retournée | réglet depuis le même chant gauche (le retournement autour de X garde la gauche) | 130,00 | ± 0,20 | — |
| Poche face B : distance au chant avant (Y), planche retournée | réglet depuis le chant qui est devant après retournement | 100,00 | ± 0,20 | — |

Réussi si toutes les cotes sont dans la tolérance, aucune marque d'entrée ni de rapide dans la matière, et le bruit de coupe reste régulier. Sinon : voir « En cas d'écart » dans `docs/cam2027/ESSAIS-MACHINE.md`.

## Two-sided machining - side A

- Flip axis: X (the stock turns 180 deg about the line X through the stock centre X 100.00 Y 75.00)
- Stock on both sides: X 0.00..200.00, Y 0.00..150.00, Z -18.00..0.00 (same work offset G54)
- Registration: 2 dowel pins D 6.00 mm at X 10.00 Y 75.00, X 190.00 Y 75.00, drilled from side A through the stock and 5.0 mm into the spoilboard
- Operations of side A: Registration holes (dowels), Alesage face A, Poche face A
