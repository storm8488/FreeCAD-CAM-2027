# CAM2027 — Organisation de l'interface et direction artistique « Atelier »

Source de la charte : dossier `FreeCAD_CAM_Direction_Artistique` v1.1 (20 oct. 2026), copié dans
`docs/design/` (charte, jetons, consignes, contrôles). Le nom de travail du dossier (« FreeCAD CAM »)
n'est pas repris : le produit reste **CAM2027**, fork indépendant basé sur FreeCAD et son atelier CAM.

Refonte UX/UI du 25 oct. 2026 (branche `cam2027-ux-refonte`) : une organisation métier unique, inspirée
de la logique d'Aspire (préparer, dessiner, parcours, vérifier, exporter), sans portage ni réécriture des
moteurs. Relevé avant / après, tableau problème / décision / composant et correspondance des anciennes
commandes : en bas de ce document.

## 1. La fenêtre

| Zone | Contenu | Composant |
|---|---|---|
| **Haut** : barre des espaces (`CAM2027_Shell`) | repère CAM2027 ; nom du projet et état d'enregistrement (« enregistré » / « non enregistré ») ; Nouveau projet, Ouvrir, Enregistrer, Annuler, Rétablir, Cadrer, Vues ; quatre espaces **PRÉPARER \| DESSINER \| USINER \| VÉRIFIER ET EXPORTER** (Ctrl+1 … Ctrl+4) ; boutons Navigateur / Panneau de tâche, Bibliothèque d'outils, Mode avancé | `gui/shell.py` |
| **Gauche** : navigateur métier (dock `CAM2027_Project`) | compact, adapté à l'espace (voir § 2) ; résumé du projet (brut, repère, machine) en tête des espaces autres que Préparer, cliquable | `gui/navigator.py` |
| **Centre** | la pièce ou le dessin (vue 3D FreeCAD, inchangée) | FreeCAD |
| **Droite** : panneau de tâche (dock `CAM2027_Inspector`) | **une seule tâche à la fois** : éditeur d'opération, ajout d'opération, brut et repère, profil machine, export, vérification ; fermé quand aucune tâche n'est ouverte | `gui/inspector.py` (`Page`, `Inspector`) |
| **Bas** : barre d'état FreeCAD | sélection (« Sélection : 2 faces (Plate) »), calcul en cours (message de `busy`), **problèmes à consulter** (bouton → Vérifier et exporter), unités FreeCAD, repère ALPHA et liens | `gui/shell.py`, `gui/alpha.py` |

Règles :

- Sans document ouvert (logiciel autonome) : **accueil seul** (`gui/welcome.py` : Nouveau projet, Ouvrir,
  Projets récents, Démo guidée), navigateur et panneau masqués. En mode atelier dans un FreeCAD complet,
  le navigateur porte les deux seuls boutons Nouveau / Ouvrir ; rien n'est doublé.
- Passer d'un espace à l'autre ne touche ni la sélection, ni la caméra, ni le document, ni la page ouverte
  dans le panneau de tâche. Ouvrir une autre tâche quand la page courante a des modifications non
  appliquées demande explicitement : **Appliquer / Abandonner / Rester** (`Inspector.release`).
- Largeur : en dessous de `shell.NARROW_WIDTH` (1600 px) un seul panneau latéral est développé
  (le panneau de tâche prend la place du navigateur quand une tâche s'ouvre ; le navigateur revient par
  son bouton). À 1280 × 800 la vue centrale garde 834 px sur 1280 ; à 1920 × 1080 les deux panneaux
  sont ouverts (320 + 440) et la vue garde 1198 px. Aucune largeur minimale de fenêtre ajoutée : le
  navigateur et les pages défilent verticalement, jamais horizontalement.
- L'arbre FreeCAD (dock « Modèle ») et l'éditeur de propriétés restent disponibles en **mode avancé**
  (Affichage > Mode avancé) ; ils ne sont pas une navigation.
- Dans le logiciel autonome, les barres FreeCAD (Fichier, Édition, Vue, Structure) et les anciennes
  barres CAM2027 / Dessin sont rangées : leurs commandes restent dans les menus et leurs raccourcis
  (préférence `MainWindow/Toolbars`, « Disposition par défaut » les range de nouveau). En mode atelier
  dans un FreeCAD complet, rien des autres ateliers n'est masqué ni restylé ; la coquille se retire
  quand on quitte l'atelier.
- Menus : un menu par espace (Préparer, Dessiner, Usiner, Vérifier et exporter), même vocabulaire que
  la barre, accès complémentaire à toutes les commandes.

## 2. Les quatre espaces

| Espace | Navigateur (gauche) | Panneau de tâche (droite) |
|---|---|---|
| **Préparer** | lignes avec état ✔ / ○ et action : Pièce ou dessin (Importer…), Brut (Régler…), Origine et repère (Régler…), Machine et postprocesseur (Régler…), Montage et mise en place (menu : zones interdites, recto-verso, imbrication, relief, palpage) ; face A / B d'un projet recto-verso ; « Ensuite » : la prochaine étape en bouton principal | page **Brut et montage** (type et dimensions du brut, repère G54–G59, note sur l'origine ; crée le job), page **Profil machine** (valeurs inconnues laissées vides, jamais zéro) |
| **Dessiner** | vues Dessus / 3D explicites ; vecteurs du dessin (sélection synchronisée avec la vue) ; outils groupés par intention : Créer (texte, rectangle, cercle, polygone, vectoriser une image), Modifier (modifier, nœuds, décalage, combiner, miroir), Aligner et répartir (copies circulaires), Organiser (imbrication, relief, importer un dessin) | les dialogues de dessin existants (`gui/vectors.py`, `sheetdlgs.py`) |
| **Usiner** | « Ajouter une opération » (bouton principal) ; liste des opérations dans l'ordre de fabrication : **inclure** (coche = fabrication et export), nom, état, outil (T, Ø), durée, **afficher** (œil = parcours visible, sans effet sur l'export) ; Modifier, Dupliquer, Supprimer, ▲ ▼ (Alt+Haut / Alt+Bas, glisser-déposer) ; Recalculer (en bleu quand des parcours sont périmés) ; menu « Plus… » : comparer et modifier, fond plat, incrustation, photo V-carve, moulure, cannelures, texture, prisme, trous, motif, projection, gravure enroulée, rotatif, modèles de parcours | page **Ajouter une opération** : 1. famille par résultat (Surfaçage, Poche, Contour / découpe, Perçage, Gravure / V-carving, Ébauche, Finition 3D) ; 2. stratégie (nom court, usage, sélection attendue, limites connues) et **moteur** alternatif en choix secondaire (« CAM2027 (recommandé) » / « Poche (moteur FreeCAD) ») ; 3. outil et préréglage (outils compatibles) ; 4. nom et géométrie. « Créer l'opération » calcule puis ouvre **le même éditeur** à la même place |
| | | **Éditeur d'opération** : nom, stratégie, index A ; bandeau toujours visible (Ø, S, F, plongée, profondeur, passe axiale, hauteurs sûre et de dégagement) ; résumé avant calcul (« 1 face — fraise Ø 6 mm — profondeur 4 mm — passes 3 mm ») ; sections dépliables dans l'ordre : Géométrie (liste, surbrillance au clic, prendre / ajouter la sélection 3D, tout le modèle), Outil (Sélectionner… / Éditer…, préréglage, valeurs copiées), Profondeurs et passes, Avances et vitesses (valeur + source, retour au préréglage), Entrée / sortie et attaches, Réglages de la stratégie (repliée), Filetage, Reprise et zone ; actions **Appliquer et calculer**, **Annuler les modifications**, **Fermer** (demande quoi faire des modifications non appliquées) |
| **Vérifier et exporter** | Parcours (n sur m calculés, durée, à recalculer → Recalculer), Simulation (aperçu exécuté, simulateur FreeCAD), Contrôle matière et collisions (non exécuté / périmé / fait / problèmes), Export G-code, Fiche de réglage PDF ; **Problèmes à consulter** classés bloquant ✕ / avertissement △ / information • (parcours invalides ou périmés, contrôle matière, données machine, zones interdites), chaque ligne ouvre le réglage concerné | page **Vérification** (une carte par contrôle : statut, résultat, **portée**), page **Exporter le G-code** (postprocesseur, fichier, récapitulatif avant export : machine, post, unités, repères, opérations incluses dans l'ordre, contrôles ; aperçu ; fiche ; export bloqué par les contrôles comme avant ; rien n'est envoyé à la machine) |

États lus sur le document (`operations.compute_state`, `Project.last_check` et son empreinte des parcours),
jamais un second état dans l'interface : une modification qui périme un parcours ou un contrôle se voit
dans la liste (« À recalculer »), dans Vérifier et exporter (« périmé ») et dans les problèmes.

## 3. Ce qui est intégré de la charte

| Élément | Où | Remarque |
|---|---|---|
| Jetons (couleurs sombre / clair, typo, espacements, rayons, densité) | `Resources/theme/tokens.json` | source unique des valeurs |
| Couche de thème | `cam2027/gui/theme.py` | rôles sémantiques (`color`, `status_color`), QSS limitée aux widgets CAM2027 ; `shell_stylesheet()` pour la barre des espaces (fond réel de la fenêtre) ; styles des sections, lignes du navigateur, bandeau, en-tête du panneau |
| Choix du thème | préférence `BaseApp/Preferences/CAM2027/Theme` = `system` / `dark` / `light` ; Affichage > Thème | panneaux, pages et barre restylés sur place |
| Icônes | `Resources/icons/atelier/{dark,light}/*.svg` (générées par `scripts/make-command-icons.py`) | espaces (`space-*`), panneaux (`panel-left` / `panel-right`), parcours masqué (`visibility-off`), commandes, familles |
| États | ✔ / ○ + couleur + infobulle (étapes), icône + couleur + texte (opérations), symbole + mot + couleur (vérification, problèmes) | jamais la couleur seule ; survol, focus, sélection, désactivé, erreur distincts |
| Calcul long | `commands.busy` : curseur, message dans la barre d'état, fenêtre « Arrêter le calcul » (quand l'opération sait s'arrêter), interface rafraîchie toutes les 0,1 s | pas de progression inventée |

## 4. Non intégré / limites

- Logo : les PNG du dossier restent des propositions ; l'icône d'atelier reste `Resources/icons/CAM2027.svg`.
- Couleurs de scène 3D : appliquées au profil du lanceur (voir `gui/prefs.py`) ; motifs de trait non
  disponibles dans FreeCAD.
- Les dialogues secondaires (zones interdites, recto-verso, imbrication, incrustation, gravure enroulée,
  rotatif, motifs, trous, palpage, relief, dessin, comparaison d'opérations) restent des dialogues modaux,
  atteints depuis le navigateur ou les menus (accès transitoire aux fonctions secondaires).
- La bibliothèque d'outils complète reste un dock (bouton de la barre ou champ Outil > Éditer…), fermée par
  défaut ; le choix d'un outil passe par « Sélectionner… » (`gui/toolpicker.py`).
- Non vérifié : mise à l'échelle native de Windows (paramètre d'affichage), navigation clavier complète hors
  éditeur, rendu sur un écran 4K réel ; voir TESTS.md pour ce qui a été observé (1280 × 800, 1920 × 1080,
  150 % et 200 % par `QT_SCALE_FACTOR`, thèmes sombre et clair).

## 5. Relevé avant / après (FreeCAD 1.1.4, mode autonome, profil isolé)

| Mesure | Avant (7e178335) | Après |
|---|---|---|
| Barres d'outils visibles avec un projet | Fichier, Édition, Vue, Structure, Aide, CAM2027 (16 icônes), Dessin (11) : trois lignes | une ligne : barre des espaces |
| Panneaux ouverts par défaut | Modèle (arbre FreeCAD), Projet (à droite), Bibliothèque d'outils (en bas, 324 px de haut à 1080) | Navigateur (gauche) ; panneau de tâche seulement pendant une tâche |
| Vue centrale à 1280 × 800 | 430 × 440 px | 1004 × 642 px (navigateur seul), 834 × 638 px (tâche ouverte) |
| Vue centrale à 1920 × 1080 | 1068 × 557 px | 1644 × 969 px (navigateur seul), 1198 × 969 px (les deux panneaux) |
| Sans projet | accueil + panneau Projet avec Nouveau / Ouvrir en double | accueil seul |
| Ajouter une opération | dialogue (liste plate de 20 stratégies avec le moteur dans le libellé) puis fenêtre d'édition à 8 onglets | une page (7 familles → stratégie → moteur secondaire → outil → nom) puis le même panneau en éditeur |
| Éditeur | 8 onglets, valeurs clés visibles seulement dans leur onglet | sections dans l'ordre du métier, bandeau des valeurs clés, résumé avant calcul |
| Simulation, contrôle, export | trois commandes, deux menus, dialogue export à 4 onglets | un espace, un navigateur, les résultats dans le panneau de tâche, problèmes classés |
| Visibilité / activation d'une opération | la coche « actif » seulement | coche « inclure » et œil « afficher » séparés |

## 6. Correspondance anciennes commandes → nouvel emplacement

| Avant | Après |
|---|---|
| Barre CAM2027 > Nouveau projet / Importer | barre des espaces (Nouveau projet) ; Préparer > Pièce ou dessin > Importer… |
| Panneau Projet > étapes 1–4 | navigateur Préparer (Pièce, Brut, Origine, Machine, Montage) et « Ensuite » |
| Panneau Projet > Nouveau projet / Ouvrir | accueil (logiciel) ; navigateur sans projet (mode atelier) |
| Brut et montage (dialogue) | Préparer > Brut > Régler… ou Origine et repère > Régler… (page du panneau de tâche) ; résumé cliquable dans les autres espaces |
| Profil machine (dialogue) | Préparer > Machine et postprocesseur > Régler… (page) ; résumé cliquable |
| Bibliothèque d'outils (dock ouvert en bas) | bouton de la barre des espaces, menu Préparer, ou champ Outil > Éditer… |
| Ajouter une opération (dialogue) | Usiner > Ajouter une opération (page), puis éditeur dans le même panneau |
| Modifier (fenêtre non modale) | Usiner > Modifier, ou double-clic : éditeur dans le panneau de tâche |
| Panneau Projet > Monter / Descendre / Dupliquer / Supprimer | Usiner > ▲ ▼ / Dupliquer / Supprimer (Alt+Haut / Alt+Bas, glisser-déposer) |
| Recalculer les parcours | Usiner > Recalculer les parcours ; Vérifier et exporter > Parcours > Recalculer |
| Comparer et modifier des opérations | Usiner > Plus… |
| Usiner > Fond plat, Incrustation, Gravure enroulée, Rotatif, Projeter, Motif, Trous, Palpage, Photo V-carve, Moulure, Cannelures, Texture, Prisme, Modèles | Usiner > Plus… (Palpage : Préparer > Montage > Options) ; menu Usiner |
| Zones interdites, Recto-verso, Imbrication, Relief | Préparer > Montage et mise en place > Options ; Dessiner > Organiser ; menu Préparer |
| Barre Dessin (11 icônes permanentes) | Dessiner > Créer / Modifier / Aligner et répartir / Organiser ; menu Dessiner |
| Simuler > Simuler | Vérifier et exporter > Simulation > Simuler |
| Simuler > Contrôle matière (dialogue Vérification) | Vérifier et exporter > Contrôle matière > Contrôler (page Vérification) |
| Exporter > Exporter le G-code (dialogue) | Vérifier et exporter > Export G-code > Exporter… (page) |
| Exporter > Fiche de préparation (PDF) | Vérifier et exporter > Fiche de réglage (PDF) > Écrire… |
| Menu CAM2027 > Thème, Langue, Mode avancé, Disposition par défaut | Affichage (logiciel) ; menu CAM2027 (mode atelier) ; Mode avancé aussi dans la barre |
