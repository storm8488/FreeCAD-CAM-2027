# CAM2027 — Intégration de la direction artistique « Atelier »

Source : dossier `FreeCAD_CAM_Direction_Artistique` v1.1 (20 oct. 2026), copié dans
`docs/design/` (charte, jetons, consignes, contrôles). Le nom de travail du dossier
(« FreeCAD CAM ») n'est pas repris : le produit reste **CAM2027**, fork indépendant basé sur
FreeCAD et son atelier CAM.

## Ce qui est intégré

| Élément | Où | Remarque |
|---|---|---|
| Jetons (couleurs sombre/clair, typo, espacements, rayons, densité) | `Resources/theme/tokens.json` (copie exacte de `02_DESIGN_TOKENS.json`) | source unique des valeurs |
| Couche de thème | `cam2027/gui/theme.py` | rôles sémantiques (`color`, `status_color`), QSS **limitée aux widgets CAM2027** (panneaux, éditeur, dialogues), jamais l'application entière |
| Choix du thème | préférence `BaseApp/Preferences/CAM2027/Theme` = `system` (défaut, suit la palette FreeCAD) / `dark` / `light` ; commande « Thème : système / sombre / clair » (menu CAM2027) | |
| Icônes | `Resources/icons/atelier/{dark,light}/*.svg` (32 × 2, copie exacte) | variante choisie selon le thème effectif ; commandes, étapes du flux, stratégies, actions de liste, opération invalide |
| Boutons | vrais `QPushButton` avec rôles `primary` / `danger` (pas d'images) | l'étape suivante du flux de travail est l'action principale (bleu cobalt) |
| États de calcul | colonne « État » de la liste d'opérations (`operations.compute_state`) | lus sur l'objet FreeCAD (Touched / Invalid / mouvements de coupe), jamais un statut parallèle ; « Calculé » ≠ vérifié |
| États | statut d'étape = symbole (✔ / ○) + couleur + info-bulle ; opération invalide = icône d'alerte + couleur + info-bulle ; contrôles d'export = niveau en texte + couleur | jamais la couleur seule |

## Non intégré / à faire

- Logo : les deux PNG du dossier sont des **propositions** non validées et lourdes (656 Ko) ;
  non copiés. L'icône d'atelier reste `Resources/icons/CAM2027.svg`. Pas de `.ico`.
- Les barres d'outils et menus de FreeCAD gardent le thème FreeCAD (profil « FAO seule » =
  « FreeCAD Dark ») ; seule la partie CAM2027 suit les jetons.
- Couleurs de scène 3D : **appliquées** au profil du lanceur (préférences FreeCAD CAM
  `DefaultNormalPathColor` = coupe, `DefaultRapidPathColor` = rapide, marqueur = plongée,
  sélection, boîte du brut ; épaisseur 2), après le pack « FreeCAD Dark » qui contient ses
  propres couleurs ; versionnées à part (`SceneVersion`). Valent pour les nouveaux parcours.
  **Motifs** (rapide en tirets, plongée en pointillés) : non disponibles, FreeCAD trace
  chaque famille d'une seule couleur en trait continu.
- Navigation Préparer / Usiner / Simuler / Exporter, barre d'état dédiée, panneaux mémorisés :
  partiellement couverts par le panneau de flux de travail (4 étapes) ; pas de refonte de la
  fenêtre FreeCAD.
- Vérifié visuellement : thème sombre et clair sur 1.1.4 (captures `tests/screenshots`).
  Vérifié aussi : fenêtre 1280 × 800 (capture `main_window_1280x800.png`, bibliothèque et flux
  lisibles). Vérifié aussi : mise à l'échelle Qt 150 % et 200 % (`QT_SCALE_FACTOR`, captures
  `*_scale15.png` / `*_scale2.png`) : textes non coupés, éditeur limité à 85 % de la hauteur
  d'écran avec onglets défilants. Non vérifié : mise à l'échelle native de Windows (paramètre
  d'affichage), navigation clavier complète hors éditeur d'opération.
