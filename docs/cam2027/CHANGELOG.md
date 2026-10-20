# CAM2027 — Historique

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
