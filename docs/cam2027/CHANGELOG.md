# CAM2027 — Historique

## Non publié

- Profil « FAO seule » appliqué au profil du lanceur (`gui/prefs.py`) : thème sombre FreeCAD,
  icônes 32 px, atelier CAM2027 au démarrage, autres ateliers masqués (opt-out `CamOnly`).
- Une icône SVG par commande (`Resources/icons/cam2027-*.svg`).
- Spécification déclarative des paramètres d'opération (`project/paramspec.py` : libellé,
  onglet, aide, traduits) ; lecture/écriture typée sur l'objet FreeCAD (`param_kind`,
  `read_params`, `set_params`).
- Éditeur d'opération à onglets, non modal (`gui/opeditor.py`) : création (après le
  dialogue « Ajouter une opération ») et modification (double-clic dans le panneau projet),
  valeurs du préréglage affichées, géométrie reprise de la sélection 3D.
- Projet : `update_operation`, `set_operation_base`, `set_operation_active`,
  `move_operation`, `duplicate_operation`, `remove_operation` (tests `test_operation_edits`,
  `test_param_specs` ; 32 tests).
- Panneau projet remplacé par un **panneau de flux de travail** : étapes Pièce → Brut et
  montage → Opérations → Contrôle et export avec statut et bouton, liste des opérations
  (case Actif, stratégie, outil, commandes, Z, temps ; Modifier / Monter / Descendre /
  Dupliquer / Supprimer), recalcul et simulation.
- Commande « Simuler » : lance le simulateur FreeCAD (`CAM_SimulatorGL`, sinon
  `CAM_Simulator`) sur le job du projet.
- Attaches (Holding Tags) et rampe d'entrée comme options d'une opération
  (`project/dressups.py`, onglet « Entrée, sortie et attaches » de l'éditeur) ; l'habillage
  remplace l'opération dans le job. Test `test_dressups` (33 tests sur 1.1.4 et 1.0.2).
- Perçage, hélice, filetage sans géométrie sélectionnée : tous les trous détectés par FreeCAD
  (plus grands que l'outil). Tests `test_drilling_all_holes`, `test_helix_and_engrave` (35 tests).
- Changement d'assemblage / de préréglage sur une opération existante (onglet Outil de
  l'éditeur, `Project.change_operation_tool`) : même coupant = contrôleur mis à jour, autre
  coupant = ToolBit + ToolController remplacés. Test `test_change_operation_tool` (36 tests).
- Dogbones (`Path.Dressup.DogboneII`) comme troisième habillage (contour, poche, adaptatif) ;
  test `test_dogbones` (37 tests).
- Bibliothèque : bouton « Ajouter les outils de démarrage manquants » (`merge_starter_tools`,
  fusion par nom, numéros d'outil libres ; test `test_merge_starter_tools`, 38 tests).
- Dialogue d'export : contrôles colorés (erreur rouge, avertissement orange, non vérifiable
  ambre, OK vert).
- Raccourcis clavier Ctrl+Maj+lettre pour les commandes principales.
- Tests V-carve (fond de poche, profondeur bornée) et rainure (points personnalisés) :
  `test_vcarve_and_slot` (39 tests).
- Rainure : points personnalisés, références et rayon de prolongement dans l'éditeur (champ
  vecteur X/Y/Z) ; panneau de flux de travail : temps d'usinage total.
- **Flux 2D « à la Aspire »** : dessin SVG/DXF posé sur un panneau généré (dessus à Z 0,
  épaisseur et marge réglables, semi-transparent), une face par contour fermé ; nouvelle
  stratégie « Poche 2D » (`Path.Op.PocketShape`) ; option « Panneau sous le dessin 2D » du
  dialogue Brut et montage. Test `test_sheet_from_drawing` (découpe, poche 2D, V-carving,
  gravure, export ; 40 tests).

## 0.1.3 — 2026-10-20

- Stratégies `threadmill` (`Path.Op.ThreadMilling`, nom de filet résolu depuis les tables
  FreeCAD, pas vérifié contre la plage de l'outil) et `chamfer` (`Path.Op.Deburr`) ; limites
  honnêtes de `millface`. Fraise à fileter 4 mm dans la bibliothèque de démarrage (col du
  ToolBit forcé < D). Dialogue « Ajouter une opération » : largeur de chanfrein, nom de
  filet, `ClearEdges` pour le surfaçage. Tests `test_facing`, `test_thread_milling`,
  `test_chamfer`, `test_strategy_translations` (30 tests sur 1.1.4 et 1.0.2).

## 0.1.2 — 2026-10-20

- Import Fusion validé sur un export réel (Fusion 2.16, version 37) : angle inclus = 2 × `TA`,
  longueur de jauge `assemblyGaugeLength`, sortie = `LB`, `tapered-type`, sens par `HAND`,
  `use-stepdown`/`use-stepover`, matière de préréglage, arrosage `tool-coolant` ; clés `CSP`,
  `DCX`, `shoulder-diameter`, `upper-radius` reconnues. Fixture + test
  `test_fusion_import_real_export` (26 tests).
- Bibliothèque utilisateur du lanceur pré-remplie : 11 outils Fusion (T1–T11) + outils de
  démarrage renumérotés T21–T27 ; rapport dans `fusion-import-report.txt`.

## 0.1.1 — 2026-10-20

- FreeCAD 1.1.4 portable installé à part (`%LOCALAPPDATA%\CAM2027\FreeCAD-1.1.4`, SHA256
  vérifié) ; suite de tests et vérification graphique passées sur 1.1.4 (API outils
  « assets », PySide6) et sur 1.0.2.
- Compatibilité Qt6 : `exec_dialog`, `QtGui.QFontDatabase` ; STEP/IGES via le module
  `Import` (Part.insert déprécié en 1.1). Lanceurs : priorité `FREECAD_BIN` > 1.1.4 > 1.0.2.

## 0.1.0 — 2026-10-20 (jalon A + première tranche du jalon B)

- Fork `storm8488/FreeCAD-CAM-2027` créé ; branche `cam2027` depuis le tag amont `1.1.4`
  (commit `4fd3bf32`). Audit de l'environnement et de FreeCAD 1.0.2 / 1.1.4 / 26.3rc2.
- Atelier `src/Mod/CAM2027` (Python, FreeCAD ≥ 1.0) :
  - bibliothèque d'outils : 20 types (champs de l'onglet « Coupant » de Fusion), porte-outils
    par segments, assemblages (sortie, longueur de jauge, numéro, correcteurs, changement
    manuel), préréglages multiples avec relations n/Vc et Vf/fz, recherche, filtres,
    favoris, duplication, édition groupée, import/export, instantané versionné par projet,
    import Fusion (.json/.tools) avec rapport de conversion ;
  - chaîne projet : import STEP/STL/OBJ/SVG/DXF, job, brut (marges/boîte/cylindre),
    repère G54–G59, brides visuelles, 9 stratégies FreeCAD, ToolController par opération
    avec valeurs copiées, export G-code (37 posts FreeCAD), analyse et contrôles
    (unités, codes GRBL, axes, courses, avance, broche), fiche de préparation ;
  - interface : atelier « CAM2027 », 9 commandes, panneau bibliothèque (coupant /
    données de coupe / porte-outil & assemblage, aperçu 2D coté), panneau projet,
    dialogues brut, opération, export (aperçu + contrôles + fiche), machine, à propos ;
    catalogue français complet.
- Lanceur `scripts/cam2027.cmd` (profil séparé, journal), raccourci et désinstallation
  par utilisateur, tests console `scripts/cam2027-tests.cmd`, vérification graphique
  `tests/gui_smoke.py`.
